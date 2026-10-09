import logging

from app.logging_config import AccessLogRedactionFilter, redact_url


def test_url_credentials_are_masked():
    assert redact_url("/kobo/abc123/v1/library/sync") == "/kobo/***/v1/library/sync"
    assert redact_url("/api/kobo/abc123") == "/api/kobo/***"
    assert redact_url("/feeds/s3cr3t.atom") == "/feeds/***.atom"
    assert redact_url("/reset-password?token=t0k&x=1") == "/reset-password?token=***&x=1"
    assert redact_url("/auth/oidc/callback?state=s&code=c") == "/auth/oidc/callback?state=***&code=***"
    assert redact_url("/kobo-devices") == "/kobo-devices"
    assert redact_url("/novel/12") == "/novel/12"


def test_uvicorn_access_log_args_are_masked():
    record = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
                               ("1.2.3.4:5", "GET", "/kobo/abc123/v1/initialization", "1.1", 200), None)
    assert AccessLogRedactionFilter().filter(record)
    assert "abc123" not in record.getMessage()
