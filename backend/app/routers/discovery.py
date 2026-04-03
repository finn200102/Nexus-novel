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
    limit: int = Query(20, ge=1, le=100, description="Max items to return"),
    cursor: Optional[int] = Query(None, description="Pagination cursor"),
    current_user: User = Depends(get_current_user),
):
    """Get novels from metadata server with optional filtering."""
    data = await metadata_client.list_novels_metadata(
        site=site,
        author=author,
        title=title,
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
