"""
Production-Grade CSV Handler with Comprehensive Validation
Handles CSV parsing, validation, and generation with robust error handling.
"""

import csv
import io
import re
from typing import List, Dict, Tuple, Set, Optional, Any
from datetime import datetime
from collections import defaultdict

from app.models.schemas import PageSchema
from app.core.logging import logger
from app.core.exceptions import CSVException, ValidationException


class CSVHandler:
    """
    Production-grade CSV parser with extensive validation and error reporting.
    
    Features:
    - Header validation
    - Data type validation
    - Duplicate detection
    - Row-level error reporting
    - BOM handling
    - Large file support
    """
    
    # Configuration constants
    REQUIRED_HEADERS = {"slug", "title", "meta_description"}
    OPTIONAL_HEADERS = {"updated_at", "keywords", "canonical_url"}
    MAX_ROWS = 10000
    MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
    MAX_FIELD_LENGTH = 1000
    
    # Validation patterns
    SLUG_PATTERN = re.compile(r'^/[a-zA-Z0-9/_-]*$')
    
    def __init__(self):
        """Initialize CSV handler."""
        self.stats = {
            "total_processed": 0,
            "validation_errors": 0,
            "warnings": 0,
        }
    
    def validate_csv_file(self, content: bytes) -> Tuple[bool, List[str]]:
        """
        Comprehensive CSV file validation.
        
        Args:
            content: Raw CSV file content as bytes
            
        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        errors: List[str] = []
        warnings: List[str] = []
        
        try:
            # Check file size
            if len(content) == 0:
                return False, ["File is empty"]
            
            if len(content) > self.MAX_FILE_SIZE:
                return False, [
                    f"File too large: {len(content) / 1024 / 1024:.2f}MB "
                    f"(max: {self.MAX_FILE_SIZE / 1024 / 1024:.0f}MB)"
                ]
            
            # Decode content (handle BOM)
            try:
                text_content = content.decode("utf-8-sig")
            except UnicodeDecodeError as e:
                return False, [
                    f"File must be UTF-8 encoded. "
                    f"Decoding error at byte {e.start}: {e.reason}"
                ]
            
            if not text_content.strip():
                return False, ["File contains no data"]
            
            # Parse CSV
            try:
                csv_file = io.StringIO(text_content)
                reader = csv.DictReader(csv_file)
                
                # Validate headers
                if not reader.fieldnames:
                    return False, ["No headers found in CSV file"]
                
                headers_lower = {h.lower().strip() for h in reader.fieldnames if h}
                
                # Check for required headers
                missing_headers = self.REQUIRED_HEADERS - headers_lower
                if missing_headers:
                    return False, [
                        f"Missing required columns: {', '.join(sorted(missing_headers))}. "
                        f"Required columns are: {', '.join(sorted(self.REQUIRED_HEADERS))}"
                    ]
                
                # Check for unexpected headers
                all_valid_headers = self.REQUIRED_HEADERS | self.OPTIONAL_HEADERS
                unexpected_headers = headers_lower - all_valid_headers
                if unexpected_headers:
                    warnings.append(
                        f"Unexpected columns will be ignored: "
                        f"{', '.join(sorted(unexpected_headers))}"
                    )
                
                # Validate rows
                row_errors = self._validate_rows(reader)
                errors.extend(row_errors)
                
                # Add warnings to errors if any
                if warnings:
                    errors.extend([f"Warning: {w}" for w in warnings])
                
                # Determine if validation passed
                # Warnings are OK, but errors are not
                critical_errors = [e for e in errors if not e.startswith("Warning:")]
                is_valid = len(critical_errors) == 0
                
                if is_valid:
                    logger.info("csv_validation_passed", 
                               rows=self.stats["total_processed"],
                               warnings=len(warnings))
                else:
                    logger.warning("csv_validation_failed", 
                                  errors=len(critical_errors),
                                  warnings=len(warnings))
                
                return is_valid, errors
                
            except csv.Error as e:
                return False, [f"CSV parsing error: {str(e)}"]
        
        except Exception as e:
            logger.error("csv_validation_exception", error=str(e), exc_info=True)
            return False, [f"Unexpected validation error: {str(e)}"]
    
    def _validate_rows(self, reader: csv.DictReader) -> List[str]:
        """
        Validate individual CSV rows.
        
        Args:
            reader: CSV DictReader instance
            
        Returns:
            List of error messages
        """
        errors = []
        slugs_seen: Set[str] = set()
        row_num = 0
        
        for row in reader:
            row_num += 1
            
            # Stop if too many rows
            if row_num > self.MAX_ROWS:
                errors.append(
                    f"Too many rows: {row_num}. Maximum allowed is {self.MAX_ROWS}"
                )
                break
            
            # Normalize keys (case-insensitive)
            normalized_row = {k.lower().strip(): v for k, v in row.items() if k}
            
            # Validate slug
            slug = normalized_row.get("slug", "").strip()
            if not slug:
                errors.append(f"Row {row_num}: Slug is required but empty")
                continue
            
            # Check slug format
            if not self.SLUG_PATTERN.match(slug):
                errors.append(
                    f"Row {row_num}: Invalid slug format '{slug}'. "
                    f"Slug must start with '/' and contain only alphanumeric "
                    f"characters, hyphens, and underscores"
                )
            
            # Check for slug path traversal
            if ".." in slug or "//" in slug:
                errors.append(
                    f"Row {row_num}: Invalid slug '{slug}'. "
                    f"Slug cannot contain '..' or '//'"
                )
            
            # Check for duplicate slugs
            slug_lower = slug.lower()
            if slug_lower in slugs_seen:
                errors.append(
                    f"Row {row_num}: Duplicate slug '{slug}'. "
                    f"Each slug must be unique"
                )
            else:
                slugs_seen.add(slug_lower)
            
            # Validate title
            title = normalized_row.get("title", "").strip()
            if title and len(title) > 200:
                errors.append(
                    f"Row {row_num}: Title too long ({len(title)} characters). "
                    f"Maximum is 200 characters"
                )
            
            # Validate meta description
            meta_desc = normalized_row.get("meta_description", "").strip()
            if meta_desc and len(meta_desc) > 300:
                errors.append(
                    f"Row {row_num}: Meta description too long "
                    f"({len(meta_desc)} characters). Maximum is 300 characters"
                )
            
            # Check for excessively long fields
            for key, value in normalized_row.items():
                if value and len(value) > self.MAX_FIELD_LENGTH:
                    errors.append(
                        f"Row {row_num}: Field '{key}' exceeds maximum length "
                        f"({len(value)} > {self.MAX_FIELD_LENGTH} characters)"
                    )
        
        self.stats["total_processed"] = row_num
        self.stats["validation_errors"] = len(errors)
        
        return errors
    
    def parse_csv(self, content: bytes) -> List[PageSchema]:
        """
        Parse CSV content into validated PageSchema objects.
        
        Args:
            content: Raw CSV file content as bytes
            
        Returns:
            List of PageSchema objects
            
        Raises:
            CSVException: If parsing fails
            ValidationException: If data validation fails
        """
        try:
            # Decode content (handle BOM)
            text_content = content.decode("utf-8-sig")
            
            # Parse CSV
            csv_file = io.StringIO(text_content)
            reader = csv.DictReader(csv_file)
            
            pages: List[PageSchema] = []
            slugs_seen: Set[str] = set()
            errors: List[str] = []
            row_num = 0
            
            for row in reader:
                row_num += 1
                
                try:
                    # Normalize keys (case-insensitive)
                    normalized = {
                        k.lower().strip(): v.strip() if v else None
                        for k, v in row.items() if k
                    }
                    
                    slug = normalized.get("slug")
                    if not slug:
                        errors.append(f"Row {row_num}: Missing slug")
                        continue
                    
                    # Normalize slug
                    slug = slug.lower().strip()
                    
                    # Skip duplicates (take first occurrence)
                    if slug in slugs_seen:
                        logger.debug("skipping_duplicate_slug", 
                                   slug=slug, 
                                   row=row_num)
                        continue
                    
                    slugs_seen.add(slug)
                    
                    # Create PageSchema object
                    page = PageSchema(
                        slug=slug,
                        title=normalized.get("title") or None,
                        meta_description=normalized.get("meta_description") or None,
                        updated_at=datetime.utcnow(),
                    )
                    
                    pages.append(page)
                
                except ValidationException as e:
                    errors.append(f"Row {row_num}: {e.message}")
                    logger.warning("row_validation_failed", 
                                 row=row_num, 
                                 error=e.message)
                
                except Exception as e:
                    errors.append(f"Row {row_num}: {str(e)}")
                    logger.warning("row_parsing_failed", 
                                 row=row_num, 
                                 error=str(e))
            
            if errors:
                error_summary = "\n".join(errors[:10])  # Show first 10 errors
                if len(errors) > 10:
                    error_summary += f"\n... and {len(errors) - 10} more errors"
                
                raise CSVException(
                    message=f"CSV parsing completed with {len(errors)} errors",
                    details={"errors": errors, "parsed_rows": len(pages)}
                )
            
            if not pages:
                raise CSVException(
                    message="No valid pages found in CSV file"
                )
            
            logger.info("csv_parsed_successfully", 
                       total_rows=row_num,
                       valid_pages=len(pages),
                       duplicates_skipped=row_num - len(pages))
            
            return pages
        
        except CSVException:
            raise
        
        except Exception as e:
            logger.error("csv_parsing_failed", error=str(e), exc_info=True)
            raise CSVException(
                message="Failed to parse CSV file",
                details={"error": str(e)}
            )
    
    def generate_csv(self, pages: List[PageSchema]) -> bytes:
        """
        Generate CSV file from PageSchema objects.
        
        Args:
            pages: List of PageSchema objects
            
        Returns:
            CSV content as bytes (UTF-8 encoded with BOM)
            
        Raises:
            CSVException: If generation fails
        """
        try:
            if not pages:
                raise CSVException(message="No pages to export")
            
            output = io.StringIO()
            
            # Define fieldnames
            fieldnames = [
                "slug",
                "title",
                "meta_description",
                "updated_at"
            ]
            
            writer = csv.DictWriter(
                output,
                fieldnames=fieldnames,
                quoting=csv.QUOTE_MINIMAL,
                lineterminator='\n'
            )
            
            # Write header
            writer.writeheader()
            
            # Write rows
            for page in pages:
                writer.writerow({
                    "slug": page.slug,
                    "title": page.title or "",
                    "meta_description": page.meta_description or "",
                    "updated_at": page.updated_at.isoformat(),
                })
            
            # Get CSV content
            csv_content = output.getvalue()
            
            # Encode with BOM for better Excel compatibility
            csv_bytes = csv_content.encode("utf-8-sig")
            
            logger.info("csv_generated", 
                       rows=len(pages),
                       size_kb=len(csv_bytes) / 1024)
            
            return csv_bytes
        
        except CSVException:
            raise
        
        except Exception as e:
            logger.error("csv_generation_failed", error=str(e), exc_info=True)
            raise CSVException(
                message="Failed to generate CSV file",
                details={"error": str(e), "page_count": len(pages)}
            )
    
    def get_template_csv(self) -> bytes:
        """
        Generate a template CSV file with example data.
        
        Returns:
            Template CSV content as bytes
        """
        template_pages = [
            PageSchema(
                slug="/example/page-one",
                title="Example Page One - SEO Title",
                meta_description="This is an example meta description for page one. "
                                "Keep it under 160 characters for best results.",
            ),
            PageSchema(
                slug="/example/page-two",
                title="Example Page Two - Another Title",
                meta_description="Another example meta description. "
                                "Make it compelling and relevant!",
            ),
            PageSchema(
                slug="/blog/seo-best-practices",
                title="SEO Best Practices 2025 | Complete Guide",
                meta_description="Learn the latest SEO best practices for 2025. "
                                "Improve your rankings with proven strategies.",
            ),
        ]
        
        return self.generate_csv(template_pages)
    
    def analyze_csv(self, content: bytes) -> Dict[str, Any]:
        """
        Analyze CSV file and return statistics.
        
        Args:
            content: Raw CSV file content
            
        Returns:
            Dictionary with analysis results
        """
        try:
            text_content = content.decode("utf-8-sig")
            csv_file = io.StringIO(text_content)
            reader = csv.DictReader(csv_file)
            
            stats = {
                "total_rows": 0,
                "unique_slugs": set(),
                "empty_titles": 0,
                "empty_descriptions": 0,
                "avg_title_length": 0,
                "avg_description_length": 0,
                "title_lengths": [],
                "description_lengths": [],
            }
            
            for row in reader:
                stats["total_rows"] += 1
                normalized = {k.lower().strip(): v for k, v in row.items() if k}
                
                slug = normalized.get("slug", "").strip()
                if slug:
                    stats["unique_slugs"].add(slug.lower())
                
                title = normalized.get("title", "").strip()
                if not title:
                    stats["empty_titles"] += 1
                else:
                    stats["title_lengths"].append(len(title))
                
                desc = normalized.get("meta_description", "").strip()
                if not desc:
                    stats["empty_descriptions"] += 1
                else:
                    stats["description_lengths"].append(len(desc))
            
            # Calculate averages
            if stats["title_lengths"]:
                stats["avg_title_length"] = (
                    sum(stats["title_lengths"]) / len(stats["title_lengths"])
                )
            
            if stats["description_lengths"]:
                stats["avg_description_length"] = (
                    sum(stats["description_lengths"]) / 
                    len(stats["description_lengths"])
                )
            
            # Convert set to count
            stats["unique_slugs"] = len(stats["unique_slugs"])
            
            # Remove raw lists
            del stats["title_lengths"]
            del stats["description_lengths"]
            
            return stats
        
        except Exception as e:
            logger.error("csv_analysis_failed", error=str(e))
            return {"error": str(e)}


# Singleton instance
csv_handler = CSVHandler()