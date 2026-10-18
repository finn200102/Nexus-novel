"""Complete private library queries: SQL filters precede bounded pagination."""
from datetime import datetime
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import event
from app.models import Novel,Library,Chapter,ReadingProgress
from app.models.follow import UserNovelFollow
from app.models.novel_personal import NovelPersonalData,NovelUserTag
from app.models.shelf import Shelf,ShelfNovel
from app.schemas.library_views import OwnedLibraryDefinition as Definition,LibraryStoryPage,LibraryViewPreviewInput
from app.services.library_view_service import page,options,validate_definition


def story(db,library,title,**kwargs):
    row=Novel(library_id=library.id,title=title,url=f'https://fixture.invalid/{title}',**kwargs);db.add(row);db.flush();return row


@pytest.mark.parametrize('change',[{'version':True},{'version':1.0},{'version':'1'},{'unknown':True},{'source':'unknown-site'},{'library_ids':[True]},{'library_ids':[-1]},{'follow_states':['unread']},{'min_rating':True},{'shelf_id':0},{'user_tag':'  '}])
def test_definition_rejects_unrecognized_or_coerced_filters(change):
    with pytest.raises(ValidationError):Definition.model_validate(change)


def test_all_owned_libraries_filters_and_deterministic_late_page(db,test_user,test_library):
    second=Library(user_id=test_user.id,name='Local EPUBs');db.add(second);db.flush()
    when=datetime(2026,1,1)
    ids=[]
    for number in range(137):
        novel=story(db,second if number%2 else test_library,f'Book {number:03}',author='AUTHOR needle' if number>=130 else 'Someone',created_at=when,novel_site='local',metadata_id=None)
        ids.append(novel.id)
    db.commit()
    result=page(db,test_user.id,Definition(sort_by='title'),100,50)
    assert result['total']==137 and result['library_total']==137
    assert [item['id'] for item in result['items']]==ids[100:]
    assert all(item['library_name'] in {'Local EPUBs',test_library.name} for item in result['items'])
    assert LibraryStoryPage.model_validate(result).total==137
    queried=page(db,test_user.id,Definition(q='needle'),0,5)
    assert queried['total']==7 and queried['library_total']==137
    tie=page(db,test_user.id,Definition(sort_by='recent'),0,5)
    assert [item['id'] for item in tie['items']]==ids[::-1][:5]


def test_foreign_or_deleted_scope_is_error_even_empty(db,test_user,test_library):
    with pytest.raises(HTTPException) as error:validate_definition(db,test_user.id,Definition(library_ids=[999999]))
    assert error.value.status_code==404
    with pytest.raises(HTTPException) as error:validate_definition(db,test_user.id,Definition(shelf_id=999999))
    assert error.value.status_code==404
    gone=Library(user_id=test_user.id,name='Deleted library');db.add(gone);db.flush();gone_id=gone.id;db.delete(gone);db.commit()
    with pytest.raises(HTTPException):page(db,test_user.id,Definition(library_ids=[gone_id]))


def test_personal_filters_and_status_facets_preserve_other_criteria(db,test_user,test_library):
    shelf=Shelf(user_id=test_user.id,name='Static');db.add(shelf);db.flush()
    rows=[]
    for number,state in enumerate(('reading','completed','ignored')):
        novel=story(db,test_library,f'Find {number}',follow_state='dropped',novel_site='ao3');rows.append(novel)
        db.add(UserNovelFollow(user_id=test_user.id,novel_id=novel.id,state=state))
        db.add(NovelPersonalData(user_id=test_user.id,novel_id=novel.id,rating=5-number))
        db.add(NovelUserTag(user_id=test_user.id,novel_id=novel.id,tag='favorite'))
        db.add(ShelfNovel(shelf_id=shelf.id,novel_id=novel.id))
    db.commit()
    selected=page(db,test_user.id,Definition(q='Find',source='ao3',user_tag=' FAVORITE ',min_rating=4,shelf_id=shelf.id,follow_states=['completed']))
    assert [item['id'] for item in selected['items']]==[rows[1].id]
    assert selected['items'][0]['follow_state']=='completed' and selected['items'][0]['personal_rating']==4
    assert selected['status_counts']=={'plan_to_read':0,'reading':1,'completed':1,'ignored':0,'on_hold':0,'dropped':0}
    assert selected['library_total']==3


def test_literal_wildcards_and_author_search(db,test_user,test_library):
    wanted=story(db,test_library,'literal %_\\ token',author='A person')
    story(db,test_library,'literal abcX token',author='B person')
    db.commit()
    assert [row['id'] for row in page(db,test_user.id,Definition(q='%_\\'))['items']]==[wanted.id]
    assert page(db,test_user.id,Definition(q='A person'))['total']==1


@pytest.mark.parametrize('sort',['personal_rating','chapters','updated_since_read'])
def test_personal_and_progress_sort_are_sql_before_page(db,test_user,test_library,sort):
    novels=[story(db,test_library,f'Book {i:03}',chapter_count=i,created_at=datetime(2026,1,1)) for i in range(120)]
    chosen=novels[-1]
    db.add(NovelPersonalData(user_id=test_user.id,novel_id=chosen.id,rating=5))
    db.add(ReadingProgress(user_id=test_user.id,novel_id=chosen.id,chapter_number=-2,percent=0))
    db.add(Chapter(novel_id=chosen.id,chapter_number=0,title='Later prologue',content='NEVER LOAD THIS BODY'))
    db.commit();statements=[]
    def observe(conn,cursor,statement,params,context,many):statements.append(statement)
    event.listen(db.bind,'before_cursor_execute',observe)
    try:result=page(db,test_user.id,Definition(sort_by=sort),0,1)
    finally:event.remove(db.bind,'before_cursor_execute',observe)
    assert result['items'][0]['id']==chosen.id and result['total']==120
    assert not any('chapters.content' in sql or 'chapters.document' in sql for sql in statements)
    assert not any('FOR UPDATE' in sql for sql in statements)


@pytest.mark.parametrize('url,site,expected',[
    ('https://archiveofourown.org/works/7',None,'archive'),
    ('https://www.fanfiction.net/s/7',None,'fanfiction'),
    ('https://forums.spacebattles.com/threads/7',None,'spacebattles'),
    ('nexus-local:epub:abc',None,'local'),
    ('https://archiveofourown.org.attacker.invalid/works/7',None,None),
    ('https://fixture.invalid/7','rr','royalroad')])
def test_source_alias_and_exact_host_fallback(db,test_user,test_library,url,site,expected):
    novel=Novel(library_id=test_library.id,title='Alias',url=url,novel_site=site);db.add(novel);db.commit()
    opts=options(db,test_user.id)
    assert [row['id'] for row in opts['sources']]==([expected] if expected else [])
    if expected:assert page(db,test_user.id,Definition(source=expected))['total']==1


def test_options_are_bounded_and_mark_truncation(db,test_user,test_library):
    novel=story(db,test_library,'Local',novel_site='local')
    for number in range(205):db.add(NovelUserTag(user_id=test_user.id,novel_id=novel.id,tag=f'tag {number:03}'))
    for number in range(101):db.add(Library(user_id=test_user.id,name=f'library {number:03}'))
    db.commit();result=options(db,test_user.id)
    assert len(result['libraries'])==100 and result['libraries_truncated']
    assert len(result['user_tags'])==200 and result['user_tags_truncated']
    assert result['sources']==[{'id':'local','label':'Local EPUB'}] and not result['sources_truncated']


def test_preview_request_is_strict_and_routes_do_not_enrich_blank_titles(client,db,test_user,test_library,auth_headers,monkeypatch):
    def forbidden(*a,**k):raise AssertionError('A private library query must not fetch a source or catalog')
    monkeypatch.setattr('app.services.metadata_client.get_novel_metadata',forbidden)
    novel=story(db,test_library,'',metadata_id=9999)
    db.commit()
    response=client.post('/library-views/preview',headers=auth_headers,json={'definition':{},'limit':1})
    assert response.status_code==200,response.text
    assert response.headers['cache-control']=='private, no-store'
    assert response.json()['items'][0]['id']==novel.id and response.json()['items'][0]['title']==''
    assert client.get('/library-views/options',headers=auth_headers).status_code==200
    with pytest.raises(ValidationError):LibraryViewPreviewInput.model_validate({'definition':{},'limit':101})


def test_foreign_collaborator_shelf_entries_cannot_expand_owned_scope(db,test_user,test_library):
    from app.models import User
    foreign=User(username='foreign-library-owner',password='unused');db.add(foreign);db.flush()
    library=Library(user_id=foreign.id,name='Foreign secret library');db.add(library);db.flush()
    secret=story(db,library,'Foreign secret',novel_site='archive')
    mine=story(db,test_library,'Owned',novel_site='local')
    shelf=Shelf(user_id=test_user.id,name='Mixed collaborator references');db.add(shelf);db.flush()
    db.add_all([ShelfNovel(shelf_id=shelf.id,novel_id=secret.id),ShelfNovel(shelf_id=shelf.id,novel_id=mine.id)])
    db.add(NovelUserTag(user_id=foreign.id,novel_id=secret.id,tag='private-tag'));db.commit()
    result=page(db,test_user.id,Definition(shelf_id=shelf.id))
    assert [row['id'] for row in result['items']]==[mine.id] and result['library_total']==1
    assert 'private-tag' not in options(db,test_user.id)['user_tags']
    with pytest.raises(HTTPException) as exc:page(db,test_user.id,Definition(library_ids=[library.id]))
    assert exc.value.status_code==404
    assert page(db,test_user.id,Definition(q='Foreign secret'))['total']==0


def test_schema_bound_applies_before_duplicate_library_id_normalization():
    with pytest.raises(ValidationError):Definition(library_ids=[1]*101)


def test_legacy_null_url_is_honestly_included_without_fetching(client,db,test_user,test_library,auth_headers):
    novel=Novel(library_id=test_library.id,title='Legacy metadata only',url=None);db.add(novel);db.commit()
    response=client.post('/library-views/preview',headers=auth_headers,json={'definition':{}})
    assert response.status_code==200,response.text
    assert response.json()['items'][0]['url'] is None


def test_chapter_sort_uses_actual_metadata_count_when_legacy_totals_absent(db,test_user,test_library):
    first=story(db,test_library,'A without chapters')
    later=story(db,test_library,'Z local chapters')
    for number in (-3,0,7):db.add(Chapter(novel_id=later.id,chapter_number=number,title='Local'))
    db.commit()
    assert [item['id'] for item in page(db,test_user.id,Definition(sort_by='chapters'))['items']]==[later.id,first.id]


@pytest.mark.parametrize('change',[{'library_ids':[2**63]},{'shelf_id':2**63},{'library_ids':[2147483648]},{'shelf_id':2147483648}])
def test_library_filter_ids_reject_database_integer_overflow(change):
    with pytest.raises(ValidationError):Definition.model_validate(change)


def test_recent_means_story_update_not_addition_date(db,test_user,test_library):
    older=story(db,test_library,'Old addition new update',created_at=datetime(2020,1,1),updated_date=datetime(2026,10,1))
    newer=story(db,test_library,'New addition old update',created_at=datetime(2026,9,1),updated_date=datetime(2025,1,1))
    db.commit()
    assert [row['id'] for row in page(db,test_user.id,Definition(sort_by='recent'))['items']]==[older.id,newer.id]


@pytest.mark.parametrize('case_name,current,furthest,furthest_percent,numbers',[
    ('rewound positive gaps',3,11,100,[3,7,11]),
    ('rewound zero',-3,0,100,[-3,0]),
    ('rewound negative',-7,-2,100,[-7,-2]),
    ('no actual manifest',-7,-2,100,[]),
])
def test_updated_since_read_never_reinterprets_rewind_or_count_as_unread(db,test_user,test_library,case_name,current,furthest,furthest_percent,numbers):
    earlier=story(db,test_library,'Already visited '+case_name,chapter_count=99999,updated_date=datetime(2026,10,1))
    later=story(db,test_library,'Actually new chapter',updated_date=datetime(2025,1,1))
    for number in numbers:db.add(Chapter(novel_id=earlier.id,chapter_number=number,title='Visited'))
    db.add(ReadingProgress(user_id=test_user.id,novel_id=earlier.id,chapter_number=current,furthest_chapter_number=furthest,furthest_percent=furthest_percent))
    db.add(Chapter(novel_id=later.id,chapter_number=0,title='Actual later prologue'))
    db.add(ReadingProgress(user_id=test_user.id,novel_id=later.id,chapter_number=-3,furthest_chapter_number=-3,furthest_percent=100))
    db.commit()
    result=page(db,test_user.id,Definition(sort_by='updated_since_read'))
    assert [row['id'] for row in result['items']]==[later.id,earlier.id]
