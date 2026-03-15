from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import logging
import time
from uuid import uuid4

from config.database import engine, Base
from app.routers import auth, novel, library, chapter
from app.logging_config import setup_logging, set_request_id, get_logger, get_request_id
from app.exceptions import NexusNovelException

setup_logging()
logger = get_logger(__name__)
# Initialize FastAPI app
app = FastAPI(title="Your API", description="API description", version="0.1.0")

# Configure CORS if needed
origins = ["http://localhost", "http://localhost:3000", "http://localhost:5173"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth.router)
app.include_router(novel.router)
app.include_router(library.router)
app.include_router(chapter.router)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    request_id = str(uuid4())[:8]
    set_request_id(request_id)

    start_time = time.perf_counter()

    logger.info(
        "request_started",
        extra={
            "extra": {
                "method": request.method,
                "path": request.url.path,
                "request_id": request_id,
            }
        },
    )

    response = await call_next(request)

    duration = time.perf_counter() - start_time

    logger.info(
        "request_completed",
        extra={
            "extra": {
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": round(duration * 1000, 2),
                "request_id": request_id,
            }
        },
    )

    response.headers["X-Request-ID"] = request_id
    return response


@app.exception_handler(NexusNovelException)
async def nexus_exception_handler(request: Request, exc: NexusNovelException):
    logger.warning(
        "Application exception",
        extra={
            "extra": {
                "error": exc.message,
                "status_code": exc.status_code,
                "request_id": get_request_id(),
            }
        },
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.message, "request_id": get_request_id()},
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logger.error(
        "Unhandled exception",
        extra={
            "extra": {
                "error": str(exc),
                "type": type(exc).__name__,
                "request_id": get_request_id(),
            }
        },
        exc_info=True,
    )
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Internal server error",
            "request_id": get_request_id(),
        },
    )


# Root endpoint
@app.get("/")
async def root():
    return {"message": "Welcome to Your API"}
