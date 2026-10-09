from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.models.follow import UserNovelFollow
from app.models.novel import Novel
from app.models.user import User
from config.database import get_db
from app.services import metadata_client
from app.services.blocklist_service import apply_blocklist, merged_exclusions
from app.services.library_organization_service import personal_for_novels
from app.services.recommendation_reasons import ReasonSource, build_reasons, terms_of

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

    ratings = personal_for_novels(db, current_user, [item.id for item in follows])
    blocked = merged_exclusions(db, current_user)
    candidates: dict[int, dict] = {}
    # candidate metadata id -> followed novel id -> the reason source for that pair
    sources_by_candidate: dict[int, dict[int, ReasonSource]] = {}
    for followed in follows:
        if not followed.metadata_id:
            continue
        try:
            source_meta = await metadata_client.get_novel_metadata(int(followed.metadata_id))
        except Exception:
            continue
        source = ReasonSource(
            title=followed.title,
            terms=terms_of(source_meta),
            author=source_meta.get("author") or followed.author,
            rating=ratings.get(followed.id, {}).get("rating"),
        )
        for term in source.terms:
            response = await metadata_client.list_novels_metadata(
                tag=term,
                sort_by="follows",
                sort_order="desc",
                limit=limit,
                exclude_tag=blocked["exclude_tag"],
                exclude_fandom=blocked["exclude_fandom"],
                exclude_genre=blocked["exclude_genre"],
                exclude_author=blocked["exclude_author"],
                exclude_text=blocked["exclude_text"],
                content_rating=blocked["content_rating"],
            )
            for candidate in response.get("data", []):
                candidate_id = candidate.get("id")
                if not candidate_id or candidate_id in followed_metadata_ids:
                    continue
                candidates.setdefault(candidate_id, dict(candidate))
                pairs = sources_by_candidate.setdefault(candidate_id, {})
                pair = pairs.setdefault(followed.id, ReasonSource(title=source.title, terms=source.terms, author=source.author, rating=source.rating))
                if term not in pair.via_terms:
                    pair.via_terms.append(term)
            if len(candidates) >= limit:
                break
        if len(candidates) >= limit:
            break
    rows = []
    for candidate_id, candidate in candidates.items():
        reasons = build_reasons(candidate, list(sources_by_candidate.get(candidate_id, {}).values()))
        rows.append({**candidate, "reasons": reasons, "explanation": reasons[0] if reasons else ""})
    rows = apply_blocklist(db, current_user, rows)
    return {"data": rows[:limit]}
