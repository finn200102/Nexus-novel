"""Account-fenced catalog query preparation and atomic matching checkpoints.

No transaction is held across a metadata request. A watch becomes active only
once every member of its immutable baseline snapshot has a durable receipt.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import secrets
from uuid import uuid4, UUID
from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session
from app.models.catalog_watch import CatalogWatch, CatalogWatchSeen, CatalogMatch
from app.models.saved_search import SavedSearch
from app.models.update_event import NovelUpdateEvent
from app.models.user import User
from app.services.saved_search_service import decode, revision as search_revision
from app.services.blocklist_service import merged_exclusions, blocked_values, item_is_blocked
from app.services.content_limit_service import item_allowed

SEMANTICS = [
    'Results use the complete saved catalog query and your current hidden-content rules.',
    'Activation records existing matches without notifying you. Later newly matching stories are reported once per story.',
    'Alerts inspect the local catalog only; they do not crawl sources, import stories or call paid providers.',
    'Changes to the saved query or your content rules require preparation and activation again.',
    'Hybrid text ranking considers up to 300 candidates per retrieval channel (up to 1,200 combined); similar-story queries retain the 500-story pool.',
]


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def fail(code, message, status=409):
    raise HTTPException(status, detail={'code': code, 'message': message})


def work_key_valid(value):
    if not isinstance(value,str) or len(value) not in (32,36):return False
    try:UUID(value)
    except ValueError:return False
    return True


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def visibility(db, user):
    return merged_exclusions(db, user)


def permission_key(db, user):
    return fingerprint(visibility(db, user))


def owned(db, user_id, search_id, *, lock=False):
    user_query = db.query(User).filter_by(id=user_id)
    user = (user_query.with_for_update() if lock else user_query).populate_existing().first()
    if user is None or user.is_disabled: fail('account_unavailable', 'Account is unavailable', 403)
    if lock: db.expire_all()
    query = db.query(SavedSearch).filter_by(id=search_id, user_id=user_id)
    search = (query.with_for_update() if lock else query).first()
    if search is None: fail('saved_search_not_found', 'Saved search not found', 404)
    if not search.identity_key:
        search.identity_key = str(uuid4())
        db.flush()
    return user, search


def get_watch(db, user_id, search_id, *, lock=False):
    query = db.query(CatalogWatch).filter_by(user_id=user_id, search_id=search_id)
    return (query.with_for_update() if lock else query).first()


def invalidate(db, watch, reason):
    watch.status = 'paused'
    watch.reason = reason
    watch.prepared = {}
    watch.baseline = None
    watch.lease_owner = None
    watch.lease_expires_at = None
    watch.revision = secrets.token_hex(32)


def valid(db, user, search, watch):
    return (watch.account_key == user.storage_id and watch.search_key == search.identity_key
        and watch.search_revision == search_revision(search)
        and watch.permission_fingerprint == permission_key(db, user))


def invalidate_search(db, user_id, search_id):
    watch = get_watch(db, user_id, search_id, lock=True)
    if watch: invalidate(db, watch, 'saved_search_changed')


def iter_permitted(db, user, rows):
    blocked = blocked_values(db, user)
    for row in rows:
        if item_allowed(user,row.novel) and not item_is_blocked(row.novel,blocked):yield row


def permitted(db,user,rows):
    return list(iter_permitted(db,user,rows))


def state(db, user_id, search_id):
    user, search = owned(db, user_id, search_id, lock=True)
    watch = get_watch(db, user_id, search_id, lock=True)
    definition, review, warnings = decode(search.filters)
    watch_valid=bool(watch and valid(db,user,search,watch))
    if watch and not watch_valid:
        invalidate(db, watch, 'query_or_permissions_changed')
    match_count=unread_count=0
    if watch_valid:
        rows=db.query(CatalogMatch).filter_by(user_id=user_id,watch_id=watch.id).order_by(CatalogMatch.id).yield_per(100)
        for match in iter_permitted(db,user,rows):
            match_count+=1
            unread_count+=int(match.read_at is None)
    result = dict(search_id=search_id, search_revision=search_revision(search), revision=watch.revision if watch else None,
        status=watch.status if watch else 'off', mode=watch.mode if watch else None,
        prepared_revision=watch.prepared_revision if watch and watch.prepared and not review else None,
        baseline_total=watch.baseline_total if watch else None,
        match_count=match_count, unread_count=unread_count,
        last_checked_at=watch.last_checked_at if watch else None, reason=watch.reason if watch else None,
        warnings=warnings, semantics=SEMANTICS + (['Lexical mode uses catalog text matching without embedding models.'] if watch and watch.mode == 'lexical' else ['Hybrid query preparation may run the configured local embedding model.']))
    db.commit()
    return result


def snapshot(db, user_id, search_id, expected_revision=None, *, need_watch=False):
    user, search = owned(db, user_id, search_id, lock=True)
    if expected_revision is not None and expected_revision != search_revision(search):
        fail('saved_search_changed', 'This saved search changed. Refresh before continuing.')
    definition, review, _ = decode(search.filters)
    if review or definition is None: fail('saved_search_review_required', 'Review and save the complete query in Discover first.')
    watch = get_watch(db, user_id, search_id, lock=True)
    if need_watch and (not watch or not watch.prepared or not valid(db, user, search, watch)):
        if watch:
            invalidate(db, watch, 'query_or_permissions_changed')
            db.commit()
        fail('catalog_watch_prepare_required', 'Prepare and review this query before continuing.')
    proof = dict(account_key=user.storage_id, search_key=search.identity_key,
        search_revision=search_revision(search), permission_fingerprint=permission_key(db, user),
        watch_revision=watch.revision if watch else None)
    result = dict(proof=proof, definition=definition.model_dump(mode='json'), visibility=visibility(db, user),
        prepared=dict(watch.prepared) if watch else None, prepared_revision=watch.prepared_revision if watch else None,
        epoch=watch.epoch if watch else None)
    db.commit()
    return result


def revalidate(db, user_id, search_id, proof):
    user, search = owned(db, user_id, search_id, lock=True)
    watch = get_watch(db, user_id, search_id, lock=True)
    current = dict(account_key=user.storage_id, search_key=search.identity_key,
        search_revision=search_revision(search), permission_fingerprint=permission_key(db, user),
        watch_revision=watch.revision if watch else None)
    if current != proof: fail('catalog_watch_changed', 'The query, account rules or alert changed. Refresh before continuing.')
    return user, search, watch


def save_prepared(db, user_id, search_id, proof, mode, remote):
    user, search, watch = revalidate(db, user_id, search_id, proof)
    prepared, epoch = remote.get('prepared'), remote.get('epoch')
    if not isinstance(prepared, dict) or not isinstance(epoch, str) or len(epoch) > 36:
        fail('catalog_query_unavailable', 'The catalog returned an invalid query snapshot.', 503)
    if watch:
        # Delete via a scoped subquery, without loading every stored result's
        # metadata into memory when replacing a long-lived watch.
        event_ids = db.query(CatalogMatch.event_id).filter_by(watch_id=watch.id,user_id=user_id)
        db.query(NovelUpdateEvent).filter(NovelUpdateEvent.id.in_(event_ids), NovelUpdateEvent.user_id == user_id).delete(synchronize_session=False)
        db.query(CatalogMatch).filter_by(watch_id=watch.id).delete(synchronize_session=False)
        db.query(CatalogWatchSeen).filter_by(watch_id=watch.id).delete(synchronize_session=False)
    else:
        watch = CatalogWatch(user_id=user_id, search_id=search_id)
        db.add(watch)
    watch.account_key = proof['account_key']; watch.search_key = proof['search_key']
    watch.search_revision = proof['search_revision']; watch.permission_fingerprint = proof['permission_fingerprint']
    watch.mode = mode; watch.prepared = prepared; watch.epoch = epoch
    watch.prepared_revision = secrets.token_hex(32); watch.revision = secrets.token_hex(32)
    watch.status = 'prepared'; watch.reason = None; watch.cursor = 0
    watch.baseline = None; watch.baseline_total = None; watch.baseline_offset = 0
    watch.lease_owner = None; watch.lease_expires_at = None; watch.last_checked_at = None
    db.commit()
    return state(db, user_id, search_id)


def add_seen(db, watch, keys):
    existing = {key for (key,) in db.query(CatalogWatchSeen.work_key).filter(CatalogWatchSeen.watch_id == watch.id, CatalogWatchSeen.work_key.in_(keys)).all()} if keys else set()
    for key in dict.fromkeys(keys):
        if key not in existing:
            db.add(CatalogWatchSeen(user_id=watch.user_id, watch_id=watch.id, work_key=key))


def apply_baseline(db, watch, data, *, first=False):
    keys = data.get('work_keys')
    if (data.get('epoch') != watch.epoch or not isinstance(keys, list) or len(keys) > 500
        or any(not work_key_valid(key) for key in keys)
        or type(data.get('through_seq')) is not int or type(data.get('total')) is not int
        or data['total'] < 0 or not isinstance(data.get('has_more'), bool)
        or not isinstance(data.get('snapshot_id'), str)):
        fail('catalog_baseline_invalid', 'The catalog baseline is invalid. Prepare this query again.')
    if len(keys)!=len(set(keys)) or keys!=sorted(keys):
        fail('catalog_baseline_invalid', 'The catalog baseline keys must be unique and ordered.')
    previous=(watch.baseline or {}).get('after_work_key')
    if not first and keys and previous is not None and keys[0]<=previous:
        fail('catalog_baseline_invalid', 'The catalog baseline did not advance past its prior page.')
    if not first and (data['snapshot_id'] != watch.baseline['snapshot_id'] or data['through_seq'] != watch.cursor or data['total'] != watch.baseline_total):
        fail('catalog_baseline_changed', 'The catalog baseline changed. Prepare this query again.')
    if data['has_more'] and (not keys or data.get('next_after_work_key') != keys[-1]):
        fail('catalog_baseline_invalid', 'The catalog baseline did not advance.')
    add_seen(db, watch, keys)
    watch.cursor = data['through_seq']; watch.baseline_total = data['total']
    watch.baseline_offset += len(keys)
    if watch.baseline_offset > watch.baseline_total or (not data['has_more'] and watch.baseline_offset != watch.baseline_total):
        fail('catalog_baseline_invalid', 'The catalog baseline is incomplete. Prepare this query again.')
    watch.baseline = {'snapshot_id': data['snapshot_id'], 'after_work_key': data.get('next_after_work_key')}
    watch.status = 'initializing' if data['has_more'] else 'active'
    watch.last_checked_at = utcnow(); watch.reason = None
    watch.next_check_at = utcnow()


def activate(db, user_id, search_id, proof, prepared_revision, data):
    user, search, watch = revalidate(db, user_id, search_id, proof)
    if not watch or not watch.prepared or watch.prepared_revision != prepared_revision:
        fail('catalog_watch_changed', 'Prepare and review the current query before activating alerts.')
    if watch.status in ('active', 'initializing'):
        db.commit(); return state(db, user_id, search_id)
    watch.baseline_offset = 0
    apply_baseline(db, watch, data, first=True)
    watch.revision = secrets.token_hex(32)
    watch.lease_owner = None; watch.lease_expires_at = None
    db.commit()
    return state(db, user_id, search_id)


def pause(db, user_id, search_id, expected_revision, watch_revision):
    user, search = owned(db, user_id, search_id, lock=True)
    watch = get_watch(db, user_id, search_id, lock=True)
    if search_revision(search) != expected_revision or not watch or watch.revision != watch_revision:
        fail('catalog_watch_changed', 'This query or alert changed. Refresh before pausing.')
    watch.status = 'paused'; watch.reason = 'paused_by_reader'
    watch.revision = secrets.token_hex(32); watch.lease_owner = None; watch.lease_expires_at = None
    db.commit()
    return state(db, user_id, search_id)


def result_page(db, user_id, search_id, proof, remote, offset, limit):
    user, search, watch = revalidate(db, user_id, search_id, proof)
    if not watch or remote.get('epoch') != watch.epoch:
        fail('catalog_epoch_changed', 'The catalog was restored or replaced. Prepare this query again.')
    from app.services.blocklist_service import apply_blocklist
    items = remote.get('items', [])
    if not isinstance(items, list) or len(items) > limit or any(not isinstance(item, dict) for item in items):
        fail('catalog_query_unavailable', 'The catalog returned invalid results.', 503)
    allowed = apply_blocklist(db, user, items)
    total = remote.get('total')
    if type(total) is not int or total < 0: fail('catalog_query_unavailable', 'The catalog returned an invalid total.', 503)
    # The same exclusions are compiled upstream before ranking and pagination;
    # a stricter local check must never expose the excluded row through counts.
    if len(allowed) != len(items):
        fail('catalog_visibility_changed', 'Catalog visibility rules changed. Prepare the query again.')
    db.commit()
    return dict(items=allowed, total=total, offset=offset, limit=limit, has_more=bool(remote.get('has_more')))


def matches(db, user_id, search_id, offset, limit):
    user, search = owned(db, user_id, search_id)
    watch = get_watch(db, user_id, search_id)
    items=[];total=0
    if watch and valid(db,user,search,watch):
        rows=db.query(CatalogMatch).filter_by(user_id=user_id,watch_id=watch.id).order_by(CatalogMatch.id.desc()).yield_per(100)
        for row in iter_permitted(db,user,rows):
            if offset<=total<offset+limit:
                items.append(dict(id=row.id,work_key=row.work_key,novel=row.novel,read_at=row.read_at,matched_at=row.created_at))
            total+=1
    result=dict(items=items,total=total,offset=offset,limit=limit,has_more=offset+limit<total)
    db.commit(); return result


def read_match(db, user_id, search_id, match_id, watch_revision):
    user, search = owned(db, user_id, search_id, lock=True)
    watch = get_watch(db, user_id, search_id, lock=True)
    if not watch or watch.revision != watch_revision or not valid(db,user,search,watch):
        fail('catalog_watch_changed', 'This alert changed. Refresh its matches.')
    row = db.query(CatalogMatch).filter_by(id=match_id, watch_id=watch.id, user_id=user_id).first()
    if not row or not permitted(db, user, [row]): fail('catalog_match_not_found', 'Match not found',404)
    if row.read_at is None: row.read_at = utcnow()
    if row.event_id:
        event = db.query(NovelUpdateEvent).filter_by(id=row.event_id,user_id=user_id).first()
        if event and event.read_at is None: event.read_at = row.read_at
    db.commit(); return {'read': True}


def event_is_deliverable(db, user, event):
    if user.is_disabled:return False
    if event.event_type != 'catalog_match': return True
    row = db.query(CatalogMatch).filter_by(user_id=user.id, event_id=event.id).first()
    if not row: return False
    watch = db.query(CatalogWatch).filter_by(id=row.watch_id,user_id=user.id).first()
    if not watch or watch.status != 'active': return False
    search = db.query(SavedSearch).filter_by(id=watch.search_id,user_id=user.id).populate_existing().first()
    return bool(search and valid(db,user,search,watch) and permitted(db,user,[row]))


def claim(db, now=None):
    now = now or utcnow()
    candidates = db.query(CatalogWatch.id).filter(CatalogWatch.status.in_(('initializing','active')),
        or_(CatalogWatch.next_check_at.is_(None),CatalogWatch.next_check_at<=now),
        or_(CatalogWatch.lease_expires_at.is_(None),CatalogWatch.lease_expires_at<=now)).order_by(CatalogWatch.id).limit(100).all()
    db.rollback()
    for (id,) in candidates:
        token = str(uuid4())
        count = db.query(CatalogWatch).filter(CatalogWatch.id==id,CatalogWatch.status.in_(('initializing','active')),
            or_(CatalogWatch.lease_expires_at.is_(None),CatalogWatch.lease_expires_at<=now),
            or_(CatalogWatch.next_check_at.is_(None),CatalogWatch.next_check_at<=now)).update(
                {'lease_owner':token,'lease_expires_at':now+timedelta(seconds=90)},synchronize_session=False)
        db.commit()
        if count: return id,token
    return None


def worker_snapshot(db, watch_id, token):
    identity=db.query(CatalogWatch.user_id).filter_by(id=watch_id).scalar()
    db.rollback()
    if identity is None:return None
    user=db.query(User).filter_by(id=identity).with_for_update().populate_existing().first()
    watch=db.query(CatalogWatch).filter_by(id=watch_id,lease_owner=token).with_for_update().populate_existing().first()
    if not watch: db.rollback(); return None
    search=db.query(SavedSearch).filter_by(id=watch.search_id,user_id=watch.user_id).populate_existing().first()
    if not user or user.is_disabled or not search or not valid(db,user,search,watch):
        invalidate(db,watch,'query_or_permissions_changed'); db.commit(); return None
    result = dict(watch_id=watch.id,user_id=user.id,account_key=user.storage_id,revision=watch.revision,
        prepared=watch.prepared,epoch=watch.epoch,cursor=watch.cursor,status=watch.status,baseline=watch.baseline)
    db.commit(); return result


def finish_worker(db, snapshot, token, data=None, *, error=None):
    user = db.query(User).filter_by(id=snapshot['user_id']).with_for_update().populate_existing().first()
    if not user or user.storage_id != snapshot['account_key']: db.rollback(); return False
    watch = db.query(CatalogWatch).filter_by(id=snapshot['watch_id'],user_id=user.id,lease_owner=token,revision=snapshot['revision']).with_for_update().populate_existing().first()
    if not watch: db.rollback(); return False
    search = db.query(SavedSearch).filter_by(id=watch.search_id,user_id=user.id).populate_existing().first()
    if user.is_disabled or not search or not valid(db,user,search,watch):
        invalidate(db,watch,'query_or_permissions_changed'); db.commit(); return False
    was_initializing = watch.status == 'initializing'
    if error:
        if error == 'review_required': invalidate(db,watch,'catalog_query_review_required')
        else:
            watch.reason = 'catalog_temporarily_unavailable'
            watch.next_check_at = utcnow()+timedelta(seconds=60)
    elif watch.status == 'initializing':
        apply_baseline(db,watch,data)
    elif watch.status == 'active':
        apply_events(db,user,search,watch,data)
    else: db.rollback(); return False
    watch.lease_owner = None; watch.lease_expires_at = None
    if not error: watch.next_check_at = utcnow()+timedelta(seconds=0 if was_initializing or data.get('has_more') else 60)
    db.commit(); return True


def apply_events(db, user, search, watch, data):
    through, scanned = data.get('through_seq'), data.get('scanned_through')
    records, deleted = data.get('matches'), data.get('deleted')
    if (data.get('epoch') != watch.epoch or type(through) is not int or type(scanned) is not int
        or not watch.cursor <= scanned <= through or not isinstance(records,list) or not isinstance(deleted,list)
        or len(records)>1200 or len(deleted)>500 or not isinstance(data.get('has_more'),bool)
        or (data['has_more'] and scanned<=watch.cursor)):
        invalidate(db,watch,'catalog_checkpoint_changed'); return
    blocked = blocked_values(db,user)
    definition,needs_review,_=decode(search.filters)
    ranked=bool(definition and not needs_review and (definition.q or definition.similar_to is not None))
    for record in records:
        key,novel,seq = record.get('work_key'),record.get('novel'),record.get('seq')
        kind=record.get('kind','change')
        # A ranked query can change solely as its recency window advances.
        # Such an observation is evaluated at the existing committed checkpoint;
        # it neither invents a catalog event nor relaxes actual event sequencing.
        sequence_valid=(watch.cursor<seq<=scanned if type(seq) is int else False)
        if kind=='ranked_observation':
            sequence_valid=ranked and type(seq) is int and watch.cursor<=seq==scanned
        elif kind!='change':
            sequence_valid=False
        if (not work_key_valid(key) or not isinstance(novel,dict) or type(seq) is not int
            or not sequence_valid or type(novel.get('id')) is not int):
            fail('catalog_event_invalid','The catalog change page is invalid.')
        if not item_allowed(user,novel) or item_is_blocked(novel,blocked): continue
        seen = db.query(CatalogWatchSeen.id).filter_by(watch_id=watch.id,work_key=key).first()
        if seen: continue
        add_seen(db,watch,[key]); db.flush()
        event = NovelUpdateEvent(user_id=user.id,novel_id=None,event_type='catalog_match',
            message='A story now matches your saved search.',details={'metadata_id':novel['id'],
                'title':str(novel.get('title') or 'Story')[:500], 'saved_search_id':search.id,
                'search_name':search.name,'work_key':key},notification_visible=True)
        db.add(event); db.flush()
        db.add(CatalogMatch(user_id=user.id,watch_id=watch.id,work_key=key,novel=novel,event_id=event.id))
    db.flush()
    for record in deleted:
        key = record.get('work_key')
        if not work_key_valid(key) or type(record.get('seq')) is not int or not watch.cursor<record['seq']<=scanned:
            fail('catalog_event_invalid','The catalog deletion page is invalid.')
        # A deleted catalog work must not remain an actionable matching alert.
        rows=db.query(CatalogMatch).filter_by(watch_id=watch.id,work_key=key).all()
        for row in rows:
            if row.event_id:
                event=db.query(NovelUpdateEvent).filter_by(id=row.event_id,user_id=user.id).first()
                if event: event.notification_visible=False
            db.delete(row)
    watch.cursor=scanned; watch.last_checked_at=utcnow(); watch.reason=None
