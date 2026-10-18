"""Named wire schemas are discoverable offline and lossless for sparse saves."""
from app.main import app
from app.schemas.chapter import ChapterContent
from uuid import uuid4


def test_sparse_rich_document_contract_preserves_explicit_null_and_extensions():
    document = {'schema_version': 1, 'content_version': 'legacy-version',
        'blocks': [{'id': 'stable', 'html': '<p><em>One</em><img src="/asset"></p>',
            'role': 'author_note', 'role_provenance': 'source',
            'future_asset': {'hash': None}}, {'text': None}],
        'image_assets': {'ready': 1, 'future_mime': ['image/webp'], 'failures': None},
        'provenance': {'source': 'private', 'fingerprint': None}}
    body = {'id': 1, 'novel_id': 2, 'chapter_number': 3, 'title': 'Original',
        'content': 'One', 'source_url': None, 'document': document,
        'chapter_key': str(uuid4()), 'manifest_epoch': str(uuid4()), 'manifest_revision': '17',
        'source_version': document['content_version'], 'current_content_version': document['content_version']}
    assert ChapterContent.model_validate(body).model_dump(exclude_unset=True) == body


def test_named_chapter_openapi_contracts_require_no_io(monkeypatch):
    from config.database import engine
    import httpx
    def forbidden(*args, **kwargs):
        raise AssertionError('OpenAPI must not query a database or source')
    monkeypatch.setattr(engine, 'connect', forbidden)
    monkeypatch.setattr(httpx.Client, 'send', forbidden)
    previous = app.openapi_schema
    try:
        app.openapi_schema = None
        document = app.openapi()
    finally:
        app.openapi_schema = previous
    expected = {
        ('/chapter/progress/recent', 'get'): 'RecentReadingProgressResponse',
        ('/chapter/history/{novel_id}', 'get'): 'ReadingHistoryResponse',
        ('/chapter/recap/{novel_id}', 'get'): 'ChapterRecapResponse',
        ('/chapter/novel/{novel_id}/download-status', 'get'): 'NovelDownloadStatusResponse',
        ('/chapter/{chapter_id}/download', 'delete'): 'ChapterDownloadCancelledResponse',
        ('/chapter/novel/{novel_id}/cancel-all-downloads', 'post'): 'ChapterDownloadsCancelledResponse',
    }
    schemas = document['components']['schemas']
    for (path, method), name in expected.items():
        response = document['paths'][path][method]['responses']['200']['content']['application/json']['schema']
        if name == 'RecentReadingProgressResponse':
            response = response['items']
        assert response == {'$ref': f'#/components/schemas/{name}'}
        assert schemas[name]['properties'] and schemas[name]['required']
    for name in ['ChapterDocumentResponse', 'ChapterBlockResponse', 'ChapterImageAssetsResponse']:
        assert schemas[name]['additionalProperties'] is True
    rich_document = schemas['ChapterContent']['properties']['document']['anyOf']
    assert {'$ref': '#/components/schemas/ChapterDocumentResponse'} in rich_document
    assert 'content' not in document['paths']['/chapter/annotations/{annotation_id}']['delete']['responses']['204']
