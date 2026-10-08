"""URL recognition for the XenForo forums and ScribbleHub."""

import pytest

from app.routers.chapter import extract_story_id_from_url
from app.routers.chapter import get_site_name_from_url as chapter_site
from app.routers.novel import get_site_name_from_url, supported_src


@pytest.mark.parametrize(
    ("url", "site"),
    [
        ("https://forums.sufficientvelocity.com/threads/the-wrong-kind.153279/", "sufficientvelocity"),
        ("https://forum.questionablequesting.com/threads/jim-the-groundskeeper.40757/", "questionablequesting"),
        ("https://www.scribblehub.com/series/123456/example-series/", "scribblehub"),
        ("https://forums.spacebattles.com/threads/example.123/", "spacebattles"),
    ],
)
def test_site_is_recognized_from_source_url(url, site):
    assert supported_src(url)
    assert get_site_name_from_url(url) == site
    assert chapter_site(url) == site


def test_story_ids_are_extracted_for_each_site():
    assert extract_story_id_from_url("https://forums.sufficientvelocity.com/threads/the-wrong-kind.153279/", "sufficientvelocity") == 153279
    assert extract_story_id_from_url("https://forum.questionablequesting.com/threads/jim.40757/", "questionablequesting") == 40757
    assert extract_story_id_from_url("https://www.scribblehub.com/series/123456/example/", "scribblehub") == 123456


@pytest.mark.parametrize(
    "url",
    [
        "http://10.0.0.1/?www.royalroad.com",
        "https://evil.example/www.fanfiction.net/s/1",
        "file:///etc/passwd#archiveofourown.org",
        "https://www.royalroad.com.evil.example/fiction/1",
        "",
        None,
    ],
)
def test_supported_src_matches_the_host_not_a_substring(url):
    assert not supported_src(url)
