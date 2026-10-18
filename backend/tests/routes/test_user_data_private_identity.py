from copy import deepcopy
from uuid import uuid4
from app.models import User,Library,Novel,Chapter,ReadingAnnotation
from app.models.import_reading_review import ImportReadingReview
from app.models.portable_story_link import PortableStoryLink
from tests.auth_helpers import bearer_headers


def setup_story(db,user,name='No source address'):
    library=Library(user_id=user.id,name='Private books');db.add(library);db.flush()
    novel=Novel(library_id=library.id,title=name,url=None,novel_site='local');db.add(novel);db.flush()
    chapter=Chapter(novel_id=novel.id,chapter_number=-2,title='Original prologue',content='Private original');db.add(chapter);db.flush();db.refresh(chapter)
    db.add(ReadingAnnotation(user_id=user.id,novel_id=novel.id,chapter_id=chapter.id,note='Retain this private note'))
    db.commit();return library,novel,chapter


def test_null_url_export_keeps_each_book_readings_and_personal_fields(client,db,test_user):
    from app.models.novel_personal import NovelPersonalData
    library,first,chapter=setup_story(db,test_user)
    second=Novel(library_id=library.id,url=None,title='Empty private book');db.add(second);db.flush()
    db.add(NovelPersonalData(user_id=test_user.id,novel_id=first.id,notes='My private book notes'));db.commit()
    document=client.get('/me/export',headers=bearer_headers(test_user.id,db)).json()
    items=document['libraries'][0]['novels'];assert len(items)==2 and all(item['url'] is None for item in items)
    assert len({item['portable_story']['story_epoch'] for item in items})==2
    original=next(item for item in items if item['title']==first.title)
    assert original['annotations'][0]['note']=='Retain this private note' and original['personal']['notes']=='My private book notes'
    assert original['chapter_refs'][0]['chapter_key']==chapter.chapter_key


def test_same_owned_epoch_links_exact_book_not_same_title_or_other_library(client,db,test_user):
    library,original,chapter=setup_story(db,test_user)
    collision=Novel(library_id=library.id,title=original.title,url=None);db.add(collision);db.commit()
    headers=bearer_headers(test_user.id,db);document=client.get('/me/export',headers=headers).json()
    response=client.post('/me/import',headers=headers,json=document);assert response.status_code==200,response.text
    assert db.query(Novel).count()==2 and db.query(PortableStoryLink).count()==2
    reports=response.json()['libraries'][0]['novels'];assert {item['novel_id'] for item in reports}=={original.id,collision.id}
    changed=deepcopy(document);changed['libraries'][0]['name']='Another owned library'
    response=client.post('/me/import',headers=headers,json=changed);assert response.status_code==200,response.text
    assert all(item['status']=='created' and item['original_status']=='unavailable' for item in response.json()['libraries'][0]['novels'])
    assert db.query(Novel).count()==4 and db.query(ReadingAnnotation).count()==1


def test_foreign_private_import_is_durable_repeatable_and_never_fetches(client,db,test_user,monkeypatch):
    from unittest.mock import AsyncMock
    from app.models import ImportJob
    library,original,chapter=setup_story(db,test_user)
    document=client.get('/me/export',headers=bearer_headers(test_user.id,db)).json()
    other=User(username='private-recipient',password='unused');db.add(other);db.commit();headers=bearer_headers(other.id,db)
    network=AsyncMock(side_effect=AssertionError('No private source may be fetched'));monkeypatch.setattr('app.services.metadata_client.scrape_novel_by_url',network)
    first=client.post('/me/import',headers=headers,json=document);assert first.status_code==200,first.text
    entry=first.json()['libraries'][0]['novels'][0];target=db.get(Novel,entry['novel_id'])
    assert target.url is None and target.scrape_status=='awaiting_original' and entry['original_status']=='unavailable'
    assert db.query(Chapter).filter_by(novel_id=target.id).count()==0 and db.query(ImportReadingReview).filter_by(user_id=other.id).count()==1
    repeat=client.post('/me/import',headers=headers,json=document);assert repeat.status_code==200 and repeat.json()['libraries'][0]['novels'][0]['novel_id']==target.id
    assert db.query(Novel).count()==2 and db.query(ImportJob).count()==0
    exported=client.get('/me/export',headers=headers).json();assert exported['libraries'][0]['novels'][0]['portable_story']==document['libraries'][0]['novels'][0]['portable_story']
    network.assert_not_awaited()


def test_stale_destination_epoch_or_library_identity_is_conflict_not_rebind(client,db,test_user):
    library,original,chapter=setup_story(db,test_user);headers=bearer_headers(test_user.id,db)
    data=client.get('/me/export',headers=headers).json();assert client.post('/me/import',headers=headers,json=data).status_code==200
    link=db.query(PortableStoryLink).one();link.target_story_epoch=str(uuid4());db.commit()
    response=client.post('/me/import',headers=headers,json=data);assert response.status_code==200,response.text
    assert response.json()['libraries'][0]['novels'][0]['status']=='conflict' and db.query(Novel).count()==1
    db.refresh(link);assert link.pending_payload['annotations'][0]['note']=='Retain this private note'
    link.target_story_epoch=original.manifest_state.manifest_epoch;library.identity_key=str(uuid4());db.commit()
    response=client.post('/me/import',headers=headers,json=data);assert response.json()['libraries'][0]['novels'][0]['status']=='conflict'


def test_missing_null_url_identity_is_rejected_instead_of_title_matching(client,db,test_user):
    headers=bearer_headers(test_user.id,db)
    response=client.post('/me/import',headers=headers,json={'format':'nexus-user-export','version':2,'libraries':[{'name':'Private','novels':[{'url':None,'title':'Ambiguous'}]}]})
    assert response.status_code==422 and db.query(Novel).count()==0


def test_mixed_200_private_books_have_individual_stable_outcomes(client,db,test_user):
    headers=bearer_headers(test_user.id,db);account=str(uuid4())
    private=[{'url':None,'title':'Same private title','portable_story':{'source_account_key':account,'story_epoch':str(uuid4())}} for _ in range(100)]
    ephemeral=[{'url':'nexus-local:capture:'+str(index),'title':'Unavailable capture'} for index in range(100)]
    document={'format':'nexus-user-export','version':2,'libraries':[{'name':'Mixed private','novels':private+ephemeral}]}
    response=client.post('/me/import',headers=headers,json=document);assert response.status_code==200,response.text
    items=response.json()['libraries'][0]['novels'];assert len(items)==200 and all(item['status']=='created' and item['original_status']=='unavailable' for item in items)
    assert len({item['novel_id'] for item in items})==200 and response.json()['import_job_ids']==[]
    repeat=client.post('/me/import',headers=headers,json=document);assert repeat.status_code==200
    assert all(item['status']=='linked' for item in repeat.json()['libraries'][0]['novels']) and db.query(Novel).count()==200


def test_deleted_target_pk_reuse_preserves_tombstone_and_new_import_payload(client,db,test_user):
    from app.services.novel_services import delete_novel
    library,original,chapter=setup_story(db,test_user);headers=bearer_headers(test_user.id,db)
    data=client.get('/me/export',headers=headers).json();assert client.post('/me/import',headers=headers,json=data).status_code==200
    original_id=original.id;epoch=original.manifest_state.manifest_epoch
    delete_novel(db,original_id)
    link=db.query(PortableStoryLink).one();assert link.novel_id is None and link.target_story_epoch==epoch and link.pending_payload is None
    replacement=Novel(id=original_id,library_id=library.id,url=None,title='Different private original');db.add(replacement);db.commit()
    assert replacement.manifest_state.manifest_epoch!=epoch
    response=client.post('/me/import',headers=headers,json=data);assert response.status_code==200,response.text
    assert response.json()['libraries'][0]['novels'][0]['status']=='conflict'
    db.refresh(replacement);assert replacement.title=='Different private original'
    db.refresh(link);assert link.novel_id is None and link.pending_payload['annotations'][0]['note']=='Retain this private note'
    exported=client.get('/me/export',headers=headers).json()['libraries'][0]['novels']
    assert len(exported)==2 and any(item['portable_story']['story_epoch']==epoch for item in exported)


def test_private_static_shelf_membership_roundtrips_by_opaque_origin(client,db,test_user):
    from app.models import Shelf,ShelfNovel
    library,original,chapter=setup_story(db,test_user)
    second=Novel(library_id=library.id,url=None,title=original.title);db.add(second);db.flush()
    shelf=Shelf(user_id=test_user.id,name='Private originals',position=0);db.add(shelf);db.flush();db.add_all([ShelfNovel(shelf_id=shelf.id,novel_id=original.id,position=0),ShelfNovel(shelf_id=shelf.id,novel_id=second.id,position=1)]);db.commit()
    document=client.get('/me/export',headers=bearer_headers(test_user.id,db)).json();members=document['shelves'][0]['novels']
    assert len(members)==2 and all(item['url'] is None and item['portable_story'] for item in members)
    other=User(username='shelf-recipient',password='unused');db.add(other);db.commit();headers=bearer_headers(other.id,db)
    imported=client.post('/me/import',headers=headers,json=document);assert imported.status_code==200,imported.text
    assert imported.json()['shelves'][0]['links_added']==2 and imported.json()['shelves'][0]['links_missing']==0
    own_shelf=db.query(Shelf).filter_by(user_id=other.id).one();assert db.query(ShelfNovel).filter_by(shelf_id=own_shelf.id).count()==2
    again=client.post('/me/import',headers=headers,json=document);assert again.status_code==200 and again.json()['shelves'][0]['links_existing']==2
    assert db.query(Novel).count()==4 and db.query(ShelfNovel).count()==4


def test_target_move_to_other_owner_never_exposes_or_binds_replacement(client,db,test_user):
    library,original,chapter=setup_story(db,test_user);headers=bearer_headers(test_user.id,db)
    data=client.get('/me/export',headers=headers).json();assert client.post('/me/import',headers=headers,json=data).status_code==200
    other=User(username='new-owner',password='unused');db.add(other);db.flush();foreign=Library(user_id=other.id,name='Secret library');db.add(foreign);db.flush()
    original.library_id=foreign.id;original.title='Secret new owner title';db.commit()
    response=client.post('/me/import',headers=headers,json=data);assert response.status_code==200 and response.json()['libraries'][0]['novels'][0]['status']=='conflict'
    assert 'Secret new owner title' not in response.text and 'Secret library' not in response.text
    assert db.query(ImportReadingReview).filter_by(user_id=test_user.id).count()==1
    from app.services.novel_services import delete_novel
    delete_novel(db,original.id)
    link=db.query(PortableStoryLink).one();assert link.novel_id is None and link.pending_payload['title']=='No source address'
