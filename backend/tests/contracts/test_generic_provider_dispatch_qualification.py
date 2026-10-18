"""Generic private guide requests remain fenced across workers and late replies."""
# ruff: noqa: F811
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy.orm import sessionmaker
from app.models.base import BaseModel
from app.models.user import User
from app.models.translation import ReaderProvider, ReaderProviderRequest
from app.services import reader_provider_usage as ledger
from tests.database.test_reading_run_migration import run_engine  # noqa: F401


def seed(engine):
    BaseModel.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        owner = User(username='generic-ledger-owner', password='unused')
        db.add(owner); db.flush()
        provider = ReaderProvider(user_id=owner.id, name='Explicit guide provider', kind='openai_compatible',
            base_url='https://unused.invalid/v1', model='chosen-guide', capabilities=['guide_text'],
            input_price=1, output_price=2, budget_microusd=100000)
        db.add(provider); db.commit()
        return factory, owner.id, provider.id


def test_actual_postgres_parallel_same_step_reserves_and_dispatches_once(run_engine):
    if run_engine.dialect.name != 'postgresql': pytest.skip('Actual PostgreSQL row-lock qualification')
    factory, user_id, provider_id = seed(run_engine)
    key = str(uuid4()); barrier = Barrier(2)
    def reserve():
        with factory() as db:
            provider = db.get(ReaderProvider, provider_id)
            approved = ledger.snapshot(provider)
            barrier.wait(timeout=5)
            try:
                record = ledger.reserve_request(db, provider, 20, expected_snapshot=approved,
                    purpose='guide_extract', job_key=key, item_key='0', retry_generation=0, authorize=lambda: None)
                return record.request_key
            except ledger.ProviderRequestUnresolved:
                db.rollback(); return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: reserve(), range(2)))
    assert sum(value is not None for value in results) == 1
    with factory() as db:
        assert db.query(ReaderProviderRequest).filter_by(user_id=user_id, job_key=key).count() == 1
        assert db.get(ReaderProvider, provider_id).reserved_microusd == 20
