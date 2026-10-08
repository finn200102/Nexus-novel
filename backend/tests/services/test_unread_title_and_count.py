import pytest

from app.services.user_data_service import title_from_url


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://www.royalroad.com/fiction/21220/mother-of-learning", "Mother of Learning"),
        ("https://example.test/jim-the-groundskeeper-original-fantasy/", "Jim the Groundskeeper Original Fantasy"),
        ("https://forums.sufficientvelocity.com/threads/the-wrong-kind-of-immortality-%E2%80%94-slow-burn.1/",
         "The Wrong Kind of Immortality — Slow Burn.1"),
        ("https://example.test/some_under_score-story", "Some Under Score Story"),
        ("https://example.test/", "Untitled story"),
    ],
)
def test_title_from_url_decodes_and_humanizes_slugs(url, expected):
    assert "%" not in title_from_url(url)
    assert title_from_url(url) == expected
