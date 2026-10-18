from unittest.mock import patch
from app.models import Novel

import app.routers.novel as novel_router

BLURB = "Due to a series of events, a young girl finds herself in another world."


def _run_failed_scrape(db, test_library, scraped: dict) -> str:
    """Run the background scrape against a failed metadata row and return the stored scrape_error."""
    stored = {}
    novel = Novel(library_id=test_library.id, title='Some Story', metadata_id=2)
    db.add(novel)
    db.commit()
    novel_id = novel.id

    def fake_update(db, novel_id, data):
        stored.update(data)

    def fake_call(coro, loop):
        coro.close()
        return scraped

    with patch.object(novel_router, "_run_metadata_call", side_effect=fake_call), patch.object(
        novel_router.novel_services, "update_novel", side_effect=fake_update
    ):
        novel_router.scrape_novel_background(novel_id, 2, lambda: db, loop=None)
    assert stored["scrape_status"] == "failed"
    return stored["scrape_error"]


def test_failed_scrape_never_stores_the_story_description_as_error(db, test_library):
    message = _run_failed_scrape(db, test_library, {"status": "error", "description": BLURB, "title": "Some Story"})
    assert message == "Metadata scrape failed"


def test_failed_scrape_uses_the_real_error_when_provided(db, test_library):
    message = _run_failed_scrape(db, test_library, {"status": "error", "description": BLURB, "last_error": "Story not found"})
    assert message == "Story not found"
