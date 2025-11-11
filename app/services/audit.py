import uuid
from datetime import datetime
from typing import Optional
from fastapi import Request
from app.core.logging import logger
from app.models.schemas import AuditLogSchema, PageSchema
from app.services.storage import storage

class AuditService:
    """Comprehensive audit trail service"""
    
    @staticmethod
    async def log_change(
        slug: str,
        old_page: Optional[PageSchema],
        new_page: PageSchema,
        username: str,
        request: Request,
    ) -> str:
        """Create audit log entry for page change"""
        audit_id = f"audit_{uuid.uuid4().hex[:12]}"
        
        audit = AuditLogSchema(
            id=audit_id,
            slug=slug,
            old_title=old_page.title if old_page else None,
            old_meta_description=old_page.meta_description if old_page else None,
            new_title=new_page.title,
            new_meta_description=new_page.meta_description,
            changed_by=username,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
        
        await storage.append_audit_log(audit)
        logger.info("change_logged", audit_id=audit_id, slug=slug, by=username)
        return audit_id
    
    @staticmethod
    async def get_recent_logs(limit: int = 100) -> list[AuditLogSchema]:
        """Get recent audit logs"""
        logs = await storage._read_json(storage.audit_path)
        return [AuditLogSchema(**log) for log in logs[-limit:]]

audit_service = AuditService()