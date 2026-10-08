from unittest.mock import MagicMock, patch

import app.routers.novel as novel_router

BLURB = "Due to a series of events, a young girl finds herself in another world."


def _run_failed_scrape(scraped: dict) -> str:
    """Run the background scrape against a failed metadata row and return the stored scrape_error."""
    stored = {}

    def fake_update(db, novel_id, data):
        stored.update(data)

    def fake_call(coro, loop):
        coro.close()
        return scraped

    with patch.object(novel_router, "_run_metadata_call", side_effect=fake_call), patch.object(
        novel_router.novel_services, "update_novel", side_effect=fake_update
    ):
        novel_router.scrape_novel_background(1, 2, lambda: MagicMock(), loop=None)
    assert stored["scrape_status"] == "failed"
    return stored["scrape_error"]


def test_failed_scrape_never_stores_the_story_description_as_error():
    message = _run_failed_scrape({"status": "error", "description": BLURB, "title": "Some Story"})
    assert message == "Metadata scrape failed"


def test_failed_scrape_uses_the_real_error_when_provided():
    message = _run_failed_scrape({"status": "error", "description": BLURB, "last_error": "Story not found"})
    assert message == "Story not found"
