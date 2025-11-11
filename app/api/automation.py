import uuid
from fastapi import APIRouter, Request, Depends, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from app.core.security import security_manager
from app.core.logging import logger
from app.services.storage import storage
from app.services.csv_handler import csv_handler
from app.services.audit import audit_service
from app.models.schemas import CSVUploadResponse

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
async def automation_page(
    request: Request,
    username: str = Depends(security_manager.require_auth),
):
    request.state.username = username
    logger.info("automation_page_accessed", username=username)
    return templates.TemplateResponse(
        "automation.html",
        {"request": request, "username": username},
    )


@router.get("/export")
async def export_csv(
    request: Request,
    username: str = Depends(security_manager.require_auth),
):
    pages = await storage.get_all_pages()
    if not pages:
        raise HTTPException(400, "No pages to export")
    csv_bytes = csv_handler.generate_csv(pages)
    logger.info("export_success", username=username, count=len(pages))
    return StreamingResponse(
        iter([csv_bytes]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=webflow-pages-{uuid.uuid4().hex[:8]}.csv"
        },
    )


@router.post("/upload", response_model=CSVUploadResponse)
async def upload_csv(
    request: Request,
    file: UploadFile = File(...),
    username: str = Depends(security_manager.require_auth),
):
    if not file.filename or not file.filename.endswith(".csv"):
        raise HTTPException(400, "Only CSV files allowed")

    content = await file.read()
    valid, errors = csv_handler.validate_csv_file(content)
    if not valid:
        return CSVUploadResponse(success=False, message="Validation failed", errors=errors)

    new_pages = csv_handler.parse_csv(content)
    existing = {p.slug: p for p in await storage.get_all_pages()}

    for page in new_pages:
        await audit_service.log_change(
            slug=page.slug,
            old_page=existing.get(page.slug),
            new_page=page,
            username=username,
            request=request,
        )

    await storage.save_pages(new_pages)
    logger.info("upload_success", username=username, processed=len(new_pages))
    return CSVUploadResponse(
        success=True,
        message=f"Processed {len(new_pages)} pages",
        processed=len(new_pages),
        audit_id=f"batch_{uuid.uuid4().hex[:8]}",
    )