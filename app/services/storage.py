"""
JSON Storage Service with Atomic Writes and Data Integrity
Provides robust file-based storage with error recovery and validation.
"""

import json
import aiofiles
import asyncio
from pathlib import Path
from typing import List, Optional, Any, Dict
from datetime import datetime
from pydantic import TypeAdapter, ValidationError

from app.core.config import get_settings
from app.core.logging import logger
from app.core.exceptions import StorageException, ValidationException
from app.models.schemas import PageSchema, AuditLogSchema


class JSONStorage:
    """
    Atomic JSON file storage with async I/O and comprehensive error handling.
    
    Features:
    - Atomic writes using temp files
    - Automatic backup creation
    - Data validation
    - Error recovery
    - File locking support
    """
    
    # Constants
    MAX_AUDIT_RECORDS = 10000
    MAX_PAGES = 50000
    BACKUP_SUFFIX = ".backup"
    LOCK_TIMEOUT = 30  # seconds
    
    def __init__(self):
        """Initialize storage with configuration."""
        self.cfg = get_settings()
        self.pages_path = self.cfg.pages_file
        self.audit_path = self.cfg.audit_file
        self._initialized = False
        self._write_locks: Dict[str, asyncio.Lock] = {
            "pages": asyncio.Lock(),
            "audit": asyncio.Lock(),
        }
    
    async def initialize(self) -> None:
        """
        Initialize storage directories and files.
        Creates directory structure and ensures files exist with valid data.
        """
        if self._initialized:
            logger.debug("storage_already_initialized")
            return
        
        try:
            # Ensure data directory exists
            data_dir = self.cfg.data_dir_path
            logger.info("initializing_storage", data_dir=str(data_dir))
            
            # Initialize pages file
            if not self.pages_path.exists():
                logger.info("creating_pages_file", path=str(self.pages_path))
                await self._write_json(self.pages_path, [])
            else:
                # Validate existing pages file
                try:
                    pages_data = await self._read_json(self.pages_path)
                    # Try to parse as PageSchema to validate structure
                    TypeAdapter(List[PageSchema]).validate_python(pages_data)
                    logger.info("pages_file_validated", 
                               path=str(self.pages_path),
                               records=len(pages_data))
                except Exception as e:
                    logger.warning("pages_file_corrupted", 
                                 error=str(e),
                                 action="creating_backup")
                    # Create backup of corrupted file
                    backup_path = self.pages_path.with_suffix(
                        self.pages_path.suffix + self.BACKUP_SUFFIX
                    )
                    if self.pages_path.exists():
                        self.pages_path.rename(backup_path)
                    # Initialize with empty file
                    await self._write_json(self.pages_path, [])
            
            # Initialize audit log file
            if not self.audit_path.exists():
                logger.info("creating_audit_file", path=str(self.audit_path))
                await self._write_json(self.audit_path, [])
            else:
                # Validate existing audit file
                try:
                    audit_data = await self._read_json(self.audit_path)
                    logger.info("audit_file_validated",
                               path=str(self.audit_path),
                               records=len(audit_data))
                except Exception as e:
                    logger.warning("audit_file_corrupted",
                                 error=str(e),
                                 action="creating_backup")
                    # Create backup of corrupted file
                    backup_path = self.audit_path.with_suffix(
                        self.audit_path.suffix + self.BACKUP_SUFFIX
                    )
                    if self.audit_path.exists():
                        self.audit_path.rename(backup_path)
                    # Initialize with empty file
                    await self._write_json(self.audit_path, [])
            
            self._initialized = True
            logger.info("storage_initialized_successfully")
            
        except Exception as e:
            logger.error("storage_initialization_failed", 
                        error=str(e), 
                        exc_info=True)
            raise StorageException(
                message="Failed to initialize storage",
                details={"error": str(e)}
            )
    
    async def _read_json(self, path: Path) -> List[Dict[str, Any]]:
        """
        Safely read JSON file with error recovery.
        
        Args:
            path: Path to JSON file
            
        Returns:
            List of dictionaries from JSON file
            
        Raises:
            StorageException: If file cannot be read or parsed
        """
        try:
            if not path.exists():
                logger.warning("file_not_found", path=str(path))
                return []
            
            # Check file size
            file_size = path.stat().st_size
            if file_size == 0:
                logger.warning("empty_file", path=str(path))
                return []
            
            if file_size > 100 * 1024 * 1024:  # 100MB limit
                logger.error("file_too_large", 
                            path=str(path), 
                            size_mb=file_size / 1024 / 1024)
                raise StorageException(
                    message=f"File too large: {file_size / 1024 / 1024:.2f}MB"
                )
            
            # Read file
            async with aiofiles.open(path, "r", encoding="utf-8") as f:
                content = await f.read()
            
            # Parse JSON
            if not content.strip():
                return []
            
            data = json.loads(content)
            
            if not isinstance(data, list):
                logger.error("invalid_json_structure", 
                            path=str(path),
                            type=type(data).__name__)
                raise StorageException(
                    message="Invalid JSON structure: expected list"
                )
            
            logger.debug("file_read_success", 
                        path=str(path), 
                        records=len(data))
            
            return data
            
        except json.JSONDecodeError as e:
            logger.error("json_parse_error", 
                        path=str(path), 
                        error=str(e),
                        line=e.lineno,
                        column=e.colno)
            raise StorageException(
                message=f"Invalid JSON in {path.name}",
                details={"error": str(e), "line": e.lineno, "column": e.colno}
            )
        
        except Exception as e:
            logger.error("file_read_error", 
                        path=str(path), 
                        error=str(e),
                        exc_info=True)
            raise StorageException(
                message=f"Failed to read {path.name}",
                details={"error": str(e)}
            )
    
    async def _write_json(
        self, 
        path: Path, 
        data: List[Dict[str, Any]],
        create_backup: bool = True
    ) -> None:
        """
        Atomically write JSON file using temp file + rename pattern.
        
        Args:
            path: Path to JSON file
            data: Data to write
            create_backup: Whether to create backup of existing file
            
        Raises:
            StorageException: If file cannot be written
        """
        # Get appropriate lock
        lock_key = "pages" if "pages" in str(path) else "audit"
        lock = self._write_locks.get(lock_key, asyncio.Lock())
        
        async with lock:
            temp_path = path.with_suffix(".tmp")
            backup_path = path.with_suffix(path.suffix + self.BACKUP_SUFFIX)
            
            try:
                # Validate data structure
                if not isinstance(data, list):
                    raise StorageException(
                        message="Data must be a list",
                        details={"type": type(data).__name__}
                    )
                
                # Check record count limits
                if "pages" in str(path) and len(data) > self.MAX_PAGES:
                    raise StorageException(
                        message=f"Too many pages: {len(data)} (max: {self.MAX_PAGES})"
                    )
                
                # Serialize data
                json_content = json.dumps(
                    data, 
                    indent=2, 
                    ensure_ascii=False,
                    default=str
                )
                
                # Write to temporary file
                async with aiofiles.open(temp_path, "w", encoding="utf-8") as f:
                    await f.write(json_content)
                
                # Verify temp file was written correctly
                async with aiofiles.open(temp_path, "r", encoding="utf-8") as f:
                    verify_content = await f.read()
                    json.loads(verify_content)  # Verify it's valid JSON
                
                # Create backup of existing file
                if create_backup and path.exists():
                    try:
                        # Read existing file to verify it's valid before backup
                        async with aiofiles.open(path, "r", encoding="utf-8") as f:
                            existing_content = await f.read()
                            json.loads(existing_content)  # Verify valid JSON
                        
                        # Create backup
                        if backup_path.exists():
                            backup_path.unlink()
                        
                        # Copy current file to backup
                        async with aiofiles.open(path, "r", encoding="utf-8") as src:
                            content = await src.read()
                        async with aiofiles.open(backup_path, "w", encoding="utf-8") as dst:
                            await dst.write(content)
                        
                        logger.debug("backup_created", path=str(backup_path))
                    
                    except Exception as e:
                        logger.warning("backup_creation_failed", 
                                      error=str(e),
                                      message="Continuing with write operation")
                
                # Atomic rename (replace existing file)
                temp_path.replace(path)
                
                logger.debug("file_write_success", 
                            path=str(path), 
                            records=len(data),
                            size_kb=len(json_content) / 1024)
                
            except json.JSONDecodeError as e:
                logger.error("json_serialization_error", 
                            path=str(path),
                            error=str(e))
                if temp_path.exists():
                    temp_path.unlink()
                raise StorageException(
                    message="Failed to serialize data to JSON",
                    details={"error": str(e)}
                )
            
            except Exception as e:
                logger.error("file_write_error", 
                            path=str(path), 
                            error=str(e),
                            exc_info=True)
                # Clean up temp file
                if temp_path.exists():
                    try:
                        temp_path.unlink()
                    except:
                        pass
                raise StorageException(
                    message=f"Failed to write {path.name}",
                    details={"error": str(e)}
                )
    
    async def get_all_pages(self) -> List[PageSchema]:
        """
        Retrieve all pages from storage.
        
        Returns:
            List of validated PageSchema objects
            
        Raises:
            StorageException: If pages cannot be retrieved
            ValidationException: If page data is invalid
        """
        try:
            data = await self._read_json(self.pages_path)
            
            # Validate and convert to PageSchema objects
            try:
                pages = TypeAdapter(List[PageSchema]).validate_python(data)
                logger.debug("pages_retrieved", count=len(pages))
                return pages
            
            except ValidationError as e:
                logger.error("page_validation_failed", 
                            error=str(e),
                            errors=e.errors())
                raise ValidationException(
                    message="Invalid page data in storage",
                    details={"errors": e.errors()}
                )
        
        except StorageException:
            raise
        except Exception as e:
            logger.error("get_pages_failed", error=str(e), exc_info=True)
            raise StorageException(
                message="Failed to retrieve pages",
                details={"error": str(e)}
            )
    
    async def get_page(self, slug: str) -> Optional[PageSchema]:
        """
        Get single page by slug.
        
        Args:
            slug: Page slug to retrieve
            
        Returns:
            PageSchema if found, None otherwise
        """
        pages = await self.get_all_pages()
        page = next((p for p in pages if p.slug == slug), None)
        
        if page:
            logger.debug("page_found", slug=slug)
        else:
            logger.debug("page_not_found", slug=slug)
        
        return page
    
    async def save_pages(self, pages: List[PageSchema]) -> None:
        """
        Save all pages to storage (atomic replacement).
        
        Args:
            pages: List of PageSchema objects to save
            
        Raises:
            StorageException: If pages cannot be saved
            ValidationException: If page data is invalid
        """
        try:
            # Validate all pages
            for i, page in enumerate(pages):
                if not isinstance(page, PageSchema):
                    raise ValidationException(
                        message=f"Invalid page at index {i}",
                        details={"index": i, "type": type(page).__name__}
                    )
            
            # Convert to dictionaries for JSON serialization
            data = [page.model_dump(mode="json") for page in pages]
            
            # Write to storage
            await self._write_json(self.pages_path, data)
            
            logger.info("pages_saved", count=len(pages))
            
        except (StorageException, ValidationException):
            raise
        except Exception as e:
            logger.error("save_pages_failed", 
                        error=str(e), 
                        exc_info=True)
            raise StorageException(
                message="Failed to save pages",
                details={"error": str(e), "page_count": len(pages)}
            )
    
    async def append_audit_log(self, log: AuditLogSchema) -> None:
        """
        Append audit entry to log (with automatic rotation).
        
        Args:
            log: AuditLogSchema object to append
            
        Raises:
            StorageException: If audit log cannot be updated
        """
        try:
            # Validate audit log entry
            if not isinstance(log, AuditLogSchema):
                raise ValidationException(
                    message="Invalid audit log entry",
                    details={"type": type(log).__name__}
                )
            
            # Read existing logs
            logs = await self._read_json(self.audit_path)
            
            # Append new log
            logs.append(log.model_dump(mode="json"))
            
            # Rotate if needed (keep only last MAX_AUDIT_RECORDS)
            if len(logs) > self.MAX_AUDIT_RECORDS:
                removed_count = len(logs) - self.MAX_AUDIT_RECORDS
                logs = logs[-self.MAX_AUDIT_RECORDS:]
                logger.info("audit_log_rotated", 
                           removed=removed_count,
                           kept=self.MAX_AUDIT_RECORDS)
            
            # Write back to storage
            await self._write_json(self.audit_path, logs)
            
            logger.info("audit_log_appended", 
                       audit_id=log.id, 
                       slug=log.slug,
                       total_records=len(logs))
            
        except (StorageException, ValidationException):
            raise
        except Exception as e:
            logger.error("append_audit_log_failed", 
                        error=str(e), 
                        exc_info=True)
            raise StorageException(
                message="Failed to append audit log",
                details={"error": str(e)}
            )
    
    async def get_audit_logs(
        self, 
        limit: int = 100,
        slug: Optional[str] = None
    ) -> List[AuditLogSchema]:
        """
        Get recent audit logs with optional filtering.
        
        Args:
            limit: Maximum number of logs to return
            slug: Optional slug to filter by
            
        Returns:
            List of AuditLogSchema objects
        """
        try:
            data = await self._read_json(self.audit_path)
            
            # Filter by slug if provided
            if slug:
                data = [log for log in data if log.get("slug") == slug]
            
            # Get most recent logs
            data = data[-limit:]
            
            # Validate and convert to AuditLogSchema objects
            try:
                logs = TypeAdapter(List[AuditLogSchema]).validate_python(data)
                logger.debug("audit_logs_retrieved", 
                            count=len(logs),
                            filtered_by_slug=slug is not None)
                return list(reversed(logs))  # Most recent first
            
            except ValidationError as e:
                logger.error("audit_log_validation_failed", 
                            error=str(e),
                            errors=e.errors())
                raise ValidationException(
                    message="Invalid audit log data in storage",
                    details={"errors": e.errors()}
                )
        
        except (StorageException, ValidationException):
            raise
        except Exception as e:
            logger.error("get_audit_logs_failed", error=str(e), exc_info=True)
            raise StorageException(
                message="Failed to retrieve audit logs",
                details={"error": str(e)}
            )
    
    async def get_storage_stats(self) -> Dict[str, Any]:
        """
        Get storage statistics.
        
        Returns:
            Dictionary with storage statistics
        """
        try:
            pages = await self.get_all_pages()
            audit_data = await self._read_json(self.audit_path)
            
            pages_size = self.pages_path.stat().st_size if self.pages_path.exists() else 0
            audit_size = self.audit_path.stat().st_size if self.audit_path.exists() else 0
            
            stats = {
                "pages": {
                    "count": len(pages),
                    "file_size_kb": pages_size / 1024,
                    "path": str(self.pages_path),
                },
                "audit_logs": {
                    "count": len(audit_data),
                    "file_size_kb": audit_size / 1024,
                    "path": str(self.audit_path),
                },
                "total_size_kb": (pages_size + audit_size) / 1024,
            }
            
            logger.debug("storage_stats_retrieved", stats=stats)
            return stats
        
        except Exception as e:
            logger.error("get_storage_stats_failed", error=str(e))
            return {}
    
    async def close(self) -> None:
        """Cleanup resources on shutdown."""
        logger.info("storage_closing")
        self._initialized = False


# Singleton instance
storage = JSONStorage()