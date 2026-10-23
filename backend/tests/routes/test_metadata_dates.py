from datetime import UTC, date, datetime

import pytest

from app.models import Novel
from app.services import novel_services
from app.services.source_refresh_guard import refresh_fields


def test_json_metadata_dates_persist_to_sqlite(db, test_library):
    novel = Novel(title="Original", library_id=test_library.id)
    db.add(novel)
    db.commit()
    incoming = {
        "title": "Imported title",
        "publish_date": "2017-12-02T00:00:00",
        "updated_date": "2026-10-18T15:00:00+02:00",
        "analyzed_at": "2026-10-18T13:00:00Z",
        "parsed_at": "2026-10-18",
    }
    updated = novel_services.update_novel(db, novel.id, refresh_fields(db, novel, incoming, incoming))
    assert updated.title == "Imported title"
    assert updated.publish_date == datetime(2017, 12, 2)
    assert updated.updated_date == datetime(2026, 10, 18, 13)
    assert updated.analyzed_at == datetime(2026, 10, 18, 13)
    assert updated.parsed_at == datetime(2026, 10, 18)


def test_metadata_native_dates_null_and_omitted_values(db, test_library):
    novel = Novel(title="Original", library_id=test_library.id)
    db.add(novel)
    db.commit()
    incoming = {"publish_date": date(2017, 12, 2), "updated_date": datetime(2026, 10, 18, tzinfo=UTC), "parsed_at": None}
    fields = {**incoming, "analyzed_at": None}
    result = refresh_fields(db, novel, incoming, fields)
    assert result == {"publish_date": datetime(2017, 12, 2), "updated_date": datetime(2026, 10, 18), "parsed_at": None}


@pytest.mark.parametrize("invalid", ["not-a-date", "2026-02-30", "", 1234, {}, True])
def test_invalid_metadata_date_preserves_original(db, test_library, invalid):
    novel = Novel(title="Original", library_id=test_library.id, publish_date=datetime(2017, 12, 2))
    db.add(novel)
    db.commit()
    incoming = {"title": "Unpublished change", "publish_date": invalid}
    with pytest.raises(ValueError, match="invalid publish_date"):
        novel_services.update_novel(db, novel.id, refresh_fields(db, novel, incoming, incoming))
    db.rollback()
    db.refresh(novel)
    assert novel.title == "Original" and novel.publish_date == datetime(2017, 12, 2)
