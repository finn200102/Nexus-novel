import logging
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import httpx
import pytest
from app.services import metadata_client


def test_http_diagnostics_keep_route_status_and_known_code_without_body_or_credentials(monkeypatch,caplog):
    secret='PRIVATE_DIAGNOSTIC_CREDENTIAL'
    request=httpx.Request('POST',f'https://user:{secret}@metadata.invalid/catalog-scrapes/preview?token={secret}')
    response=httpx.Response(409,json={'detail':{'code':'run_active','message':secret,'source_url':f'https://source.invalid/?password={secret}'}},request=request)
    upstream=SimpleNamespace(request=AsyncMock(return_value=response))
    monkeypatch.setattr(metadata_client,'_get_client',AsyncMock(return_value=upstream))
    monkeypatch.setattr(metadata_client,'_get_headers',lambda **kwargs:{'X-Nexus-Admin-Key':secret})
    caplog.set_level(logging.WARNING,logger='metadata_client')
    with pytest.raises(RuntimeError,match='Metadata server returned HTTP 409') as raised:
        asyncio.run(metadata_client._request('POST',f'https://user:{secret}@metadata.invalid/catalog-scrapes/preview?api_key={secret}#fragment-{secret}',timeout=httpx.Timeout(1),admin=True,json={'secret':secret}))
    assert isinstance(raised.value.__cause__,httpx.HTTPStatusError)
    assert secret not in str(raised.value)
    assert secret not in caplog.text and 'metadata.invalid' not in caplog.text and 'source.invalid' not in caplog.text
    records=[row for row in caplog.records if row.name=='metadata_client']
    assert len(records)==1 and records[0].message=='metadata_request.http_error'
    assert records[0].extra=={'method':'POST','path':'/catalog-scrapes/preview','status_code':409,'error_code':'run_active'}
    assert secret not in repr(records[0].__dict__)


@pytest.mark.parametrize('failure,event,message',[(httpx.ReadTimeout,'metadata_request.timeout','request timeout'),(httpx.ConnectError,'metadata_request.failed','request failed')])
def test_transport_diagnostics_classify_without_logging_exception_urls(monkeypatch,caplog,failure,event,message):
    marker='PRIVATE_TRANSPORT_MARKER'
    request=httpx.Request('GET',f'https://metadata.invalid/secret?token={marker}')
    error=failure(f'{marker} https://user:password@private.invalid/?api_key={marker}',request=request)
    monkeypatch.setattr(metadata_client,'_get_client',AsyncMock(return_value=SimpleNamespace(request=AsyncMock(side_effect=error))))
    caplog.set_level(logging.WARNING,logger='metadata_client')
    with pytest.raises(RuntimeError,match=message) as raised:
        asyncio.run(metadata_client._request('GET',f'/catalog-scrapes?key={marker}',timeout=httpx.Timeout(1)))
    assert raised.value.__cause__ is error
    records=[row for row in caplog.records if row.name=='metadata_client']
    assert len(records)==1 and records[0].message==event
    assert records[0].extra=={'method':'GET','path':'/catalog-scrapes'}
    assert marker not in caplog.text and 'private.invalid' not in caplog.text
    assert marker not in repr(records[0].__dict__) and marker not in str(raised.value)


def test_unrecognized_provider_error_code_is_not_echoed_into_diagnostics(monkeypatch,caplog):
    request=httpx.Request('GET','https://metadata.invalid/catalog-scrapes')
    response=httpx.Response(422,json={'detail':{'code':'PRIVATE_CODE_MARKER','message':'PRIVATE_BODY_MARKER'}},request=request)
    monkeypatch.setattr(metadata_client,'_get_client',AsyncMock(return_value=SimpleNamespace(request=AsyncMock(return_value=response))))
    caplog.set_level(logging.WARNING,logger='metadata_client')
    with pytest.raises(RuntimeError):
        asyncio.run(metadata_client._request('GET','/catalog-scrapes',timeout=httpx.Timeout(1)))
    assert 'PRIVATE_' not in caplog.text
    record=next(row for row in caplog.records if row.name=='metadata_client')
    assert record.extra=={'method':'GET','path':'/catalog-scrapes','status_code':422}
