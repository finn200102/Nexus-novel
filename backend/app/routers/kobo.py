"""Native Kobo sync (experimental): the Kobo store API under ``/kobo/<token>``.

The device's ``api_endpoint`` points here (see docs/kobo-sync.md). Nexus
answers initialization, library sync, metadata, downloads and reading state
itself. Everything else gets an empty answer, or, when
``NEXUS_KOBO_STORE_PROXY`` is on, is forwarded to the Kobo store without the
Nexus token, cookies or forwarding headers.

``/kobo-devices`` is the signed-in management API for Settings, E-readers.
"""

import json
import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status, Query
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.auth.dependencies import get_current_user
from app.models.ereader import KoboDevice
from app.models.shelf import Shelf
from app.models.user import User
from app.services import epub_service, kobo_service
from config.database import get_db
from config.settings import settings
from app.schemas.ereader_identity import KoboVersionConfirmation,KoboBookVersionPage,KoboVersionConfirmed

KOBO_STORE = "https://storeapi.kobo.com"
# Headers worth sending to the store: the device's own store credentials and
# content negotiation. Cookies, Host and X-Forwarded-* never leave Nexus.
FORWARDED_HEADERS = ("authorization", "content-type", "accept", "accept-language", "user-agent")

router = APIRouter(prefix="/kobo", tags=["kobo"])
devices_router = APIRouter(prefix="/kobo-devices", tags=["kobo"])


# ---- management (signed in) ------------------------------------------------------

class KoboDeviceCreate(BaseModel):
    label: str = Field(default="", max_length=120)
    shelf_id: int | None = None


class KoboDeviceUpdate(BaseModel):
    shelf_id: int


def _device_out(db: Session, device: KoboDevice) -> dict:
    shelf = db.query(Shelf).filter(Shelf.id == device.shelf_id).first() if device.shelf_id else None
    return {
        "id": device.id,
        "label": device.label,
        "shelf_id": device.shelf_id,
        "shelf_name": shelf.name if shelf else None,
        "created_at": device.created_at,
        "last_used_at": device.last_used_at,
        "last_sync_at": device.last_sync_at,
    }


@devices_router.get("")
def list_devices(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return {
        "kepub": kobo_service.kepubify_binary() is not None,
        "devices": [_device_out(db, device) for device in kobo_service.list_devices(db, user.id)],
    }


@devices_router.post("", status_code=status.HTTP_201_CREATED)
def create_device(payload: KoboDeviceCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    device, token = kobo_service.create_device(db, user, payload.label, payload.shelf_id)
    # Shown once; the path the device's api_endpoint must end with.
    return {**_device_out(db, device), "token": token, "endpoint_path": f"/kobo/{token}"}


@devices_router.patch("/{device_id}")
def update_device(
    device_id: int, payload: KoboDeviceUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    device = kobo_service.get_device(db, user.id, device_id)
    device.shelf_id = kobo_service.owned_shelf(db, user, payload.shelf_id).id
    db.commit()
    return _device_out(db, device)


@devices_router.delete("/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_device(device_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    kobo_service.revoke_device(db, user.id, device_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@devices_router.get('/{device_id}/books',response_model=KoboBookVersionPage)
def device_books(response:Response,device_id:int,offset:int=Query(0,ge=0,le=2147483647),limit:int=Query(50,ge=1,le=100),
                 db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    response.headers["Cache-Control"]="private, no-store"
    return kobo_service.book_versions(db,user.id,device_id,offset=offset,limit=limit)


@devices_router.get('/{device_id}/books/{entitlement}/versions/{fingerprint}/file')
def historical_device_file(device_id:int,entitlement:str,fingerprint:str,db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    from app.models.ereader import EpubBuild,KoboSyncedBook
    from app.services.ereader_identity_service import owner
    device=kobo_service.get_device(db,user.id,device_id)
    row=db.query(KoboSyncedBook).filter_by(device_id=device.id,entitlement_id=entitlement).first()
    if row is None:raise HTTPException(404,'Book not found')
    account,_=owner(db,user.id,row.novel_id)
    build=db.query(EpubBuild).filter_by(novel_id=row.novel_id,fingerprint=fingerprint,owner_storage_id=account.storage_id).first()
    if build is None:raise HTTPException(404,'Private book version not found')
    try:path=epub_service.cached_path(build)
    except FileNotFoundError:raise HTTPException(404,'Private book file unavailable') from None
    db.commit()
    return FileResponse(path,media_type='application/epub+zip',filename='saved-book.epub',headers={'Cache-Control':'private, no-store'})


@devices_router.post('/{device_id}/books/{entitlement}/confirm-version',response_model=KoboVersionConfirmed)
def confirm_device_book(response:Response,device_id:int,entitlement:str,value:KoboVersionConfirmation,
                        db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    response.headers["Cache-Control"]="private, no-store"
    return kobo_service.confirm_version(db,user.id,device_id,entitlement,**value.model_dump())


# ---- the Kobo protocol --------------------------------------------------------------

class KoboContext:
    def __init__(self, token: str, device: KoboDevice, user: User):
        self.token = token
        self.device = device
        self.user = user


def kobo_context(token: str, request: Request, db: Session = Depends(get_db)) -> KoboContext:
    device, user = kobo_service.device_for_token(db, request, token)
    return KoboContext(token, device, user)


async def _proxy(request: Request, store_path: str) -> Response:
    """Forward to the Kobo store. ``store_path`` excludes ``/kobo/<token>``."""
    headers = {name: value for name, value in request.headers.items() if name.lower() in FORWARDED_HEADERS or name.lower().startswith("x-kobo-")}
    headers.pop(kobo_service.SYNC_TOKEN_HEADER, None)
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            upstream = await client.request(
                request.method,
                f"{KOBO_STORE}/{store_path.lstrip('/')}",
                params=request.query_params,
                headers=headers,
                content=await request.body(),
            )
    except httpx.HTTPError:
        return JSONResponse({}, status_code=status.HTTP_502_BAD_GATEWAY)
    passthrough = {key: value for key, value in upstream.headers.items() if key.lower().startswith("x-kobo-")}
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type"),
        headers=passthrough,
    )


def _resources(base: str, host: str) -> dict:
    """Store resources pointing at Nexus, so an unproxied device never calls Kobo's API."""
    api = {
        "add_entitlement": "/v1/library/{RevisionIds}",
        "affiliaterequest": "/v1/affiliate",
        "authorproduct_recommendations": "/v1/products/books/authors/recommendations",
        "autocomplete": "/v1/products/autocomplete",
        "book": "/v1/products/books/{ProductId}",
        "book_subscription": "/v1/products/books/subscriptions",
        "categories": "/v1/categories",
        "category": "/v1/categories/{CategoryId}",
        "category_featured_lists": "/v1/categories/{CategoryId}/featured",
        "category_products": "/v1/categories/{CategoryId}/products",
        "checkout_borrowed_book": "/v1/library/borrow",
        "configuration_data": "/v1/configuration",
        "content_access_book": "/v1/products/books/{ProductId}/access",
        "daily_deal": "/v1/products/dailydeal",
        "deals": "/v1/deals",
        "delete_entitlement": "/v1/library/{Ids}",
        "delete_tag": "/v1/library/tags/{TagId}",
        "delete_tag_items": "/v1/library/tags/{TagId}/items/delete",
        "device_auth": "/v1/auth/device",
        "device_refresh": "/v1/auth/refresh",
        "exchange_auth": "/v1/auth/exchange",
        "external_book": "/v1/products/books/external/{Ids}",
        "featured_list": "/v1/products/featured/{FeaturedListId}",
        "featured_lists": "/v1/products/featured",
        "get_tests_request": "/v1/analytics/gettests",
        "library_book": "/v1/user/library/books/{LibraryItemId}",
        "library_items": "/v1/user/library",
        "library_metadata": "/v1/library/{Ids}/metadata",
        "library_prices": "/v1/user/library/previews/prices",
        "library_search": "/v1/library/search",
        "library_sync": "/v1/library/sync",
        "notifications_registration_issue": "/v1/notifications/registration",
        "post_analytics_event": "/v1/analytics/event",
        "product_nextread": "/v1/products/{ProductIds}/nextread",
        "product_prices": "/v1/products/{ProductIds}/prices",
        "product_recommendations": "/v1/products/{ProductId}/recommendations",
        "product_reviews": "/v1/products/{ProductIds}/reviews",
        "products": "/v1/products",
        "rating": "/v1/products/{ProductId}/rating/{Rating}",
        "reading_state": "/v1/library/{Ids}/state",
        "related_items": "/v1/products/{Id}/related",
        "remaining_book_series": "/v1/products/books/series/{SeriesId}",
        "rename_tag": "/v1/library/tags/{TagId}",
        "review": "/v1/products/reviews/{ReviewId}",
        "tag_items": "/v1/library/tags/{TagId}/Items",
        "tags": "/v1/library/tags",
        "taste_profile": "/v1/products/tasteprofile",
        "update_accessibility_to_preview": "/v1/library/{EntitlementIds}/preview",
        "user_loyalty_benefits": "/v1/user/loyalty/benefits",
        "user_platform": "/v1/user/platform",
        "user_profile": "/v1/user/profile",
        "user_ratings": "/v1/user/ratings",
        "user_recommendations": "/v1/user/recommendations",
        "user_reviews": "/v1/user/reviews",
        "user_wishlist": "/v1/user/wishlist",
    }
    resources = {key: base + path for key, path in api.items()}
    resources.update(
        {
            "kobo_audiobooks_enabled": "False",
            "kobo_audiobooks_subscriptions_enabled": "False",
            "kobo_nativeborrow_enabled": "False",
            "kobo_onestorelibrary_enabled": "False",
            "kobo_redeem_enabled": "False",
            "kobo_shelfie_enabled": "False",
            "kobo_subscriptions_enabled": "False",
            "kobo_superpoints_enabled": "False",
            "kobo_wishlist_enabled": "False",
            "use_one_store": "False",
        }
    )
    resources.update(_image_resources(base, host))
    return resources


def _image_resources(base: str, host: str) -> dict:
    return {
        "image_host": host,
        "image_url_template": base + "/{ImageId}/{Width}/{Height}/false/image.jpg",
        "image_url_quality_template": base + "/{ImageId}/{Width}/{Height}/{Quality}/{IsGreyscale}/image.jpg",
        "library_sync": base + "/v1/library/sync",
    }


@router.get("/{token}/v1/initialization")
async def initialization(request: Request, ctx: KoboContext = Depends(kobo_context)):
    base = kobo_service.kobo_base(request, ctx.token)
    host = "/".join(kobo_service.api_base(request).split("/", 3)[:3])
    resources = None
    if settings.NEXUS_KOBO_STORE_PROXY:
        upstream = await _proxy(request, "/v1/initialization")
        try:
            resources = json.loads(upstream.body).get("Resources") if upstream.status_code == 200 else None
        except (ValueError, AttributeError):
            resources = None
        if isinstance(resources, dict):
            resources.update(_image_resources(base, host))
    if not isinstance(resources, dict):
        resources = _resources(base, host)
    # "e30=" is base64 "{}": no store API token.
    return JSONResponse({"Resources": resources}, headers={"x-kobo-apitoken": "e30="})


@router.post("/{token}/v1/auth/device")
@router.post("/{token}/v1/auth/refresh")
async def auth_device(request: Request, ctx: KoboContext = Depends(kobo_context)):
    if settings.NEXUS_KOBO_STORE_PROXY:
        return await _proxy(request, request.url.path.split(f"/kobo/{ctx.token}", 1)[1])
    try:
        body = await request.json()
    except ValueError:
        body = {}
    return {
        "AccessToken": uuid.uuid4().hex,
        "RefreshToken": uuid.uuid4().hex,
        "TokenType": "Bearer",
        "TrackingId": str(uuid.uuid4()),
        "UserKey": (body or {}).get("UserKey", "") if isinstance(body, dict) else "",
    }


@router.get("/{token}/v1/library/sync")
def library_sync(request: Request, ctx: KoboContext = Depends(kobo_context), db: Session = Depends(get_db)):
    result = kobo_service.sync(
        db, ctx.device, kobo_service.kobo_base(request, ctx.token), request.headers.get(kobo_service.SYNC_TOKEN_HEADER)
    )
    headers = {kobo_service.SYNC_TOKEN_HEADER: kobo_service.encode_sync_token(ctx.device)}
    if result.more:
        headers["x-kobo-sync"] = "continue"
    return JSONResponse(result.items, headers=headers)


async def _unknown_book(request: Request, ctx: KoboContext) -> Response:
    if settings.NEXUS_KOBO_STORE_PROXY:
        return await _proxy(request, request.url.path.split(f"/kobo/{ctx.token}", 1)[1])
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Book not found")


def _local_book_call(db,device,book_id,action):
    """Synchronous locks run in the thread pool; no transaction crosses proxy I/O."""
    try:
        found=kobo_service.synced_book(db,device,book_id)
        if found is None or found[0].removed:
            db.rollback()
            return None
        result=action(*found)
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise


@router.get("/{token}/v1/library/{book_id}/metadata")
async def book_metadata(book_id:str,request:Request,ctx:KoboContext=Depends(kobo_context),db:Session=Depends(get_db)):
    def local(row,novel):
        try:file=kobo_service.book_file(db,novel)
        except epub_service.NoDownloadedChapters:raise HTTPException(404,'Book not found') from None
        return [kobo_service.book_metadata(kobo_service.kobo_base(request,ctx.token),row,novel,file)]
    result=await run_in_threadpool(_local_book_call,db,ctx.device,book_id,local)
    return result if result is not None else await _unknown_book(request,ctx)


@router.get("/{token}/v1/library/{book_id}/state")
async def get_state(book_id:str,request:Request,ctx:KoboContext=Depends(kobo_context),db:Session=Depends(get_db)):
    result=await run_in_threadpool(_local_book_call,db,ctx.device,book_id,lambda row,novel:[kobo_service.reading_state(db,ctx.device,row)])
    return result if result is not None else await _unknown_book(request,ctx)


@router.put("/{token}/v1/library/{book_id}/state")
async def put_state(book_id:str,request:Request,ctx:KoboContext=Depends(kobo_context),db:Session=Depends(get_db)):
    try:
        body=await request.json()
        state=body['ReadingStates'][0]
        if not isinstance(state,dict):raise TypeError
    except (ValueError,KeyError,IndexError,TypeError):raise HTTPException(400,'Malformed reading state') from None
    result=await run_in_threadpool(_local_book_call,db,ctx.device,book_id,lambda row,novel:kobo_service.apply_reading_state(db,ctx.device,row,state))
    return {'RequestResult':'Success','UpdateResults':[result]} if result is not None else await _unknown_book(request,ctx)


@router.delete("/{token}/v1/library/{book_id}")
async def delete_book(book_id:str,request:Request,ctx:KoboContext=Depends(kobo_context),db:Session=Depends(get_db)):
    def local(row,novel):
        kobo_service.forget_book(db,ctx.device,row)
        return True
    result=await run_in_threadpool(_local_book_call,db,ctx.device,book_id,local)
    return Response(status_code=204) if result is not None else await _unknown_book(request,ctx)


@router.get("/{token}/download/{book_id}/{book_format}")
def download(
    book_id: str, book_format: str, v:str|None=Query(None,max_length=64), ctx: KoboContext = Depends(kobo_context), db: Session = Depends(get_db)
):
    found = kobo_service.synced_book(db, ctx.device, book_id)
    if found is None or found[0].removed or book_format not in ("kepub", "epub"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Book not found")
    row,novel=found
    from app.models.ereader import EpubBuild
    from app.services.ereader_identity_service import owner
    user,novel=owner(db,ctx.user.id,novel.id)
    build=db.query(EpubBuild).filter_by(novel_id=novel.id,fingerprint=row.fingerprint).first()
    if not build or build.owner_storage_id!=user.storage_id or (v is not None and v not in (build.fingerprint,build.fingerprint[:12])):
        raise HTTPException(409,'This download belongs to a different book version. Sync the device again.')
    try:path=epub_service.cached_path(build)
    except FileNotFoundError:raise HTTPException(404,'This book file is unavailable. Sync again.') from None
    if book_format=='kepub':
        converted=kobo_service.ensure_kepub(epub_service.BuiltEpub(build=build,path=path))
        if converted:path=converted
    db.commit()
    suffix = ".kepub.epub" if path.name.endswith(".kepub.epub") else ".epub"
    filename = f"{(novel.title or 'nexus-novel').replace(' ', '-').lower()}{suffix}"
    return FileResponse(path, media_type="application/epub+zip", filename=filename,headers={"Cache-Control":"private, no-store"})


@router.get("/{token}/{image_id}/{width}/{height}/{greyscale}/image.jpg")
@router.get("/{token}/{image_id}/{width}/{height}/{quality}/{greyscale}/image.jpg")
def cover(image_id: str, ctx: KoboContext = Depends(kobo_context)):
    # No local cover files yet; the device draws its own placeholder cover.
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No cover")


@router.get("/{token}/v1/analytics/gettests")
@router.post("/{token}/v1/analytics/gettests")
async def get_tests(request: Request, ctx: KoboContext = Depends(kobo_context)):
    if settings.NEXUS_KOBO_STORE_PROXY:
        return await _proxy(request, "/v1/analytics/gettests")
    return {"Result": "Success", "TestKey": request.headers.get("x-kobo-userkey", ""), "Tests": {}}


@router.get("/{token}/v1/user/loyalty/benefits")
async def loyalty_benefits(request: Request, ctx: KoboContext = Depends(kobo_context)):
    if settings.NEXUS_KOBO_STORE_PROXY:
        return await _proxy(request, "/v1/user/loyalty/benefits")
    return {"Benefits": {}}


@router.api_route("/{token}/{store_path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def store_fallback(store_path: str, request: Request, ctx: KoboContext = Depends(kobo_context)):
    """Endpoints Nexus does not implement (store, tags edited on the device, analytics)."""
    if settings.NEXUS_KOBO_STORE_PROXY:
        return await _proxy(request, store_path)
    return JSONResponse({})
