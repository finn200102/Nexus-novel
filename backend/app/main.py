from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import logging
import time
from uuid import uuid4

from config.database import engine, Base
from app.routers import auth, novel, library, chapter, discovery
from app.models.author import Author
from app.models.chapter import Chapter
from app.models.genre import Genre
from app.models.library import Library
from app.models.novel import Novel
from app.models.tag import Tag
from app.models.user import User
from app.database_migrations import ensure_runtime_schema

Base.metadata.create_all(bind=engine)
ensure_runtime_schema(engine)
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

app = FastAPI(title="Your API", description="API description", version="0.1.0")

origins = ["http://localhost", "http://localhost:3000", "http://localhost:5173"]

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
