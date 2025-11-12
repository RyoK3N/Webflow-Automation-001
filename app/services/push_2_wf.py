import csv
import time
import requests
from typing import List, Dict, Optional

# --- Constants / small helpers ---
PAGES_URL = "https://api.webflow.com/v2/sites/{site_id}/pages"
PAGE_UPDATE_URL = "https://api.webflow.com/v2/pages/{page_id}"
LIST_COLLECTIONS_URL = "https://api.webflow.com/v2/sites/{site_id}/collections"
LIST_ITEMS_URL = "https://api.webflow.com/v2/collections/{collection_id}/items"
UPDATE_ITEM_URL = "https://api.webflow.com/v2/collections/{collection_id}/items/{item_id}"

DEFAULT_ACCEPT_VERSION = "1.0.0"

# Common candidate field slugs/names in CMS items to try updating for SEO
COMMON_SEO_FIELD_KEYS = [
    "seo_title", "seo_description", "meta_title", "meta_description",
    "metaDesc", "metaDescription", "seoTitle", "seoDescription",
    "title", "description", "excerpt", "summary"
]

def _make_session(api_token: str, accept_version: str = DEFAULT_ACCEPT_VERSION) -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "Authorization": f"Bearer {api_token}",
        "accept-version": accept_version,
        "Content-Type": "application/json",
    })
    return s

def _read_csv(csv_path: str) -> List[Dict[str, str]]:
    rows = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        # Expecting columns: slug, title, meta_description (case-insensitive)
        for r in reader:
            # normalize keys
            keys = {k.strip().lower(): v for k, v in r.items()}
            rows.append({
                "slug": keys.get("slug", "").strip(),
                "title": keys.get("title", "").strip(),
                "meta_description": keys.get("meta_description", keys.get("meta description", "")).strip()
            })
    return rows

def update_webflow_seo_from_csv(
    api_token: str,
    site_id: str,
    csv_path: str,
    accept_version: str = DEFAULT_ACCEPT_VERSION,
    dry_run: bool = False,
    timeout: int = 10,
    max_retries: int = 3,
    sleep_on_retry: float = 1.0
) -> Dict[str, List[Dict[str, str]]]:
    """
    Reads a CSV (slug, title, meta_description) and updates Webflow:
      1. tries to update page-level metadata (title + seo.metaDescription)
         via PUT /v2/pages/:page_id (requires pages:write). :contentReference[oaicite:2]{index=2}
      2. for slugs not found as pages, searches CMS collections for items with that slug,
         and attempts to update likely SEO fields inside the item's fieldData via PATCH
         /v2/collections/:collection_id/items/:item_id (requires CMS:write). :contentReference[oaicite:3]{index=3}

    Returns a summary dict with keys: updated_pages, updated_items, skipped, failed
    """
    session = _make_session(api_token, accept_version=accept_version)
    rows = _read_csv(csv_path)

    summary = {"updated_pages": [], "updated_items": [], "skipped": [], "failed": []}

    # --- 1) get pages listing and build slug->page mapping ---
    try:
        r = session.get(PAGES_URL.format(site_id=site_id), timeout=timeout)
        r.raise_for_status()
        pages_json = r.json()
    except Exception as e:
        raise RuntimeError(f"Failed to list pages for site {site_id}: {e}\nResponse: {getattr(r, 'text', '')[:1000]!r}") from e

    # normalize pages_json -> list of dicts
    if isinstance(pages_json, dict):
        # webflow sometimes wraps responses, try common keys
        for k in ("pages", "items", "data", "results"):
            if isinstance(pages_json.get(k), list):
                pages_list = pages_json.get(k)
                break
        else:
            # if dict looks like a single page
            pages_list = [pages_json]
    else:
        pages_list = pages_json

    slug_to_page = {}
    for p in pages_list:
        if not isinstance(p, dict):
            continue
        slug = p.get("slug") or p.get("path") or p.get("publishedPath") or p.get("published_path")
        page_id = p.get("id") or p.get("_id")
        title = p.get("title") or ""
        if slug and page_id:
            slug_to_page[slug] = {"id": page_id, "title": title}

    # --- Helper: update page metadata (PUT /v2/pages/:page_id) ---
    def _update_page(page_id: str, title: str, meta_description: str) -> bool:
        payload = {}
        if title:
            payload["title"] = title
        if meta_description is not None:
            payload["seo"] = {"metaDescription": meta_description}
        # If nothing to update, skip
        if not payload:
            return False
        if dry_run:
            return True
        url = PAGE_UPDATE_URL.format(page_id=page_id)
        for attempt in range(1, max_retries+1):
            try:
                resp = session.put(url, json=payload, timeout=timeout)
                resp.raise_for_status()
                return True
            except requests.RequestException as e:
                if attempt == max_retries:
                    raise
                time.sleep(sleep_on_retry * attempt)
        return False

    # --- 2) find collections (for slugs not found as pages) ---
    try:
        rc = session.get(LIST_COLLECTIONS_URL.format(site_id=site_id), timeout=timeout)
        rc.raise_for_status()
        collections_json = rc.json()
    except Exception as e:
        raise RuntimeError(f"Failed to list collections for site {site_id}: {e}\nResponse: {getattr(rc,'text','')[:1000]!r}") from e

    # normalize collections_json
    collections = []
    if isinstance(collections_json, dict):
        if isinstance(collections_json.get("collections"), list):
            collections = collections_json["collections"]
        else:
            # API may return list directly wrapped
            # try common keys fallback
            for k in ("items", "data", "results"):
                if isinstance(collections_json.get(k), list):
                    collections = collections_json.get(k)
                    break
            else:
                # if the dict seems like a single collection
                if "id" in collections_json:
                    collections = [collections_json]
    elif isinstance(collections_json, list):
        collections = collections_json

    # Build map of collection_id -> collection schema (fields)
    collection_fields_map = {}
    for coll in collections:
        if not isinstance(coll, dict):
            continue
        coll_id = coll.get("id") or coll.get("_id")
        # Some collection responses include field definitions; if not, fetch collection detail
        if coll_id:
            # GET collection details to know fields/field slugs
            try:
                g = session.get(f"https://api.webflow.com/v2/collections/{coll_id}", timeout=timeout)
                g.raise_for_status()
                coll_detail = g.json()
            except Exception:
                coll_detail = coll  # fallback to whatever we have
            # coll_detail['fields'] is expected to be a list of field objects (with slug & name)
            fields = coll_detail.get("fields") or coll_detail.get("fieldData") or []
            collection_fields_map[coll_id] = {"details": coll_detail, "fields": fields}

    # Helper: find item by slug inside a collection (paginated)
    def _find_item_in_collection(coll_id: str, target_slug: str) -> Optional[Dict]:
        limit = 100
        offset = 0
        while True:
            params = {"limit": limit}
            if offset:
                params["offset"] = offset
            url = LIST_ITEMS_URL.format(collection_id=coll_id)
            resp = session.get(url, params=params, timeout=timeout)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            j = resp.json()
            items = j.get("items") or j.get("results") or j if isinstance(j, list) else []
            if not items:
                return None
            for it in items:
                # item slug key could be 'slug' or 'fieldData.slug'
                if it.get("slug") == target_slug:
                    return {"item": it, "collection_id": coll_id}
                # also check fieldData.slug
                fd = it.get("fieldData") or {}
                if fd.get("slug") == target_slug:
                    return {"item": it, "collection_id": coll_id}
            # pagination handling: Webflow returns pagination.offset or j.get('offset')
            pagination = j.get("pagination") or {}
            # try offset based pagination
            if isinstance(pagination, dict) and pagination.get("nextOffset"):
                offset = pagination.get("nextOffset")
                continue
            # else if 'total' or items < limit, break
            if len(items) < limit:
                break
            # otherwise try increasing offset
            offset += limit
        return None

    # Helper: pick candidate field to update inside item based on collection fields
    def _pick_item_field_to_update(fields: List[Dict]) -> Dict[str, str]:
        """
        Given list of field objs (each with 'slug' and 'name' typically),
        prioritize common SEO-like field slugs. Return dict mapping:
          {"title_field": slug_or_none, "desc_field": slug_or_none}
        """
        title_field = None
        desc_field = None
        # prepare lower-cased lookup
        for f in fields:
            fslug = f.get("slug") or ""
            fname = f.get("name") or ""
            key = (fslug or fname).lower()
            # pick title-like
            if (not title_field) and any(k in key for k in ("seo_title", "meta_title", "title", "name")):
                title_field = fslug
            # pick desc-like
            if (not desc_field) and any(k in key for k in ("seo_description", "meta_description", "description", "excerpt", "summary")):
                desc_field = fslug
        # fallback: if no matched field, try common keys present in schema
        if not title_field:
            for candidate in COMMON_SEO_FIELD_KEYS:
                for f in fields:
                    if (f.get("slug") or "").lower() == candidate.lower():
                        title_field = f.get("slug")
                        break
                if title_field:
                    break
        if not desc_field:
            for candidate in COMMON_SEO_FIELD_KEYS:
                for f in fields:
                    if (f.get("slug") or "").lower() == candidate.lower():
                        desc_field = f.get("slug")
                        break
                if desc_field:
                    break
        return {"title_field": title_field, "desc_field": desc_field}

    # Helper: update collection item (PATCH)
    def _update_collection_item(collection_id: str, item_id: str, field_updates: Dict[str, str]) -> bool:
        if dry_run:
            return True
        url = UPDATE_ITEM_URL.format(collection_id=collection_id, item_id=item_id)
        payload = {"fieldData": field_updates}
        for attempt in range(1, max_retries+1):
            try:
                resp = session.patch(url, json=payload, timeout=timeout)
                resp.raise_for_status()
                return True
            except requests.RequestException as e:
                if attempt == max_retries:
                    raise
                time.sleep(sleep_on_retry * attempt)
        return False

    # --- Main loop through CSV rows ---
    for row in rows:
        slug = row["slug"]
        title = row["title"]
        meta_description = row["meta_description"]

        if not slug:
            summary["skipped"].append({"reason": "empty_slug", "row": row})
            continue

        # 1) try pages
        page_info = slug_to_page.get(slug)
        if page_info:
            page_id = page_info["id"]
            try:
                updated = _update_page(page_id, title, meta_description)
                if updated:
                    summary["updated_pages"].append({"slug": slug, "page_id": page_id})
                else:
                    summary["skipped"].append({"slug": slug, "reason": "nothing_to_update_for_page"})
            except Exception as e:
                summary["failed"].append({"slug": slug, "location": "page_update", "error": str(e)})
            continue

        # 2) search collections for item with this slug
        found = None
        for coll_id in collection_fields_map.keys():
            try:
                candidate = _find_item_in_collection(coll_id, slug)
            except Exception as e:
                # log and continue with next collection
                continue
            if candidate:
                found = candidate
                break

        if not found:
            summary["failed"].append({"slug": slug, "location": "not_found", "error": "slug not found in pages or collections"})
            continue

        item = found["item"]
        coll_id = found["collection_id"]
        item_id = item.get("id") or item.get("_id") or item.get("itemId")
        # get collection fields list
        coll_fields = collection_fields_map.get(coll_id, {}).get("fields", [])
        pick = _pick_item_field_to_update(coll_fields)
        field_updates = {}
        if pick["title_field"] and title:
            field_updates[pick["title_field"]] = title
        if pick["desc_field"] and meta_description:
            field_updates[pick["desc_field"]] = meta_description

        # If we couldn't detect semantic fields, fallback: try to update fields on item that contain 'title'/'description' substrings
        if not field_updates:
            # inspect item['fieldData'] keys
            fd = item.get("fieldData") or {}
            updated_any = False
            for k in fd.keys():
                kl = k.lower()
                if "title" in kl and title:
                    field_updates[k] = title
                    updated_any = True
                elif "desc" in kl or "summary" in kl or "excerpt" in kl or "meta" in kl:
                    if meta_description:
                        field_updates[k] = meta_description
                        updated_any = True
            if not updated_any and title:
                # as final resort, if there is a 'name' field, update it
                if "name" in fd:
                    field_updates["name"] = title

        if not field_updates:
            summary["failed"].append({"slug": slug, "location": "item_no_updatable_fields", "error": "no candidate fields detected in collection item"})
            continue

        try:
            ok = _update_collection_item(coll_id, item_id, field_updates)
            if ok:
                summary["updated_items"].append({"slug": slug, "collection_id": coll_id, "item_id": item_id, "fields_updated": list(field_updates.keys())})
            else:
                summary["failed"].append({"slug": slug, "location": "item_update_unknown", "error": "unknown"})
        except Exception as e:
            summary["failed"].append({"slug": slug, "location": "item_update_error", "error": str(e)})

    return summary

# --- Example usage ---
if __name__ == "__main__":
    api_token = "27ddf1a26c1998c8403592c7a5bfc84fdc825759ee4d1f63c5e591d666694f22"
    site_id = "68ab31c3e6d1d2e932aba474"
    csv_path = "selected_pages_meta.csv"
    # set dry_run=True to preview without writing
    result = update_webflow_seo_from_csv(api_token, site_id, csv_path, dry_run=False)
    print("Result summary:", result)
