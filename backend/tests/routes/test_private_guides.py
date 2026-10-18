"""Private guide lifecycle never sends unread material or silently repeats a step."""
import json
from datetime import timedelta
import pytest
from app.models import Novel, Chapter
from app.models.translation import ReaderProvider
from app.models.reader_guide import PrivateGuideJob, PrivateGuideArtifact
from app.services.chapter_document import from_text
from app.services.reading_progress_service import save_reading_progress
from app.services.reading_run_service import action
from app.schemas.reading_runs import ReadingRunAction
from app.services import reader_guide_service as guide
from app.services.job_lease import utcnow


@pytest.fixture
def material(db, test_user, test_library, monkeypatch):
    monkeypatch.setenv('NEXUS_LOCAL_AI_BASE_URL', 'http://private-guide.invalid/v1')
    novel = Novel(title='Private fixture', library_id=test_library.id)
    db.add(novel)
    db.flush()
    chapters = []
    for number, text in [(-2, 'Alice, wearing a blue coat, enters the harbour.'), (0, 'Alice meets the captain.'), (7, 'FUTURE_SECRET Alice is the queen.')]:
        document = from_text(text)
        chapter = Chapter(novel_id=novel.id, chapter_number=number, title=str(number), content=text, document=document)
        db.add(chapter)
        chapters.append(chapter)
    provider = ReaderProvider(user_id=test_user.id, name='Local guide', kind='local', model='fixture',
        base_url='http://private-guide.invalid/v1', capabilities=['guide_text'])
    db.add(provider)
    db.commit()
    progress = None
    for chapter in chapters[:2]:
        progress = save_reading_progress(db, user_id=test_user.id, chapter=chapter, position=0, percent=100,
            content_version=chapter.document['content_version'])
    return novel, chapters, provider, progress


def prepare(client, auth_headers, material, boundary=None, operation='queue-guide'):
    novel, _, provider, _ = material
    base = f'/reader/stories/{novel.id}/guide'
    value = {'provider_id': provider.id, 'through_chapter': boundary}
    preview = client.post(base+'/preview', json=value, headers=auth_headers)
    assert preview.status_code == 200, preview.text
    value.update(review_token=preview.json()['review_token'], operation_id=operation)
    response = client.post(base+'/jobs', json=value, headers=auth_headers)
    assert response.status_code == 200, response.text
    return base, value, response.json()


def fake_invoke(calls):
    def invoke(db, provider, **kwargs):
        kwargs['authorize']()
        payload = json.loads(kwargs['prompt'])
        calls.append(payload)
        if payload['evidence']:
            first = payload['evidence'][0]
            citations = [{key: first[key] for key in ('chapter', 'block_id')} | {'quote': first['text']}]
        else:
            citations = payload['observations'][0]['citations']
        assert 'FUTURE_SECRET' not in kwargs['prompt']
        return json.dumps({'recap': {'text': 'Alice arrives.', 'certainty': 'observed', 'citations': citations}, 'characters': [], 'relationships': [], 'locations': [], 'glossary': [], 'citations': citations}), 10, 5, 0
    return invoke


def factory(db):
    from sqlalchemy.orm import sessionmaker
    return sessionmaker(bind=db.get_bind(), expire_on_commit=False)


def test_review_queue_is_idempotent_and_gets_never_infer(client, db, test_user, auth_headers, material, monkeypatch):
    calls = []
    monkeypatch.setattr(guide.reader_provider, 'invoke', fake_invoke(calls))
    base, value, job = prepare(client, auth_headers, material, -2)
    replay = client.post(base+'/jobs', json=value, headers=auth_headers)
    assert replay.json() == job
    assert db.query(PrivateGuideJob).count() == 1 and calls == []
    state = client.get(base, headers=auth_headers)
    assert state.status_code == 200 and state.headers['cache-control'] == 'private, no-store'
    assert state.json()['artifacts'] == [] and calls == []
    assert guide.process_one(factory(db))
    assert guide.process_one(factory(db))
    state = client.get(base, headers=auth_headers).json()
    assert state['jobs'][0]['status'] == 'completed' and len(state['artifacts']) == 1
    assert calls[0]['through_chapter'] == -2
    assert all(row['chapter'] == -2 for row in calls[0]['evidence'])
    assert len(calls) == 2


def test_ordinary_position_tick_preserves_preview_but_reread_invalidates(client, db, test_user, auth_headers, material):
    novel, chapters, provider, progress = material
    base = f'/reader/stories/{novel.id}/guide'
    value = {'provider_id': provider.id}
    reviewed = client.post(base+'/preview', json=value, headers=auth_headers).json()
    progress = save_reading_progress(db, user_id=test_user.id, chapter=chapters[1], position=22, percent=100,
        content_version=chapters[1].document['content_version'], expected_revision=progress.revision)
    queued = client.post(base+'/jobs', json={**value, 'review_token': reviewed['review_token'], 'operation_id': 'tick'}, headers=auth_headers)
    assert queued.status_code == 200, queued.text
    action(db, test_user.id, novel.id, ReadingRunAction(expected_revision=progress.revision,
        operation_id='start-again', reading_run_key=progress.reading_run_key), 'start')
    stale = client.post(base+'/jobs', json={**value, 'review_token': reviewed['review_token'], 'operation_id': 'reread'}, headers=auth_headers)
    assert stale.status_code == 409
    empty = client.post(base+'/preview', json=value, headers=auth_headers)
    assert empty.status_code == 422


def test_crash_resume_retains_completed_step_and_expired_dispatch_requires_review(client, db, test_user, auth_headers, material, monkeypatch):
    calls = []
    monkeypatch.setattr(guide.reader_provider, 'invoke', fake_invoke(calls))
    base, _, job = prepare(client, auth_headers, material)
    assert guide.process_one(factory(db))
    db.expire_all()
    row = db.get(PrivateGuideJob, job['id'])
    assert row.completed_steps == 1 and db.query(PrivateGuideArtifact).count() == 1
    row.status, row.lease_owner, row.lease_expires_at = 'processing', 'lost-worker', utcnow()-timedelta(seconds=1)
    db.commit()
    assert guide.process_one(factory(db))
    db.refresh(row)
    assert row.status == 'needs_review' and row.completed_steps == 1 and len(calls) == 1
    monkeypatch.setattr('app.services.reader_provider_usage.require_job_retry_review', lambda *args: None)
    retry = client.post(base+f"/jobs/{row.id}/retry", json={'expected_revision': row.revision, 'operation_id': 'retry-reviewed'}, headers=auth_headers)
    assert retry.status_code == 200, retry.text
    assert guide.process_one(factory(db))
    db.refresh(row)
    assert row.status == 'completed' and len(calls) == 2 and calls[1]['operation'] == 'synthesize'


def test_post_inference_reread_discards_private_artifact(client, db, test_user, auth_headers, material, monkeypatch):
    novel, _, _, progress = material
    base, _, job = prepare(client, auth_headers, material)
    def concurrent(db2, provider, **kwargs):
        result = fake_invoke([])(db2, provider, **kwargs)
        # Reservation normally commits before I/O; release the test callback's read lock too.
        db2.commit()
        action(db, test_user.id, novel.id, ReadingRunAction(expected_revision=progress.revision,
            operation_id='new-run-during-inference', reading_run_key=progress.reading_run_key), 'start')
        return result
    monkeypatch.setattr(guide.reader_provider, 'invoke', concurrent)
    assert guide.process_one(factory(db))
    assert db.query(PrivateGuideArtifact).count() == 0
    response = client.get(base+f"/jobs/{job['id']}", headers=auth_headers)
    assert response.json()['status'] == 'needs_review'


def test_foreign_story_and_job_are_hidden(client, db, test_user, auth_headers, material):
    from app.models import User, Library
    other = User(username='foreign-private', password='x')
    db.add(other)
    db.flush()
    library = Library(name='foreign', user_id=other.id)
    db.add(library)
    db.flush()
    foreign = Novel(title='Hidden', library_id=library.id)
    db.add(foreign)
    db.commit()
    response = client.get(f'/reader/stories/{foreign.id}/guide', headers=auth_headers)
    assert response.status_code == 404


def complete(db, monkeypatch):
    calls = []
    monkeypatch.setattr(guide.reader_provider, 'invoke', fake_invoke(calls))
    while guide.process_one(factory(db)):
        pass
    return calls


def test_saved_output_survives_disabled_provider_price_and_permission_changes(client, db, test_user, auth_headers, material, monkeypatch):
    novel, _, provider, _ = material
    base, _, job = prepare(client, auth_headers, material)
    complete(db, monkeypatch)
    db.refresh(provider)
    provider.enabled = False
    provider.input_price = 17
    db.commit()
    from app.models.story_processing_permission import StoryProcessingPermission
    db.add(StoryProcessingPermission(user_id=test_user.id, novel_id=novel.id, provider_id=provider.id, companion=False))
    db.commit()
    output = client.get(base, headers=auth_headers)
    assert output.status_code == 200 and len(output.json()['artifacts']) == 1
    artifact_id = output.json()['artifacts'][0]['id']
    assert client.get(base+f'/artifacts/{artifact_id}', headers=auth_headers).status_code == 200
    # Reusing already-computed material requires no new provider authorization.
    reused = client.post(base+'/preview', headers=auth_headers, json={'provider_id': provider.id})
    assert reused.status_code == 200 and reused.json()['reuse_job_id'] == job['id']
    assert reused.json()['estimated_max_microusd'] == 0


def test_control_replay_after_new_run_has_no_artifacts(client, db, test_user, auth_headers, material, monkeypatch):
    novel, _, _, progress = material
    base, _, job = prepare(client, auth_headers, material)
    complete(db, monkeypatch)
    current = client.get(base+f"/jobs/{job['id']}", headers=auth_headers).json()
    payload = {'expected_revision': current['revision'], 'operation_id': 'cancel-after-complete'}
    first = client.post(base+f"/jobs/{job['id']}/cancel", headers=auth_headers, json=payload)
    assert first.status_code == 200 and first.json()['artifacts'] == []
    action(db, test_user.id, novel.id, ReadingRunAction(expected_revision=progress.revision,
        operation_id='restart-after-guide', reading_run_key=progress.reading_run_key), 'start')
    replay = client.post(base+f"/jobs/{job['id']}/cancel", headers=auth_headers, json=payload)
    assert replay.json() == first.json() and replay.json()['artifacts'] == []
    assert client.get(base, headers=auth_headers).json()['artifacts'] == []


def test_newly_read_future_does_not_expand_or_invalidate_queued_snapshot(client, db, test_user, auth_headers, material, monkeypatch):
    _, chapters, _, progress = material
    base, _, job = prepare(client, auth_headers, material)
    save_reading_progress(db, user_id=test_user.id, chapter=chapters[2], position=0, percent=100,
        content_version=chapters[2].document['content_version'], expected_revision=progress.revision)
    calls = complete(db, monkeypatch)
    assert len(calls) == 2 and calls[0]['through_chapter'] == 0
    assert all(row['chapter'] <= 0 for row in calls[0]['evidence'])
    assert client.get(base+f"/jobs/{job['id']}", headers=auth_headers).json()['status'] == 'completed'


def test_state_verifies_source_once_even_with_many_artifacts(client, db, test_user, auth_headers, material, monkeypatch):
    base, _, _ = prepare(client, auth_headers, material)
    complete(db, monkeypatch)
    _, _, second = prepare(client, auth_headers, material, -2, operation='second-guide')
    complete(db, monkeypatch)
    original = guide.verified_chapters
    calls = []
    def observe(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(guide, 'verified_chapters', observe)
    response = client.get(base, headers=auth_headers)
    assert len(response.json()['artifacts']) == 2 and len(calls) == 1


def test_revised_source_fences_queued_dispatch_and_saved_artifact(client, db, test_user, auth_headers, material, monkeypatch):
    _, chapters, _, _ = material
    base, _, job = prepare(client, auth_headers, material)
    calls = complete(db, monkeypatch)
    chapters[0].content = 'Revised Alice arrives.'
    chapters[0].document = from_text(chapters[0].content)
    db.commit()
    assert client.get(base, headers=auth_headers).json()['artifacts'] == []
    assert len(calls) == 2


def test_actual_generic_ledger_resume_and_invalid_model_citation_stops(client, db, test_user, auth_headers, material, monkeypatch):
    from app.models.translation import ReaderProviderRequest
    base, _, job = prepare(client, auth_headers, material)
    calls = []
    def transport(provider, **kwargs):
        prompt = json.loads(kwargs['prompt'])
        calls.append(prompt)
        evidence = prompt['evidence'][0]
        citation = {'chapter': evidence['chapter'], 'block_id': evidence['block_id'], 'quote': evidence['text']}
        text = {'characters': [], 'relationships': [], 'locations': [], 'glossary': [], 'recap': None, 'citations': [citation]}
        return {'choices': [{'message': {'content': json.dumps(text)}, 'finish_reason': 'stop'}],
                'usage': {'prompt_tokens': 10, 'completion_tokens': 5}}
    monkeypatch.setattr('app.services.companion_client.guide_request', transport)
    assert guide.process_one(factory(db))
    assert guide.process_one(factory(db))
    assert db.query(ReaderProviderRequest).count() == 2
    assert client.get(base+f"/jobs/{job['id']}", headers=auth_headers).json()['status'] == 'completed'
    assert len(calls) == 2


def test_typed_claims_require_per_fact_exact_citations():
    evidence = [[{'chapter': -2, 'block_id': 'a', 'text': 'Alice enters.'}]]
    cite = {'chapter': -2, 'block_id': 'a', 'quote': 'Alice enters.'}
    for character in [
        {'name': 'Alice', 'description': 'A traveller', 'certainty': 'observed', 'citations': []},
        {'name': 'Alice', 'description': 'A traveller', 'certainty': 'invented', 'citations': [cite]},
        {'name': 'Alice', 'description': 'A traveller', 'certainty': 'observed', 'citations': [{**cite, 'quote': 'FUTURE'}]},
    ]:
        with pytest.raises(ValueError):
            guide.validate_result(json.dumps({'characters': [character], 'relationships': [], 'locations': [],
                'glossary': [], 'recap': None, 'citations': [cite]}), evidence)


def test_private_portrait_real_ledger_inline_png_range_storage_and_revocation(client, db, test_user, auth_headers, material, monkeypatch):
    import base64
    import struct
    import zlib
    from app.models.story_processing_permission import StoryProcessingPermission
    from app.services.reader_provider_usage import snapshot
    novel, _, provider, _ = material
    provider.capabilities = ['guide_text', 'guide_portrait']
    provider.image_model = 'private-image-fixture'
    provider.image_sizes = ['1024x1024']
    provider.image_qualities = ['medium']
    db.commit()
    permission = StoryProcessingPermission(user_id=test_user.id, novel_id=novel.id, provider_id=provider.id,
        portrait=True, portrait_provider_snapshot=snapshot(provider))
    db.add(permission)
    db.commit()
    base = f'/reader/stories/{novel.id}/guide'
    value = {'provider_id': provider.id, 'kind': 'portrait', 'portrait_subject': 'Alice'}
    preview = client.post(base+'/preview', json=value, headers=auth_headers)
    assert preview.status_code == 200, preview.text
    job = client.post(base+'/jobs', json={**value, 'review_token': preview.json()['review_token'], 'operation_id': 'portrait'}, headers=auth_headers)
    assert job.status_code == 200, job.text
    def text_transport(provider, **kwargs):
        payload = json.loads(kwargs['prompt'])
        first = payload['evidence'][0]
        citation = {'chapter': first['chapter'], 'block_id': first['block_id'], 'quote': first['text']}
        content = dict(characters=[dict(name='Alice', description='A traveller at the harbour.', certainty='observed', citations=[citation], appearance={'text':'Alice wears a blue coat.', 'certainty':'observed', 'citations':[citation]})],
            relationships=[], locations=[], glossary=[], recap=None, citations=[citation])
        return {'choices': [{'message': {'content': json.dumps(content)}, 'finish_reason': 'stop'}], 'usage': {'prompt_tokens': 10, 'completion_tokens': 5}}
    def chunk(kind, data):
        return struct.pack('>I', len(data))+kind+data+struct.pack('>I', zlib.crc32(kind+data)&0xffffffff)
    png = b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR', struct.pack('>IIBBBBB',1024,1024,8,0,0,0,0))+chunk(b'IDAT',zlib.compress((b'\0'+b'\xff'*1024)*1024))+chunk(b'IEND',b'')
    images = []
    def image_transport(provider, **kwargs):
        payload = json.loads(kwargs['prompt'])
        assert payload['portrait_subject'] == 'Alice'
        assert 'FUTURE_SECRET' not in kwargs['prompt']
        images.append(payload)
        return {'data': [{'b64_json': base64.b64encode(png).decode()}]}
    monkeypatch.setattr('app.services.companion_client.guide_request', text_transport)
    monkeypatch.setattr('app.services.companion_client.image_request', image_transport)
    for _ in range(3):
        assert guide.process_one(factory(db))
    state = client.get(base, headers=auth_headers).json()
    assert state['jobs'][0]['status'] == 'completed' and len(images) == 1
    artifact = next(item for item in state['artifacts'] if item['kind'] == 'portrait')
    media = client.get(artifact['media_url'], headers=auth_headers)
    assert media.status_code == 200 and media.content == png
    part = client.get(artifact['media_url'], headers={**auth_headers, 'Range': 'bytes=0-7'})
    assert part.status_code == 206 and part.content == png[:8] and part.headers['cache-control'] == 'private, no-store'
    assert state['portrait_bytes'] == len(png)
    permission.portrait = False
    provider.enabled = False
    db.commit()
    assert client.get(artifact['media_url'], headers=auth_headers).content == png
    assert client.get(artifact['media_url']).status_code == 401


def test_explicit_cancel_stale_revision_and_duplicate_creation_guard(client, db, test_user, auth_headers, material):
    base, value, job = prepare(client, auth_headers, material)
    same = client.post(base+'/jobs', headers=auth_headers, json={**value, 'operation_id': 'second-click'})
    assert same.json()['id'] == job['id'] and db.query(PrivateGuideJob).count() == 1
    canceled = client.post(base+f"/jobs/{job['id']}/cancel", headers=auth_headers,
        json={'expected_revision': job['revision'], 'operation_id': 'cancel-click'})
    assert canceled.status_code == 200 and canceled.json()['status'] == 'canceled'
    stale = client.post(base+f"/jobs/{job['id']}/retry", headers=auth_headers,
        json={'expected_revision': job['revision'], 'operation_id': 'stale-retry'})
    assert stale.status_code == 409
    duplicate = client.post(base+'/jobs', headers=auth_headers, json={**value, 'operation_id': 'bypass-retry'})
    assert duplicate.status_code == 200 and duplicate.json()['id'] == job['id'] and duplicate.json()['status'] == 'canceled'
    assert db.query(PrivateGuideJob).count() == 1


@pytest.mark.parametrize('failure', ['invalid_facts', 'artifact_commit'])
def test_known_paid_charge_survives_failed_artifact_and_explicit_retry(client, db, test_user, auth_headers, material, monkeypatch, failure):
    from decimal import Decimal
    from sqlalchemy import event
    from app.models.story_processing_permission import StoryProcessingPermission
    from app.models.translation import ReaderProviderRequest
    from app.services.notification_crypto import encrypt_url
    novel, _, provider, _ = material
    provider.kind, provider.base_url = 'openai_compatible', 'https://provider.invalid/v1'
    provider.secret_ciphertext = encrypt_url('SYNTHETIC_GUIDE_KEY')
    provider.input_price, provider.output_price = Decimal('1'), Decimal('2')
    provider.budget_microusd = 100_000_000
    db.add(StoryProcessingPermission(user_id=test_user.id, novel_id=novel.id, provider_id=provider.id, companion=True))
    db.commit()
    base, _, job = prepare(client, auth_headers, material)
    def transport(provider, **kwargs):
        payload = json.loads(kwargs['prompt'])
        first = payload['evidence'][0]
        citation = {'chapter': first['chapter'], 'block_id': first['block_id'], 'quote': first['text']}
        content = dict(characters=[], relationships=[], locations=[], glossary=[], recap=None, citations=[citation])
        return {'choices': [{'message': {'content': json.dumps(content) if failure == 'artifact_commit' else '{"invented":true}'}, 'finish_reason': 'stop'}],
                'usage': {'prompt_tokens': 10, 'completion_tokens': 5}}
    monkeypatch.setattr('app.services.companion_client.guide_request', transport)
    def reject_artifact(*args):
        raise RuntimeError('Synthetic database artifact commit failure')
    if failure == 'artifact_commit':
        event.listen(PrivateGuideArtifact, 'before_insert', reject_artifact)
    try:
        assert guide.process_one(factory(db))
    finally:
        if failure == 'artifact_commit':
            event.remove(PrivateGuideArtifact, 'before_insert', reject_artifact)
    response = client.get(base+f"/jobs/{job['id']}", headers=auth_headers).json()
    assert response['status'] == 'needs_review' and response['charged_microusd'] == 20
    assert response['reserved_microusd'] == 0 and db.query(PrivateGuideArtifact).count() == 0
    assert db.query(ReaderProviderRequest).one().actual_microusd == 20
    assert not guide.process_one(factory(db))
    retry = client.post(base+f"/jobs/{job['id']}/retry", headers=auth_headers,
        json={'expected_revision': response['revision'], 'operation_id': 'reviewed-paid-retry'})
    assert retry.status_code == 200 and retry.json()['charged_microusd'] == 20


def test_story_removal_purges_only_owned_guide_rows_and_keeps_financial_receipt(client, db, test_user, auth_headers, material, monkeypatch):
    from app.models.reader_guide import PrivateGuideOperation
    from app.models.translation import ReaderProviderRequest
    from app.services.story_audio_cleanup import stage_story_audio_removal
    novel, _, _, _ = material
    base, _, job = prepare(client, auth_headers, material)
    def transport(provider, **kwargs):
        value = json.loads(kwargs['prompt'])
        row = value['evidence'][0]
        citation = {'chapter': row['chapter'], 'block_id': row['block_id'], 'quote': row['text']}
        return {'choices':[{'message':{'content':json.dumps(dict(characters=[],relationships=[],locations=[],glossary=[],recap=None,citations=[citation]))},'finish_reason':'stop'}], 'usage':{'prompt_tokens':10,'completion_tokens':5}}
    monkeypatch.setattr('app.services.companion_client.guide_request', transport)
    assert guide.process_one(factory(db))
    assert db.query(ReaderProviderRequest).count() == 1
    stage_story_audio_removal(db, novel)
    db.delete(novel)
    db.commit()
    assert db.query(PrivateGuideJob).count() == db.query(PrivateGuideArtifact).count() == 0
    assert db.query(PrivateGuideOperation).count() == 1
    assert db.query(ReaderProviderRequest).count() == 1


def test_account_purge_removes_private_artifacts_and_operation_rows(client, db, test_user, auth_headers, material, monkeypatch):
    from app.models.reader_guide import PrivateGuideOperation
    from app.services.account_service import delete_user_account
    prepare(client, auth_headers, material)
    complete(db, monkeypatch)
    assert db.query(PrivateGuideArtifact).count() == 2
    delete_user_account(db, test_user)
    assert db.query(PrivateGuideJob).count() == db.query(PrivateGuideArtifact).count() == db.query(PrivateGuideOperation).count() == 0


def test_preview_bound_provider_changes_and_invalid_capability_never_queue(client, db, test_user, auth_headers, material):
    _, _, provider, _ = material
    base = f'/reader/stories/{material[0].id}/guide'
    value = {'provider_id':provider.id}
    reviewed = client.post(base+'/preview', json=value, headers=auth_headers).json()
    assert reviewed['provider_snapshot']['model'] == provider.model
    provider.model = 'new-model'
    db.commit()
    stale = client.post(base+'/jobs', headers=auth_headers, json={**value,'review_token':reviewed['review_token'],'operation_id':'changed-provider'})
    assert stale.status_code == 409 and db.query(PrivateGuideJob).count() == 0
    provider.capabilities = []
    db.commit()
    assert client.post(base+'/preview', json=value, headers=auth_headers).status_code == 422


def test_huge_unselected_newly_approved_chapter_does_not_hide_saved_guide(client, db, test_user, auth_headers, material, monkeypatch):
    _, chapters, _, progress = material
    base, _, job = prepare(client, auth_headers, material, -2)
    complete(db, monkeypatch)
    chapters[2].content = 'Large future material. ' * 100_000
    chapters[2].document = from_text(chapters[2].content)
    db.commit()
    save_reading_progress(db, user_id=test_user.id, chapter=chapters[2], position=0, percent=100,
        content_version=chapters[2].document['content_version'], expected_revision=progress.revision)
    result = client.get(base, headers=auth_headers)
    assert result.status_code == 200, result.text
    assert len(result.json()['artifacts']) == 1
    assert result.json()['through_chapter'] == 7
    artifact = result.json()['artifacts'][0]
    assert client.get(base+f"/artifacts/{artifact['id']}", headers=auth_headers).status_code == 200


def test_portrait_without_observed_appearance_never_calls_image_provider(client, db, test_user, auth_headers, material, monkeypatch):
    from app.models.story_processing_permission import StoryProcessingPermission
    from app.services.reader_provider_usage import snapshot
    novel, _, provider, _ = material
    provider.capabilities = ['guide_text','guide_portrait']
    provider.image_model, provider.image_sizes, provider.image_qualities = 'fixture', ['1024x1024'], ['medium']
    db.commit()
    db.add(StoryProcessingPermission(user_id=test_user.id, novel_id=novel.id, provider_id=provider.id,
        portrait=True, portrait_provider_snapshot=snapshot(provider)))
    db.commit()
    base = f'/reader/stories/{novel.id}/guide'
    value = {'provider_id':provider.id, 'kind':'portrait', 'portrait_subject':'Alice'}
    review = client.post(base+'/preview', headers=auth_headers, json=value)
    assert review.status_code == 200
    job = client.post(base+'/jobs', headers=auth_headers, json={**value,'review_token':review.json()['review_token'],'operation_id':'no-appearance'})
    calls = []
    def text_invoke(db, provider, **kwargs):
        text, incoming, outgoing, charged = fake_invoke(calls)(db, provider, **kwargs)
        result = json.loads(text)
        result['characters'] = [{'name':'Alice','description':'A traveller','certainty':'observed','citations':result['citations'],'appearance':None}]
        return json.dumps(result), incoming, outgoing, charged
    monkeypatch.setattr(guide.reader_provider, 'invoke', text_invoke)
    def forbidden(*args, **kwargs):
        raise AssertionError('Insufficient appearance must never call the image provider')
    monkeypatch.setattr(guide.reader_provider, 'invoke_image', forbidden)
    for _ in range(3):
        assert guide.process_one(factory(db))
    response = client.get(base+f"/jobs/{job.json()['id']}", headers=auth_headers).json()
    assert response['status'] == 'needs_review' and response['completed_steps'] == 2
    assert len(calls) == 2 and all(item['kind'] != 'portrait' for item in response['artifacts'])


def test_openapi_references_typed_private_facts_and_public_provider_snapshot():
    from app.main import app
    schema = app.openapi()
    definitions = schema['components']['schemas']
    assert definitions['GuideArtifact']['properties']['content']['anyOf'] == [
        {'$ref':'#/components/schemas/GuideResultResponse'}, {'$ref':'#/components/schemas/GuidePortraitContent'}]
    assert definitions['GuideArtifact']['properties']['citations']['items']['$ref'].endswith('/GuideCitationResponse')
    assert {'chapter_key', 'source_version'} <= set(definitions['GuideCitationResponse']['required'])
    assert definitions['GuidePreview']['properties']['provider_snapshot']['$ref'].endswith('/GuideProviderSnapshot')
    assert not {'secret_ciphertext','credential_fingerprint','secret_hash'}.intersection(definitions['GuideProviderSnapshot']['properties'])


def test_semantic_cache_reuses_completed_work_after_price_secret_budget_and_grant_changes(client, db, test_user, auth_headers, material, monkeypatch):
    from decimal import Decimal
    from app.models.story_processing_permission import StoryProcessingPermission
    from app.services.notification_crypto import encrypt_url
    novel, _, provider, _ = material
    base, _, job = prepare(client, auth_headers, material)
    calls = complete(db, monkeypatch)
    assert len(calls) == 2
    provider.name = 'Renamed private provider'
    provider.input_price, provider.output_price = Decimal('10'), Decimal('20')
    provider.budget_microusd = 1
    provider.secret_ciphertext = encrypt_url('ROTATED_SYNTHETIC_SECRET')
    provider.enabled = False
    db.add(StoryProcessingPermission(user_id=test_user.id, novel_id=novel.id, provider_id=provider.id, companion=False))
    db.commit()
    preview = client.post(base+'/preview', headers=auth_headers, json={'provider_id':provider.id})
    assert preview.status_code == 200, preview.text
    assert preview.json()['reuse_job_id'] == job['id'] and preview.json()['reuse_status'] == 'completed'
    assert preview.json()['estimated_max_microusd'] == 0
    response = client.post(base+'/jobs', headers=auth_headers, json={'provider_id':provider.id,
        'review_token':preview.json()['review_token'], 'operation_id':'new-op-same-semantic-content'})
    assert response.status_code == 200 and response.json()['id'] == job['id']
    assert db.query(PrivateGuideJob).count() == 1 and len(calls) == 2
    assert client.get(base+f"/jobs/{job['id']}", headers=auth_headers).json()['artifacts']


def test_unknown_paid_job_cannot_be_bypassed_by_new_preview_and_operation(client, db, test_user, auth_headers, material, monkeypatch):
    from decimal import Decimal
    from app.models.story_processing_permission import StoryProcessingPermission
    from app.models.translation import ReaderProviderRequest
    from app.services.notification_crypto import encrypt_url
    novel, _, provider, _ = material
    provider.kind, provider.base_url = 'openai_compatible', 'https://provider.invalid/v1'
    provider.secret_ciphertext = encrypt_url('SYNTHETIC_KEY')
    provider.input_price, provider.output_price, provider.budget_microusd = Decimal('1'), Decimal('2'), 100_000_000
    db.add(StoryProcessingPermission(user_id=test_user.id, novel_id=novel.id, provider_id=provider.id, companion=True))
    db.commit()
    base, _, job = prepare(client, auth_headers, material)
    calls = []
    def unknown(*args, **kwargs):
        calls.append(1)
        raise TimeoutError('Synthetic response lost')
    monkeypatch.setattr('app.services.companion_client.guide_request',unknown)
    assert guide.process_one(factory(db))
    assert db.query(ReaderProviderRequest).one().status == 'unknown'
    preview = client.post(base+'/preview', headers=auth_headers, json={'provider_id':provider.id})
    assert preview.status_code == 200 and preview.json()['reuse_status'] == 'needs_review'
    assert preview.json()['estimated_max_microusd'] == 0
    created = client.post(base+'/jobs',headers=auth_headers,json={'provider_id':provider.id,
        'review_token':preview.json()['review_token'],'operation_id':'different-create-operation'})
    assert created.status_code == 200 and created.json()['id'] == job['id']
    assert db.query(PrivateGuideJob).count() == 1 and not guide.process_one(factory(db)) and len(calls) == 1
    retry = client.post(base+f"/jobs/{job['id']}/retry",headers=auth_headers,
        json={'expected_revision':created.json()['revision'],'operation_id':'review-unresolved'})
    assert retry.status_code == 409


def test_reused_preview_never_silently_creates_work_if_cached_job_disappears(client, db, test_user, auth_headers, material, monkeypatch):
    base, _, job = prepare(client, auth_headers, material)
    complete(db, monkeypatch)
    preview = client.post(base+'/preview',headers=auth_headers,json={'provider_id':material[2].id}).json()
    assert preview['reuse_job_id'] == job['id']
    db.query(PrivateGuideArtifact).delete(synchronize_session=False)
    db.query(PrivateGuideJob).delete(synchronize_session=False)
    db.commit()
    response = client.post(base+'/jobs',headers=auth_headers,json={'provider_id':material[2].id,
        'review_token':preview['review_token'],'operation_id':'missing-reviewed-cache'})
    assert response.status_code == 409 and db.query(PrivateGuideJob).count() == 0


def test_completed_cache_created_after_preview_is_reused_even_after_price_changes(client, db, test_user, auth_headers, material, monkeypatch):
    base = f'/reader/stories/{material[0].id}/guide'
    early = client.post(base+'/preview',headers=auth_headers,json={'provider_id':material[2].id}).json()
    assert early['reuse_job_id'] is None
    _, _, job = prepare(client, auth_headers, material)
    complete(db, monkeypatch)
    material[2].input_price = 20
    db.commit()
    response = client.post(base+'/jobs',headers=auth_headers,json={'provider_id':material[2].id,
        'review_token':early['review_token'],'operation_id':'earlier-review-now-cached'})
    assert response.status_code == 200 and response.json()['id'] == job['id']
    assert db.query(PrivateGuideJob).count() == 1


def test_same_html_version_with_changed_block_identity_invalidates_review(client, db, test_user, auth_headers, material, monkeypatch):
    base, _, job = prepare(client, auth_headers, material)
    chapter = material[1][0]
    document = json.loads(json.dumps(chapter.document))
    old_version = document['content_version']
    document['blocks'][0]['id'] = 'new-anchor-same-rendered-source'
    chapter.document = document
    db.commit()
    assert chapter.document['content_version'] == old_version
    def forbidden(*args, **kwargs):
        raise AssertionError('Changed reviewed block identities cannot enter a model call')
    monkeypatch.setattr(guide.reader_provider,'invoke',forbidden)
    assert guide.process_one(factory(db))
    assert client.get(base+f"/jobs/{job['id']}",headers=auth_headers).json()['status'] == 'needs_review'
    assert db.query(PrivateGuideArtifact).count() == 0


def test_reviewed_retry_adopts_new_key_prices_and_grant_without_repeating_completed_step(client, db, test_user, auth_headers, material, monkeypatch):
    from decimal import Decimal
    from app.models.story_processing_permission import StoryProcessingPermission
    from app.services.notification_crypto import encrypt_url
    novel, _, provider, _ = material
    provider.kind, provider.base_url = 'openai_compatible', 'https://provider.invalid/v1'
    provider.secret_ciphertext = encrypt_url('OLD_SYNTHETIC_KEY')
    provider.input_price, provider.output_price, provider.budget_microusd = Decimal('1'), Decimal('2'), 100_000_000
    permission = StoryProcessingPermission(user_id=test_user.id, novel_id=novel.id, provider_id=provider.id, companion=True)
    db.add(permission)
    db.commit()
    base, _, job = prepare(client, auth_headers, material)
    calls = []
    def transport(selected, **kwargs):
        payload = json.loads(kwargs['prompt'])
        calls.append((payload['operation'], kwargs['api_key']))
        first = payload['evidence'][0]
        citation = {'chapter':first['chapter'],'block_id':first['block_id'],'quote':first['text']}
        result = dict(characters=[],relationships=[],locations=[],glossary=[],recap=None,citations=[citation])
        return {'choices':[{'message':{'content':json.dumps(result)},'finish_reason':'stop'}], 'usage':{'prompt_tokens':10,'completion_tokens':5}}
    monkeypatch.setattr('app.services.companion_client.guide_request',transport)
    assert guide.process_one(factory(db))
    current = client.get(base+f"/jobs/{job['id']}",headers=auth_headers).json()
    canceled = client.post(base+f"/jobs/{job['id']}/cancel",headers=auth_headers,
        json={'expected_revision':current['revision'],'operation_id':'stop-after-first'}).json()
    provider.input_price, provider.output_price = Decimal('10'), Decimal('20')
    provider.secret_ciphertext = encrypt_url('ROTATED_SYNTHETIC_KEY')
    permission.companion = False
    db.commit()
    blocked = client.post(base+'/preview',headers=auth_headers,json=canceled['retry_input']).json()
    assert blocked['reuse_job_id'] == job['id'] and blocked['retry_estimated_max_microusd'] is None
    assert blocked['retry_blocked_reason']
    permission.companion = True
    db.commit()
    review = client.post(base+'/preview',headers=auth_headers,json=canceled['retry_input']).json()
    assert review['estimated_max_microusd'] == 0 and review['retry_estimated_max_microusd'] > 0
    permission.companion = False
    db.commit()
    revoked = client.post(base+f"/jobs/{job['id']}/retry",headers=auth_headers,json={
        'expected_revision':canceled['revision'],'operation_id':'revoked-current-review','review_token':review['review_token']})
    assert revoked.status_code == 409 and len(calls) == 1
    permission.companion = True
    db.commit()
    review = client.post(base+'/preview',headers=auth_headers,json=canceled['retry_input']).json()
    retry_value = {'expected_revision':canceled['revision'],'operation_id':'fresh-priced-retry','review_token':review['review_token']}
    retry = client.post(base+f"/jobs/{job['id']}/retry",headers=auth_headers,json=retry_value)
    assert retry.status_code == 200 and retry.json()['completed_steps'] == 1
    assert guide.process_one(factory(db))
    done = client.get(base+f"/jobs/{job['id']}",headers=auth_headers).json()
    assert done['status'] == 'completed' and done['charged_microusd'] == 220
    assert calls == [('extract','OLD_SYNTHETIC_KEY'),('synthesize','ROTATED_SYNTHETIC_KEY')]
    assert db.query(PrivateGuideJob).count() == 1


def test_revoked_retry_review_has_no_dispatch_and_stale_retry_ack_cannot_uncancel(client, db, test_user, auth_headers, material):
    base, _, job = prepare(client, auth_headers, material)
    canceled = client.post(base+f"/jobs/{job['id']}/cancel",headers=auth_headers,
        json={'expected_revision':job['revision'],'operation_id':'stop-before-work'}).json()
    review = client.post(base+'/preview',headers=auth_headers,json=canceled['retry_input']).json()
    # A different provider model invalidates the exact retry review.
    material[2].model = 'changed-after-review'
    db.commit()
    value = {'expected_revision':canceled['revision'],'operation_id':'stale-reviewed-retry','review_token':review['review_token']}
    stale = client.post(base+f"/jobs/{job['id']}/retry",headers=auth_headers,json=value)
    assert stale.status_code == 409
    material[2].model = 'fixture'
    db.commit()
    fresh = client.post(base+'/preview',headers=auth_headers,json=canceled['retry_input']).json()
    value = {'expected_revision':canceled['revision'],'operation_id':'valid-reviewed-retry','review_token':fresh['review_token']}
    retried = client.post(base+f"/jobs/{job['id']}/retry",headers=auth_headers,json=value)
    assert retried.status_code == 200
    later = client.post(base+f"/jobs/{job['id']}/cancel",headers=auth_headers,
        json={'expected_revision':retried.json()['revision'],'operation_id':'cancel-after-retry'})
    assert later.json()['status'] == 'canceled'
    replay = client.post(base+f"/jobs/{job['id']}/retry",headers=auth_headers,json=value)
    assert replay.json() == retried.json()
    assert client.get(base+f"/jobs/{job['id']}",headers=auth_headers).json()['status'] == 'canceled'


def test_permission_revoked_during_paid_reply_keeps_charge_but_publishes_no_material(client, db, test_user, auth_headers, material, monkeypatch):
    from decimal import Decimal
    from app.models.story_processing_permission import StoryProcessingPermission
    from app.services.notification_crypto import encrypt_url
    novel, _, provider, _ = material
    provider.kind, provider.base_url = 'openai_compatible', 'https://provider.invalid/v1'
    provider.secret_ciphertext = encrypt_url('SYNTHETIC_KEY')
    provider.input_price, provider.output_price, provider.budget_microusd = Decimal('1'), Decimal('2'), 100_000_000
    permission = StoryProcessingPermission(user_id=test_user.id, novel_id=novel.id, provider_id=provider.id, companion=True)
    db.add(permission)
    db.commit()
    base, _, job = prepare(client,auth_headers,material)
    def transport(selected, **kwargs):
        payload = json.loads(kwargs['prompt'])
        first = payload['evidence'][0]
        citation = {'chapter':first['chapter'],'block_id':first['block_id'],'quote':first['text']}
        permission.companion = False
        db.commit()
        return {'choices':[{'message':{'content':json.dumps(dict(characters=[],relationships=[],locations=[],glossary=[],recap=None,citations=[citation]))},'finish_reason':'stop'}], 'usage':{'prompt_tokens':10,'completion_tokens':5}}
    monkeypatch.setattr('app.services.companion_client.guide_request',transport)
    assert guide.process_one(factory(db))
    response = client.get(base+f"/jobs/{job['id']}",headers=auth_headers).json()
    assert response['status'] == 'needs_review' and response['charged_microusd'] == 20
    assert response['artifacts'] == [] and db.query(PrivateGuideArtifact).count() == 0
