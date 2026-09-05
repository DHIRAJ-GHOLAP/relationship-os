"""Main application entry point for Relationship OS API."""

import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from apps.api.src.core.config import settings
from apps.api.src.core.database import Base, engine
from apps.api.src.core.exceptions import (
    AppException,
    app_exception_handler,
    generic_http_exception_handler,
    unhandled_exception_handler,
    validation_exception_handler,
)
from apps.api.src.core.middleware import (
    RateLimitMiddleware,
    RequestContextAndSecurityHeadersMiddleware,
)
from apps.api.src.routers import (
    admin,
    attachments,
    auth,
    conversations,
    health,
    webhooks,
    websocket,
)
from apps.api.src.services.outbox_worker import OutboxWorker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("relationship_os")

outbox_worker = OutboxWorker(poll_interval=1.0)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up Relationship OS API server (version %s)...", settings.APP_VERSION)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    outbox_worker.start()
    yield
    logger.info("Shutting down Relationship OS API server...")
    await outbox_worker.stop()
    await engine.dispose()


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Relationship OS - Private One-to-One Communication Ecosystem",
    docs_url="/docs" if settings.ENVIRONMENT != "production" else None,
    redoc_url="/redoc" if settings.ENVIRONMENT != "production" else None,
    openapi_url="/openapi.json" if settings.ENVIRONMENT != "production" else None,
    lifespan=lifespan,
)

# 1. Security Headers & Request Correlation Middleware
app.add_middleware(RequestContextAndSecurityHeadersMiddleware)

# 2. Rate Limiting Middleware
app.add_middleware(RateLimitMiddleware)

# 3. CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)

# Exception Handlers
app.add_exception_handler(AppException, app_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(StarletteHTTPException, generic_http_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)

# Register API Routers
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(conversations.router)
app.include_router(admin.router)
app.include_router(webhooks.router)
app.include_router(attachments.router)
app.include_router(websocket.router)

# Mount web client static distribution if built
web_dist = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../apps/web/dist"))
assets_dir = os.path.join(web_dist, "assets")

if os.path.exists(assets_dir):
    app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

# Mount launcher / cli downloadable static distribution if requested
cli_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../apps/cli/src"))
if os.path.exists(cli_dir):
    app.mount("/static", StaticFiles(directory=cli_dir), name="static")

@app.get("/{full_path:path}", include_in_schema=False)
async def serve_spa(request: Request, full_path: str):
    # Only serve SPA for non-api routes
    if full_path.startswith("api/") or full_path.startswith("docs") or full_path.startswith("openapi"):
        raise StarletteHTTPException(status_code=404, detail="Not Found")
    index_file = os.path.join(web_dist, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return {"status": "ok", "app": settings.APP_NAME, "message": "API is running. Build apps/web to view UI."}
