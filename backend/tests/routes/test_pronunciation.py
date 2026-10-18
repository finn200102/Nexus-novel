import copy
import pytest
from pydantic import ValidationError
from app.models import Novel, Chapter, ChapterAudioJob, ChapterAudioPart, User, Library
from app.schemas.pronunciation import PronunciationRule
from app.services.pronunciation_service import apply, version
from app.services.audio_alignment import plan_passages
from app.services.chapter_document import from_html
from app.services.audio_job_service import queue_audio_job


def save(client, headers, rules, revision=0, operation="pronunciation-1", novel=None, inherit=True):
    return client.put("/audio/pronunciation" + (f"/stories/{novel}" if novel else ""), headers=headers,
        json={"rules": rules, "expected_revision": revision, "operation_id": operation, "inherit_account": inherit})


def test_private_scopes_cas_idempotency_and_explicit_inheritance(client, db, test_library, test_user, auth_headers):
    novel = Novel(title="Own pronunciation", library_id=test_library.id)
    stranger = User(username="other-pronunciation", password="unused")
    db.add_all([novel, stranger]); db.flush()
    library = Library(name="Other", user_id=stranger.id); db.add(library); db.flush()
    hidden = Novel(title="Other private story", library_id=library.id); db.add(hidden); db.commit()
    route = f"/audio/pronunciation/stories/{novel.id}"
    initial = client.get(route, headers=auth_headers).json()
    assert initial["effective_rules"] == [] and initial["effective_version"] is None and initial["inherit_account"]
    rules = [{"source":"Anna", "spoken":"AH nah"}, {"source":"Keeper", "spoken":"KEEP er"}]
    first = save(client, auth_headers, rules)
    assert first.status_code == 200 and first.json()["revision"] == 1
    assert save(client, auth_headers, rules).json() == first.json()
    stale = save(client, auth_headers, [], operation="stale")
    assert stale.status_code == 409 and stale.json()["detail"]["current"]["effective_rules"] == first.json()["rules"]
    story = save(client, auth_headers, [{"source":"Anna", "spoken":"AN na"}], operation="story", novel=novel.id).json()
    assert story["effective_rules"] == [{"source":"Anna","spoken":"AN na"},{"source":"Keeper","spoken":"KEEP er"}]
    assert story["account_rules"] == first.json()["rules"] and story["effective_version"] != first.json()["effective_version"]
    disabled = save(client, auth_headers, [], 1, "disable-inherit", novel.id, False).json()
    assert disabled["effective_rules"] == [] and disabled["effective_version"] is None
    reset = save(client, auth_headers, [], 2, "inherit-again", novel.id, True).json()
    assert reset["effective_rules"] == first.json()["rules"]
    assert client.get(f"/audio/pronunciation/stories/{hidden.id}", headers=auth_headers).status_code == 404
    assert save(client, auth_headers, rules, operation="other-story", novel=hidden.id).status_code == 404


def test_literal_substitution_does_not_cascade_or_rewrite_source_offsets():
    rules = [{"source":"Ann","spoken":"An"},{"source":"Anna","spoken":"AH nah"},{"source":".*","spoken":"dot star"},{"source":"AH","spoken":"changed"}]
    assert apply("Anna Ann anna .* AH", rules) == "AH nah An anna dot star changed"
    doc = from_html("<p>😀 Anna meets Ann. .* Ann</p><aside class='author-note'><p>Anna note</p></aside>")
    before = copy.deepcopy(doc)
    planned = plan_passages(doc, "Anna", 12, pronunciation_rules=rules)
    assert planned[0]["text"] == "AH nah" and planned[0]["block_id"] is None
    for part in planned[1:]:
        source = doc["blocks"][0]["text"].encode("utf-16-le")[part["text_offset"]*2:(part["text_offset"]+part["text_length"])*2].decode("utf-16-le")
        assert " ".join(apply(source, rules).split()) == part["text"]
        assert len(part["text"].encode("utf-16-le"))//2 <= 12
    assert doc == before and not any("note" in part["text"] for part in planned)
    assert version(rules) == version(list(reversed(rules)))


@pytest.mark.parametrize("source,spoken", [("", "say"), ("<speak>", "say"), ("A", "<phoneme>"), ("A\nB","say"), ("A", "x"*161), ("a\u202eb","say")])
def test_plain_rule_validation(source, spoken):
    with pytest.raises(ValidationError): PronunciationRule(source=source, spoken=spoken)


def test_jobs_snapshot_rules_and_retries_keep_original_parts(client, db, test_library, test_user, auth_headers):
    novel = Novel(title="Pronounced story", library_id=test_library.id); db.add(novel); db.flush()
    document = from_html("<p>😀 Anna meets Anna.</p>")
    chapter = Chapter(novel_id=novel.id, chapter_number=1, title="Anna arrives", content=document["plain_text"], document=document)
    db.add(chapter); db.commit()
    provider = {"id":"custom","base_url":"http://fixture/v1","model":"fixture","voice":"fixture"}
    save(client, auth_headers, [{"source":"Anna","spoken":"AH nah"}])
    job = queue_audio_job(db, user_id=test_user.id, library_id=test_library.id, novel_id=novel.id, chapter=chapter, provider=provider)
    version_before = job.pronunciation_version
    parts_before = db.query(ChapterAudioPart).filter_by(job_id=job.id).order_by(ChapterAudioPart.part_index).all()
    assert [part.text for part in parts_before] == ["AH nah arrives", "😀 AH nah meets AH nah."]
    assert chapter.document == document and chapter.content == document["plain_text"]
    assert job.pronunciation_rules == [{"source":"Anna","spoken":"AH nah"}]
    save(client, auth_headers, [{"source":"Anna","spoken":"AN na"}], 1, "new-voice-rules")
    assert queue_audio_job(db, user_id=test_user.id, library_id=test_library.id, novel_id=novel.id, chapter=chapter, provider=provider).id == job.id
    db.refresh(job); assert job.pronunciation_version == version_before
    assert [part.text for part in parts_before] == ["AH nah arrives", "😀 AH nah meets AH nah."]
    job.status = "completed"; db.commit()
    new_job = queue_audio_job(db, user_id=test_user.id, library_id=test_library.id, novel_id=novel.id, chapter=chapter, provider=provider)
    assert new_job.id != job.id and new_job.pronunciation_version != version_before
    assert db.get(ChapterAudioJob, job.id).pronunciation_version == version_before


def test_batch_identity_includes_pronunciation_and_preserves_ready_audio(client, db, test_library, auth_headers, tmp_path):
    from app.models.chapter import ContentStatus
    novel = Novel(title="Batch rules", library_id=test_library.id); db.add(novel); db.flush()
    document = from_html("<p>Anna arrives.</p>")
    chapter = Chapter(novel_id=novel.id, chapter_number=1, title="Arrival", content=document["plain_text"], document=document, content_status=ContentStatus.PRESENT)
    db.add(chapter); db.commit()
    provider = {"id":"custom","base_url":"http://fixture/v1","model":"fixture","voice":"fixture","execution_mode":"server"}
    route = f"/audio/stories/{novel.id}/jobs"
    save(client, auth_headers, [{"source":"Anna","spoken":"AH nah"}])
    first = client.post(route, headers=auth_headers, json={"chapter_numbers":[1],"provider":provider})
    assert first.status_code == 202
    job = db.get(ChapterAudioJob, first.json()["outcomes"][0]["job"]["id"])
    path = tmp_path / "retained.wav"; path.write_bytes(b"retained fixture recording")
    job.audio_path = str(path); job.status = "completed"; db.commit()
    same = client.post(route, headers=auth_headers, json={"chapter_numbers":[1],"provider":provider})
    assert same.json()["outcomes"][0]["outcome"] == "already_ready"
    version_before = job.pronunciation_version
    save(client, auth_headers, [{"source":"Anna","spoken":"AN na"}], 1, "batch-changed-rules")
    changed = client.post(route, headers=auth_headers, json={"chapter_numbers":[1],"provider":provider})
    assert changed.json()["outcomes"][0]["outcome"] == "queued"
    new_id = changed.json()["outcomes"][0]["job"]["id"]
    assert new_id != job.id and db.get(ChapterAudioJob, new_id).pronunciation_version != version_before
    assert path.read_bytes() == b"retained fixture recording" and job.pronunciation_version == version_before
    assert chapter.document == document


def test_additive_pronunciation_upgrade_preserves_populated_legacy_audio(tmp_path):
    from alembic import command
    from sqlalchemy import create_engine, text
    from app.db_migrations import alembic_config
    engine = create_engine(f"sqlite:///{tmp_path / 'pronunciation-upgrade.db'}")
    try:
        with engine.begin() as connection:
            config = alembic_config(connection); command.upgrade(config, "0039")
            connection.execute(text("INSERT INTO users (id,username,password,storage_id) VALUES (1,'reader','unused','00000000-0000-4000-8000-000000000001')"))
            connection.execute(text("INSERT INTO libraries (id,user_id,name) VALUES (1,1,'Books')"))
            connection.execute(text("INSERT INTO novels (id,library_id,title) VALUES (1,1,'Story')"))
            connection.execute(text("INSERT INTO chapters (id,novel_id,chapter_number,title,content_status,audio_status,retry_count) VALUES (1,1,1,'Chapter','PRESENT','PRESENT',0)"))
            connection.execute(text("INSERT INTO chapter_audio_jobs (id,user_id,library_id,novel_id,chapter_id,status,provider_id,provider_url,provider_model,provider_voice,audio_path,total_parts,source_version) VALUES (1,1,1,1,1,'completed','custom','http://local/v1','fixture','reader','/private/narration.wav',1,'original')"))
            command.upgrade(config, "0040")
            assert connection.execute(text("SELECT source_version,audio_path,pronunciation_version,pronunciation_rules FROM chapter_audio_jobs WHERE id=1")).one() == ("original", "/private/narration.wav", None, None)
            command.downgrade(config, "0039")
            assert connection.execute(text("SELECT source_version,audio_path FROM chapter_audio_jobs WHERE id=1")).one() == ("original", "/private/narration.wav")
    finally: engine.dispose()


def test_planner_total_spoken_and_part_limits_preserve_source():
    from app.services.pronunciation_service import AudioPlanningLimitError, MAX_AUDIO_SPOKEN_UTF16, MAX_AUDIO_PARTS
    rules = [{"source": "x", "spoken": "y" * 160}]
    document = from_html("<p>" + "x" * 12500 + "</p>")
    before = copy.deepcopy(document)
    parts = plan_passages(document, "", 20000, pronunciation_rules=rules)
    assert sum(len(part["text"]) for part in parts) == MAX_AUDIO_SPOKEN_UTF16
    assert document == before
    with pytest.raises(AudioPlanningLimitError, match="Shorten or disable"):
        plan_passages(document, "x", 20000, pronunciation_rules=rules)
    assert document == before
    many = {"blocks": [{"id": str(index), "text": "a"} for index in range(MAX_AUDIO_PARTS)]}
    assert len(plan_passages(many, "", 100)) == MAX_AUDIO_PARTS
    with pytest.raises(AudioPlanningLimitError): plan_passages(many, "title", 100)
    assert len(plan_passages({"blocks": [{"id": "legacy", "text": "a" * 1620}]}, "", 10)) == 162


def test_budget_errors_are_typed_before_jobs_or_provider_calls(client, db, test_library, auth_headers, monkeypatch):
    from app.services import pronunciation_service, audio_job_service
    from app.models.chapter import ContentStatus
    monkeypatch.setattr(pronunciation_service, "MAX_AUDIO_SPOKEN_UTF16", 200)
    monkeypatch.setattr(audio_job_service.httpx, "Client", lambda **kw: pytest.fail("No provider calls during planning"))
    novel = Novel(title="Budget story", library_id=test_library.id); db.add(novel); db.flush()
    for number, text in [(1, "xxx"), (2, "ok")]:
        document = from_html(f"<p>{text}</p>")
        db.add(Chapter(novel_id=novel.id, chapter_number=number, title="Chapter", content=document["plain_text"], document=document, content_status=ContentStatus.PRESENT))
    db.commit()
    save(client, auth_headers, [{"source": "x", "spoken": "y" * 80}])
    provider = {"id": "custom", "base_url": "http://fixture/v1", "model": "fixture", "voice": "fixture"}
    single = client.post("/audio/jobs", headers=auth_headers, json={"library_id": test_library.id, "novel_id": novel.id, "chapter_number": 1, "provider": provider})
    assert single.status_code == 422 and single.json()["detail"]["code"] == "audio_planning_limit"
    assert db.query(ChapterAudioJob).count() == 0 and db.query(ChapterAudioPart).count() == 0
    batch = client.post(f"/audio/stories/{novel.id}/jobs", headers=auth_headers, json={"chapter_numbers": [1, 2], "provider": provider})
    assert batch.status_code == 202
    first, second = batch.json()["outcomes"]
    assert first["outcome"] == "unavailable" and first["error_code"] == "audio_planning_limit" and "Shorten" in first["message"]
    assert second["outcome"] == "queued" and db.query(ChapterAudioJob).count() == 1
