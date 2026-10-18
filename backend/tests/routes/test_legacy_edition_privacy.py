"""The legacy edition wire is an adapter over the guarded reader picker."""
from datetime import datetime
from unittest.mock import AsyncMock
from uuid import uuid4
import pytest
from app.models.account import UserSession
from app.models.blocklist import BlocklistEntry


def group():
    def member(id,title,rating='general',description=None):
        return dict(edition_id=100+id,novel_id=id,title=title,author='Writer',description=description,
            source_url=f'https://fixture.invalid/{id}',site='royalroad',language='en',edition_kind='original',
            content_rating=rating,tags=[],genres=[],fandoms=[],created_at='2026-10-10T10:00:00Z',updated_at='2026-10-16T12:00:00Z')
    return dict(group_key=str(uuid4()),canonical_work_id=55,revision=7,title='Hidden upstream group title',reviewed=True,
        edition_count=3,editions=[member(1,'Visible'),member(2,'Explicit hidden','explicit'),member(3,'Word hidden',description='privateword')])


def test_legacy_editions_retains_exact_wire_and_filters_sibling_ids(client,db,test_user,auth_headers,monkeypatch):
    test_user.max_content_rating='general'
    db.add(BlocklistEntry(user_id=test_user.id,kind='word',value='privateword'));db.commit()
    async def fetch(path,**kwargs):
        assert not db.in_transaction()
        assert path=='/edition-groups/by-novel/1'
        return group()
    upstream=AsyncMock(side_effect=fetch)
    monkeypatch.setattr('app.routers.catalog_editions.catalog_read_service.request',upstream)
    old=AsyncMock();monkeypatch.setattr('app.routers.discovery.metadata_client.get_canonical_work',old)
    result=client.get('/discovery/novels/1/editions',headers=auth_headers)
    assert result.status_code==200,result.text
    assert result.json()=={'id':55,'title':'Visible','editions':[{'id':101,'novel_id':1,'edition_kind':'original','language':'en','created_at':'2026-10-10T10:00:00Z','updated_at':'2026-10-16T12:00:00Z'}]}
    assert result.headers['cache-control']=='private, no-store'
    old.assert_not_awaited()


@pytest.mark.parametrize('hidden_id',[2,3])
def test_legacy_hidden_seed_cannot_reveal_visible_siblings(client,db,test_user,auth_headers,monkeypatch,hidden_id):
    test_user.max_content_rating='general'
    db.add(BlocklistEntry(user_id=test_user.id,kind='word',value='privateword'));db.commit()
    monkeypatch.setattr('app.routers.catalog_editions.catalog_read_service.request',AsyncMock(return_value=group()))
    result=client.get(f'/discovery/novels/{hidden_id}/editions',headers=auth_headers)
    assert result.status_code==404,result.text
    assert 'editions' not in result.json()


@pytest.mark.parametrize('change',['signout','rules','disabled'])
def test_legacy_editions_rechecks_account_session_and_rules_after_wait(client,db,test_user,auth_headers,monkeypatch,change):
    async def fetch(*args,**kwargs):
        assert not db.in_transaction()
        if change=='signout':db.query(UserSession).filter_by(user_id=test_user.id).update({'revoked_at':datetime.now()})
        elif change=='disabled':test_user.is_disabled=True
        else:db.add(BlocklistEntry(user_id=test_user.id,kind='word',value='new rule'))
        db.commit();return group()
    monkeypatch.setattr('app.routers.catalog_editions.catalog_read_service.request',fetch)
    result=client.get('/discovery/novels/1/editions',headers=auth_headers)
    assert result.status_code=={'signout':401,'rules':409,'disabled':403}[change],result.text
    assert 'editions' not in result.json()
