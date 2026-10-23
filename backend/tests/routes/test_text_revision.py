import copy
import json
import pytest
from app.models import Chapter, Novel
from app.models.chapter import ContentStatus
from app.models.translation import ReaderProvider, TranslationJob
from app.services.chapter_document import from_html


@pytest.fixture
def editing(db, test_library, test_user, monkeypatch):
    monkeypatch.setenv("NEXUS_LOCAL_AI_BASE_URL", "http://local-reader:8020/v1")
    novel = Novel(title="Editing", library_id=test_library.id)
    db.add(novel); db.flush()
    document = from_html("<p>Alice go home.</p><p>She is tired.</p>")
    chapter = Chapter(novel_id=novel.id, chapter_number=1, title="Chapter", content=document["plain_text"], document=document, content_status=ContentStatus.PRESENT)
    provider = ReaderProvider(user_id=test_user.id, name="Local", kind="local", base_url="http://local-reader:8020/v1", model="local-model")
    db.add_all([chapter, provider]); db.commit()
    return novel, chapter, provider


def post(client, headers, editing, **changes):
    return client.post(f"/reader/text-revisions/{editing[0].id}/1/preview", headers=headers,
        json={"provider_id": editing[2].id, "mode": "proofreading", **changes})


def answer(monkeypatch, calls, text="Alice goes home.\n\nShe is tired.", mutate=None):
    def request(provider, **kwargs):
        calls.append(kwargs)
        if mutate:
            mutate()
        return {"choices": [{"message": {"content": text}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 10}}
    monkeypatch.setattr("app.services.reader_provider.direct_request", request)


@pytest.mark.parametrize("mode", ["proofreading", "rewrite"])
def test_no_source_write(client, db, auth_headers, editing, monkeypatch, mode):
    original = copy.deepcopy(editing[1].document)
    calls = []; answer(monkeypatch, calls)
    result = post(client, auth_headers, editing, mode=mode)
    assert result.status_code == 200, result.text
    assert result.json()["saved"] is False
    assert result.headers["cache-control"] == "private, no-store"
    assert json.loads(calls[0]["prompt"])["text"] == "Alice go home.\n\nShe is tired."
    db.expire_all()
    assert db.get(Chapter, editing[1].id).document == original
    assert db.query(TranslationJob).count() == 0


def test_reformat_checks_words(client, auth_headers, editing, monkeypatch):
    calls = []; answer(monkeypatch, calls)
    assert post(client, auth_headers, editing, mode="reformat").status_code == 422
    answer(monkeypatch, calls, text="Alice go home.\nShe is tired.")
    assert post(client, auth_headers, editing, mode="reformat").status_code == 200


@pytest.mark.parametrize("kind", ["local_translation", "openai_compatible"])
def test_only_local_llm(client, db, auth_headers, editing, monkeypatch, kind):
    editing[2].kind = kind; db.commit()
    calls = []; answer(monkeypatch, calls)
    assert post(client, auth_headers, editing).status_code == 422
    assert not calls


def test_stale_before_and_after_io(client, db, auth_headers, editing, monkeypatch):
    calls = []; answer(monkeypatch, calls)
    assert post(client, auth_headers, editing, expected_content_version="0" * 64).status_code == 409
    assert not calls
    def change():
        chapter = db.get(Chapter, editing[1].id)
        document = from_html("<p>A changed chapter.</p>")
        chapter.document = document; chapter.content = document["plain_text"]; db.commit()
    answer(monkeypatch, calls, mutate=change)
    response = post(client, auth_headers, editing)
    assert response.status_code == 409, response.text


def test_provider_revocation(client, db, auth_headers, editing, monkeypatch):
    def change():
        editing[2].enabled = False; db.commit()
    calls = []; answer(monkeypatch, calls, mutate=change)
    assert post(client, auth_headers, editing).status_code == 422


def test_translation_polish(client, db, test_user, auth_headers, editing, monkeypatch):
    novel, chapter, provider = editing
    calls = []; answer(monkeypatch, calls)
    assert post(client, auth_headers, editing).status_code == 200
    from app.services.chapter_identity_service import identity
    proof = identity(chapter)
    document = copy.deepcopy(chapter.document)
    job = TranslationJob(user_id=test_user.id, novel_id=novel.id, chapter_id=chapter.id, provider_id=provider.id,
        language="de", fingerprint="polish-fixture", source_version=document["content_version"],
        chapter_key=proof["chapter_key"], manifest_epoch=proof["manifest_epoch"], manifest_revision=proof["manifest_revision"],
        identity_inferred=False, provider_snapshot={}, source_blocks=document["blocks"], glossary={},
        translated_blocks=[{"id":"de-1", "text":"Alice geht heim."}], status="completed")
    db.add(job); db.commit()
    answer(monkeypatch, calls, text="Alice geht nach Hause.")
    result = post(client, auth_headers, editing, mode="translation_polish", translation_job_id=job.id)
    assert result.status_code == 200, result.text
    assert result.json()["draft"] == "Alice geht heim."
    db.expire_all()
    assert db.get(TranslationJob, job.id).translated_blocks == [{"id":"de-1", "text":"Alice geht heim."}]
    job.source_version = "0" * 64; db.commit()
    before = len(calls)
    assert post(client, auth_headers, editing, mode="translation_polish", translation_job_id=job.id).status_code == 409
    assert len(calls) == before


def test_other_accounts_story_and_provider_are_hidden(client, db, auth_headers, editing, test_user, monkeypatch):
    from app.models import User
    stranger = User(username="revision-stranger", password="fixture")
    db.add(stranger); db.commit()
    calls = []; answer(monkeypatch, calls)
    editing[2].user_id = stranger.id; db.commit()
    assert post(client, auth_headers, editing).status_code == 404
    assert not calls
    editing[2].user_id = test_user.id
    editing[0].library.user_id = stranger.id
    db.commit()
    assert post(client, auth_headers, editing).status_code == 404
    assert not calls


def test_oversized_chapter_and_invalid_mode_before_io(client, db, auth_headers, editing, monkeypatch):
    calls = []; answer(monkeypatch, calls)
    assert post(client, auth_headers, editing, mode="anything").status_code == 422
    document = from_html("<p>" + "Long prose. " * 2000 + "</p>")
    editing[1].document = document; editing[1].content = document["plain_text"]; db.commit()
    assert post(client, auth_headers, editing).status_code == 422
    assert not calls


def test_style_owned_revision_and_prompt(client, db, auth_headers, editing, monkeypatch):
    path = f"/reader/text-revisions/stories/{editing[0].id}/style"
    assert client.get(path, headers=auth_headers).json() == {"revision":0,"style_guide":""}
    saved = client.put(path, headers=auth_headers, json={"expected_revision":0,"style_guide":"Preserve honorifics."})
    assert saved.status_code == 200, saved.text
    assert client.put(path, headers=auth_headers, json={"expected_revision":0,"style_guide":"Stale"}).status_code == 409
    calls=[]; answer(monkeypatch,calls)
    response=post(client,auth_headers,editing)
    assert response.status_code==200, response.text
    assert json.loads(calls[0]["prompt"])["style_preferences"]=="Preserve honorifics."
    assert response.json()["style_revision"]==1
    assert client.get("/reader/text-revisions/stories/999999/style",headers=auth_headers).status_code==404


def test_style_change_during_io_discards_preview(client, db, auth_headers, editing, monkeypatch):
    from app.models.reader_preference import ReaderPreference
    row=ReaderPreference(user_id=editing[2].user_id,novel_id=editing[0].id,scope=f"textstyle:{editing[0].id}",revision=1,values={"style_guide":"Quiet"})
    db.add(row);db.commit()
    def change():
        row.revision=2;row.values={"style_guide":"Loud"};db.commit()
    calls=[];answer(monkeypatch,calls,mutate=change)
    assert post(client,auth_headers,editing).status_code==409


def test_verified_passage_limits_disclosure(client, auth_headers, editing, monkeypatch):
    document=editing[1].document
    selection={"content_version":document["content_version"],"block_id":document["blocks"][0]["id"],"text_offset":0,"text_length":14,"quote":"Alice go home."}
    calls=[];answer(monkeypatch,calls,text="Alice goes home.")
    result=post(client,auth_headers,editing,selection=selection)
    assert result.status_code==200,result.text
    assert result.json()["original"]=="Alice go home."
    assert "She is tired" not in calls[0]["prompt"]
    assert post(client,auth_headers,editing,selection={**selection,"quote":"FORGED"}).status_code==409


def test_style_portable_export_and_keeps_local_on_import(client, db, test_user, auth_headers, editing):
    from app.services.user_data_service import export_user_data, _apply_reader_preferences
    from app.schemas.user_data import ExportNovel
    style={"style_guide":"Keep honorifics"}
    assert _apply_reader_preferences(db,test_user,style,editing[0],scope=f"textstyle:{editing[0].id}")=="applied"
    exported=export_user_data(db,test_user)
    entries=[row for library in exported['libraries'] for row in library['novels']]
    assert any(row.get('text_style_guide')=='Keep honorifics' for row in entries)
    assert ExportNovel.model_validate(entries[0]).text_style_guide=='Keep honorifics'
    assert _apply_reader_preferences(db,test_user,{"style_guide":"Overwrite"},editing[0],scope=f"textstyle:{editing[0].id}")=="kept_local"


@pytest.mark.parametrize('mutation', ['disabled_user', 'ownership', 'deleted_chapter', 'manifest'])
def test_revocation_or_identity_change_during_inference(client, db, test_user, auth_headers, editing, monkeypatch, mutation):
    from app.models import User
    stranger=User(username='change-owner',password='fixture');db.add(stranger);db.commit()
    def change():
        if mutation=='disabled_user':
            test_user.is_disabled=True
        elif mutation=='ownership':
            editing[0].library.user_id=stranger.id
        elif mutation=='deleted_chapter':
            db.delete(editing[1])
        else:
            editing[0].manifest_state.revision+=1
        db.commit()
    calls=[];answer(monkeypatch,calls,mutate=change)
    response=post(client,auth_headers,editing)
    assert response.status_code in (401,404,409),response.text
    assert 'preview' not in response.json()


@pytest.mark.parametrize('finish', ['length','content_filter','tool_calls',None])
def test_incomplete_provider_prose_never_shown(client, auth_headers, editing, monkeypatch, finish):
    def incomplete(provider,**kwargs):
        return {'choices':[{'message':{'content':'Partial prose'},'finish_reason':finish}]}
    monkeypatch.setattr('app.services.reader_provider.direct_request',incomplete)
    result=post(client,auth_headers,editing)
    assert result.status_code==422,result.text


def test_disabled_user_before_inference(client, db, test_user, auth_headers, editing, monkeypatch):
    test_user.is_disabled=True;db.commit()
    calls=[];answer(monkeypatch,calls)
    assert post(client,auth_headers,editing).status_code==401
    assert not calls


def test_glossary_mutation_during_translation_polish_discards_preview(client, db, test_user, auth_headers, editing, monkeypatch):
    novel,chapter,provider=editing
    calls=[];answer(monkeypatch,calls)
    assert post(client,auth_headers,editing).status_code==200
    from app.services.chapter_identity_service import identity
    proof=identity(chapter)
    job=TranslationJob(user_id=test_user.id,novel_id=novel.id,chapter_id=chapter.id,provider_id=provider.id,
        language='de',fingerprint='mutating-glossary',source_version=chapter.document['content_version'],
        chapter_key=proof['chapter_key'],manifest_epoch=proof['manifest_epoch'],manifest_revision=proof['manifest_revision'],
        identity_inferred=False,provider_snapshot={},source_blocks=copy.deepcopy(chapter.document['blocks']),glossary={},
        translated_blocks=[{'id':'de-1','text':'Alice geht heim.'}],status='completed')
    db.add(job);db.commit()
    glossary={'Alice':'Alice'}
    monkeypatch.setattr('app.services.text_revision_service.glossary_for',lambda *args:dict(glossary))
    answer(monkeypatch,calls,mutate=lambda:glossary.update(Alice='Alise'))
    result=post(client,auth_headers,editing,mode='translation_polish',translation_job_id=job.id)
    assert result.status_code==409,result.text
    assert 'preview' not in result.json()


def test_local_defaults_do_not_probe_or_echo_url_secrets(client, auth_headers, monkeypatch):
    monkeypatch.setenv('NEXUS_LOCAL_AI_BASE_URL','http://127.0.0.1:8080/v1')
    monkeypatch.setenv('NEXUS_LOCAL_AI_MODEL','qwen3.8-27b')
    result=client.get('/reader/text-revisions/local-defaults',headers=auth_headers)
    assert result.json()=={'base_url':'http://127.0.0.1:8080/v1','model':'qwen3.8-27b'}
    assert result.headers['cache-control']=='private, no-store'
    monkeypatch.setenv('NEXUS_LOCAL_AI_BASE_URL','http://user:secret@127.0.0.1:8080/v1')
    assert client.get('/reader/text-revisions/local-defaults',headers=auth_headers).json()['base_url']==''
