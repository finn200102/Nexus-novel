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
from pydantic import BaseModel, Field, ConfigDict
from app.schemas.chapter_identity import ChapterWriteIdentity
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


class ExtCaptureRequest(ExtAddRequest,ChapterWriteIdentity):
    model_config=ConfigDict(extra="forbid")
    library_id:int=Field(gt=0,le=2147483647,strict=True)
    title: str = Field(..., min_length=1, max_length=255)
    html: str = Field(..., min_length=1, max_length=2_000_000)



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


def _capture_conflict():
    raise HTTPException(409,detail={'code':'capture_review_required','message':'This saved page changed source or chapter identity. Its originals have been kept; review it instead of overwriting a chapter number.'},headers={'Cache-Control':'private, no-store'})


def _capture_credential(db,request,user):
    """Snapshot the authenticated credential before parsing; never commit under write locks."""
    import hashlib
    from app.auth.passwords import verify_password
    from app.models.ereader import AppPassword
    try:
        decoded=base64.b64decode(request.headers.get('authorization','')[6:].strip(),validate=True).decode('utf-8')
        username,separator,password=decoded.partition(':')
        if not separator or username!=user.username:raise ValueError()
    except (ValueError,UnicodeError):raise HTTPException(401,'Extension authorization changed') from None
    key=hashlib.md5(password.encode()).hexdigest()
    candidates=db.query(AppPassword).filter_by(user_id=user.id,scope='extension',revoked_at=None).populate_existing().all()
    matched=next((row for row in candidates if verify_password(key,row.secret_hash)),None)
    if matched is None:raise HTTPException(401,'Extension authorization changed')
    return matched.id,matched.secret_hash,username


def _capture_target(db,user_id,library_id,key,url,*,lock=False):
    from sqlalchemy.orm import load_only
    from app.models.chapter import Chapter
    from app.models.novel import Novel
    from app.services.chapter_identity_service import manifest_state,source_version,sqlite_transaction
    sqlite_transaction(db,write=lock)
    query=db.query(Library).filter_by(id=library_id,user_id=user_id).populate_existing()
    if lock:query=query.with_for_update()
    library=query.first()
    if library is None:raise HTTPException(404,'Library not found')
    query=db.query(Novel).filter_by(library_id=library.id,url=key).populate_existing()
    if lock:query=query.with_for_update()
    novel=query.first()
    scope=(library.id,library.identity_key)
    if novel is None:return scope,None,None,None
    if (novel.metadata_id is not None or novel.source_url!=url[:500] or novel.site!='local' or novel.novel_site!='local'
            or novel.story_id not in (None,0) or novel.site_story_id not in (None,0)):_capture_conflict()
    query=db.query(Chapter).options(load_only(Chapter.id,Chapter.novel_id,Chapter.chapter_key,Chapter.chapter_number,
        Chapter.archived,Chapter.source_url,Chapter.metadata_manifest_key,Chapter.metadata_chapter_key,Chapter.site_chapter_id)).filter_by(novel_id=novel.id).execution_options(include_archived_chapters=True).order_by(Chapter.id).limit(2).populate_existing()
    if lock:query=query.with_for_update()
    chapters=query.all()
    state=manifest_state(db,novel.id,lock=lock)
    if (len(chapters)!=1 or chapters[0].archived or chapters[0].chapter_number!=1 or not chapters[0].chapter_key
            or state.identity_required or state.metadata_manifest_key is not None or state.metadata_source is not None
            or state.metadata_revision is not None or state.metadata_fingerprint is not None):_capture_conflict()
    chapter=chapters[0]
    if (chapter.source_url!=url[:500] or chapter.metadata_manifest_key is not None or chapter.metadata_chapter_key is not None
            or chapter.site_chapter_id not in (None,0)):_capture_conflict()
    proof=(novel.id,chapter.id,chapter.chapter_key,state.manifest_epoch,str(state.revision),source_version(chapter))
    return scope,novel,chapter,proof


def _expected_capture(payload,proof):
    expected=(payload.expected_chapter_key,payload.expected_manifest_epoch,payload.expected_manifest_revision,payload.expected_content_version)
    if any(value is not None for value in expected):
        if proof is None or any(value is None for value in expected) or expected!=proof[2:]:_capture_conflict()


@router.post("/capture", status_code=201)
def capture_page(payload:ExtCaptureRequest,request:Request,db:Session=Depends(get_db),user:User=Depends(get_ext_user)):
    """Explicit private page capture; no source, provider or shared catalog calls."""
    import hashlib
    import hmac
    from urllib.parse import urlsplit
    from app.models.chapter import Chapter,ContentStatus
    from app.models.novel import Novel
    from app.models.ereader import AppPassword
    from app.services.chapter_document import from_html
    from app.services.chapter_identity_service import sqlite_transaction,manifest_state,source_version,state_fields
    from app.services.content_limit_service import item_allowed,RESTRICTED_MESSAGE
    user_id,storage_id=user.id,user.storage_id
    try:
        parts=urlsplit(payload.url)
        if parts.scheme not in {'http','https'} or not parts.hostname or parts.username or parts.password:raise ValueError('Capture requires a web page URL without credentials')
    except ValueError as exc:raise HTTPException(422,detail=str(exc)) from exc
    key='nexus-capture:'+hashlib.sha256(payload.url.encode()).hexdigest()
    credential=_capture_credential(db,request,user)
    initial_scope,_,_,initial_proof=_capture_target(db,user_id,payload.library_id,key,payload.url)
    _expected_capture(payload,initial_proof)
    # Sanitation can take time. No account/story locks or read transactions
    # cross it; the exact initial lifecycle is checked again before publication.
    db.rollback()
    try:document=from_html(payload.html)
    except ValueError as exc:raise HTTPException(422,detail=str(exc)) from exc
    if not document['plain_text'].strip():raise HTTPException(422,'The selected page has no readable text')
    sqlite_transaction(db,write=True)
    user=db.query(User).filter_by(id=user_id).populate_existing().with_for_update().first()
    if user is None or user.is_disabled or user.storage_id!=storage_id:raise HTTPException(401,'Account is unavailable')
    app_password=db.query(AppPassword).filter_by(id=credential[0],user_id=user_id,scope='extension',revoked_at=None).populate_existing().with_for_update().first()
    if app_password is None or user.username!=credential[2] or not hmac.compare_digest(app_password.secret_hash,credential[1]):raise HTTPException(401,'Extension authorization changed')
    scope,novel,chapter,proof=_capture_target(db,user_id,payload.library_id,key,payload.url,lock=True)
    if scope!=initial_scope or proof!=initial_proof:_capture_conflict()
    _expected_capture(payload,proof)
    if not item_allowed(user,{'content_rating':'not_rated','tags':[]}):raise HTTPException(403,detail=RESTRICTED_MESSAGE)
    if novel is None:
        novel=Novel(library_id=payload.library_id,title=payload.title,url=key,source_url=payload.url[:500],novel_site='local',site='local',scrape_status='completed',chapter_count=1,num_chapters=1)
        db.add(novel);db.flush()
        chapter=Chapter(novel_id=novel.id,chapter_number=1,title=payload.title,content=document['plain_text'],document=document,source_url=payload.url[:500],content_status=ContentStatus.PRESENT)
        db.add(chapter);db.flush();db.refresh(chapter)
    else:
        from app.services.chapter_version_service import retain_current
        retain_current(db,chapter,reason='browser_capture')
        # No helper commits; recheck the captured UUID/epoch/version rather than
        # selecting whatever might now occupy numeric chapter one.
        _,fresh,current,captured=_capture_target(db,user_id,payload.library_id,key,payload.url,lock=True)
        if fresh.id!=novel.id or captured!=proof:_capture_conflict()
        chapter=current
        chapter.title,chapter.content,chapter.document=payload.title,document['plain_text'],document
        chapter.content_status=ContentStatus.PRESENT
        db.flush()
    state=manifest_state(db,novel.id,lock=True)
    result={'novel_id':novel.id,'library_id':payload.library_id,'chapter_number':1,'chapter_key':chapter.chapter_key,
        **state_fields(state),'source_version':source_version(chapter),'status':'saved','message':'Private page saved; no source or model requests made'}
    db.commit()
    return result



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
