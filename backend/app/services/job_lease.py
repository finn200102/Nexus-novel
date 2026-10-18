"""Atomic ownership and recovery shared by chapter download and audio jobs."""
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from threading import Event, Thread
from uuid import uuid4

from sqlalchemy import func, or_, update

LEASE_SECONDS = 900


def utcnow():
    return datetime.now(UTC).replace(tzinfo=None)


def claim(db, model, job_id, *, worker_id=None):
    now = utcnow()
    owner = worker_id or str(uuid4())
    values = dict(
        status="processing", lease_owner=owner,
        lease_expires_at=now + timedelta(seconds=LEASE_SECONDS),
        attempt_count=model.attempt_count + 1,
        started_at=func.coalesce(model.started_at, now),
        next_attempt_at=None, error=None, error_code=None,
    )
    if hasattr(model, "last_attempt_at"):
        values["last_attempt_at"] = now
    result = db.execute(update(model).where(
        model.id == job_id, model.status.in_(("queued", "retry_wait")),
        or_(model.next_attempt_at.is_(None), model.next_attempt_at <= now),
    ).values(**values).execution_options(synchronize_session=False))
    db.commit()
    if result.rowcount != 1:
        return None
    db.expire_all()
    return db.get(model, job_id)


def recover_expired(db, model):
    now = utcnow()
    expired = or_(
        model.lease_expires_at <= now,
        model.lease_expires_at.is_(None) & or_(
            model.started_at.is_(None), model.started_at <= now - timedelta(seconds=LEASE_SECONDS),
        ),
    )
    predicate = (model.status == "processing") & expired
    # One statement per outcome avoids read/modify/write races between workers.
    failed = db.execute(update(model).where(predicate, model.attempt_count >= model.max_attempts).values(
        status="failed", finished_at=now, lease_owner=None, lease_expires_at=None,
        error_code="WORKER_LEASE_EXPIRED", error="Worker stopped before finishing the job",
    ).execution_options(synchronize_session=False)).rowcount
    retried = db.execute(update(model).where(predicate, model.attempt_count < model.max_attempts).values(
        status="retry_wait", next_attempt_at=now, lease_owner=None, lease_expires_at=None,
        error_code="WORKER_LEASE_EXPIRED", error="Interrupted job recovered; retry scheduled",
    ).execution_options(synchronize_session=False)).rowcount
    db.commit()
    db.expire_all()
    return failed + retried


@contextmanager
def heartbeat(session_factory, model, job_id, owner):
    stop = Event()

    def renew():
        while not stop.wait(30):
            with session_factory() as db:
                try:
                    result = db.execute(update(model).where(
                        model.id == job_id, model.status == "processing", model.lease_owner == owner,
                    ).values(lease_expires_at=utcnow() + timedelta(seconds=LEASE_SECONDS)))
                    db.commit()
                    if not result.rowcount:
                        return
                except Exception:
                    db.rollback()

    thread = Thread(target=renew, daemon=True, name=f"nexus-job-{job_id}")
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=1)
