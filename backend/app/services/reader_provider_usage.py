"""Private request accounting with durable dispatch and late-response fences."""
from datetime import timedelta, UTC
import hashlib
import json
from uuid import uuid4
from fastapi import HTTPException
from sqlalchemy import update
from app.models.user import User
from app.models.translation import ReaderProvider, ReaderProviderRequest, ReaderProviderReconciliationOperation
from app.services.job_lease import utcnow

REQUEST_LEASE_SECONDS = 900
UNRESOLVED = ('pending', 'unknown', 'legacy_unknown')


class ProviderRequestUnresolved(ValueError):
    """Never retry paid work automatically after an unknown or lost response."""


def snapshot(provider):
    return {key: getattr(provider, key) for key in ('kind', 'base_url', 'model')} | {
        'input_price': str(provider.input_price), 'output_price': str(provider.output_price)} | {
        'capabilities': getattr(provider, 'capabilities', None), 'image_model': getattr(provider, 'image_model', None),
        'image_price_microusd': getattr(provider, 'image_price_microusd', 0) or 0,
        'image_sizes': getattr(provider, 'image_sizes', None) or [], 'image_qualities': getattr(provider, 'image_qualities', None) or [],
        'credential_fingerprint': getattr(provider, 'credential_fingerprint', None) or hashlib.sha256((getattr(provider, 'secret_ciphertext', None) or '').encode()).hexdigest()}


def own_provider(db, user_id, provider_id):
    row = db.query(ReaderProvider).filter_by(id=provider_id, user_id=user_id).populate_existing().first()
    if row is None:
        raise HTTPException(404, 'Provider not found')
    return row


def accounting(provider):
    return {key: getattr(provider, key) for key in ('budget_microusd', 'used_microusd', 'reserved_microusd')}


def view(row):
    result = {key: getattr(row, key) for key in ('request_key', 'provider_id', 'status', 'revision', 'reserved_microusd',
        'actual_microusd', 'input_tokens', 'output_tokens', 'model_snapshot', 'translation_job_id', 'translation_block_index', 'purpose', 'job_key', 'item_key', 'retry_generation')}
    for key in ('created_at', 'expires_at', 'resolved_at'):
        value = getattr(row, key)
        result[key] = value.replace(tzinfo=UTC).isoformat().replace('+00:00', 'Z') if value is not None else None
    result['can_reconcile'] = row.status in ('unknown', 'legacy_unknown') or (
        row.status == 'pending' and row.expires_at is not None and row.expires_at <= utcnow())
    return result


def reserve_request(db, provider, reserved, *, expected_snapshot=None, translation_job_id=None, translation_block_index=None, retry_generation=None, purpose=None, job_key=None, item_key=None, authorize=None):
    db.query(User).filter_by(id=provider.user_id).with_for_update().first()
    current = own_provider(db, provider.user_id, provider.id)
    if not current.enabled:
        raise ValueError('This provider is disabled')
    if authorize is not None:
        try:
            authorize()
        except Exception:
            db.rollback()
            raise
    if purpose is not None:
        from uuid import UUID
        if purpose not in {'guide_extract', 'guide_synthesize', 'guide_portrait'} or not isinstance(job_key, str) or not isinstance(item_key, str) or not 1 <= len(item_key) <= 120 or type(retry_generation) is not int or retry_generation < 0:
            raise ValueError('Invalid private processing request identity')
        UUID(job_key)
        previous = db.query(ReaderProviderRequest).filter_by(user_id=provider.user_id, purpose=purpose,
            job_key=job_key, item_key=item_key).filter((ReaderProviderRequest.retry_generation == retry_generation) |
            ReaderProviderRequest.status.in_(UNRESOLVED)).first()
        if previous is not None:
            db.rollback()
            raise ProviderRequestUnresolved('This private guide step already has a request. Review its ledger before explicitly retrying; completed results cannot be resent automatically.')
    if translation_job_id is not None:
        previous = db.query(ReaderProviderRequest).filter_by(user_id=provider.user_id,
            translation_job_id=translation_job_id, translation_block_index=translation_block_index).filter(
            (ReaderProviderRequest.retry_generation == retry_generation) | ReaderProviderRequest.status.in_(UNRESOLVED)).first()
        if previous is not None:
            db.rollback()
            raise ProviderRequestUnresolved('This paragraph already has a paid request. Review its ledger and explicitly retry the translation before making another request.')
    values = snapshot(current)
    # The caller priced exactly this immutable snapshot. Do not substitute new
    # settings while dispatching an already reviewed request.
    if values != (expected_snapshot or snapshot(provider)):
        raise ValueError('Provider configuration changed before reservation')
    changed = db.execute(update(ReaderProvider).where(ReaderProvider.id == current.id,
        ReaderProvider.enabled.is_(True), (ReaderProvider.budget_microusd > 0) if reserved else ReaderProvider.enabled.is_(True),
        ReaderProvider.used_microusd + ReaderProvider.reserved_microusd + reserved <= ReaderProvider.budget_microusd,
    ).values(reserved_microusd=ReaderProvider.reserved_microusd + reserved).execution_options(synchronize_session=False)).rowcount
    if changed != 1:
        db.rollback()
        raise ValueError('The provider budget cannot cover this request')
    row = ReaderProviderRequest(request_key=str(uuid4()), user_id=current.user_id, provider_id=current.id,
        model_snapshot=values, status='pending', revision=0, reserved_microusd=reserved,
        expires_at=utcnow() + timedelta(seconds=REQUEST_LEASE_SECONDS), translation_job_id=translation_job_id,
        translation_block_index=translation_block_index, retry_generation=retry_generation, purpose=purpose, job_key=job_key, item_key=item_key)
    db.add(row)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(row)
    return row


def mark_unknown(db, request_key):
    db.rollback()
    db.execute(update(ReaderProviderRequest).where(ReaderProviderRequest.request_key == request_key,
        ReaderProviderRequest.status == 'pending', ReaderProviderRequest.revision == 0).values(status='unknown', revision=1)
        .execution_options(synchronize_session=False))
    db.commit()


def settle_request(db, request_key, *, charged, input_tokens, output_tokens):
    row = db.query(ReaderProviderRequest).filter_by(request_key=request_key).first()
    if row is None:
        raise ProviderRequestUnresolved('This paid request is no longer available; its response was discarded')
    db.query(User).filter_by(id=row.user_id).with_for_update().first()
    row = db.query(ReaderProviderRequest).filter_by(request_key=request_key).populate_existing().with_for_update().first()
    if row.status != 'pending' or row.revision != 0:
        db.rollback()
        raise ProviderRequestUnresolved('This paid request was already settled or reconciled; the late response was discarded')
    claimed = db.execute(update(ReaderProviderRequest).where(ReaderProviderRequest.id == row.id,
        ReaderProviderRequest.status == 'pending', ReaderProviderRequest.revision == 0).values(
        status='completed', revision=1, actual_microusd=charged, input_tokens=input_tokens,
        output_tokens=output_tokens, resolved_at=utcnow()).execution_options(synchronize_session=False)).rowcount
    if claimed != 1:
        db.rollback()
        raise ProviderRequestUnresolved('This paid request changed; the late response was discarded')
    changed = db.execute(update(ReaderProvider).where(ReaderProvider.id == row.provider_id,
        ReaderProvider.user_id == row.user_id, ReaderProvider.reserved_microusd >= row.reserved_microusd).values(
        reserved_microusd=ReaderProvider.reserved_microusd - row.reserved_microusd,
        used_microusd=ReaderProvider.used_microusd + charged).execution_options(synchronize_session=False)).rowcount
    if changed != 1:
        db.rollback()
        raise ProviderRequestUnresolved('The provider balance changed unexpectedly; review this reservation before retrying')
    db.commit()


def require_retry_review(db, job):
    outstanding = db.query(ReaderProviderRequest).filter(ReaderProviderRequest.user_id == job.user_id,
        ((ReaderProviderRequest.translation_job_id == job.id) & ReaderProviderRequest.status.in_(UNRESOLVED)) |
        ((ReaderProviderRequest.provider_id == job.provider_id) & (ReaderProviderRequest.status == 'legacy_unknown'))).first()
    if outstanding is not None:
        raise HTTPException(409, detail={'code': 'paid_request_unresolved', 'request_key': outstanding.request_key,
            'message': 'Review and reconcile outstanding paid requests before retrying this translation'})
    job.paid_retry_generation = (job.paid_retry_generation or 0) + 1


def listing(db, user_id, provider_id, offset, limit):
    db.query(User).filter_by(id=user_id).with_for_update().first()
    provider = own_provider(db, user_id, provider_id)
    query = db.query(ReaderProviderRequest).filter_by(user_id=user_id, provider_id=provider_id)
    return dict(items=[view(row) for row in query.order_by(ReaderProviderRequest.id.desc()).offset(offset).limit(limit)],
        total=query.count(), offset=offset, limit=limit, accounting=accounting(provider))


def reconcile(db, user_id, provider_id, request_key, value):
    db.query(User).filter_by(id=user_id).with_for_update().first()
    own_provider(db, user_id, provider_id)
    row = db.query(ReaderProviderRequest).filter_by(user_id=user_id, provider_id=provider_id,
        request_key=request_key).populate_existing().with_for_update().first()
    if row is None:
        raise HTTPException(404, 'Provider request not found')
    signature = hashlib.sha256(json.dumps([provider_id, request_key, value.expected_revision, value.actual_microusd]).encode()).hexdigest()
    receipt = db.query(ReaderProviderReconciliationOperation).filter_by(user_id=user_id, operation_id=value.operation_id).first()
    def conflict(code, message):
        raise HTTPException(409, detail={'code': code, 'message': message, 'current': view(row)}, headers={'Cache-Control': 'private, no-store'})
    if receipt is not None:
        if receipt.fingerprint != signature:
            conflict('operation_id_reused', 'This operation identifier was already used for another reconciliation')
        return receipt.response
    if row.revision != value.expected_revision:
        conflict('request_changed', 'This request changed; review its current state')
    if row.status not in UNRESOLVED:
        conflict('request_resolved', 'This request has already been settled')
    if not view(row)['can_reconcile']:
        conflict('request_inflight', 'This request may still be in flight; wait for its reservation lease to expire')
    claimed = db.execute(update(ReaderProviderRequest).where(ReaderProviderRequest.id == row.id,
        ReaderProviderRequest.revision == value.expected_revision, ReaderProviderRequest.status == row.status).values(
        status='reconciled', revision=ReaderProviderRequest.revision + 1,
        actual_microusd=value.actual_microusd, resolved_at=utcnow()).execution_options(synchronize_session=False)).rowcount
    if claimed != 1:
        db.rollback()
        row = db.query(ReaderProviderRequest).filter_by(id=row.id).populate_existing().first()
        conflict('request_changed', 'This request changed; review its current state')
    changed = db.execute(update(ReaderProvider).where(ReaderProvider.id == provider_id, ReaderProvider.user_id == user_id,
        ReaderProvider.reserved_microusd >= row.reserved_microusd).values(
        reserved_microusd=ReaderProvider.reserved_microusd - row.reserved_microusd,
        used_microusd=ReaderProvider.used_microusd + value.actual_microusd).execution_options(synchronize_session=False)).rowcount
    if changed != 1:
        db.rollback()
        raise HTTPException(422, 'The outstanding balance does not cover this reservation; restore consistent accounting before reconciling')
    db.refresh(row)
    provider = own_provider(db, user_id, provider_id)
    result = dict(item=view(row), accounting=accounting(provider))
    db.add(ReaderProviderReconciliationOperation(user_id=user_id, provider_id=provider_id, operation_id=value.operation_id,
        fingerprint=signature, response=result))
    db.commit()
    return result


def require_job_retry_review(db, user_id, job_key):
    row = db.query(ReaderProviderRequest).filter_by(user_id=user_id, job_key=job_key).filter(ReaderProviderRequest.status.in_(UNRESOLVED)).first()
    if row is not None:
        raise HTTPException(409, detail={"code": "paid_request_unresolved", "request_key": row.request_key,
            "message": "Review and reconcile outstanding private guide requests before explicitly retrying"})
