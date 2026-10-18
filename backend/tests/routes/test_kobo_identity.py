"""Advertising or fetching a Kobo file never confirms what the device installed."""
# ruff: noqa: F811
import pytest
from app.models import ReadingProgress,Chapter,User
from app.models.ereader import KoboSyncedBook,EpubBuild
from app.models.chapter_read_receipt import ChapterReadReceipt
from app.services.chapter_document import from_text
from tests.routes.test_kobo import setup as kobo_setup,sync,books,device_state,SYNC_TOKEN  # noqa: F401
from tests.auth_helpers import bearer_headers


def confirm(client,headers,device,book_id):
    version=client.get(f"/kobo-devices/{device['id']}/books",headers=headers).json()['items'][0]
    payload=dict(expected_fingerprint=version['fingerprint'],expected_manifest_epoch=version['manifest_epoch'],
        expected_manifest_revision=version['manifest_revision'],reading_run_key=version['reading_run_key'])
    response=client.post(f"/kobo-devices/{device['id']}/books/{book_id}/confirm-version",headers=headers,json=payload)
    assert response.status_code==200,response.text
    return payload


def test_only_reviewed_current_version_can_create_inferred_points_and_new_advertisement_revokes_it(client,db,kobo_setup,auth_headers,test_user):
    device,novel=kobo_setup
    response=sync(client,device['token']);token=response.headers[SYNC_TOKEN]
    [(_,entry)]=books(response.json());book_id=entry['BookEntitlement']['Id'] if 'Id' in entry['BookEntitlement'] else db.query(KoboSyncedBook).one().entitlement_id
    row=db.query(KoboSyncedBook).one();book_id=row.entitlement_id
    download_url=entry['BookMetadata']['DownloadUrls'][0]['Url']
    assert client.get(download_url).status_code==200
    state_url=f"/kobo/{device['token']}/v1/library/{book_id}/state"
    packet=device_state(book_id,source='OEBPS/chapter-2.xhtml',content=40,overall=45)
    assert client.put(state_url,json=packet).status_code==200
    assert db.query(ReadingProgress).count()==0
    db.refresh(row);assert row.bookmark_source=='OEBPS/chapter-2.xhtml' and row.progress_review_reason=='book_version_confirmation_required'
    original=confirm(client,auth_headers,device,book_id)
    assert client.put(state_url,json=packet).status_code==200
    point=db.query(ReadingProgress).one();revision=point.revision
    assert point.current_identity_inferred and point.chapter_number==2 and db.query(ChapterReadReceipt).count()==0
    assert client.put(state_url,json=packet).status_code==200
    db.refresh(point);assert point.revision==revision
    old_file=client.get(f"/kobo-devices/{device['id']}/books/{book_id}/versions/{original['expected_fingerprint']}/file",headers=auth_headers)
    assert old_file.status_code==200 and old_file.headers['cache-control']=='private, no-store'
    chapter=db.query(Chapter).filter_by(novel_id=novel.id,chapter_number=2).one();doc=from_text('Revised source material.')
    chapter.document=doc;chapter.content=doc['plain_text'];db.commit()
    changed=sync(client,device['token'],token);assert books(changed.json())
    db.refresh(row);assert row.confirmed_fingerprint is None
    assert client.put(state_url,json=packet).status_code==200
    db.refresh(point);assert point.revision==revision and row.bookmark_source=='OEBPS/chapter-2.xhtml'
    assert client.get(download_url).status_code==409
    assert client.post(f"/kobo-devices/{device['id']}/books/{book_id}/confirm-version",headers=auth_headers,json=original).status_code==409
    preserved=client.get(f"/kobo-devices/{device['id']}/books/{book_id}/versions/{original['expected_fingerprint']}/file",headers=auth_headers)
    assert preserved.content==old_file.content and db.query(EpubBuild).count()==2


def test_confirmation_and_saved_files_are_account_owned(client,db,kobo_setup,auth_headers):
    device,novel=kobo_setup;sync(client,device['token']);row=db.query(KoboSyncedBook).one()
    other=User(username='foreign-device-user',password='unused');db.add(other);db.commit();headers=bearer_headers(other.id,db)
    assert client.get(f"/kobo-devices/{device['id']}/books",headers=headers).status_code==404
    assert client.get(f"/kobo-devices/{device['id']}/books/{row.entitlement_id}/versions/{row.fingerprint}/file",headers=headers).status_code==404


@pytest.mark.parametrize('number',[10**1000,float('inf'),float('-inf'),float('nan')])
def test_untrusted_extreme_device_percentages_are_not_inferred(client,db,kobo_setup,auth_headers,number):
    import json
    device,novel=kobo_setup;sync(client,device['token']);row=db.query(KoboSyncedBook).one()
    confirm(client,auth_headers,device,row.entitlement_id)
    packet=device_state(row.entitlement_id,source='',content=number,overall=number)
    response=client.put(f"/kobo/{device['token']}/v1/library/{row.entitlement_id}/state",
        content=json.dumps(packet),headers={'Content-Type':'application/json'})
    assert response.status_code==200,response.text
    db.refresh(row)
    assert row.content_percent is None and row.progress_percent is None
    assert row.progress_review_reason=='book_position_unknown' and db.query(ReadingProgress).count()==0
