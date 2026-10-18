"""No real provider requests: exercise the shared consent/budget pipeline."""
import copy
import json
import pytest
from app.models import Chapter, Novel, User, Library
from app.models.chapter import ContentStatus
from app.models.translation import ReaderProvider, TranslationJob
from app.models.story_processing_permission import StoryProcessingPermission
from app.services.chapter_document import from_html
from app.services.notification_crypto import encrypt_url


@pytest.fixture
def passage(db, test_library, test_user, monkeypatch):
    monkeypatch.setenv("NEXUS_LOCAL_AI_BASE_URL", "http://local-reader:8020/v1")
    novel = Novel(title="Private selected translation", library_id=test_library.id)
    db.add(novel); db.flush()
    document = from_html("<p>😀 Alice arrives. Bob greets her.</p><p>Unselected SECRET prose.</p>")
    chapter = Chapter(novel_id=novel.id, chapter_number=1, title="Chapter", content=document["plain_text"], document=document, content_status=ContentStatus.PRESENT)
    provider = ReaderProvider(user_id=test_user.id, name="Local", kind="local", base_url="http://local-reader:8020/v1", model="local-model")
    db.add_all([chapter, provider]); db.commit()
    value = {"provider_id":provider.id, "language":"de", "content_version":document["content_version"], "block_id":document["blocks"][0]["id"], "text_offset":3, "text_length":13, "quote":"Alice arrives"}
    return novel, chapter, provider, value


def post(client, auth_headers, novel, value):
    return client.post(f"/reader/translations/{novel.id}/1/passage-preview", json=value, headers=auth_headers)


def answer(monkeypatch, calls):
    def request(provider, **kwargs):
        calls.append((provider.id, kwargs))
        return {"choices":[{"message":{"content":"Alice kommt an."},"finish_reason":"stop"}], "usage":{"prompt_tokens":10,"completion_tokens":5}}
    monkeypatch.setattr("app.services.reader_provider.direct_request", request)


def approve_passage_terms(client,headers,db,user,novel,chapter):
    future_document=from_html('<p>Future names are disclosed here.</p>')
    future=Chapter(novel_id=novel.id,chapter_number=2,title='Later material',content=future_document['plain_text'],
        document=future_document,content_status=ContentStatus.PRESENT)
    db.add(future);db.commit()
    from app.services.chapter_identity_service import identity
    # Approve both terms through the real version-bound API. An unapproved
    # legacy numeric term would only test rejection of unknown provenance.
    for floor,source,target in ((chapter,'Alice','Alise'),(future,'Bob','FUTURE KING')):
        proof=identity(floor)
        approved=client.post(f'/reader/glossary/{novel.id}',headers=headers,json={
            'source':source,'target':target,'language':'de','through_chapter':floor.chapter_number,
            **{f'expected_{key}':proof[key] for key in ('chapter_key','manifest_epoch','manifest_revision')},
            'expected_content_version':floor.document['content_version']})
        assert approved.status_code==200,approved.text


def test_verified_utf16_slice_only_and_saved_variants_untouched(client, db, test_user, auth_headers, passage, monkeypatch):
    novel, chapter, provider, value = passage
    original = copy.deepcopy(chapter.document)
    existing = TranslationJob(user_id=test_user.id, novel_id=novel.id, chapter_id=chapter.id, provider_id=provider.id, language="de", fingerprint="saved", source_version=original["content_version"], provider_snapshot={}, source_blocks=original["blocks"], glossary={}, translated_blocks=[{"id":"saved-block","text":"Saved translation"}], status="completed")
    db.add(existing)
    approve_passage_terms(client,auth_headers,db,test_user,novel,chapter)
    calls=[]; answer(monkeypatch,calls)
    response = post(client,auth_headers,novel,value)
    assert response.status_code == 200, response.text
    result=response.json()
    assert result["original"] == "Alice arrives" and result["translation"] == "Alice kommt an."
    assert result["anchor"] == {key:value[key] for key in ("content_version","block_id","text_offset","text_length","quote")}
    assert response.headers["cache-control"] == "private, no-store"
    assert len(calls)==1 and json.loads(calls[0][1]["prompt"])["text"] == "Alice arrives"
    assert "SECRET" not in calls[0][1]["prompt"] and "FUTURE KING" not in calls[0][1]["prompt"]
    assert json.loads(calls[0][1]["prompt"])["glossary"] == {"Alice":"Alise"}
    db.expire_all()
    assert db.get(Chapter,chapter.id).document == original
    assert db.query(TranslationJob).count()==1 and db.get(TranslationJob,existing.id).translated_blocks == [{"id":"saved-block","text":"Saved translation"}]


@pytest.mark.parametrize("patch,status", [({"content_version":"old"},409),({"block_id":"other"},409),({"quote":"forged content"},409),({"text_offset":1,"text_length":1,"quote":"x"},422),({"text_offset":99999},422),({"text_length":0},422),({"text_offset":True},422),({"text_length":1.5},422),({"quote":"a"*3001},422),({"arbitrary_text":"injected"},422)])
def test_invalid_or_stale_anchors_fail_before_provider(client,auth_headers,passage,monkeypatch,patch,status):
    novel,_,_,value=passage; calls=[]; answer(monkeypatch,calls)
    response=post(client,auth_headers,novel,{**value,**patch})
    assert response.status_code==status,response.text
    assert calls==[]


def test_exact_size_limit_and_whitespace_rejection(client,db,auth_headers,passage,monkeypatch):
    novel,chapter,_,value=passage; calls=[]; answer(monkeypatch,calls)
    document=from_html("<p>"+"😀"*3000+"</p>"); chapter.document=document;chapter.content=document["plain_text"];db.commit()
    value.update(content_version=document["content_version"],block_id=document["blocks"][0]["id"],text_offset=0,text_length=6000,quote="😀"*3000)
    assert post(client,auth_headers,novel,value).status_code==200
    assert len(json.loads(calls[0][1]["prompt"])["text"].encode())==12000
    document=from_html("<p>A   B</p>");chapter.document=document;chapter.content=document["plain_text"];db.commit()
    value.update(content_version=document["content_version"],block_id=document["blocks"][0]["id"],text_offset=1,text_length=1,quote=" ")
    assert post(client,auth_headers,novel,value).status_code==422
    assert len(calls)==1


def test_remote_consent_ao3_revocation_and_budget_are_shared(client,db,test_user,auth_headers,passage,monkeypatch):
    novel,_,provider,value=passage; calls=[]; answer(monkeypatch,calls)
    novel.novel_site="ao3"; provider.kind="openai_compatible";provider.base_url="https://provider.invalid/v1";provider.secret_ciphertext=encrypt_url("fixture-key");provider.input_price=1;provider.output_price=2;provider.budget_microusd=1_000_000;db.commit()
    assert post(client,auth_headers,novel,value).status_code==422
    value["external_consent"]=True
    assert post(client,auth_headers,novel,value).status_code==422
    value["ao3_consent"]=True
    provider.budget_microusd=1;db.commit()
    assert post(client,auth_headers,novel,value).status_code==422 and calls==[]
    provider.budget_microusd=1_000_000;db.commit()
    assert post(client,auth_headers,novel,value).status_code==200 and len(calls)==1
    db.refresh(provider)
    assert provider.used_microusd==20 and provider.reserved_microusd==0
    db.add(StoryProcessingPermission(user_id=test_user.id,novel_id=novel.id,provider_id=provider.id,translation=False,companion=False,ao3_consent=False));db.commit()
    assert post(client,auth_headers,novel,value).status_code==422 and len(calls)==1


def test_private_disabled_unsupported_provider_and_no_fallback(client,db,auth_headers,passage,monkeypatch):
    novel,_,provider,value=passage; calls=[]; answer(monkeypatch,calls)
    provider.enabled=False;db.commit()
    assert post(client,auth_headers,novel,value).status_code==422 and calls==[]
    provider.enabled=True;provider.supported_languages=["ja"];db.commit()
    assert post(client,auth_headers,novel,value).status_code==422 and calls==[]
    stranger=User(username="passage-stranger",password="unused");db.add(stranger);db.flush()
    library=Library(name="Hidden",user_id=stranger.id);db.add(library);db.flush()
    other=Novel(title="Hidden",library_id=library.id);db.add(other);db.commit()
    assert post(client,auth_headers,other,value).status_code==404
    provider.user_id=stranger.id;db.commit()
    assert post(client,auth_headers,novel,value).status_code==404
    provider.user_id=novel.library.user_id;provider.supported_languages=[];db.commit()
    def unavailable(*args,**kwargs):calls.append(1);raise RuntimeError("private credential must not leak")
    monkeypatch.setattr("app.services.reader_provider.direct_request",unavailable)
    failure=post(client,auth_headers,novel,value)
    assert failure.status_code==502 and "no alternative provider" in failure.text
    assert "credential" not in failure.text and calls==[1]


def test_source_update_during_provider_response_rejects_stale_preview(client,db,auth_headers,passage,monkeypatch):
    novel,chapter,_,value=passage
    def changed(*args,**kwargs):
        document=from_html("<p>Revised original.</p>");chapter.document=document;chapter.content=document["plain_text"];db.commit()
        return {"choices":[{"message":{"content":"Stale preview"},"finish_reason":"stop"}]}
    monkeypatch.setattr("app.services.reader_provider.direct_request",changed)
    assert post(client,auth_headers,novel,value).status_code==409
    assert db.query(TranslationJob).count()==0
