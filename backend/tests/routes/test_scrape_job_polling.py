"""Metadata import polling follows its job without mistaking retries for failure."""
import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest

from app.services import metadata_client as metadata


@pytest.mark.parametrize("status", ["failed", "paused", "cancelled", "archived"])
def test_placeholder_stops_waiting_when_its_job_stops(monkeypatch, status):
    monkeypatch.setattr(metadata, "get_novel_metadata", AsyncMock(return_value={"status": "scraping", "title": "Existing title"}))
    request = AsyncMock(return_value=httpx.Response(200, json={"status": status}))
    monkeypatch.setattr(metadata, "_request", request)
    with pytest.raises(RuntimeError, match=f"Metadata import (is )?{status}.*Operations"):
        asyncio.run(metadata.wait_for_scrape_complete(4, job_id="job-4", poll_interval_seconds=0))
    assert request.call_args.args == ("GET", "/api/jobs/job-4")


@pytest.mark.parametrize("status", ["queued", "running", "retry_wait"])
def test_active_job_keeps_polling_until_metadata_ready(monkeypatch, status):
    ready = {"status": "ongoing", "title": "Real title", "chapter_count": 10}
    fetch = AsyncMock(side_effect=[{"status": "scraping", "title": "Scraping..."}, ready])
    monkeypatch.setattr(metadata, "get_novel_metadata", fetch)
    request = AsyncMock(return_value=httpx.Response(200, json={"status": status, "error_code": "SOURCE_CIRCUIT_OPEN"}))
    monkeypatch.setattr(metadata, "_request", request)
    assert asyncio.run(metadata.wait_for_scrape_complete(4, job_id="job-4", poll_interval_seconds=0)) == ready
    assert fetch.await_count == 2


def test_ready_metadata_wins_over_older_job_failure(monkeypatch):
    ready = {"status": "completed", "title": "Real title"}
    monkeypatch.setattr(metadata, "get_novel_metadata", AsyncMock(return_value=ready))
    request = AsyncMock(side_effect=AssertionError("Ready metadata needs no job lookup"))
    monkeypatch.setattr(metadata, "_request", request)
    assert asyncio.run(metadata.wait_for_scrape_complete(4, job_id="old-job")) == ready


def test_legacy_metadata_without_job_id_still_polls(monkeypatch):
    ready = {"status": "ongoing", "title": "Real title"}
    monkeypatch.setattr(metadata, "get_novel_metadata", AsyncMock(side_effect=[{"status": "scraping", "title": "Scraping..."}, ready]))
    monkeypatch.setattr(metadata, "_request", AsyncMock(side_effect=AssertionError("No job was provided")))
    assert asyncio.run(metadata.wait_for_scrape_complete(4, poll_interval_seconds=0)) == ready
