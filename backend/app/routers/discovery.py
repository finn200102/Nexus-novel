from fastapi import APIRouter, Depends, Query
from typing import Optional
from app.auth.dependencies import get_current_user
from app.models.user import User
from app.services import metadata_client

router = APIRouter(
    prefix="/discovery",
    tags=["discovery"],
    responses={404: {"description": "Not found"}},
)


@router.get("/novels/")
async def get_novels(
    site: Optional[str] = Query(
        None,
        description="Filter by site: royalroad, fanfiction, webnovel, archive, spacebattles",
    ),
    author: Optional[str] = Query(None, description="Filter by author name"),
    title: Optional[str] = Query(None, description="Search by title"),
    tag: Optional[str] = Query(None, description="Search source tags"),
    fandom: Optional[str] = Query(None, description="Search normalized fandom tags"),
    genre: Optional[str] = Query(None, description="Search source genres"),
    status: Optional[str] = Query(None, description="Filter by publication status"),
    min_word_count: Optional[int] = Query(None, ge=0),
    min_favorites: Optional[int] = Query(None, ge=0),
    min_follows: Optional[int] = Query(None, ge=0),
    min_reviews: Optional[int] = Query(None, ge=0),
    min_chapter_count: Optional[int] = Query(None, ge=0),
    max_word_count: Optional[int] = Query(None, ge=0),
    updated_since_days: Optional[int] = Query(None, ge=1, le=3650),
    label: Optional[str] = Query(None),
    label_origin: Optional[str] = Query(None, pattern="^(source|ai|user|community)$"),
    import_state: Optional[str] = Query(None, pattern="^(ready|in_progress)$"),
    sort_by: str = Query("updated"),
    sort_order: str = Query("desc", pattern="^(asc|desc)$"),
    limit: int = Query(20, ge=1, le=100, description="Max items to return"),
    cursor: Optional[int] = Query(None, description="Pagination cursor"),
    current_user: User = Depends(get_current_user),
):
    """Get novels from metadata server with optional filtering."""
    data = await metadata_client.list_novels_metadata(
        site=site,
        author=author,
        title=title,
        tag=tag,
        fandom=fandom,
        genre=genre,
        status=status,
        min_word_count=min_word_count,
        min_favorites=min_favorites,
        min_follows=min_follows,
        min_reviews=min_reviews,
        min_chapter_count=min_chapter_count,
        max_word_count=max_word_count,
        updated_since_days=updated_since_days,
        label=label,
        label_origin=label_origin,
        import_state=import_state,
        sort_by=sort_by,
        sort_order=sort_order,
        limit=limit,
        cursor=cursor,
    )
    return data


@router.get("/novels/{novel_id}")
async def get_novel_by_id(
    novel_id: int,
    current_user: User = Depends(get_current_user),
):
    """Get a single novel's details from metadata server."""
    data = await metadata_client.get_novel_metadata(novel_id)
    return data


@router.get("/sites/")
async def get_supported_sites(
    current_user: User = Depends(get_current_user),
):
    """Get list of supported sites."""
    return {
        "sites": [
            {"id": "royalroad", "name": "Royal Road"},
            {"id": "fanfiction", "name": "FanFiction.Net"},
            {"id": "spacebattles", "name": "SpaceBattles"},
            {"id": "archive", "name": "Archive of Our Own"},
            {"id": "webnovel", "name": "WebNovel"},
        ]
    }


@router.get("/fandoms/")
async def get_fandoms(
    site: Optional[str] = Query(None, description="Restrict to a source site"),
    media_type: Optional[str] = Query(None, description="Restrict to a source archive category"),
    q: Optional[str] = Query(None, description="Search canonical fandom names"),
    limit: int = Query(100, ge=1, le=250),
    current_user: User = Depends(get_current_user),
):
    """Expose persisted source fandoms without making the browser call metadata directly."""
    return await metadata_client.list_fandoms_metadata(
        site=site, media_type=media_type, query=q, limit=limit
    )
