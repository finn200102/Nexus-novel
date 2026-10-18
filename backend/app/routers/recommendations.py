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
from app.models.feedback_event import ReaderFeedbackEvent
from app.services.feedback_service import user_signal_matrix, taste_profile
from pydantic import BaseModel, Field
from typing import Literal
import asyncio
from app.schemas.discovery_preferences import DiscoveryPreferenceWrite
from app.services import discovery_preferences

router = APIRouter(prefix="/recommendations", tags=["recommendations"])


@router.get("")
async def recommendations(
    limit: int = Query(20, ge=1, le=50),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retrieve real catalog records using private library/interests signals.

    Cold-start feeds have a separate basis label; no model invents records.
    """
    follows = (
        db.query(Novel)
        .join(UserNovelFollow, UserNovelFollow.novel_id == Novel.id)
        .filter(UserNovelFollow.user_id == current_user.id, Novel.library.has(user_id=current_user.id))
        .order_by(UserNovelFollow.updated_at.desc())
        .limit(12)
        .all()
    )
    followed_metadata_ids = {item.metadata_id for item in follows if item.metadata_id}
    followed_metadata_ids.update(item[0] for item in db.query(Novel.metadata_id).join(Novel.library)
                                .filter(Novel.library.has(user_id=current_user.id)).all() if item[0])
    signals = dict(user_signal_matrix(db, current_user))
    follows = sorted([item for item in follows if signals.get(item.id, 0) >= 0],
                     key=lambda item: (-signals.get(item.id, 0), item.id))
    hidden_ids = {-row.novel_id for row in db.query(ReaderFeedbackEvent).filter(
        ReaderFeedbackEvent.user_id == current_user.id, ReaderFeedbackEvent.novel_id < 0,
        ReaderFeedbackEvent.kind.in_(("hidden", "dismissed_recommendation")),
    )}
    preferences = discovery_preferences.read(db, current_user)["values"]

    ratings = personal_for_novels(db, current_user, [item.id for item in follows])
    blocked = merged_exclusions(db, current_user)
    source_errors = []
    candidates: dict[int, dict] = {}
    # candidate metadata id -> followed novel id -> the reason source for that pair
    sources_by_candidate: dict[int, dict[int, ReasonSource]] = {}
    library_queries = 0
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
        term_queries = [("tag", name) for name in terms_of({"tags": source_meta.get("tags")})] + [("genre", name) for name in terms_of({"genres": source_meta.get("genres")})]
        for field, term in term_queries[:6]:
            if library_queries >= 12:
                break
            library_queries += 1
            try:
                response = await metadata_client.list_novels_metadata(
                **{field: [term]},
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
            except Exception:
                source_errors.append({"filter": field, "value": term, "state": "unavailable"})
                continue
            for candidate in response.get("data", []):
                candidate_id = candidate.get("id")
                if not candidate_id or candidate_id in followed_metadata_ids or candidate_id in hidden_ids:
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
        if library_queries >= 12:
            break
    # Optional explicit interests support cold start without inventing titles.
    preference_candidates = {}
    preference_errors = []
    groups = (("tag", preferences["tags"]), ("fandom", preferences["fandoms"]), ("genre", preferences["genres"]))
    queries = [(field, values[index]) for index in range(max((len(values) for _, values in groups), default=0)) for field, values in groups if index < len(values)][:12]
    if not queries and not candidates:
        queries = [(None, None)]
    semaphore = asyncio.Semaphore(4)
    async def fetch_preference(field, name):
        try:
            async with semaphore:
                response = await metadata_client.list_novels_metadata(**({field: [name]} if field else {}), language=preferences["languages"] or None,
                    sort_by="follows", sort_order="desc", limit=limit, **blocked)
            return field, name, response
        except Exception:
            return field, name, None
    for field, name, response in await asyncio.gather(*(fetch_preference(field, name) for field, name in queries)):
        if response is None:
            preference_errors.append({"filter": field, "value": name, "state": "unavailable"})
            continue
        for candidate in response.get("data", []):
            candidate_id = candidate.get("id")
            if not candidate_id or candidate_id in followed_metadata_ids or candidate_id in hidden_ids:
                continue
            preference_candidates.setdefault(candidate_id, []).append(f"Matches your {field}: {name}" if field else "From the local catalog feed")
            candidates.setdefault(candidate_id, dict(candidate))
    rows = []
    for candidate_id, candidate in candidates.items():
        reasons = build_reasons(candidate, list(sources_by_candidate.get(candidate_id, {}).values()))
        reasons.extend(preference_candidates.get(candidate_id, []))
        rows.append({**candidate, "reasons": reasons, "explanation": reasons[0] if reasons else ""})
    rows = apply_blocklist(db, current_user, rows)
    # Prefer supported explanations and diversify the visible page. This
    # deterministic baseline remains useful without model artifacts.
    rows.sort(key=lambda row: (-len(row.get("reasons", [])), str(row.get("title", "")).lower(), row.get("id", 0)))
    chosen, deferred = [], []
    authors, sites = {}, {}
    for row in rows:
        author, site = str(row.get("author") or "").casefold(), row.get("novel_site")
        if (author and authors.get(author, 0) >= 2) or (site and sites.get(site, 0) >= max(3, limit // 2)):
            deferred.append(row)
            continue
        chosen.append(row)
        authors[author] = authors.get(author, 0) + 1
        sites[site] = sites.get(site, 0) + 1
    if preferences["languages"]:
        allowed_languages = {name.casefold() for name in preferences["languages"]}
        chosen = [row for row in chosen if str(row.get("language") or "").casefold() in allowed_languages]
        deferred = [row for row in deferred if str(row.get("language") or "").casefold() in allowed_languages]
    return {"data": (chosen + deferred)[:limit], "basis": "your_library" if sources_by_candidate else "your_preferences" if any(preferences[name] for name in ("tags", "fandoms", "genres", "languages")) else "catalog_feed", "source_states": source_errors + preference_errors}


@router.get("/preferences")
def get_preferences(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return discovery_preferences.read(db, user)


@router.put("/preferences")
def set_preferences(value: DiscoveryPreferenceWrite, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return discovery_preferences.write(db, user, value)


class RecommendationFeedback(BaseModel):
    metadata_id: int = Field(ge=1)
    action: Literal["not_interested", "dismissed", "opened", "already_read"]


@router.post("/feedback")
def feedback(value: RecommendationFeedback, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    # Catalog feedback uses a negative id so it cannot masquerade as feedback
    # about a local library copy with an unrelated, coincidentally equal id.
    kind = {"not_interested": "hidden", "dismissed": "dismissed_recommendation", "opened": "opened_from_recommendation", "already_read": "hidden"}[value.action]
    db.add(ReaderFeedbackEvent(user_id=current_user.id, novel_id=-value.metadata_id, kind=kind))
    db.commit()
    return {"saved": True}


@router.get("/profile")
def profile(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return taste_profile(db, current_user)


@router.delete("/profile")
def reset_profile(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    db.query(ReaderFeedbackEvent).filter(ReaderFeedbackEvent.user_id == current_user.id).delete()
    db.commit()
    return {"reset": True}
