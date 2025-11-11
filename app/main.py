"""
SEO Automation Platform - Main Application Entry Point
Production-ready FastAPI application with comprehensive error handling,
middleware, and monitoring capabilities.
"""

import time
import uuid
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Dict, Any, Optional

from fastapi import FastAPI, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import get_settings
from app.core.logging import setup_logging, logger
from app.core.exceptions import (
    AppException,
    StorageException,
    ValidationException,
    AuthenticationException,
)
from app.api import auth, automation
from app.services.storage import storage
from app.services.audit import audit_service


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Application lifespan manager for startup and shutdown events.
    Handles initialization and cleanup of resources.
    """
    # Startup
    logger.info("application_startup_initiated", version=app.version)
    
    try:
        # Initialize storage directories and files
        await storage.initialize()
        logger.info("storage_initialized", 
                   pages_path=str(storage.pages_path),
                   audit_path=str(storage.audit_path))
        
        # Verify data integrity
        pages = await storage.get_all_pages()
        logger.info("data_verification_complete", page_count=len(pages))
        
        # Initialize audit service
        await audit_service.initialize()
        logger.info("audit_service_initialized")
        
        # Additional startup checks
        settings = get_settings()
        if settings.debug:
            logger.warning("application_running_in_debug_mode", 
                         message="DO NOT use debug mode in production!")
        
        logger.info("application_startup_complete", 
                   app_name=settings.app_name,
                   python_version="3.11+")
        
    except Exception as e:
        logger.error("application_startup_failed", error=str(e), exc_info=True)
        raise
    
    yield
    
    # Shutdown
    logger.info("application_shutdown_initiated")
    
    try:
        # Perform graceful shutdown operations
        await storage.close()
        logger.info("storage_closed")
        
        logger.info("application_shutdown_complete")
        
    except Exception as e:
        logger.error("application_shutdown_error", error=str(e), exc_info=True)


def create_app() -> FastAPI:
    """
    Application factory pattern for creating and configuring FastAPI instance.
    
    Returns:
        FastAPI: Configured application instance
    """
    # Initialize structured logging
    setup_logging()
    
    # Get application settings
    settings = get_settings()
    
    # Create FastAPI application
    app = FastAPI(
        title=settings.app_name,
        version="1.0.0",
        description="Enterprise-grade Webflow meta tag bulk updater with full audit trail",
        docs_url="/api/docs" if settings.debug else None,
        redoc_url="/api/redoc" if settings.debug else None,
        openapi_url="/api/openapi.json" if settings.debug else None,
        lifespan=lifespan,
    )
    
    # Store settings in app state for access in routes
    app.state.config = settings
    
    # Configure middleware stack
    configure_middleware(app, settings)
    
    # Mount static files
    app.mount("/static", StaticFiles(directory="app/static"), name="static")
    
    # Include API routers
    app.include_router(auth.router, tags=["authentication"])
    app.include_router(
        automation.router,
        prefix="/automation",
        tags=["automation"]
    )
    
    # Register exception handlers
    register_exception_handlers(app)
    
    # Register core routes
    register_core_routes(app)
    
    # Add request/response logging middleware
    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        """Log all HTTP requests with timing information"""
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        
        start_time = time.time()
        
        # Log incoming request
        logger.info(
            "http_request_received",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            client_ip=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent", "unknown"),
        )
        
        try:
            response = await call_next(request)
            
            # Calculate processing time
            process_time = time.time() - start_time
            
            # Add custom headers
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Process-Time"] = f"{process_time:.3f}"
            
            # Log response
            logger.info(
                "http_request_completed",
                request_id=request_id,
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                process_time=f"{process_time:.3f}s",
            )
            
            return response
            
        except Exception as e:
            process_time = time.time() - start_time
            logger.error(
                "http_request_failed",
                request_id=request_id,
                method=request.method,
                path=request.url.path,
                error=str(e),
                process_time=f"{process_time:.3f}s",
                exc_info=True,
            )
            raise
    
    # Add security headers middleware
    @app.middleware("http")
    async def add_security_headers(request: Request, call_next):
        """Add security headers to all responses"""
        response = await call_next(request)
        
        # Security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        
        if not settings.debug:
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )
        
        return response
    
    logger.info("application_created", app_name=settings.app_name)
    
    return app


def configure_middleware(app: FastAPI, settings) -> None:
    """
    Configure application middleware stack.
    
    Args:
        app: FastAPI application instance
        settings: Application settings
    """
    # CORS middleware
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "DELETE"],
            allow_headers=["*"],
            expose_headers=["X-Request-ID", "X-Process-Time"],
        )
        logger.info("cors_middleware_configured", origins=settings.cors_origins)
    
    # GZip compression middleware
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    logger.info("gzip_middleware_configured")
    
    # Trusted host middleware (only in production)
    if not settings.debug:
        app.add_middleware(
            TrustedHostMiddleware,
            allowed_hosts=["localhost", "127.0.0.1", "*"]  # Configure for production
        )
        logger.info("trusted_host_middleware_configured")


def register_exception_handlers(app: FastAPI) -> None:
    """
    Register custom exception handlers for the application.
    
    Args:
        app: FastAPI application instance
    """
    
    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request, 
        exc: StarletteHTTPException
    ) -> Response:
        """Handle standard HTTP exceptions"""
        request_id = getattr(request.state, "request_id", "unknown")
        
        logger.warning(
            "http_exception",
            request_id=request_id,
            status_code=exc.status_code,
            detail=exc.detail,
            path=request.url.path,
        )
        
        # For HTMX requests, return appropriate response
        if request.headers.get("HX-Request"):
            return JSONResponse(
                status_code=exc.status_code,
                content={
                    "success": False,
                    "message": exc.detail,
                    "request_id": request_id,
                }
            )
        
        # For regular requests, return JSON
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": exc.detail,
                "status_code": exc.status_code,
                "request_id": request_id,
            }
        )
    
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request,
        exc: RequestValidationError
    ) -> JSONResponse:
        """Handle validation errors"""
        request_id = getattr(request.state, "request_id", "unknown")
        
        errors = []
        for error in exc.errors():
            errors.append({
                "field": ".".join(str(loc) for loc in error["loc"]),
                "message": error["msg"],
                "type": error["type"],
            })
        
        logger.warning(
            "validation_error",
            request_id=request_id,
            errors=errors,
            path=request.url.path,
        )
        
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "success": False,
                "message": "Validation error",
                "errors": errors,
                "request_id": request_id,
            }
        )
    
    @app.exception_handler(AppException)
    async def app_exception_handler(
        request: Request,
        exc: AppException
    ) -> JSONResponse:
        """Handle custom application exceptions"""
        request_id = getattr(request.state, "request_id", "unknown")
        
        logger.error(
            "application_exception",
            request_id=request_id,
            error=str(exc),
            error_type=type(exc).__name__,
            path=request.url.path,
        )
        
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "success": False,
                "message": exc.message,
                "error_type": type(exc).__name__,
                "request_id": request_id,
            }
        )
    
    @app.exception_handler(Exception)
    async def general_exception_handler(
        request: Request,
        exc: Exception
    ) -> JSONResponse:
        """Handle unexpected exceptions"""
        request_id = getattr(request.state, "request_id", "unknown")
        
        logger.error(
            "unexpected_exception",
            request_id=request_id,
            error=str(exc),
            error_type=type(exc).__name__,
            path=request.url.path,
            exc_info=True,
        )
        
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "success": False,
                "message": "Internal server error",
                "request_id": request_id,
            }
        )
    
    logger.info("exception_handlers_registered")


def register_core_routes(app: FastAPI) -> None:
    """
    Register core application routes.
    
    Args:
        app: FastAPI application instance
    """
    templates = Jinja2Templates(directory="app/templates")
    
    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def index() -> RedirectResponse:
        """Redirect root to login page"""
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    
    @app.get("/health", include_in_schema=False)
    async def health_check() -> Dict[str, Any]:
        """
        Health check endpoint for monitoring and load balancers.
        
        Returns:
            Dict containing health status and system information
        """
        try:
            # Check storage accessibility
            pages = await storage.get_all_pages()
            storage_healthy = True
        except Exception as e:
            logger.error("health_check_storage_failed", error=str(e))
            storage_healthy = False
        
        settings = get_settings()
        
        health_status = {
            "status": "healthy" if storage_healthy else "degraded",
            "timestamp": time.time(),
            "version": app.version,
            "storage": {
                "accessible": storage_healthy,
                "page_count": len(pages) if storage_healthy else 0,
            },
            "system": {
                "debug_mode": settings.debug,
            }
        }
        
        status_code = (
            status.HTTP_200_OK if storage_healthy 
            else status.HTTP_503_SERVICE_UNAVAILABLE
        )
        
        return JSONResponse(content=health_status, status_code=status_code)
    
    @app.get("/readiness", include_in_schema=False)
    async def readiness_check() -> Dict[str, str]:
        """
        Readiness check for Kubernetes/container orchestration.
        
        Returns:
            Dict indicating if the service is ready to accept traffic
        """
        try:
            # Quick check if critical services are ready
            await storage.get_all_pages()
            return {"status": "ready"}
        except Exception as e:
            logger.error("readiness_check_failed", error=str(e))
            return JSONResponse(
                content={"status": "not_ready", "reason": str(e)},
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE
            )
    
    @app.get("/liveness", include_in_schema=False)
    async def liveness_check() -> Dict[str, str]:
        """
        Liveness check for Kubernetes/container orchestration.
        
        Returns:
            Dict indicating if the service is alive
        """
        return {"status": "alive"}
    
    logger.info("core_routes_registered")


# Create application instance
app = create_app()

# Initialize templates for use in routes
templates = Jinja2Templates(directory="app/templates")


if __name__ == "__main__":
    """
    Development server entry point.
    For production, use: uvicorn app.main:app --host 0.0.0.0 --port 8000
    """
    import uvicorn
    
    settings = get_settings()
    
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug,
        log_level=settings.log_level.lower(),
        access_log=True,
    )