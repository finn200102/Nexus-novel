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
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.models.ereader import KoboDevice
from app.models.shelf import Shelf
from app.models.user import User
from app.services import epub_service, kobo_service
from config.database import get_db
from config.settings import settings

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


@router.get("/{token}/v1/library/{book_id}/metadata")
async def book_metadata(
    book_id: str, request: Request, ctx: KoboContext = Depends(kobo_context), db: Session = Depends(get_db)
):
    found = kobo_service.synced_book(db, ctx.device, book_id)
    if found is None or found[0].removed:
        return await _unknown_book(request, ctx)
    row, novel = found
    try:
        file = kobo_service.book_file(db, novel)
    except epub_service.NoDownloadedChapters:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Book not found")
    return [kobo_service.book_metadata(kobo_service.kobo_base(request, ctx.token), row, novel, file)]


@router.get("/{token}/v1/library/{book_id}/state")
async def get_state(book_id: str, request: Request, ctx: KoboContext = Depends(kobo_context), db: Session = Depends(get_db)):
    found = kobo_service.synced_book(db, ctx.device, book_id)
    if found is None:
        return await _unknown_book(request, ctx)
    return [kobo_service.reading_state(db, ctx.device, found[0])]


@router.put("/{token}/v1/library/{book_id}/state")
async def put_state(book_id: str, request: Request, ctx: KoboContext = Depends(kobo_context), db: Session = Depends(get_db)):
    found = kobo_service.synced_book(db, ctx.device, book_id)
    if found is None:
        return await _unknown_book(request, ctx)
    try:
        body = await request.json()
        state = body["ReadingStates"][0]
        if not isinstance(state, dict):
            raise TypeError
    except (ValueError, KeyError, IndexError, TypeError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Malformed reading state")
    result = kobo_service.apply_reading_state(db, ctx.device, found[0], state)
    return {"RequestResult": "Success", "UpdateResults": [result]}


@router.delete("/{token}/v1/library/{book_id}")
async def delete_book(book_id: str, request: Request, ctx: KoboContext = Depends(kobo_context), db: Session = Depends(get_db)):
    """Removed on the device: take the story off the synced shelf so it does not come back."""
    found = kobo_service.synced_book(db, ctx.device, book_id)
    if found is None:
        return await _unknown_book(request, ctx)
    kobo_service.forget_book(db, ctx.device, found[0])
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{token}/download/{book_id}/{book_format}")
def download(
    book_id: str, book_format: str, ctx: KoboContext = Depends(kobo_context), db: Session = Depends(get_db)
):
    found = kobo_service.synced_book(db, ctx.device, book_id)
    if found is None or found[0].removed or book_format not in ("kepub", "epub"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Book not found")
    _, novel = found
    try:
        file = kobo_service.book_file(db, novel)
    except epub_service.NoDownloadedChapters:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Book not found")
    path = file.path if book_format == "kepub" or file.kobo_format != "KEPUB" else file.built.path
    suffix = ".kepub.epub" if path.name.endswith(".kepub.epub") else ".epub"
    filename = f"{(novel.title or 'nexus-novel').replace(' ', '-').lower()}{suffix}"
    return FileResponse(path, media_type="application/epub+zip", filename=filename)


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
