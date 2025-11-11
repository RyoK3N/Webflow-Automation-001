import secrets
from fastapi import APIRouter, Request, Form, Response, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from slowapi import Limiter
from slowapi.util import get_remote_address
from app.core.security import security_manager
from app.core.logging import logger

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
limiter = Limiter(key_func=get_remote_address)


@router.get("/login", response_class=HTMLResponse)
@limiter.limit("10/minute")
async def login_page(request: Request) -> HTMLResponse:
    logger.info("login_page_requested", ip=request.client.host if request.client else None)
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "app_name": request.app.state.config.app_name},
    )


@router.post("/login", response_class=HTMLResponse)
@limiter.limit("5/minute")
async def login_post(
    request: Request,
    response: Response,
    username: str = Form(...),
    password: str = Form(...),
) -> HTMLResponse:
    cfg = request.app.state.config
    ok = secrets.compare_digest(username, cfg.admin_username) and \
         secrets.compare_digest(password, cfg.admin_password.get_secret_value())
    if not ok:
        logger.warning("login_failed", username=username)
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Invalid credentials"},
            status_code=401,
        )

    token = security_manager.create_session_token(username)
    response.set_cookie(
        key=cfg.session_cookie_name,
        value=token,
        httponly=True,
        samesite="lax",
        secure=not cfg.debug,
        max_age=cfg.session_max_age,
    )
    logger.info("login_success", username=username)
    return templates.TemplateResponse(
        "automation.html",
        {"request": request, "username": username},
    )


@router.get("/logout")
async def logout(request: Request, response: Response) -> RedirectResponse:
    response.delete_cookie(request.app.state.config.session_cookie_name)
    return RedirectResponse("/login", status_code=303)