from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from app.core.config import get_settings
from app.core.logging import setup_logging
from app.api import auth, automation

def create_app() -> FastAPI:
    setup_logging()
    app = FastAPI(
        title=get_settings().app_name,
        docs_url=None,
        redoc_url=None,
    )
    app.state.config = get_settings()          # <-- already here
    app.mount("/static", StaticFiles(directory="app/static"), name="static")
    app.include_router(auth.router)
    app.include_router(automation.router, prefix="/automation", tags=["automation"])

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def index() -> RedirectResponse:
        return RedirectResponse("/login")

    @app.get("/health", include_in_schema=False)
    def health() -> dict:
        return {"status": "ok"}

    return app


app = create_app()
templates = Jinja2Templates(directory="app/templates")