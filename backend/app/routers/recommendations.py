from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.models.follow import UserNovelFollow
from app.models.novel import Novel
from app.models.user import User
from config.database import get_db
from app.services import metadata_client

router = APIRouter(prefix="/recommendations", tags=["recommendations"])


@router.get("")
async def recommendations(
    limit: int = Query(20, ge=1, le=50),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return recommendations derived only from this user's followed works.

    There is deliberately no global fallback: a result must have a readable
    connection to a work the current user follows.
    """
    follows = (
        db.query(Novel)
        .join(UserNovelFollow, UserNovelFollow.novel_id == Novel.id)
        .filter(UserNovelFollow.user_id == current_user.id)
        .order_by(UserNovelFollow.updated_at.desc())
        .limit(12)
        .all()
    )
    followed_metadata_ids = {item.metadata_id for item in follows if item.metadata_id}
    if not follows:
        return {"data": [], "reason": "Follow stories to receive personal recommendations."}

    candidates: dict[int, dict] = {}
    for followed in follows:
        if not followed.metadata_id:
            continue
        try:
            source = await metadata_client.get_novel_metadata(int(followed.metadata_id))
        except Exception:
            continue
        terms = [tag.get("name") if isinstance(tag, dict) else tag for tag in source.get("tags", [])]
        terms += [genre.get("name") if isinstance(genre, dict) else genre for genre in source.get("genres", [])]
        for term in (value for value in terms if value):
            response = await metadata_client.list_novels_metadata(
                tag=str(term), sort_by="follows", sort_order="desc", limit=limit
            )
            for candidate in response.get("data", []):
                candidate_id = candidate.get("id")
                if not candidate_id or candidate_id in followed_metadata_ids:
                    continue
                candidates.setdefault(
                    candidate_id,
                    {
                        **candidate,
                        "explanation": f"Shares {term} with {followed.title}.",
                    },
                )
                if len(candidates) >= limit:
                    return {"data": list(candidates.values())[:limit]}
    return {"data": list(candidates.values())[:limit]}
