from app.models import Novel
from app.models.reader_preference import ReaderPreference


def test_pronunciations_export_by_story_source_and_import_preserves_local_choices(client,db,test_user,test_library,auth_headers):
    novel=Novel(title='Names',url='https://www.royalroad.com/fiction/123/names',library_id=test_library.id)
    db.add(novel);db.commit()
    account=[{'source':'Anna','spoken':'AH nah'}]
    story=[{'source':'Nexus','spoken':'Nek-sus'}]
    for route,rules,inherit in [('/audio/pronunciation',account,True),(f'/audio/pronunciation/stories/{novel.id}',story,False)]:
        saved=client.put(route,headers=auth_headers,json={'rules':rules,'inherit_account':inherit,'expected_revision':0,'operation_id':route})
        assert saved.status_code==200
    exported=client.get('/me/export',headers=auth_headers).json()
    assert exported['pronunciation']=={'rules':account,'inherit_account':False}
    assert exported['libraries'][0]['novels'][0]['pronunciation']=={'rules':story,'inherit_account':False}
    assert 'pronunciation:' not in str(exported)
    db.query(ReaderPreference).filter(ReaderPreference.user_id==test_user.id,ReaderPreference.scope.like('pronunciation%')).delete(synchronize_session=False)
    db.commit()
    imported=client.post('/me/import',headers=auth_headers,json=exported)
    assert imported.status_code==200 and imported.json()['pronunciation']=='applied'
    assert imported.json()['libraries'][0]['novels'][0]['pronunciation']=='applied'
    profile=client.get(f'/audio/pronunciation/stories/{novel.id}',headers=auth_headers).json()
    assert profile['rules']==story and profile['effective_rules']==story and not profile['inherit_account']
    assert client.post('/me/import',headers=auth_headers,json=exported).json()['pronunciation']=='unchanged'
    assert client.put('/audio/pronunciation',headers=auth_headers,json={'rules':[],'expected_revision':1,'operation_id':'local-clear'}).status_code==200
    assert client.post('/me/import',headers=auth_headers,json=exported).json()['pronunciation']=='kept_local'
    assert client.get('/audio/pronunciation',headers=auth_headers).json()['rules']==[]


def test_pronunciation_import_rejects_unsafe_or_duplicate_rules(client,auth_headers):
    document={'format':'nexus-user-export','version':1,'libraries':[]}
    for rules in ([{'source':'A','spoken':'<speak>B</speak>'}],[{'source':'A','spoken':'One'},{'source':' A ','spoken':'Two'}]):
        response=client.post('/me/import',headers=auth_headers,json={**document,'pronunciation':{'rules':rules}})
        assert response.status_code==422
