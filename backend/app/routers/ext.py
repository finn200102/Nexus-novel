"""Endpoints for the "Send to Nexus" browser extension.

Every route here accepts HTTP Basic auth with the username and an app password
of scope ``extension``; the account password is never accepted. Rate limits are
the same as OPDS (they live in ``app_password_service``).

CORS is path-scoped: only ``/ext/*`` answers browser extension origins
(``chrome-extension://`` and ``moz-extension://``), so the rest of the API keeps
the localhost-only policy from ``main.py``.
"""

import base64

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.models.library import Library
from app.models.user import User
from app.routers.novel import check_library
from app.services import app_password_service
from app.services import import_job_service as imports
from config.database import get_db

EXTENSION_ORIGIN_PREFIXES = ("chrome-extension://", "moz-extension://")
EXT_PATH_PREFIX = "/ext/"
MAX_URL_CHARS = 2048

router = APIRouter(
    prefix="/ext",
    tags=["extension"],
    responses={401: {"description": "Invalid username or app password"}},
)


class ExtAddRequest(BaseModel):
    url: str = Field(..., min_length=1, max_length=MAX_URL_CHARS)
    library_id: int


def get_ext_user(request: Request, db: Session = Depends(get_db)) -> User:
    challenge = {"WWW-Authenticate": 'Basic realm="Nexus"'}
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("basic "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required", headers=challenge)
    try:
        decoded = base64.b64decode(header[6:].strip()).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required", headers=challenge)
    username, separator, password = decoded.partition(":")
    if not separator:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required", headers=challenge)
    try:
        return app_password_service.authenticate_extension(db, request, username, password)
    except HTTPException as exc:
        if exc.status_code == status.HTTP_401_UNAUTHORIZED:
            raise HTTPException(status_code=401, detail=exc.detail, headers=challenge)
        raise


@router.get("/libraries")
def list_libraries(db: Session = Depends(get_db), user: User = Depends(get_ext_user)):
    libraries = db.query(Library).filter(Library.user_id == user.id).order_by(Library.name, Library.id).all()
    return [{"id": library.id, "name": library.name} for library in libraries]


@router.post("/add", status_code=status.HTTP_202_ACCEPTED)
def add_page(payload: ExtAddRequest, db: Session = Depends(get_db), user: User = Depends(get_ext_user)):
    """Queue one story URL with the same job flow as pasted URLs (/imports/urls)."""
    library = check_library(db, payload.library_id, user)
    urls = imports.extract_urls(payload.url.strip())
    if not urls:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Not a story URL")
    job = imports.create_job(db, user, library, "url_list", entries=[{"url": urls[0]}])
    return imports.job_to_dict(db, job, items=True)


class ExtensionCorsMiddleware:
    """Pure ASGI middleware: CORS for extension origins, on ``/ext/*`` only."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith(EXT_PATH_PREFIX):
            await self.app(scope, receive, send)
            return

        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        origin = headers.get(b"origin", b"").decode("latin-1")
        allowed = origin.startswith(EXTENSION_ORIGIN_PREFIXES)

        if allowed and scope["method"] == "OPTIONS" and b"access-control-request-method" in headers:
            await send({
                "type": "http.response.start",
                "status": 204,
                "headers": _cors_headers(origin, preflight=True),
            })
            await send({"type": "http.response.body", "body": b""})
            return

        async def send_with_cors(message):
            if allowed and message["type"] == "http.response.start":
                message["headers"] = list(message.get("headers", [])) + _cors_headers(origin)
            await send(message)

        await self.app(scope, receive, send_with_cors)


def _cors_headers(origin: str, preflight: bool = False) -> list[tuple[bytes, bytes]]:
    headers = [
        (b"access-control-allow-origin", origin.encode("latin-1")),
        (b"vary", b"Origin"),
    ]
    if preflight:
        headers += [
            (b"access-control-allow-methods", b"GET, POST, OPTIONS"),
            (b"access-control-allow-headers", b"Authorization, Content-Type"),
            (b"access-control-max-age", b"600"),
        ]
    return headers
