"""Preferred terminology can never silently migrate into an earlier reading scope."""
from uuid import uuid4
import pytest
from sqlalchemy import text
from fastapi import HTTPException
from app.models import Novel,Chapter
from app.models.translation import StoryGlossary
from app.services import glossary_identity_service as service
from app.services.translation_service import glossary_for
from app.services.chapter_document import from_text
from app.services.chapter_identity_service import identity,source_version


def setup(db,library):
    novel=Novel(title='Scope',library_id=library.id);db.add(novel);db.flush()
    rows=[]
    for number in [-2,0,7]:
        doc=from_text(f'Original prose {number}.')
        row=Chapter(novel_id=novel.id,chapter_number=number,title=f'Part {number}',document=doc,content=doc['plain_text'])
        db.add(row);rows.append(row)
    db.commit()
    for row in rows:db.refresh(row)
    return novel,rows


def approve(db,user,novel,row,**extra):
    capture={f'expected_{key}':value for key,value in identity(row).items()}
    value=service.upsert(db,user.id,novel.id,source='Secret',target='Preferred',language='de',through_chapter=row.chapter_number,
        expected_content_version=source_version(row),**capture,**extra)
    db.commit();return value


def test_signed_gapped_floor_and_reordered_prerequisites_never_broaden_knowledge(db,test_user,test_library):
    novel,rows=setup(db,test_library);view=approve(db,test_user,novel,rows[-1])
    assert view['prerequisite_count']==3 and glossary_for(db,test_user.id,novel.id,'de',0)=={}
    assert glossary_for(db,test_user.id,novel.id,'de',7)=={'Secret':'Preferred'}
    rows[-1].chapter_number=-3;db.commit()
    assert glossary_for(db,test_user.id,novel.id,'de',-2)=={}
    assert glossary_for(db,test_user.id,novel.id,'de',0)=={'Secret':'Preferred'}
    view=service.entries(db,test_user.id,novel.id)['items'][0]
    assert view['current_number']==-3 and view['through_chapter']==7 and view['effective_through_chapter']==0


@pytest.mark.parametrize('change',['floor','earlier','archive','epoch'])
def test_revised_or_missing_prerequisite_never_reaches_provider(db,test_user,test_library,change):
    novel,rows=setup(db,test_library);approve(db,test_user,novel,rows[-1])
    if change in {'floor','earlier'}:
        row=rows[-1] if change=='floor' else rows[0];row.document=from_text('Revised original prose.')
    elif change=='archive':rows[0].archived=True
    else:db.query(StoryGlossary).one().manifest_epoch=str(uuid4())
    db.commit()
    assert glossary_for(db,test_user.id,novel.id,'de',7)=={}
    view=service.entries(db,test_user.id,novel.id)['items'][0]
    assert view['binding_state']=='review_required' and view['reason']


def test_legacy_terms_stay_manageable_but_require_explicit_identity_review(db,test_user,test_library):
    novel,rows=setup(db,test_library)
    old=StoryGlossary(user_id=test_user.id,novel_id=novel.id,source='Secret',target='Old',language='de',through_chapter=0)
    db.add(old);db.commit();old_id=old.id
    assert glossary_for(db,test_user.id,novel.id,'de',7)=={}
    assert service.entries(db,test_user.id,novel.id)['items'][0]['reason']=='legacy_identity_unknown'
    view=approve(db,test_user,novel,rows[1],entry_id=old_id)
    assert view['id']==old_id and view['binding_state']=='verified' and view['prerequisite_count']==2
    assert glossary_for(db,test_user.id,novel.id,'de',-2)=={} and glossary_for(db,test_user.id,novel.id,'de',0)=={'Secret':'Preferred'}


def test_identical_text_and_reused_pk_cannot_supply_old_glossary_floor(db,test_user,test_library):
    novel,rows=setup(db,test_library);row=rows[-1];approve(db,test_user,novel,row)
    pk,doc=row.id,row.document
    db.execute(text('DELETE FROM chapters WHERE id=:id'),{'id':pk});db.commit();db.expunge(row)
    db.add(Chapter(id=pk,novel_id=novel.id,chapter_number=7,document=doc,content=doc['plain_text']));db.commit()
    assert glossary_for(db,test_user.id,novel.id,'de',7)=={}
    assert service.entries(db,test_user.id,novel.id)['items'][0]['reason']=='prerequisite_missing_or_archived'


def test_unknown_floor_and_foreign_owner_do_not_capture_terms(db,test_user,test_library):
    novel,rows=setup(db,test_library)
    with pytest.raises(HTTPException) as error:
        service.upsert(db,test_user.id,novel.id,source='X',target='Y',language='de',through_chapter=999)
    assert error.value.status_code==409
    with pytest.raises(HTTPException) as error:service.entries(db,test_user.id+1000,novel.id)
    assert error.value.status_code==404 and db.query(StoryGlossary).count()==0



def test_zero_is_real_floor_unicode_terms_survive_unrelated_append_without_implicit_global_scope(db,test_user,test_library):
    novel,rows=setup(db,test_library)
    capture={f'expected_{key}':value for key,value in identity(rows[1]).items()}
    service.upsert(db,test_user.id,novel.id,source='Castle',target='Schlösschen',language='de',through_chapter=0,
        expected_content_version=source_version(rows[1]),**capture);db.commit()
    new=Chapter(novel_id=novel.id,chapter_number=900,title='Much later');db.add(new);db.commit()
    assert glossary_for(db,test_user.id,novel.id,'de',-2)=={}
    assert glossary_for(db,test_user.id,novel.id,'de',900)=={'Castle':'Schlösschen'}
    view=service.entries(db,test_user.id,novel.id)['items'][0]
    assert view['through_chapter']==view['current_number']==view['effective_through_chapter']==0


def test_bounded_prerequisite_capture_rejects_without_partial_term(db,test_user,test_library,monkeypatch):
    novel,rows=setup(db,test_library);monkeypatch.setattr(service,'MAX_PREREQUISITES',2)
    with pytest.raises(HTTPException) as error:approve(db,test_user,novel,rows[-1])
    assert error.value.status_code==422 and db.query(StoryGlossary).count()==0
