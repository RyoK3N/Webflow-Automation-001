import json
import aiofiles
from pathlib import Path
from typing import List, Optional, Any
from datetime import datetime
from pydantic import TypeAdapter
from app.core.config import get_settings
from app.core.logging import logger
from app.models.schemas import PageSchema, AuditLogSchema

class JSONStorage:
    """Atomic JSON file storage with async I/O"""
    
    def __init__(self):
        self.cfg = get_settings()
        self.pages_path = self.cfg.pages_file
        self.audit_path = self.cfg.audit_file
    
    async def _read_json(self, path: Path) -> List[dict]:
        """Safely read JSON file with error recovery"""
        try:
            if not path.exists():
                await self._write_json(path, [])
                return []
            
            async with aiofiles.open(path, "r") as f:
                content = await f.read()
                return json.loads(content) if content.strip() else []
        except Exception as e:
            logger.error("storage_read_error", path=str(path), error=str(e))
            raise
    
    async def _write_json(self, path: Path, data: list) -> None:
        """Atomic write using temp file + rename"""
        temp_path = path.with_suffix(".tmp")
        try:
            async with aiofiles.open(temp_path, "w") as f:
                await f.write(json.dumps(data, indent=2, default=str))
            temp_path.replace(path)
            logger.debug("storage_write_success", path=str(path), records=len(data))
        except Exception as e:
            logger.error("storage_write_error", path=str(path), error=str(e))
            if temp_path.exists():
                temp_path.unlink()
            raise
    
    async def get_all_pages(self) -> List[PageSchema]:
        """Retrieve all pages"""
        data = await self._read_json(self.pages_path)
        return TypeAdapter(List[PageSchema]).validate_python(data)
    
    async def get_page(self, slug: str) -> Optional[PageSchema]:
        """Get single page by slug"""
        pages = await self.get_all_pages()
        return next((p for p in pages if p.slug == slug), None)
    
    async def save_pages(self, pages: List[PageSchema]) -> None:
        """Overwrite all pages (atomic)"""
        data = [page.model_dump(mode="json") for page in pages]
        await self._write_json(self.pages_path, data)
        logger.info("pages_saved", count=len(pages))
    
    async def append_audit_log(self, log: AuditLogSchema) -> None:
        """Append audit entry (max 10k records, FIFO)"""
        logs = await self._read_json(self.audit_path)
        logs.append(log.model_dump(mode="json"))
        
        # Keep only last 10k records
        if len(logs) > 10000:
            logs = logs[-10000:]
            logger.info("audit_log_truncated", kept=10000)
        
        await self._write_json(self.audit_path, logs)
        logger.info("audit_log_appended", audit_id=log.id, slug=log.slug)

# Singleton instance
storage = JSONStorage()