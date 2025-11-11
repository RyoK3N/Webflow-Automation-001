"""
Automation API Routes with Complete HTMX Support
Handles CSV export, upload, and audit trail display.
"""

import uuid
from typing import List, Dict, Any
from datetime import datetime

from fastapi import APIRouter, Request, Depends, UploadFile, File, HTTPException, Response
from fastapi.responses import StreamingResponse, HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from app.core.security import security_manager
from app.core.logging import logger
from app.core.exceptions import (
    CSVException,
    StorageException,
    ValidationException,
    AppException
)
from app.services.storage import storage
from app.services.csv_handler import csv_handler
from app.services.audit import audit_service
from app.models.schemas import CSVUploadResponse, PageSchema


router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
async def automation_page(
    request: Request,
    username: str = Depends(security_manager.require_auth),
) -> HTMLResponse:
    """
    Display automation dashboard with upload/export controls.
    
    Args:
        request: FastAPI request object
        username: Authenticated username from dependency
        
    Returns:
        HTML response with automation page
    """
    try:
        request.state.username = username
        
        # Get recent audit logs for display
        try:
            recent_logs = await audit_service.get_recent_logs(limit=10)
        except Exception as e:
            logger.warning("failed_to_load_audit_logs", error=str(e))
            recent_logs = []
        
        # Get storage statistics
        try:
            storage_stats = await storage.get_storage_stats()
        except Exception as e:
            logger.warning("failed_to_load_storage_stats", error=str(e))
            storage_stats = {}
        
        logger.info("automation_page_accessed", 
                   username=username,
                   recent_logs=len(recent_logs))
        
        return templates.TemplateResponse(
            "automation.html",
            {
                "request": request,
                "username": username,
                "recent_logs": recent_logs,
                "storage_stats": storage_stats,
            },
        )
    
    except Exception as e:
        logger.error("automation_page_error", 
                    error=str(e), 
                    exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Failed to load automation page"
        )


@router.get("/export")
async def export_csv(
    request: Request,
    username: str = Depends(security_manager.require_auth),
) -> StreamingResponse:
    """
    Export all pages as CSV file.
    
    Args:
        request: FastAPI request object
        username: Authenticated username
        
    Returns:
        StreamingResponse with CSV file
        
    Raises:
        HTTPException: If export fails
    """
    try:
        logger.info("export_initiated", username=username)
        
        # Get all pages from storage
        pages = await storage.get_all_pages()
        
        if not pages:
            logger.warning("export_no_pages", username=username)
            raise HTTPException(
                status_code=400,
                detail="No pages available to export. Please upload a CSV first."
            )
        
        # Generate CSV
        csv_bytes = csv_handler.generate_csv(pages)
        
        # Generate unique filename
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"webflow-pages-export-{timestamp}.csv"
        
        # Log successful export
        logger.info("export_successful", 
                   username=username,
                   page_count=len(pages),
                   file_size_kb=len(csv_bytes) / 1024)
        
        # Return CSV file
        return StreamingResponse(
            iter([csv_bytes]),
            media_type="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Content-Length": str(len(csv_bytes)),
                "X-Page-Count": str(len(pages)),
            },
        )
    
    except HTTPException:
        raise
    
    except CSVException as e:
        logger.error("export_csv_error", 
                    username=username,
                    error=e.message,
                    details=e.details)
        raise HTTPException(status_code=400, detail=e.message)
    
    except StorageException as e:
        logger.error("export_storage_error",
                    username=username,
                    error=e.message)
        raise HTTPException(status_code=500, detail=e.message)
    
    except Exception as e:
        logger.error("export_unexpected_error", 
                    username=username,
                    error=str(e),
                    exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Failed to export CSV. Please try again."
        )


@router.get("/export/template")
async def export_template(
    request: Request,
    username: str = Depends(security_manager.require_auth),
) -> StreamingResponse:
    """
    Download CSV template with example data.
    
    Args:
        request: FastAPI request object
        username: Authenticated username
        
    Returns:
        StreamingResponse with template CSV
    """
    try:
        logger.info("template_download_initiated", username=username)
        
        # Generate template CSV
        template_csv = csv_handler.get_template_csv()
        
        return StreamingResponse(
            iter([template_csv]),
            media_type="text/csv",
            headers={
                "Content-Disposition": 'attachment; filename="webflow-template.csv"',
                "Content-Length": str(len(template_csv)),
            },
        )
    
    except Exception as e:
        logger.error("template_download_error", 
                    error=str(e), 
                    exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Failed to generate template"
        )


@router.post("/upload")
async def upload_csv(
    request: Request,
    file: UploadFile = File(...),
    username: str = Depends(security_manager.require_auth),
) -> Response:
    """
    Upload and process CSV file with comprehensive validation.
    Returns HTMX-compatible HTML response.
    
    Args:
        request: FastAPI request object
        file: Uploaded CSV file
        username: Authenticated username
        
    Returns:
        HTML response for HTMX or JSON for API clients
    """
    request_id = getattr(request.state, "request_id", "unknown")
    
    try:
        logger.info("csv_upload_initiated", 
                   username=username,
                   filename=file.filename,
                   content_type=file.content_type)
        
        # Validate file type
        if not file.filename:
            raise HTTPException(400, "No file provided")
        
        if not file.filename.lower().endswith(".csv"):
            raise HTTPException(
                400,
                "Invalid file type. Only CSV files are allowed."
            )
        
        # Read file content
        content = await file.read()
        
        if not content:
            raise HTTPException(400, "Empty file uploaded")
        
        logger.debug("file_read", 
                    size_kb=len(content) / 1024,
                    filename=file.filename)
        
        # Validate CSV structure and content
        valid, errors = csv_handler.validate_csv_file(content)
        
        if not valid:
            logger.warning("csv_validation_failed",
                          username=username,
                          filename=file.filename,
                          errors=errors)
            
            # Return HTMX-compatible error response
            return _create_htmx_response(
                success=False,
                message="CSV validation failed",
                errors=errors,
                request=request
            )
        
        # Parse CSV into PageSchema objects
        try:
            new_pages = csv_handler.parse_csv(content)
        except CSVException as e:
            logger.error("csv_parsing_failed",
                        username=username,
                        error=e.message,
                        details=e.details)
            return _create_htmx_response(
                success=False,
                message=e.message,
                errors=e.details.get("errors", []),
                request=request
            )
        
        # Get existing pages for audit trail
        existing_pages = await storage.get_all_pages()
        existing_pages_map = {p.slug: p for p in existing_pages}
        
        # Track changes for audit
        added_count = 0
        updated_count = 0
        unchanged_count = 0
        
        for page in new_pages:
            if page.slug in existing_pages_map:
                old_page = existing_pages_map[page.slug]
                if (old_page.title != page.title or 
                    old_page.meta_description != page.meta_description):
                    updated_count += 1
                    # Log change to audit trail
                    await audit_service.log_change(
                        slug=page.slug,
                        old_page=old_page,
                        new_page=page,
                        username=username,
                        request=request,
                    )
                else:
                    unchanged_count += 1
            else:
                added_count += 1
                # Log new page to audit trail
                await audit_service.log_change(
                    slug=page.slug,
                    old_page=None,
                    new_page=page,
                    username=username,
                    request=request,
                )
        
        # Save all pages to storage
        await storage.save_pages(new_pages)
        
        # Create success message
        message_parts = []
        if added_count > 0:
            message_parts.append(f"{added_count} new page(s)")
        if updated_count > 0:
            message_parts.append(f"{updated_count} updated")
        if unchanged_count > 0:
            message_parts.append(f"{unchanged_count} unchanged")
        
        success_message = (
            f"Successfully processed {len(new_pages)} pages: "
            f"{', '.join(message_parts)}"
        )
        
        logger.info("csv_upload_successful",
                   username=username,
                   filename=file.filename,
                   total_pages=len(new_pages),
                   added=added_count,
                   updated=updated_count,
                   unchanged=unchanged_count)
        
        # Return HTMX-compatible success response
        return _create_htmx_response(
            success=True,
            message=success_message,
            processed=len(new_pages),
            added=added_count,
            updated=updated_count,
            unchanged=unchanged_count,
            request=request
        )
    
    except HTTPException:
        raise
    
    except (CSVException, StorageException, ValidationException) as e:
        logger.error("csv_upload_app_error",
                    username=username,
                    error=e.message,
                    error_type=type(e).__name__)
        return _create_htmx_response(
            success=False,
            message=e.message,
            errors=[e.message],
            request=request
        )
    
    except Exception as e:
        logger.error("csv_upload_unexpected_error",
                    username=username,
                    error=str(e),
                    exc_info=True)
        return _create_htmx_response(
            success=False,
            message="An unexpected error occurred during upload",
            errors=[str(e)],
            request=request
        )


@router.get("/audit-logs")
async def get_audit_logs(
    request: Request,
    limit: int = 50,
    username: str = Depends(security_manager.require_auth),
) -> Response:
    """
    Get recent audit logs for display.
    Returns HTML fragment for HTMX.
    
    Args:
        request: FastAPI request object
        limit: Maximum number of logs to return
        username: Authenticated username
        
    Returns:
        HTML response with audit log table
    """
    try:
        logs = await audit_service.get_recent_logs(limit=limit)
        
        logger.debug("audit_logs_retrieved",
                    username=username,
                    count=len(logs))
        
        # Return HTML fragment for HTMX
        return templates.TemplateResponse(
            "partials/audit_table.html",
            {
                "request": request,
                "logs": logs,
            }
        )
    
    except Exception as e:
        logger.error("audit_logs_retrieval_error",
                    error=str(e),
                    exc_info=True)
        return HTMLResponse(
            content='<tr><td colspan="4" class="px-6 py-4 text-center text-red-600">'
                   'Failed to load audit logs</td></tr>',
            status_code=500
        )


@router.get("/stats")
async def get_stats(
    request: Request,
    username: str = Depends(security_manager.require_auth),
) -> Dict[str, Any]:
    """
    Get current system statistics.
    
    Args:
        request: FastAPI request object
        username: Authenticated username
        
    Returns:
        JSON response with statistics
    """
    try:
        pages = await storage.get_all_pages()
        storage_stats = await storage.get_storage_stats()
        
        stats = {
            "pages": {
                "total": len(pages),
                "with_titles": sum(1 for p in pages if p.title),
                "with_descriptions": sum(1 for p in pages if p.meta_description),
            },
            "storage": storage_stats,
            "last_updated": max(
                (p.updated_at for p in pages), 
                default=datetime.utcnow()
            ).isoformat(),
        }
        
        return JSONResponse(content=stats)
    
    except Exception as e:
        logger.error("stats_retrieval_error", error=str(e))
        raise HTTPException(500, "Failed to retrieve statistics")


def _create_htmx_response(
    success: bool,
    message: str,
    errors: List[str] = None,
    processed: int = 0,
    added: int = 0,
    updated: int = 0,
    unchanged: int = 0,
    request: Request = None
) -> Response:
    """
    Create HTMX-compatible response with toast notification.
    
    Args:
        success: Whether the operation succeeded
        message: Main message to display
        errors: List of error messages
        processed: Number of records processed
        added: Number of records added
        updated: Number of records updated
        unchanged: Number of records unchanged
        request: FastAPI request object
        
    Returns:
        HTMLResponse with toast notification
    """
    errors = errors or []
    
    # Determine toast type and icon
    if success:
        toast_type = "success"
        icon_svg = '''<svg class="h-5 w-5 text-emerald-400" viewBox="0 0 20 20" fill="currentColor">
            <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd"/>
        </svg>'''
        bg_color = "bg-emerald-50"
        border_color = "border-emerald-400"
        text_color = "text-emerald-800"
    else:
        toast_type = "error"
        icon_svg = '''<svg class="h-5 w-5 text-red-400" viewBox="0 0 20 20" fill="currentColor">
            <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clip-rule="evenodd"/>
        </svg>'''
        bg_color = "bg-red-50"
        border_color = "border-red-400"
        text_color = "text-red-800"
    
    # Build error list HTML
    error_html = ""
    if errors:
        error_items = "".join(
            f'<li class="text-sm">{error}</li>' 
            for error in errors[:5]  # Show first 5 errors
        )
        if len(errors) > 5:
            error_items += f'<li class="text-sm font-medium">... and {len(errors) - 5} more errors</li>'
        error_html = f'<ul class="mt-2 ml-4 list-disc list-inside space-y-1">{error_items}</ul>'
    
    # Build stats HTML
    stats_html = ""
    if success and processed > 0:
        stats_html = f'''
        <div class="mt-2 text-sm {text_color}">
            <span class="font-medium">Added:</span> {added} | 
            <span class="font-medium">Updated:</span> {updated} | 
            <span class="font-medium">Unchanged:</span> {unchanged}
        </div>
        '''
    
    # Create toast HTML
    toast_html = f'''
    <div class="fixed bottom-4 right-4 max-w-md w-full {bg_color} border-l-4 {border_color} p-4 rounded-lg shadow-lg z-50 fade-in" 
         id="toast-notification">
        <div class="flex items-start">
            <div class="flex-shrink-0">
                {icon_svg}
            </div>
            <div class="ml-3 w-0 flex-1">
                <p class="text-sm font-medium {text_color}">
                    {message}
                </p>
                {stats_html}
                {error_html}
            </div>
            <div class="ml-4 flex-shrink-0 flex">
                <button onclick="this.parentElement.parentElement.parentElement.remove()" 
                        class="{bg_color} rounded-md inline-flex {text_color} hover:text-gray-500 focus:outline-none">
                    <svg class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
                        <path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd"/>
                    </svg>
                </button>
            </div>
        </div>
    </div>
    <script>
        setTimeout(function() {{
            const toast = document.getElementById('toast-notification');
            if (toast) {{
                toast.style.opacity = '0';
                toast.style.transition = 'opacity 0.5s ease-out';
                setTimeout(function() {{ toast.remove(); }}, 500);
            }}
        }}, 5000);
        
        // Refresh audit logs if successful
        {'htmx.ajax("GET", "/automation/audit-logs", {target: "#audit-log-body", swap: "innerHTML"});' if success else ''}
    </script>
    '''
    
    return HTMLResponse(content=toast_html)