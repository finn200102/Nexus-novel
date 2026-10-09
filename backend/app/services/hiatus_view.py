"""Turn the metadata service's raw hiatus estimate into what the story page shows.

The metadata service reports ``state`` as ``active``, ``likely_hiatus`` or
``unknown`` plus ``last_update_at`` (ISO 8601) and ``baseline_days``. The page
needs one of three states and a short human label.
"""
from datetime import datetime, timezone


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def days_since(last_update_at: datetime, now: datetime) -> int:
    return max(0, int((now - last_update_at).total_seconds() // 86400))


def hiatus_label(last_update_at: datetime, now: datetime) -> str:
    days = days_since(last_update_at, now)
    if days < 1:
        return "Updated today"
    if days < 30:
        return f"Updated {days} day{'s' if days != 1 else ''} ago"
    months = days // 30
    return f"No update in {months} month{'s' if months != 1 else ''}"


def hiatus_view(raw: dict | None, now: datetime | None = None) -> dict:
    """Map a raw metadata hiatus payload to ``{state, last_update_at, label}``.

    ``state`` is ``hiatus`` when the metadata service thinks the work is on
    hiatus, ``slowing`` when the gap since the last update is past twice the
    usual cadence, and ``active`` otherwise (including when nothing is known).
    """
    now = now or datetime.now(timezone.utc)
    raw = raw or {}
    last = _parse(raw.get("last_update_at"))
    state = "active"
    if raw.get("state") == "likely_hiatus":
        state = "hiatus"
    elif last is not None:
        baseline = raw.get("baseline_days")
        if isinstance(baseline, (int, float)) and baseline > 0 and days_since(last, now) >= baseline * 2:
            state = "slowing"
    label = hiatus_label(last, now) if last is not None else "Update timing unknown"
    return {
        "state": state,
        "last_update_at": last.isoformat() if last is not None else None,
        "label": label,
    }
