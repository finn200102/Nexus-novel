from copy import deepcopy

from app.models.saved_search import SavedSearch
from app.models.user import User
from app.services.saved_search_service import imported, decode
from tests.auth_helpers import bearer_headers


DEFINITION = {'version':1,'scope':'catalog','q':'dragon & moon','site':'fanfiction','similar_to':912,
    'filters':{'tag':['Adventure'],'excludeFandom':['No spoilers'],'crossover':'true','minWordCount':'10000','sortBy':'favorites','sortOrder':'desc'}}


def test_full_query_roundtrip_edit_revision_and_duplicate_name(client, db, test_user, auth_headers):
    response=client.post('/saved-searches',headers=auth_headers,json={'name':'  Evening reading  ','definition':DEFINITION})
    assert response.status_code==201, response.text
    row=response.json()
    assert response.headers['cache-control']=='private, no-store'
    assert row['name']=='Evening reading' and not row['needs_review']
    assert row['definition']['q']=='dragon & moon' and row['definition']['site']=='fanfiction'
    assert row['definition']['similar_to']==912 and row['filters']['sortBy']=='favorites'
    assert db.get(SavedSearch,row['id']).filters['q']=='dragon & moon'
    assert client.get('/saved-searches',headers=auth_headers).json()==[row]
    duplicate=client.post('/saved-searches',headers=auth_headers,json={'name':row['name'],'definition':DEFINITION})
    assert duplicate.status_code==409 and duplicate.json()['detail']['code']=='saved_search_name_taken'
    edited=deepcopy(row['definition']); edited['q']='new query'; edited['site']='royalroad'
    update=client.put(f"/saved-searches/{row['id']}",headers=auth_headers,json={'name':'Revised','definition':edited,'expected_revision':row['revision']})
    assert update.status_code==200, update.text
    newer=update.json(); assert newer['revision']!=row['revision'] and newer['definition']==edited
    stale=client.put(f"/saved-searches/{row['id']}",headers=auth_headers,json={'name':'Stale','definition':DEFINITION,'expected_revision':row['revision']})
    assert stale.status_code==409 and stale.json()['detail']['code']=='saved_search_changed'
    assert client.delete(f"/saved-searches/{row['id']}",headers=auth_headers,params={'expected_revision':row['revision']}).status_code==409
    assert client.delete(f"/saved-searches/{row['id']}",headers=auth_headers,params={'expected_revision':newer['revision']}).status_code==200


def test_unsupported_filters_and_whitespace_names_rejected(client, auth_headers):
    for name, definition in [('   ',DEFINITION),('Unknown',{**DEFINITION,'filters':{'unknownFutureCriterion':'strict'}}),
                              ('Range',{**DEFINITION,'filters':{'minWordCount':'20','maxWordCount':'10'}}),
                              ('Negative',{**DEFINITION,'filters':{'minFavorites':'-1'}}),
                              ('Too many days',{**DEFINITION,'filters':{'updatedSinceDays':'3651'}})]:
        response=client.post('/saved-searches',headers=auth_headers,json={'name':name,'definition':definition})
        assert response.status_code==422,response.text
    for version in (True,1.0,3):
        assert client.post('/saved-searches',headers=auth_headers,json={'name':'Version','definition':{**DEFINITION,'version':version}}).status_code==422


def test_canonical_saved_query_versioning_and_portable_review(client, db, test_user, auth_headers):
    from uuid import uuid4
    from app.schemas.saved_search import SavedSearchDefinition
    term = str(uuid4())
    legacy = SavedSearchDefinition.model_validate(DEFINITION).model_dump(mode='json')
    assert 'canonical_include' not in legacy and 'canonical_exclude' not in legacy
    assert client.post('/saved-searches', headers=auth_headers, json={'name':'Invalid legacy',
        'definition':{**DEFINITION, 'canonical_include':[term]}}).status_code == 422
    definition = {**DEFINITION, 'version':2, 'canonical_include':[term.upper(), term]}
    response = client.post('/saved-searches', headers=auth_headers, json={'name':'Reviewed vocabulary', 'definition':definition})
    assert response.status_code == 201, response.text
    assert response.json()['definition']['canonical_include'] == [term]
    assert not response.json()['needs_review']
    conflicting = {**definition, 'canonical_exclude':[term]}
    assert client.post('/saved-searches', headers=auth_headers, json={'name':'Contradiction', 'definition':conflicting}).status_code == 422
    portable = imported(definition)
    assert portable['unresolved_similarity']['previous_catalog_id'] == 912
    assert portable['unresolved_canonical']['canonical_include'] == [term.upper(), term]
    assert 'canonical_include' not in portable
    decoded, review, warnings = decode(portable)
    assert review and len(warnings) == 2
    assert decoded.canonical_include == [] and decoded.similar_to is None
    assert decoded.q == DEFINITION['q'] and decoded.filters.tag == ['Adventure']
    assert imported(portable) == portable
    document = {'format':'nexus-user-export', 'version':1, 'libraries':[],
        'saved_searches':[{'name':'Imported vocabulary', 'filters':definition, 'notify_on_match':True}]}
    result = client.post('/me/import', headers=auth_headers, json=document)
    assert result.status_code == 200, result.text
    row = next(row for row in client.get('/saved-searches', headers=auth_headers).json() if row['name']=='Imported vocabulary')
    assert row['needs_review'] and row['alert_state'] == 'paused'
    retained = db.get(SavedSearch, row['id']).filters
    assert retained['unresolved_canonical'] == portable['unresolved_canonical']
    again = client.post('/me/import', headers=auth_headers, json=document)
    assert again.json()['saved_searches'] == [{'name':'Imported vocabulary','status':'unchanged'}]


def test_owner_isolation_and_legacy_search_review(client, db, test_user, auth_headers):
    stranger=User(username='other-search-owner',password='hashed'); db.add(stranger); db.flush()
    foreign=SavedSearch(user_id=stranger.id,name='Private',filters=DEFINITION)
    legacy=SavedSearch(user_id=test_user.id,name='Legacy',filters={'tags':['Time loop']},notify_on_match=True)
    unsupported=SavedSearch(user_id=test_user.id,name='Unknown',filters={'alien_filter':'must match'})
    db.add_all([foreign,legacy,unsupported]); db.commit()
    values=client.get('/saved-searches',headers=auth_headers).json()
    assert {row['name'] for row in values}=={'Legacy','Unknown'}
    row=next(row for row in values if row['name']=='Legacy')
    assert row['needs_review'] and row['definition']['filters']['tag']==['Time loop']
    assert row['alert_state']=='paused' and row['warnings']
    assert next(row for row in values if row['name']=='Unknown')['definition'] is None
    assert client.delete(f'/saved-searches/{foreign.id}',headers=auth_headers).status_code==404
    assert client.put(f'/saved-searches/{foreign.id}',headers=auth_headers,json={'name':'Steal','definition':DEFINITION,'expected_revision':'a'*64}).status_code==404
    assert len(client.get('/saved-searches',headers=bearer_headers(stranger.id,db)).json())==1


def test_portable_similarity_is_not_reinterpreted_as_another_instances_id(client, db, test_user, auth_headers):
    document={'format':'nexus-user-export','version':1,'libraries':[],
        'saved_searches':[{'name':'Portable seed','filters':DEFINITION,'notify_on_match':True}]}
    first=client.post('/me/import',headers=auth_headers,json=document)
    assert first.status_code==200, first.text
    row=client.get('/saved-searches',headers=auth_headers).json()[0]
    assert row['definition']['similar_to'] is None and row['needs_review'] and row['alert_state']=='paused'
    assert row['definition']['q']=='dragon & moon' and row['definition']['filters']['tag']==['Adventure']
    retained=db.query(SavedSearch).filter_by(user_id=test_user.id).one().filters
    assert retained['q']=='dragon & moon' and retained['site']=='fanfiction'
    assert retained['unresolved_similarity']['previous_catalog_id']==912 and 'similar_to' not in retained
    second=client.post('/me/import',headers=auth_headers,json=document)
    assert second.json()['saved_searches']==[{'name':'Portable seed','status':'unchanged'}]
    assert imported(retained)==retained and decode(retained)[1]
