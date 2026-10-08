from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import time
from uuid import uuid4

from app import models  # noqa: F401  (registers every mapper before the first request)
from config.database import engine
from config.settings import settings
from app.routers import auth, novel, library, chapter, discovery, follow, download, activity, operations, catalog_scrape, audio, saved_search, recommendations, admin_integrations, admin_users, notifications
from app.routers import user_data, imports
from app.routers import app_passwords, kosync, opds, source_status, stories
from app.routers import blocklist, personal, shelves
from app.db_migrations import upgrade_database
from app.services import metadata_client
from app.logging_config import (
    setup_logging,
    set_request_id,
    get_logger,
    get_request_id,
    set_user_context,
    clear_user_context,
)
from app.exceptions import NexusNovelException

setup_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.RUN_MIGRATIONS_ON_STARTUP:
        upgrade_database(engine)
    await metadata_client.start()
    try:
        yield
    finally:
        await metadata_client.close()


app = FastAPI(title="Nexus Novel API", description="Nexus reader and library API", version="1.0.0", lifespan=lifespan)

origins = [
    "http://localhost",
    "http://localhost:3000",
    "http://localhost:5173",
    "http://localhost:5174",
    "http://127.0.0.1:5174",
    "http://127.0.0.1:5173",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(novel.router)
app.include_router(library.router)
app.include_router(chapter.router)
app.include_router(discovery.router)
app.include_router(follow.router)
app.include_router(download.router)
app.include_router(activity.router)
app.include_router(operations.router)
app.include_router(catalog_scrape.router)
app.include_router(audio.router)
app.include_router(saved_search.router)
app.include_router(recommendations.router)
app.include_router(admin_integrations.router)
app.include_router(admin_users.router)
app.include_router(user_data.router)
app.include_router(imports.router)
app.include_router(notifications.router)
app.include_router(app_passwords.router)
app.include_router(opds.router)
app.include_router(kosync.router)
app.include_router(blocklist.router)
app.include_router(shelves.router)
app.include_router(personal.router)
app.include_router(source_status.router)
app.include_router(stories.router)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    request_id = str(uuid4())[:8]
    set_request_id(request_id)
    clear_user_context()

    user_id = request.headers.get("x-user-id")
    if user_id:
        try:
            set_user_context(user_id=int(user_id))
        except ValueError:
            pass

    start_time = time.perf_counter()

    logger.info(
        "request_started",
        method=request.method,
        path=request.url.path,
    )

    try:
        response = await call_next(request)
    except Exception as e:
        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
        logger.error(
            "request_failed",
            method=request.method,
            path=request.url.path,
            duration_ms=duration_ms,
            error=str(e),
        )
        raise

    duration_ms = round((time.perf_counter() - start_time) * 1000, 2)

    logger.info(
        "request_completed",
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        duration_ms=duration_ms,
    )

    response.headers["X-Request-ID"] = request_id
    return response


@app.exception_handler(NexusNovelException)
async def nexus_exception_handler(request: Request, exc: NexusNovelException):
    logger.warning(
        "Application exception",
        error=exc.message,
        status_code=exc.status_code,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.message, "request_id": get_request_id()},
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logger.error(
        "Unhandled exception",
        error=str(exc),
        type=type(exc).__name__,
    )
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Internal server error",
            "request_id": get_request_id(),
        },
    )


@app.get("/")
async def root():
    return {"message": "Welcome to Your API"}


@app.get("/health")
async def health():
    return {"status": "healthy"}
