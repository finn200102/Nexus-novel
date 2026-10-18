"""Mock-only external waits exercise independent committed edits and revocation."""
# ruff: noqa: F811
from unittest.mock import patch
import pytest
from sqlalchemy import update,delete
from sqlalchemy.orm import Session
from app.models import ReadingAnnotation,User
from app.models.account import UserSession
from app.models.readwise import ReadwiseConnection
from tests.routes.test_highlights_export import _story,_response,TOKEN,VERIFY,POST
from tests.routes.conftest import db,test_user,client,auth_headers  # noqa: F401


def connected(client,db,test_user,auth_headers):
    novel=_story(db,test_user)
    with patch(VERIFY,return_value=_response(204)):
        assert client.put('/export/readwise',json={'token':TOKEN},headers=auth_headers).status_code==200
    return novel.id


@pytest.mark.parametrize('change',['edit','replace','delete','version'])
def test_late_ack_never_marks_changed_annotation(client,db,test_user,auth_headers,change):
    novel_id=connected(client,db,test_user,auth_headers)
    row=db.query(ReadingAnnotation).filter_by(quote='First quote').one()
    identifier,key=row.id,row.export_key
    values={c.name:getattr(row,c.name) for c in ReadingAnnotation.__table__.columns}
    def sent(*args,**kwargs):
        assert not db.in_transaction()
        with Session(db.get_bind()) as other:
            if change=='replace':
                other.execute(delete(ReadingAnnotation).where(ReadingAnnotation.id==identifier))
                values.pop('export_key');other.add(ReadingAnnotation(**values))
            elif change=='delete':other.execute(delete(ReadingAnnotation).where(ReadingAnnotation.id==identifier))
            else:other.execute(update(ReadingAnnotation).where(ReadingAnnotation.id==identifier).values(**({'note':'Changed while sending'} if change=='edit' else {'locator_content_version':'b'*64})))
            other.commit()
        return _response(201)
    with patch(POST,side_effect=sent):
        response=client.post('/export/readwise/sync',json={'novel_id':novel_id},headers=auth_headers)
    assert response.status_code==200,response.text
    db.expire_all();current=db.get(ReadingAnnotation,identifier)
    if change=='delete':assert current is None
    else:
        assert current.exported_at is None
        if change=='replace':assert current.export_key!=key
    assert db.query(ReadingAnnotation).filter(ReadingAnnotation.quote!='First quote',ReadingAnnotation.annotation_type=='highlight',ReadingAnnotation.exported_at.is_not(None)).count()==1


@pytest.mark.parametrize('change',['session','disabled','connection'])
def test_revocation_after_send_stops_ack_and_next_batch(client,db,test_user,auth_headers,change):
    novel_id=connected(client,db,test_user,auth_headers)
    user_id=test_user.id
    def sent(*args,**kwargs):
        assert not db.in_transaction()
        with Session(db.get_bind()) as other:
            if change=='session':other.execute(update(UserSession).where(UserSession.user_id==user_id).values(revoked_at=__import__('datetime').datetime.now()))
            elif change=='disabled':other.execute(update(User).where(User.id==user_id).values(is_disabled=True))
            else:other.execute(delete(ReadwiseConnection).where(ReadwiseConnection.user_id==user_id))
            other.commit()
        return _response(201)
    with patch(POST,side_effect=sent) as outbound:
        response=client.post('/export/readwise/sync',json={'novel_id':novel_id},headers=auth_headers)
    assert response.status_code==(409 if change=='connection' else 401),response.text
    assert outbound.call_count==1
    db.rollback();assert db.query(ReadingAnnotation).filter(ReadingAnnotation.exported_at.is_not(None)).count()==0


def test_token_verification_cannot_restore_disconnected_connection(client,db,test_user,auth_headers):
    connected(client,db,test_user,auth_headers)
    user_id=test_user.id
    def verify(*args,**kwargs):
        assert not db.in_transaction()
        with Session(db.get_bind()) as other:
            other.execute(delete(ReadwiseConnection).where(ReadwiseConnection.user_id==user_id));other.commit()
        return _response(204)
    with patch(VERIFY,side_effect=verify):
        response=client.put('/export/readwise',json={'token':'different-token'},headers=auth_headers)
    assert response.status_code==409,response.text
    db.rollback();assert db.query(ReadwiseConnection).count()==0


def test_next_batch_is_rebuilt_after_note_changes(client,db,test_user,auth_headers,monkeypatch):
    from app.services import highlights_export_service as export
    novel_id=connected(client,db,test_user,auth_headers)
    identifier=db.query(ReadingAnnotation.id).filter_by(quote='Second line\nsecond paragraph').scalar()
    monkeypatch.setattr(export,'READWISE_BATCH_SIZE',1)
    def sent(*args,**kwargs):
        assert not db.in_transaction()
        with Session(db.get_bind()) as other:
            other.execute(update(ReadingAnnotation).where(ReadingAnnotation.id==identifier).values(note='Not yet reviewed for export'))
            other.commit()
        return _response(201)
    with patch(POST,side_effect=sent) as outbound:
        response=client.post('/export/readwise/sync',json={'novel_id':novel_id},headers=auth_headers)
    assert response.json()=={'exported':1}
    assert outbound.call_count==1
    db.expire_all();assert db.get(ReadingAnnotation,identifier).exported_at is None


def test_revoked_verification_cannot_connect_token(client,db,test_user,auth_headers):
    user_id=test_user.id
    def verify(*args,**kwargs):
        assert not db.in_transaction()
        with Session(db.get_bind()) as other:
            other.execute(update(UserSession).where(UserSession.user_id==user_id).values(revoked_at=__import__('datetime').datetime.now()))
            other.commit()
        return _response(204)
    with patch(VERIFY,side_effect=verify):
        response=client.put('/export/readwise',json={'token':TOKEN},headers=auth_headers)
    assert response.status_code==401,response.text
    db.rollback();assert db.query(ReadwiseConnection).count()==0
