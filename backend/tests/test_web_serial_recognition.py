"""Unsupported http(s) URLs are read as generic web serials."""

import pytest

from app.routers.novel import accepted_src, get_site_name_from_url, is_web_serial_url, supported_src


@pytest.mark.parametrize(
    "url",
    [
        "https://practicalguidetoevil.wordpress.com/",
        "http://example-serial.net/story/1/chapter-2",
        "https://www.example-serial.org/series/abc",
    ],
)
def test_unknown_http_url_is_recognized_as_webserial(url):
    assert not supported_src(url)
    assert is_web_serial_url(url)
    assert accepted_src(url)
    assert get_site_name_from_url(url) == "webserial"


@pytest.mark.parametrize(
    ("url", "site"),
    [
        ("https://www.royalroad.com/fiction/1", "royalroad"),
        ("https://www.fanfiction.net/s/1", "fanfiction"),
        ("https://www.scribblehub.com/series/1/x/", "scribblehub"),
    ],
)
def test_known_sites_keep_their_names(url, site):
    assert get_site_name_from_url(url) == site


@pytest.mark.parametrize(
    "url",
    ["", None, "ftp://example-serial.net/story", "file:///etc/passwd", "http://", "not a url"],
)
def test_non_web_urls_are_not_accepted(url):
    assert not is_web_serial_url(url)
    assert not accepted_src(url)
    assert get_site_name_from_url(url or "") is None
