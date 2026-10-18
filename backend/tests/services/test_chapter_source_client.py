import httpx
import asyncio
from app.services import metadata_client


def test_async_chapter_fetch_uses_the_dedicated_download_timeout(monkeypatch):
    received = {}
    async def request(method, path, **kwargs):
        received.update(method=method, path=path, **kwargs)
        return httpx.Response(200, json={"text": "Story", "image_assets": {"missing": 1}})
    monkeypatch.setattr(metadata_client, "_request", request)
    result = asyncio.run(metadata_client.fetch_public_chapter_text(12, 3))
    assert received["timeout"] is metadata_client.CHAPTER_FETCH_TIMEOUT
    assert received["path"] == "/chapters/novel/12/3/fetch"
    assert result["image_assets"]["missing"] == 1


def test_sync_chapter_fetch_keeps_source_access_in_the_metadata_gateway(monkeypatch):
    received = {}
    class Client:
        def __init__(self, **kwargs): received.update(kwargs)
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def post(self, url, **kwargs):
            received["url"] = url
            return httpx.Response(200, request=httpx.Request("POST", url), json={"text": "Story"})
    monkeypatch.setattr(metadata_client.httpx, "Client", Client)
    monkeypatch.setattr(metadata_client, "_get_headers", lambda: {})
    assert metadata_client.fetch_public_chapter_text_sync(12, 3)["text"] == "Story"
    assert received["timeout"] is metadata_client.CHAPTER_FETCH_TIMEOUT
    assert received["url"].endswith("/chapters/novel/12/3/fetch")
    assert 20 <= received["timeout"].read <= 300 and received["timeout"].connect == 3


def test_bound_source_request_passes_both_keys_and_rejects_unproved_response(monkeypatch):
    from uuid import uuid4
    import httpx
    import pytest
    from app.services import metadata_client
    manifest,chapter=str(uuid4()),str(uuid4())
    source={'site':'royalroad','story_id':12,'source_url':'https://www.royalroad.com/fiction/12'}
    requests=[]
    class Client:
        def __init__(self,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def post(self,url,**kwargs):
            assert url.endswith('/12/-2/fetch-by-identity')
            requests.append(kwargs)
            return httpx.Response(200,json={'text':'Unproved numeric content'},request=httpx.Request('POST',url))
    monkeypatch.setattr(metadata_client.httpx,'Client',Client)
    with pytest.raises(metadata_client.ChapterSourceError) as caught:
        metadata_client.fetch_public_chapter_text_sync(12,-2,expected_manifest_key=manifest,expected_chapter_key=chapter,expected_source=source)
    assert caught.value.category=='chapter_review_required' and not caught.value.retryable
    import json
    assert requests[0]['params']['expected_manifest_key']==manifest and requests[0]['params']['expected_chapter_key']==chapter
    assert json.loads(requests[0]['params']['expected_source'])==source
