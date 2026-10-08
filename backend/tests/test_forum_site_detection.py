"""URL recognition for the XenForo forums and ScribbleHub."""

import pytest

from app.routers.chapter import extract_story_id_from_url, supported_src as chapter_supported
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
    assert chapter_supported(url)
    assert get_site_name_from_url(url) == site
    assert chapter_site(url) == site


def test_story_ids_are_extracted_for_each_site():
    assert extract_story_id_from_url("https://forums.sufficientvelocity.com/threads/the-wrong-kind.153279/", "sufficientvelocity") == 153279
    assert extract_story_id_from_url("https://forum.questionablequesting.com/threads/jim.40757/", "questionablequesting") == 40757
    assert extract_story_id_from_url("https://www.scribblehub.com/series/123456/example/", "scribblehub") == 123456
