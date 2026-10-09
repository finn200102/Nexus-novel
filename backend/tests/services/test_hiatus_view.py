from datetime import datetime, timedelta, timezone

from app.services.hiatus_view import hiatus_label, hiatus_view

NOW = datetime(2026, 10, 9, tzinfo=timezone.utc)


def _ago(days: float) -> str:
    return (NOW - timedelta(days=days)).isoformat()


def test_label_for_recent_updates():
    assert hiatus_label(NOW - timedelta(hours=3), NOW) == "Updated today"
    assert hiatus_label(NOW - timedelta(days=1), NOW) == "Updated 1 day ago"
    assert hiatus_label(NOW - timedelta(days=3, hours=5), NOW) == "Updated 3 days ago"
    assert hiatus_label(NOW - timedelta(days=29), NOW) == "Updated 29 days ago"


def test_label_for_long_gaps_counts_whole_months():
    assert hiatus_label(NOW - timedelta(days=30), NOW) == "No update in 1 month"
    assert hiatus_label(NOW - timedelta(days=14 * 30 + 2), NOW) == "No update in 14 months"


def test_likely_hiatus_maps_to_hiatus():
    view = hiatus_view({"state": "likely_hiatus", "baseline_days": 3.0, "last_update_at": _ago(400)}, NOW)
    assert view["state"] == "hiatus"
    assert view["label"] == "No update in 13 months"


def test_recent_update_is_active():
    view = hiatus_view({"state": "active", "baseline_days": 3.0, "last_update_at": _ago(2)}, NOW)
    assert view == {"state": "active", "last_update_at": _ago(2), "label": "Updated 2 days ago"}


def test_overdue_beyond_twice_cadence_is_slowing():
    view = hiatus_view({"state": "active", "baseline_days": 5.0, "last_update_at": _ago(12)}, NOW)
    assert view["state"] == "slowing"


def test_unknown_payload_is_active_without_date():
    assert hiatus_view({"state": "unknown", "confidence": 0.0}, NOW) == {
        "state": "active",
        "last_update_at": None,
        "label": "Update timing unknown",
    }
    assert hiatus_view(None, NOW)["state"] == "active"
