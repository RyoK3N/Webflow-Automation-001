import csv
import requests
from typing import Union, List, Dict, Any

def _normalize_pages_list(raw_json: Any) -> List[Dict[str, Any]]:
    """
    Try to normalize the API response to a list of page dicts.
    Accepts:
      - list[dict]
      - dict with keys like 'pages', 'items', 'data'
    Raises RuntimeError with the raw content if it cannot normalize.
    """
    # If it's already a list of dicts, return it (validate elements)
    if isinstance(raw_json, list):
        # quick sanity check: ensure list elements are dict-like
        if all(isinstance(el, dict) for el in raw_json):
            return raw_json
        else:
            # maybe it's a list of strings (often an unexpected error); raise a helpful error
            raise RuntimeError(
                "Webflow pages endpoint returned a list, but elements are not objects.\n"
                f"First few elements: {raw_json[:5]!r}\n"
                "This usually indicates an unexpected response from the API (check token/site_id)."
            )

    # If it's a dict, try common container keys
    if isinstance(raw_json, dict):
        for key in ("pages", "items", "data", "results"):
            v = raw_json.get(key)
            if isinstance(v, list) and all(isinstance(el, dict) for el in v):
                return v
        # Maybe the dict itself is a single page object?
        if all(isinstance(raw_json.get(k), (str, list, dict, type(None))) for k in raw_json):
            # if it seems dict-like but not wrapped, maybe it's a single page. Wrap it.
            if any(k in raw_json for k in ("id", "slug", "_id", "title", "seo")):
                return [raw_json]
        # Otherwise, raise helpful error
        raise RuntimeError(
            "Webflow pages endpoint returned a JSON object that couldn't be parsed as a list of pages.\n"
            f"Response keys: {list(raw_json.keys())}\n"
            "If this is an error payload, check the 'message' / 'errors' fields and your API credentials."
        )

    # If it's a string or other unexpected type, raise
    raise RuntimeError(
        "Webflow pages endpoint returned an unexpected type (not JSON list/dict).\n"
        f"Raw response: {raw_json!r}\n"
        "Make sure the API token and site_id are correct and that the token has pages:read scope."
    )


def export_webflow_pages_meta_to_csv(
    api_token: str,
    site_id: str,
    slugs: Union[str, List[str]],
    output_path: str = "pages_meta.csv",
    accept_version: str = "1.0.0",
    timeout: int = 10
) -> str:
    """
    Fetch page title and meta description for given slug(s) from a Webflow site and write to CSV.

    Args:
        api_token: Webflow API token (site token or OAuth token with pages:read scope).
        site_id: Webflow site id (UUID).
        slugs: single slug (str) or list of slugs to look up.
        output_path: path to write CSV file to.
        accept_version: API version header (default 1.0.0).
        timeout: network timeout in seconds.

    Returns:
        output_path: path to the CSV file written.

    CSV columns: slug, title, meta_description
    """
    # Normalize slugs to list
    if isinstance(slugs, str):
        requested_slugs = [slugs]
    else:
        requested_slugs = list(slugs)

    # Headers for Webflow API
    headers = {
        "Authorization": f"Bearer {api_token}",
        "accept-version": accept_version,
        "Content-Type": "application/json",
    }

    session = requests.Session()
    session.headers.update(headers)

    # 1) List pages for site to find page ids by slug
    list_pages_url = f"https://api.webflow.com/v2/sites/{site_id}/pages"
    try:
        resp = session.get(list_pages_url, timeout=timeout)
        # Keep the raw text handy for debugging unexpected responses
        raw_text = resp.text
        resp.raise_for_status()
        pages_json = resp.json()
    except requests.RequestException as e:
        # Surface the raw response text for easier debugging
        raise RuntimeError(
            f"Failed to call Webflow pages endpoint: {e}\n"
            f"Response status: {getattr(resp, 'status_code', None)}\n"
            f"Response body (truncated): {raw_text[:1000]!r}"
        ) from e
    except ValueError as e:
        # JSON decode failed
        raise RuntimeError(
            "Failed to decode JSON from Webflow pages response.\n"
            f"Raw response (truncated): {raw_text[:1000]!r}"
        ) from e

    # Normalize into list of page dicts
    try:
        pages_list = _normalize_pages_list(pages_json)
    except RuntimeError as e:
        # Re-raise with extra context including a snippet of the raw JSON so you can debug
        raise RuntimeError(f"{e}\nRaw JSON (truncated): {str(pages_json)[:1000]!r}") from e

    # Build slug -> page mapping (take first match if duplicates)
    slug_to_page = {}
    for p in pages_list:
        # example fields: 'slug', 'id' (or '_id' in older responses), 'title'
        slug = p.get("slug") or p.get("path") or p.get("publishedPath") or p.get("published_path")
        page_id = p.get("id") or p.get("_id") or p.get("_cid")
        title = p.get("title") or ""
        if slug and page_id:
            slug_to_page.setdefault(slug, {"id": page_id, "title": title})

    # Prepare rows for CSV
    rows = []
    for slug in requested_slugs:
        page_info = slug_to_page.get(slug)
        if not page_info:
            # slug not found in site's pages
            rows.append({"slug": slug, "title": "", "meta_description": ""})
            continue

        page_id = page_info["id"]
        # 2) Get page metadata for the page_id
        metadata_url = f"https://api.webflow.com/v2/pages/{page_id}"
        try:
            mr = session.get(metadata_url, timeout=timeout)
            raw_meta_text = mr.text
            mr.raise_for_status()
            meta_obj = mr.json()
        except requests.RequestException:
            # If metadata fetch fails, include what we have from listing and continue
            rows.append({
                "slug": slug,
                "title": page_info.get("title", ""),
                "meta_description": "",
            })
            continue
        except ValueError:
            # failed to decode JSON for metadata
            rows.append({
                "slug": slug,
                "title": page_info.get("title", ""),
                "meta_description": "",
            })
            continue

        # Extract title (prefer metadata's title, fall back to listing)
        title = meta_obj.get("title") or page_info.get("title") or ""

        # Extract meta description from possible fields inside seo object
        seo = meta_obj.get("seo") or {}
        meta_description = ""
        if isinstance(seo, dict):
            for k in ("metaDescription", "meta_description", "description", "metaDesc", "meta"):
                if seo.get(k):
                    meta_description = seo.get(k)
                    break

        # If still empty, sometimes openGraph.description exists
        if not meta_description:
            og = meta_obj.get("openGraph") or {}
            if isinstance(og, dict):
                meta_description = og.get("description") or ""

        rows.append({
            "slug": slug,
            "title": title,
            "meta_description": meta_description or "",
        })

    # Write CSV
    fieldnames = ["slug", "title", "meta_description"]
    try:
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for r in rows:
                writer.writerow(r)
    except OSError as e:
        raise RuntimeError(f"Failed to write CSV to {output_path}: {e}") from e

    return output_path
