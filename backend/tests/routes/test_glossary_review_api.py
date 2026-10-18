"""Legacy terms remain manageable without supplying provider authority."""
from app.models.translation import StoryGlossary
from app.services.chapter_identity_service import identity,source_version
from tests.routes.test_glossary_identity import setup


def test_retained_term_requires_explicit_exact_chapter_approval(client,db,test_user,test_library,auth_headers):
    novel,chapters=setup(db,test_library)
    legacy=StoryGlossary(user_id=test_user.id,novel_id=novel.id,source='Mira',target='Mirabelle',language='de',through_chapter=7)
    db.add(legacy);db.commit()
    base=f'/reader/glossary/{novel.id}'
    page=client.get(base+'/entries',headers=auth_headers,params={'language':'de'})
    assert page.status_code==200,page.text
    assert page.json()['items'][0]['binding_state']=='review_required'
    assert client.get(base,headers=auth_headers,params={'language':'de','through_chapter':7}).json()=={}
    value=dict(source='Mira',target='Mirabelle',language='de',through_chapter=-2,entry_id=legacy.id)
    rejected=client.post(base,headers=auth_headers,json=value)
    assert rejected.status_code==409 and rejected.json()['detail']['code']=='chapter_identity_required'
    chapter=chapters[0]
    value.update({f'expected_{key}':item for key,item in identity(chapter).items()})
    value['expected_content_version']=source_version(chapter)
    approved=client.post(base,headers=auth_headers,json=value)
    assert approved.status_code==200,approved.text
    assert approved.json()['binding_state']=='verified' and approved.json()['id']==legacy.id
    assert approved.json()['chapter_key']==chapter.chapter_key
    assert client.get(base,headers=auth_headers,params={'language':'de','through_chapter':-2}).json()=={'Mira':'Mirabelle'}
    assert db.query(StoryGlossary).count()==1


def test_stale_approval_cannot_adopt_a_new_chapter_address(client,db,test_library,auth_headers):
    novel,chapters=setup(db,test_library)
    chapter=chapters[-1]
    value=dict(source='Mira',target='Queen',language='de',through_chapter=7,
        **{f'expected_{key}':item for key,item in identity(chapter).items()},expected_content_version=source_version(chapter))
    chapter.chapter_number=8;db.commit()
    response=client.post(f'/reader/glossary/{novel.id}',headers=auth_headers,json=value)
    assert response.status_code in {404,409}
    assert db.query(StoryGlossary).count()==0
