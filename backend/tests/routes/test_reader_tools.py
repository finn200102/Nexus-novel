from sqlalchemy.orm import sessionmaker
from app.models.chapter import Chapter, ContentStatus
from app.models.novel import Novel
from app.models.translation import ReaderProvider, StoryGlossary, TranslationJob
from app.services.chapter_document import from_text
from app.services.translation_service import process_translation


def story(db, test_library):
    novel = Novel(title="Private", library_id=test_library.id)
    db.add(novel)
    db.flush()
    first = Chapter(novel_id=novel.id, chapter_number=1, content="Alice arrives at the castle.\nBob welcomes Alice.",
                    content_status=ContentStatus.PRESENT)
    second = Chapter(novel_id=novel.id, chapter_number=2, content="Alice is secretly the queen.", content_status=ContentStatus.PRESENT)
    db.add_all([first, second])
    db.commit()
    return novel, first, second


def provider(client, auth_headers, monkeypatch):
    monkeypatch.setenv("NEXUS_LOCAL_AI_BASE_URL", "http://local-reader:8020/v1")
    response = client.post("/reader/providers", json={"name": "Local", "kind": "local",
        "base_url": "http://local-reader:8020/v1", "model": "local-model"}, headers=auth_headers)
    assert response.status_code == 201
    return response.json()["id"]


def test_translation_and_export_keep_source_note_roles(client, db, test_library, auth_headers, monkeypatch):
    from app.services.chapter_document import from_html
    novel, chapter, _ = story(db, test_library)
    document = from_html('<aside class="author-note"><p>Author commentary.</p></aside><p>The story.</p>')
    chapter.document, chapter.content = document, document["plain_text"]
    db.commit()
    provider_id = provider(client, auth_headers, monkeypatch)
    queued = client.post(f"/reader/translations/{novel.id}/1", headers=auth_headers, json={"provider_id": provider_id, "language": "de"})
    monkeypatch.setattr("app.services.translation_service.invoke", lambda *_args, **_kwargs: ("Übersetzter Text", 10, 20, 0))
    process_translation(queued.json()["id"], sessionmaker(bind=db.get_bind()))
    db.expire_all()
    job = db.get(TranslationJob, queued.json()["id"])
    assert job.translated_blocks[0]["role"] == "author_note"
    assert job.translated_blocks[0]["role_provenance"] == "source"
    assert "role" not in job.translated_blocks[1]
    from io import BytesIO
    from zipfile import ZipFile
    exported = client.get(f"/reader/translation-jobs/{job.id}/epub", headers=auth_headers)
    assert exported.status_code == 200
    with ZipFile(BytesIO(exported.content)) as archive:
        assert b'data-nexus-role="author_note"' in archive.read("OEBPS/chapter-1.xhtml")


def test_translation_and_epub_retain_inline_and_image_only_blocks_without_model_images(client, db, test_library, auth_headers, monkeypatch):
    from app.services.chapter_document import from_html
    from app.services.translation_service import job_view
    from io import BytesIO
    from zipfile import ZipFile
    novel, chapter, _ = story(db, test_library)
    src = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGNQ6pgJAAITAUTGjr3DAAAAAElFTkSuQmCC"
    document = from_html(f'<p>A pictured scene.<img src="{src}" alt="Map"></p><p><img src="{src}" alt="Portrait"></p>')
    document["image_assets"] = {"total": 3, "ready": 2, "missing": 1, "limited": 0, "bytes": 138, "failures": {"source_failed": 1}}
    chapter.document, chapter.content = document, document["plain_text"]; db.commit()
    provider_id = provider(client, auth_headers, monkeypatch)
    queued = client.post(f"/reader/translations/{novel.id}/1", headers=auth_headers, json={"provider_id": provider_id, "language": "de"})
    calls = []
    def translate(*args, **kwargs):
        calls.append(kwargs["prompt"]); return "Eine bebilderte Szene.", 10, 20, 0
    monkeypatch.setattr("app.services.translation_service.invoke", translate)
    process_translation(queued.json()["id"], sessionmaker(bind=db.get_bind())); db.expire_all()
    job = db.get(TranslationJob, queued.json()["id"])
    assert job.status == "completed" and len(calls) == 1
    assert "base64" not in calls[0] and "data:image" not in calls[0]
    assert all(src in block["html"] for block in job.translated_blocks)
    assert [block["id"] for block in job.translated_blocks] == [block["id"] for block in document["blocks"]]
    assert job_view(job)["document"]["image_assets"]["missing"] == 1
    exported = client.get(f"/reader/translation-jobs/{job.id}/epub", headers=auth_headers)
    assert exported.status_code == 200
    with ZipFile(BytesIO(exported.content)) as archive:
        assert archive.read("OEBPS/chapter-1.xhtml").count(b"<img") == 2
        assert any(name.endswith(".png") for name in archive.namelist())


def test_translation_resumes_and_glossary_does_not_include_future_entries(client, db, test_user, test_library, auth_headers, monkeypatch):
    novel, first, _ = story(db, test_library)
    provider_id = provider(client, auth_headers, monkeypatch)
    db.add(StoryGlossary(user_id=test_user.id, novel_id=novel.id, source="Alice", target="Future Queen", language="de", through_chapter=2))
    db.commit()
    url = f"/reader/translations/{novel.id}/1"
    payload = {"provider_id": provider_id, "language": "de"}
    queued = client.post(url, json=payload, headers=auth_headers)
    assert queued.status_code == 202
    job_id = queued.json()["id"]
    assert client.post(url, json=payload, headers=auth_headers).json()["id"] == job_id
    job = db.get(TranslationJob, job_id)
    assert job.glossary == {}
    # The injected fixture session survives HTTP requests; release the dedupe
    # request's identity lock before an independent worker transaction starts.
    db.rollback()
    calls = []
    def translate(_db, _provider, *, prompt, system, **context):
        if context.get('authorize'):
            context['authorize']()
        calls.append(prompt)
        if len(calls) == 2:
            raise ValueError("Temporary failure")
        return "Ankunft <script> is literal text", 10, 20, 0
    monkeypatch.setattr("app.services.translation_service.invoke", translate)
    factory = sessionmaker(bind=db.get_bind())
    process_translation(job_id, factory)
    db.expire_all()
    assert db.get(TranslationJob, job_id).status == "failed"
    assert len(db.get(TranslationJob, job_id).translated_blocks) == 1
    client.post(f"/reader/translation-jobs/{job_id}", json={"action": "retry"}, headers=auth_headers)
    monkeypatch.setattr("app.services.translation_service.invoke", lambda *_args, **_kwargs: ("Willkommen", 10, 20, 0))
    process_translation(job_id, factory)
    db.expire_all()
    result = client.get(url, headers=auth_headers).json()[0]
    assert result["status"] == "completed" and result["completed_blocks"] == 2
    assert "&lt;script&gt;" in result["document"]["blocks"][0]["html"]
    assert db.get(Chapter, first.id).content.startswith("Alice arrives")
    from io import BytesIO
    from zipfile import ZipFile
    exported = client.get(f"/reader/translation-jobs/{job_id}/epub", headers=auth_headers)
    assert exported.status_code == 200
    assert exported.headers["cache-control"] == "private, no-store"
    with ZipFile(BytesIO(exported.content)) as archive:
        assert "<dc:language>de</dc:language>" in archive.read("OEBPS/content.opf").decode()
        assert result["document"]["blocks"][0]["id"] in archive.read("OEBPS/chapter-1.xhtml").decode()


def test_remote_keys_are_private_and_paid_jobs_require_consent_and_budget(client, db, test_user, test_library, auth_headers):
    novel, _, _ = story(db, test_library)
    secret = "private-provider-key"
    configured = client.post("/reader/providers", json={"name": "Premium", "kind": "anthropic",
        "base_url": "https://api.anthropic.com/v1", "model": "claude-opus-5-5", "api_key": secret,
        "input_price": 4, "output_price": 20}, headers=auth_headers)
    assert configured.status_code == 201
    assert secret not in configured.text
    stored = db.get(ReaderProvider, configured.json()["id"])
    assert stored.secret_ciphertext != secret
    payload = {"provider_id": stored.id, "language": "de"}
    assert client.post(f"/reader/translations/{novel.id}/1", json=payload, headers=auth_headers).status_code == 422
    payload["external_consent"] = True
    assert client.post(f"/reader/translations/{novel.id}/1", json=payload, headers=auth_headers).status_code == 422


def test_identical_models_with_distinct_provider_accounts_keep_distinct_variants(client, db, test_library, auth_headers, monkeypatch):
    novel, _, _ = story(db, test_library)
    first_provider = provider(client, auth_headers, monkeypatch)
    second_provider = provider(client, auth_headers, monkeypatch)
    url = f"/reader/translations/{novel.id}/1"
    first = client.post(url, json={"provider_id": first_provider, "language": "de"}, headers=auth_headers)
    second = client.post(url, json={"provider_id": second_provider, "language": "de"}, headers=auth_headers)
    assert first.status_code == second.status_code == 202
    assert first.json()["id"] != second.json()["id"]
    assert db.get(TranslationJob, second.json()["id"]).provider_id == second_provider


def test_author_commentary_is_not_sent_as_story_evidence(client, db, test_user, test_library, auth_headers, monkeypatch):
    from unittest.mock import Mock
    from app.services.chapter_document import from_html
    from app.services.reading_progress_service import save_reading_progress
    novel, chapter, _ = story(db, test_library)
    document = from_html('<p>Seen story.</p><aside class="author-note"><p>Alice FUTURE_FROM_NOTE: a later plot identity.</p></aside>')
    chapter.document, chapter.content = document, document["plain_text"]
    db.commit()
    save_reading_progress(db, user_id=test_user.id, chapter=chapter, position=0, percent=100, content_version=document["content_version"])
    provider_id = provider(client, auth_headers, monkeypatch)
    model = Mock(side_effect=AssertionError("Commentary must be filtered before model input"))
    monkeypatch.setattr("app.services.reader_provider.invoke", model)
    response = client.post(f"/reader/companion/{novel.id}/questions", headers=auth_headers, json={"provider_id": provider_id, "question": "Who is Alice?"})
    assert response.status_code == 200 and response.json()["citations"] == []
    assert "not enough evidence" in response.json()["answer"]
    model.assert_not_called()


def test_questions_filter_future_chapters_before_model_input(client, db, test_user, test_library, auth_headers, monkeypatch):
    import json
    from config.settings import settings
    monkeypatch.setattr(settings, "ANALYSIS_ENGINE_URL", "http://analysis:8010")
    monkeypatch.setattr(settings, "ANALYSIS_ENGINE_API_KEY", "internal-test-key")
    novel, first, _ = story(db, test_library)
    provider_id = provider(client, auth_headers, monkeypatch)
    from app.services.reading_progress_service import save_reading_progress
    document = from_text(first.content)
    saved=save_reading_progress(db,user_id=test_user.id,chapter=first,position=0,percent=100,content_version=document['content_version'])
    second=db.query(Chapter).filter_by(novel_id=novel.id,chapter_number=2).one()
    save_reading_progress(db,user_id=test_user.id,chapter=second,position=0,percent=1,expected_revision=saved.revision,reading_run_key=saved.reading_run_key)
    seen = []
    def answer(_db, _provider, *, prompt, **kwargs):
        seen.append(prompt)
        return json.dumps({"answer": "Alice arrives at the castle.", "citations": [{"chapter": 1,
            "block_id": document["blocks"][0]["id"], "quote": "Alice arrives at the castle."}]}), 10, 10, 0
    monkeypatch.setattr("app.services.reader_provider.invoke", answer)
    response = client.post(f"/reader/companion/{novel.id}/questions", json={"provider_id": provider_id, "question": "Who is Alice?"}, headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["through_chapter"] == 1
    assert response.json()["citations"][0]["chapter"] == 1
    assert "secretly the queen" not in seen[0]
    repeated = client.post(f"/reader/companion/{novel.id}/questions", json={"provider_id": provider_id, "question": "Who is Alice?"}, headers=auth_headers)
    assert repeated.status_code == 200 and repeated.json()["cached"] is True
    assert len(seen) == 1 and repeated.json()["charged_usd"] == 0
    first.content = "Alice enters a different castle."
    db.commit()
    changed = client.post(f"/reader/companion/{novel.id}/questions", json={"provider_id": provider_id, "question": "Who is Alice?"}, headers=auth_headers)
    assert changed.status_code == 200 and len(seen) == 1
    assert changed.json()["citations"] == []
    # Confirming the new edition is explicit; an old completion cannot do it.
    save_reading_progress(db,user_id=test_user.id,chapter=first,position=0,percent=100,
        content_version=from_text(first.content)["content_version"],intent='confirm_read')
    confirmed = client.post(f"/reader/companion/{novel.id}/questions", json={"provider_id": provider_id, "question": "Who is Alice?"}, headers=auth_headers)
    assert confirmed.status_code == 200 and len(seen) == 2
    earlier = client.post(f"/reader/companion/{novel.id}/questions", json={"provider_id": provider_id, "question": "Who is Alice?", "through_chapter": 0}, headers=auth_headers)
    assert earlier.status_code == 200 and earlier.json()["through_chapter"] is None
    assert earlier.json()["citations"] == [] and len(seen) == 2


def test_provider_controls_preserve_originals_cancel_work_and_keep_rotated_keys_private(client, db, test_library, auth_headers, monkeypatch):
    from app.models.translation import ReaderProvider, TranslationJob
    from app.services.notification_crypto import decrypt_url
    novel, first, _ = story(db, test_library)
    provider_id = provider(client, auth_headers, monkeypatch)
    request = {"provider_id": provider_id, "language": "de"}
    queued = client.post(f"/reader/translations/{novel.id}/1", json=request, headers=auth_headers)
    assert queued.status_code == 202
    original = first.content
    blocked = client.put(f"/reader/providers/{provider_id}", json={"model": "changed-model"}, headers=auth_headers)
    assert blocked.status_code == 409
    disabled = client.put(f"/reader/providers/{provider_id}", json={"enabled": False}, headers=auth_headers)
    assert disabled.status_code == 200 and disabled.json()["enabled"] is False
    db.expire_all()
    assert db.get(TranslationJob, queued.json()["id"]).status == "cancelled"
    rotated = client.put(f"/reader/providers/{provider_id}", json={"api_key": "private-fixture-key"}, headers=auth_headers)
    assert rotated.status_code == 200 and "private-fixture-key" not in rotated.text
    db.expire_all()
    assert decrypt_url(db.get(ReaderProvider, provider_id).secret_ciphertext) == "private-fixture-key"
    enabled = client.put(f"/reader/providers/{provider_id}", json={"enabled": True, "supported_languages": ["en"]}, headers=auth_headers)
    assert enabled.status_code == 200
    assert client.post(f"/reader/translations/{novel.id}/1", json=request, headers=auth_headers).status_code == 422
    assert db.get(type(first), first.id).content == original


def test_ao3_requires_specific_consent_and_story_revocation_stops_retries(client, db, test_library, auth_headers, monkeypatch):
    novel, first, _ = story(db, test_library)
    novel.novel_site = "archive"
    novel.source_url = "https://archiveofourown.org/works/123"
    db.commit()
    created = client.post("/reader/providers", json={"name": "Remote fixture", "kind": "openai_compatible",
        "base_url": "https://api.example.org/v1", "model": "fixture", "api_key": "fake-test-key",
        "input_price": 1, "output_price": 1, "budget_usd": 10}, headers=auth_headers)
    assert created.status_code == 201
    provider_id = created.json()["id"]
    request = {"provider_id": provider_id, "language": "de", "external_consent": True}
    rejected = client.post(f"/reader/translations/{novel.id}/1/preview", json=request, headers=auth_headers)
    assert rejected.status_code == 422 and "AO3" in rejected.text
    permission_url = f"/reader/permissions/{novel.id}/{provider_id}"
    assert client.put(permission_url, json={"translation": True}, headers=auth_headers).status_code == 422
    assert client.put(permission_url, json={"translation": True, "companion": True, "ao3_consent": True}, headers=auth_headers).status_code == 200
    queued = client.post(f"/reader/translations/{novel.id}/1", json={"provider_id": provider_id, "language": "de"}, headers=auth_headers)
    assert queued.status_code == 202
    revoked = client.put(permission_url, json={"translation": False, "companion": False}, headers=auth_headers)
    assert revoked.status_code == 200
    assert client.post(f"/reader/translation-jobs/{queued.json()['id']}", json={"action": "retry"}, headers=auth_headers).status_code == 422
    assert client.post(f"/reader/translations/{novel.id}/1/preview", json={**request, "ao3_consent": True}, headers=auth_headers).status_code == 422


def test_skipped_chapters_do_not_enter_companion_input_even_below_furthest_read(client, db, test_user, test_library, auth_headers, monkeypatch):
    import json
    from config.settings import settings
    from app.services.reading_progress_service import save_reading_progress
    novel, first, _ = story(db, test_library)
    third = Chapter(novel_id=novel.id, chapter_number=3, content="Bob leaves the castle.", content_status=ContentStatus.PRESENT)
    db.add(third); db.commit()
    for chapter in (first, third):
        save_reading_progress(db, user_id=test_user.id, chapter=chapter, position=0, percent=100,
                             content_version=from_text(chapter.content)["content_version"])
    provider_id = provider(client, auth_headers, monkeypatch)
    monkeypatch.setattr(settings, "ANALYSIS_ENGINE_URL", "http://analysis:8010")
    monkeypatch.setattr(settings, "ANALYSIS_ENGINE_API_KEY", "internal-test-key")
    seen = []
    def answer(_db, _provider, *, prompt, **kwargs):
        seen.append(json.loads(prompt))
        return json.dumps({"answer": "Insufficient", "citations": []}), 10, 10, 0
    monkeypatch.setattr("app.services.reader_provider.invoke", answer)
    response = client.post(f"/reader/companion/{novel.id}/questions", json={"provider_id": provider_id, "question": "Who is Alice?"}, headers=auth_headers)
    assert response.status_code == 200 and response.json()["through_chapter"] == 3
    assert all(row["chapter"] == 1 for row in seen[0]["evidence"])
    assert "secretly the queen" not in json.dumps(seen)
