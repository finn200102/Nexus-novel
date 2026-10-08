import pytest

from app.services.novel_title import clean_title


@pytest.mark.parametrize(
    ("raw", "url", "expected"),
    [
        ("mother-of-learning", "https://www.royalroad.com/fiction/mother-of-learning", "Mother of Learning"),
        ("Some%20Title", None, "Some Title"),
        ("Threadmarks for: Worm", None, "Worm"),
        ("Scraping...", "https://example.test/stories/some-story/", "Some Story"),
        ("Unknown", "https://example.test/stories/my_tale", "My Tale"),
        ("", "https://example.test/x/the-end-of-days", "The End of Days"),
        ("Already Clean Title", "https://example.test/x/already-clean-title", "Already Clean Title"),
        ("Bad %E9 escape", None, "Bad escape"),
    ],
)
def test_clean_title(raw, url, expected):
    assert clean_title(raw, url) == expected


def test_clean_title_empty_without_source():
    assert clean_title(None, None) == ""


def test_clean_title_idempotent():
    once = clean_title("Threadmarks for: some-long-title", None)
    assert clean_title(once, None) == once
