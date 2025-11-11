from datetime import datetime
from pydantic import BaseModel, Field, field_validator
from typing import Optional, List

class PageSchema(BaseModel):
    """Webflow page metadata schema"""
    slug: str = Field(..., min_length=1, max_length=500)
    title: Optional[str] = Field(None, max_length=200)
    meta_description: Optional[str] = Field(None, max_length=300)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    @field_validator("slug")
    @classmethod
    def validate_slug(cls, v: str) -> str:
        """Sanitize slug"""
        if not v.startswith("/"):
            raise ValueError("Slug must start with /")
        if ".." in v or v.count("//") > 0:
            raise ValueError("Invalid slug path")
        return v.strip().lower()
    
    class Config:
        json_schema_extra = {
            "example": {
                "slug": "/blog/seo-tips",
                "title": "SEO Tips 2025",
                "meta_description": "Expert SEO strategies for modern websites",
            }
        }

class AuditLogSchema(BaseModel):
    """Audit trail for all changes"""
    id: str = Field(..., description="Unique audit ID")
    slug: str = Field(...)
    old_title: Optional[str] = None
    old_meta_description: Optional[str] = None
    new_title: Optional[str] = None
    new_meta_description: Optional[str] = None
    changed_by: str = Field(...)
    changed_at: datetime = Field(default_factory=datetime.utcnow)
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    
    class Config:
        json_schema_extra = {
            "example": {
                "id": "audit_123",
                "slug": "/blog/seo-tips",
                "old_title": "Old Title",
                "new_title": "New Title",
                "changed_by": "Admin",
            }
        }

class CSVUploadResponse(BaseModel):
    """Response for CSV upload operation"""
    success: bool
    message: str
    processed: int
    errors: List[str] = Field(default_factory=list)
    audit_id: Optional[str] = None

class ToastMessage(BaseModel):
    """Frontend toast notification"""
    type: str = Field(..., pattern="^(success|error|warning|info)$")
    message: str
    duration: int = Field(default=5000)