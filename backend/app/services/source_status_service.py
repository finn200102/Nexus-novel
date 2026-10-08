"""Reader-facing source health: a readable summary of each site the user reads from."""

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.logging_config import get_logger
from app.models.library import Library
from app.models.novel import Novel
from app.models.user import User
from app.services import metadata_client

logger = get_logger("source_status")

SITE_LABELS = {
    "fanfiction": "FanFiction.net",
    "royalroad": "Royal Road",
    "scribblehub": "Scribble Hub",
    "webnovel": "WebNovel",
    "ao3": "AO3",
}


def user_sites(db: Session, user: User) -> list[str]:
    rows = (
        db.query(Novel.novel_site)
        .join(Library, Novel.library_id == Library.id)
        .filter(Library.user_id == user.id, Novel.novel_site.isnot(None))
        .distinct()
        .all()
    )
    return sorted({row[0].strip().lower() for row in rows if row[0] and row[0].strip()})


def _parse_until(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def summarize_site(site: str, health: dict, now: datetime) -> dict:
    """Map one metadata health row to ok|degraded|rate_limited|down without internals."""
    label = SITE_LABELS.get(site, site)
    until = _parse_until(health.get("rate_limit_until"))
    if (until and until > now) or health.get("status") == "rate_limited":
        active_until = until if until and until > now else None
        return {
            "site": site,
            "label": label,
            "state": "rate_limited",
            "until": active_until.isoformat() if active_until else None,
            "message": f"{label} is rate-limiting us.",
        }
    if health.get("status") == "offline" or health.get("circuit_state") == "open":
        return {"site": site, "label": label, "state": "down", "until": None, "message": f"{label} is unavailable right now."}
    if health.get("status") == "degraded" or health.get("circuit_state") == "half-open":
        return {"site": site, "label": label, "state": "degraded", "until": None, "message": f"{label} is responding slowly; updates may be delayed."}
    return {"site": site, "label": label, "state": "ok", "until": None, "message": f"{label} is working normally."}


async def sites_status(db: Session, user: User, now: datetime | None = None) -> dict:
    sites = user_sites(db, user)
    if not sites:
        return {"sites": []}
    try:
        rows = await metadata_client.source_health()
    except RuntimeError as exc:
        # Better to show nothing than to claim a site is down when we cannot check.
        logger.warning("source_status.unavailable", error=str(exc))
        return {"sites": []}
    by_site = {str(row.get("site", "")).lower(): row for row in rows}
    current = now or datetime.now(timezone.utc)
    return {"sites": [summarize_site(site, by_site.get(site, {}), current) for site in sites]}
