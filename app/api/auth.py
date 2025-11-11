"""
Fixed Authentication Routes - Resolves cookie persistence issue
"""

import secrets
from typing import Optional
from datetime import datetime

from fastapi import APIRouter, Request, Form, Response, HTTPException, Depends
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
@limiter.limit("20/minute")
async def login_page(request: Request) -> HTMLResponse:
    """Display login page."""
    # Check if already authenticated
    existing_user = security_manager.verify_session(request)
    if existing_user:
        logger.info("login_page_already_authenticated", username=existing_user)
        return RedirectResponse(url="/automation/", status_code=303)
    
    client_ip = request.client.host if request.client else "unknown"
    logger.info("login_page_requested", ip=client_ip)
    
    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "app_name": request.app.state.config.app_name,
            "error": None,
        },
    )


@router.post("/login")
@limiter.limit("5/minute")
async def login_post(
    request: Request,
    username: str = Form(..., min_length=1, max_length=100),
    password: str = Form(..., min_length=1, max_length=200),
) -> Response:
    """
    Process login - FIXED to properly set cookie before redirect.
    """
    client_ip = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "unknown")
    
    logger.info("login_attempt", 
               username=username,
               ip=client_ip,
               user_agent=user_agent[:100])
    
    try:
        cfg = request.app.state.config
        
        # Validate credentials using constant-time comparison
        username_valid = secrets.compare_digest(
            username.strip(), 
            cfg.admin_username
        )
        password_valid = secrets.compare_digest(
            password, 
            cfg.admin_password.get_secret_value()
        )
        
        if not (username_valid and password_valid):
            logger.warning("login_failed_invalid_credentials", 
                          username=username,
                          ip=client_ip)
            
            return templates.TemplateResponse(
                "login.html",
                {
                    "request": request,
                    "app_name": cfg.app_name,
                    "error": "Invalid username or password. Please try again.",
                },
                status_code=401,
            )
        
        # Create session token
        token = security_manager.create_session_token(username.strip())
        
        # FIXED: Create redirect response and set cookie with correct settings
        response = RedirectResponse(
            url="/automation/",  # Direct to /automation/ with trailing slash
            status_code=303
        )
        
        # Set cookie with proper settings
        response.set_cookie(
            key=cfg.session_cookie_name,
            value=token,
            httponly=True,
            samesite="lax",
            secure=False,  # Set to True in production with HTTPS
            max_age=cfg.session_max_age,
            path="/",  # Cookie available for all paths
            domain=None,  # Let browser determine domain
        )
        
        logger.info("login_successful", 
                   username=username.strip(),
                   ip=client_ip,
                   session_duration=cfg.session_max_age,
                   cookie_name=cfg.session_cookie_name)
        
        return response
    
    except Exception as e:
        logger.error("login_error", 
                    error=str(e),
                    username=username,
                    ip=client_ip,
                    exc_info=True)
        
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "app_name": request.app.state.config.app_name,
                "error": "An error occurred during login. Please try again.",
            },
            status_code=500,
        )


@router.get("/logout")
async def logout(request: Request) -> RedirectResponse:
    """Logout user and clear session."""
    username = security_manager.verify_session(request)
    client_ip = request.client.host if request.client else "unknown"
    
    logger.info("logout", 
               username=username or "unknown",
               ip=client_ip)
    
    response = RedirectResponse(url="/login", status_code=303)
    
    # Delete cookie with same parameters it was set with
    cfg = request.app.state.config
    response.delete_cookie(
        key=cfg.session_cookie_name,
        path="/",
    )
    
    return response


@router.get("/check-auth")
async def check_auth(
    request: Request,
    username: str = Depends(security_manager.require_auth)
) -> dict:
    """Check authentication status."""
    return {
        "authenticated": True,
        "username": username,
        "timestamp": datetime.utcnow().isoformat(),
    }