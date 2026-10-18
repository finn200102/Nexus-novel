"""A new reading run restricts lifetime read receipts before model construction."""
import json
import pytest
from fastapi import HTTPException
from app.models import Chapter, Novel
from app.models.chapter_read_receipt import ChapterReadReceipt
from app.models.translation import ReaderProvider
from app.schemas.reading_runs import ReadingRunAction
from app.services.chapter_document import from_text
from app.services.reading_progress_service import save_reading_progress
from app.services.reading_run_service import action


@pytest.mark.parametrize("first_number", [1, 3])
@pytest.mark.parametrize("stale_identity", ["missing", "prior"])
def test_reread_preserves_receipts_but_fences_prior_progress_and_future_evidence(client,db,test_user,test_library,auth_headers,monkeypatch,stale_identity,first_number):
    from config.settings import settings
    monkeypatch.setenv("NEXUS_LOCAL_AI_BASE_URL","http://local-reader:8020/v1")
    monkeypatch.setattr(settings,"ANALYSIS_ENGINE_URL","http://analysis.invalid:8010")
    monkeypatch.setattr(settings,"ANALYSIS_ENGINE_API_KEY","fixture-internal-key")
    novel=Novel(title="Reread boundary",library_id=test_library.id);db.add(novel);db.flush()
    chapters=[]
    for number,text in [(first_number,"Alice arrives at the castle."),(first_number+1,"Alice FUTURE_ONLY is secretly the queen.")]:
        document=from_text(text)
        chapter=Chapter(novel_id=novel.id,chapter_number=number,title=f"Chapter {number}",content=text,document=document)
        db.add(chapter);chapters.append(chapter)
    provider=ReaderProvider(user_id=test_user.id,name="Local fixture",kind="local",base_url="http://local-reader:8020/v1",model="fixture")
    db.add(provider);db.commit()
    for chapter in chapters:
        progress=save_reading_progress(db,user_id=test_user.id,chapter=chapter,position=0,percent=100,content_version=chapter.document["content_version"])
    old_key=progress.reading_run_key
    assert db.query(ChapterReadReceipt).filter_by(user_id=test_user.id,completed=True).count()==2
    new=action(db,test_user.id,novel.id,ReadingRunAction(expected_revision=progress.revision,operation_id="start-reread",reading_run_key=old_key),"start")
    key=new["current_run_key"]
    assert key!=old_key and new["current_progress"]["furthest_chapter_number"]==0 and new["current_progress"]["furthest_percent"]==0
    assert db.query(ChapterReadReceipt).filter_by(user_id=test_user.id,completed=True).count()==2
    identity={} if stale_identity=="missing" else {"reading_run_key":old_key}
    with pytest.raises(HTTPException) as rejected:
        save_reading_progress(db,user_id=test_user.id,chapter=chapters[1],position=0,percent=100,expected_revision=new["revision"],content_version=chapters[1].document["content_version"],**identity)
    assert rejected.value.status_code==409 and rejected.value.detail["code"]=="reading_run_changed"
    inputs=[]
    def model(_provider,**kwargs):
        value=json.loads(kwargs["prompt"]);inputs.append(value)
        assert value["through_chapter"]==first_number and all(row["chapter"]<=first_number and "FUTURE_ONLY" not in row["text"] for row in value["evidence"])
        evidence=value["evidence"][0]
        answer={"answer":"Alice arrives at the castle.","citations":[{"chapter":first_number,"block_id":evidence["block_id"],"quote":"Alice arrives"}]}
        return {"choices":[{"message":{"content":json.dumps(answer)},"finish_reason":"stop"}],"usage":{"prompt_tokens":10,"completion_tokens":5}}
    monkeypatch.setattr("app.services.companion_client.request",model)
    url=f"/reader/companion/{novel.id}/questions"
    payload={"provider_id":provider.id,"question":"Who is Alice?","through_chapter":first_number+1}
    before=client.post(url,headers=auth_headers,json=payload)
    assert before.status_code==200 and before.json()["through_chapter"] is None and inputs==[]
    save_reading_progress(db,user_id=test_user.id,chapter=chapters[0],position=0,percent=100,expected_revision=new["revision"],content_version=chapters[0].document["content_version"],reading_run_key=key)
    response=client.post(url,headers=auth_headers,json=payload)
    assert response.status_code==200,response.text
    assert response.json()["through_chapter"]==first_number and len(inputs)==1
    assert all(citation["chapter"]==first_number for citation in response.json()["citations"])
    selected=client.post(url,headers=auth_headers,json={**payload,"through_chapter":0})
    assert selected.status_code==200 and selected.json()["through_chapter"] is None and len(inputs)==1
    assert db.query(ChapterReadReceipt).filter_by(user_id=test_user.id,completed=True).count()==2


@pytest.mark.parametrize('prologue_number', [0, -1])
def test_unread_boundary_never_uses_old_nonpositive_prologue_receipts(client,db,test_user,test_library,auth_headers,monkeypatch,prologue_number):
    from config.settings import settings
    monkeypatch.setattr(settings,'ANALYSIS_ENGINE_URL','http://analysis.invalid:8010')
    monkeypatch.setattr(settings,'ANALYSIS_ENGINE_API_KEY','fixture-only')
    monkeypatch.setenv('NEXUS_LOCAL_AI_BASE_URL','http://local-reader:8020/v1')
    novel=Novel(title='Nonpositive earlier prologue',library_id=test_library.id);db.add(novel);db.flush()
    old=from_text('Alice ZERO_ONLY knows a secret in the earlier prologue.')
    prologue=Chapter(novel_id=novel.id,chapter_number=prologue_number,title='Old private prologue',
        content=old['plain_text'],document=old,category='appendix')
    current=from_text('Alice arrives at the harbour.')
    first=Chapter(novel_id=novel.id,chapter_number=3,title='First followed chapter',content=current['plain_text'],document=current)
    provider=ReaderProvider(user_id=test_user.id,name='Local prologue fixture',kind='local',base_url='http://local-reader:8020/v1',model='fixture')
    db.add_all([prologue,first,provider]);db.flush()
    db.add(ChapterReadReceipt(user_id=test_user.id,chapter_id=prologue.id,content_version=old['content_version'],completed=True))
    db.commit()
    progress=save_reading_progress(db,user_id=test_user.id,chapter=first,position=0,percent=100,content_version=current['content_version'])
    restarted=action(db,test_user.id,novel.id,ReadingRunAction(expected_revision=progress.revision,
        operation_id='restart-prologue-boundary',reading_run_key=progress.reading_run_key),'start')
    assert restarted['first_chapter_number']==3 and restarted['current_progress']['furthest_chapter_number']==0
    def forbidden(*args,**kwargs):raise AssertionError('Unread prologue must never enter model input')
    monkeypatch.setattr('app.services.companion_client.request',forbidden)
    route=f'/reader/companion/{novel.id}/questions'
    payload={'provider_id':provider.id,'question':'What does Alice know about ZERO_ONLY?'}
    unread=client.post(route,headers=auth_headers,json=payload)
    assert unread.status_code==200 and unread.json()['through_chapter'] is None and unread.json()['citations']==[]
    save_reading_progress(db,user_id=test_user.id,chapter=first,position=0,percent=100,content_version=current['content_version'],
        expected_revision=restarted['revision'],reading_run_key=restarted['current_run_key'])
    explicit_zero=client.post(route,headers=auth_headers,json={**payload,'through_chapter':0})
    assert explicit_zero.status_code==200 and explicit_zero.json()['through_chapter'] is None and explicit_zero.json()['citations']==[]
