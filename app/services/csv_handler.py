import csv
import io
from typing import List, Dict, Tuple
from datetime import datetime
from app.models.schemas import PageSchema
from app.core.logging import logger

class CSVHandler:
    """Production-grade CSV parser with validation"""
    
    REQUIRED_HEADERS = {"slug", "title", "meta_description"}
    
    def validate_csv_file(self, content: bytes) -> Tuple[bool, List[str]]:
        """Validate CSV structure and headers"""
        errors = []
        
        try:
            text_content = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            return False, ["File must be UTF-8 encoded"]
        
        if not text_content.strip():
            return False, ["File is empty"]
        
        try:
            reader = csv.DictReader(io.StringIO(text_content))
            
            # Check headers
            if not reader.fieldnames:
                return False, ["No headers found"]
            
            missing = self.REQUIRED_HEADERS - set(f.lower() for f in reader.fieldnames)
            if missing:
                return False, [f"Missing required columns: {', '.join(missing)}"]
            
            # Validate rows
            row_num = 0
            for row in reader:
                row_num += 1
                if not row.get("slug"):
                    errors.append(f"Row {row_num}: Empty slug")
                if row_num > 10000:
                    errors.append("Maximum 10,000 rows allowed")
                    break
            
        except csv.Error as e:
            return False, [f"CSV parsing error: {str(e)}"]
        
        return len(errors) == 0, errors
    
    def parse_csv(self, content: bytes) -> List[PageSchema]:
        """Parse CSV content into PageSchema objects"""
        text_content = content.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text_content))
        
        pages = []
        for row in reader:
            # Normalize keys (case-insensitive)
            normalized = {k.lower(): v for k, v in row.items()}
            
            pages.append(PageSchema(
                slug=normalized["slug"].strip().lower(),
                title=normalized["title"].strip() if normalized.get("title") else None,
                meta_description=normalized["meta_description"].strip() if normalized.get("meta_description") else None,
                updated_at=datetime.utcnow(),
            ))
        
        logger.info("csv_parsed", rows=len(pages))
        return pages
    
    def generate_csv(self, pages: List[PageSchema]) -> bytes:
        """Generate CSV from pages"""
        output = io.StringIO()
        fieldnames = ["slug", "title", "meta_description", "updated_at"]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        
        for page in pages:
            writer.writerow({
                "slug": page.slug,
                "title": page.title or "",
                "meta_description": page.meta_description or "",
                "updated_at": page.updated_at.isoformat(),
            })
        
        logger.info("csv_generated", rows=len(pages))
        return output.getvalue().encode("utf-8")

csv_handler = CSVHandler()