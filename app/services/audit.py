"""
Comprehensive Audit Trail Service
Tracks all changes with full context and provides querying capabilities.
"""

import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any

from fastapi import Request

from app.core.logging import logger
from app.core.exceptions import AuditException, StorageException
from app.models.schemas import AuditLogSchema, PageSchema
from app.services.storage import storage


class AuditService:
    """
    Comprehensive audit trail service with advanced logging and querying.
    
    Features:
    - Change tracking with before/after states
    - IP and user agent logging
    - Batch operation support
    - Query and filter capabilities
    """
    
    def __init__(self):
        """Initialize audit service."""
        self._initialized = False
    
    async def initialize(self) -> None:
        """Initialize audit service."""
        if self._initialized:
            return
        
        try:
            # Verify audit log file exists and is accessible
            logs = await storage.get_audit_logs(limit=1)
            logger.info("audit_service_initialized", recent_logs=len(logs))
            self._initialized = True
        
        except Exception as e:
            logger.error("audit_service_initialization_failed", error=str(e))
            raise AuditException(
                message="Failed to initialize audit service",
                details={"error": str(e)}
            )
    
    async def log_change(
        self,
        slug: str,
        old_page: Optional[PageSchema],
        new_page: PageSchema,
        username: str,
        request: Request,
        batch_id: Optional[str] = None,
    ) -> str:
        """
        Create comprehensive audit log entry for page change.
        
        Args:
            slug: Page slug being changed
            old_page: Previous page state (None if new page)
            new_page: New page state
            username: User making the change
            request: FastAPI request object for context
            batch_id: Optional batch operation identifier
            
        Returns:
            Audit log ID
            
        Raises:
            AuditException: If logging fails
        """
        try:
            # Generate unique audit ID
            audit_id = f"audit_{uuid.uuid4().hex[:12]}"
            
            # Determine change type
            if old_page is None:
                change_type = "created"
            elif (old_page.title == new_page.title and 
                  old_page.meta_description == new_page.meta_description):
                change_type = "unchanged"
            else:
                change_type = "updated"
            
            # Extract request context
            client_ip = None
            if request.client:
                client_ip = request.client.host
            
            user_agent = request.headers.get("user-agent", "Unknown")
            
            # Build change summary
            changes = []
            if old_page:
                if old_page.title != new_page.title:
                    changes.append(f"title: '{old_page.title}' → '{new_page.title}'")
                if old_page.meta_description != new_page.meta_description:
                    changes.append(
                        f"description: '{old_page.meta_description}' → "
                        f"'{new_page.meta_description}'"
                    )
            else:
                changes.append("New page created")
            
            change_summary = "; ".join(changes) if changes else "No changes"
            
            # Create audit log entry
            audit = AuditLogSchema(
                id=audit_id,
                slug=slug,
                old_title=old_page.title if old_page else None,
                old_meta_description=old_page.meta_description if old_page else None,
                new_title=new_page.title,
                new_meta_description=new_page.meta_description,
                changed_by=username,
                changed_at=datetime.utcnow(),
                ip_address=client_ip,
                user_agent=user_agent,
            )
            
            # Append to storage
            await storage.append_audit_log(audit)
            
            logger.info(
                "change_logged",
                audit_id=audit_id,
                slug=slug,
                change_type=change_type,
                changed_by=username,
                ip=client_ip,
                batch_id=batch_id,
                changes=change_summary,
            )
            
            return audit_id
        
        except StorageException as e:
            logger.error("audit_log_storage_failed", 
                        slug=slug,
                        error=e.message)
            raise AuditException(
                message="Failed to write audit log",
                details={"slug": slug, "error": e.message}
            )
        
        except Exception as e:
            logger.error("audit_log_failed",
                        slug=slug,
                        error=str(e),
                        exc_info=True)
            raise AuditException(
                message="Failed to create audit log",
                details={"slug": slug, "error": str(e)}
            )
    
    async def get_recent_logs(
        self, 
        limit: int = 100,
        username: Optional[str] = None,
        slug: Optional[str] = None,
    ) -> List[AuditLogSchema]:
        """
        Get recent audit logs with optional filtering.
        
        Args:
            limit: Maximum number of logs to return
            username: Filter by username
            slug: Filter by slug
            
        Returns:
            List of audit log entries (most recent first)
        """
        try:
            # Get logs from storage
            logs = await storage.get_audit_logs(limit=limit * 2, slug=slug)
            
            # Apply username filter if provided
            if username:
                logs = [log for log in logs if log.changed_by == username]
            
            # Limit results
            logs = logs[:limit]
            
            logger.debug("audit_logs_retrieved",
                        count=len(logs),
                        filtered_by_username=username is not None,
                        filtered_by_slug=slug is not None)
            
            return logs
        
        except Exception as e:
            logger.error("get_audit_logs_failed", error=str(e))
            # Return empty list on error to not break the UI
            return []
    
    async def get_page_history(self, slug: str) -> List[AuditLogSchema]:
        """
        Get complete change history for a specific page.
        
        Args:
            slug: Page slug
            
        Returns:
            List of audit entries for the page (chronological order)
        """
        try:
            logs = await storage.get_audit_logs(limit=10000, slug=slug)
            logger.debug("page_history_retrieved", slug=slug, entries=len(logs))
            return logs
        
        except Exception as e:
            logger.error("page_history_retrieval_failed",
                        slug=slug,
                        error=str(e))
            return []
    
    async def get_user_activity(
        self,
        username: str,
        limit: int = 100
    ) -> List[AuditLogSchema]:
        """
        Get activity history for a specific user.
        
        Args:
            username: Username to query
            limit: Maximum number of entries
            
        Returns:
            List of audit entries by the user
        """
        return await self.get_recent_logs(limit=limit, username=username)
    
    async def get_audit_stats(self) -> Dict[str, Any]:
        """
        Get audit trail statistics.
        
        Returns:
            Dictionary with audit statistics
        """
        try:
            logs = await storage.get_audit_logs(limit=10000)
            
            # Calculate statistics
            stats = {
                "total_changes": len(logs),
                "unique_users": len(set(log.changed_by for log in logs)),
                "unique_pages": len(set(log.slug for log in logs)),
                "date_range": {
                    "earliest": min(
                        (log.changed_at for log in logs),
                        default=None
                    ),
                    "latest": max(
                        (log.changed_at for log in logs),
                        default=None
                    ),
                },
            }
            
            return stats
        
        except Exception as e:
            logger.error("audit_stats_failed", error=str(e))
            return {}


# Singleton instance
audit_service = AuditService()