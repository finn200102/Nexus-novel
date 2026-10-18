"""Real PostgreSQL races and additive migration, never public-schema reset."""
import os
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from datetime import datetime,timedelta
import pytest
from sqlalchemy import create_engine,text,MetaData
from sqlalchemy.orm import sessionmaker
from alembic import command
from app.db_migrations import alembic_config
from config.database import Base
from app.models.notification_delivery import NotificationDelivery
from app.services import notification_delivery as delivery
from tests.services.test_notification_delivery import make_user,make_novel,add_channel,event


@pytest.fixture(params=['sqlite','postgres'])
def migration_engine(request,tmp_path):
    if request.param=='sqlite':
        engine=create_engine(f'sqlite:///{tmp_path}/outbox.db');yield engine;engine.dispose();return
    url=os.getenv('NEXUS_TEST_POSTGRES_URL')
    if not url:pytest.skip('Requires owned disposable PostgreSQL')
    schema='outbox_migration_'+uuid4().hex
    admin=create_engine(url)
    with admin.begin() as connection:connection.execute(text(f'CREATE SCHEMA {schema}'))
    engine=create_engine(url,connect_args={'options':f'-csearch_path={schema}'})
    try:yield engine
    finally:
        engine.dispose()
        with admin.begin() as connection:connection.execute(text(f'DROP SCHEMA IF EXISTS {schema} CASCADE'))
        admin.dispose()


def test_0049_preserves_legacy_claims_and_destinations(migration_engine):
    with migration_engine.begin() as connection:command.upgrade(alembic_config(connection),'0048')
    old=MetaData();old.reflect(migration_engine)
    with migration_engine.begin() as connection:
        uid=connection.execute(old.tables['users'].insert().values(username='migration-reader',password='unused',storage_id=str(uuid4()))).inserted_primary_key[0]
        connection.execute(old.tables['push_subscriptions'].insert().values(user_id=uid,endpoint='https://fixture.invalid/push',p256dh='key',auth='auth'))
        connection.execute(old.tables['notification_channels'].insert().values(user_id=uid,url_encrypted='opaque-fixture',label='Original',enabled=False))
        for claimed in (None,datetime(2020,1,1)):
            connection.execute(old.tables['novel_update_events'].insert().values(user_id=uid,novel_id=None,event_type='author_new_work',message='Original',details={},notified_at=claimed))
    with migration_engine.begin() as connection:command.upgrade(alembic_config(connection),'0049')
    new=MetaData();new.reflect(migration_engine)
    with migration_engine.connect() as connection:
        for name in ('push_subscriptions','notification_channels'):
            target=connection.execute(new.tables[name].select()).mappings().one()
            assert len(target['delivery_key'])==36 and target['eligibility_event_id']==0
        assert connection.execute(new.tables['notification_deliveries'].select()).all()==[]
        dates=connection.execute(new.tables['novel_update_events'].select().order_by(new.tables['novel_update_events'].c.id)).mappings().all()
        assert dates[0]['notified_at'] is None and dates[1]['notified_at']==datetime(2020,1,1)
    with migration_engine.begin() as connection:command.downgrade(alembic_config(connection),'0048')
    restored=MetaData();restored.reflect(migration_engine)
    assert 'notification_deliveries' not in restored.tables and 'delivery_key' not in restored.tables['push_subscriptions'].c


def test_postgres_overlapping_snapshot_claim_and_dispatch_never_double_send(monkeypatch):
    url=os.getenv('NEXUS_TEST_POSTGRES_URL')
    if not url:pytest.skip('Requires owned disposable PostgreSQL')
    schema='outbox_races_'+uuid4().hex;admin=create_engine(url);engine=None
    try:
        with admin.begin() as connection:connection.execute(text(f'CREATE SCHEMA {schema}'))
        engine=create_engine(url,connect_args={'options':f'-csearch_path={schema}'})
        Base.metadata.create_all(engine);sessions=sessionmaker(bind=engine)
        # This qualifies concurrent claims, not agreement between the host and
        # Docker VM wall clocks. Freeze due/lease time and explicitly establish
        # that the fixture event follows destination registration.
        now=datetime(2026,1,1,12)
        monkeypatch.setattr(delivery,'_now',lambda:now)
        with sessions() as db:
            user=make_user(db);novel=make_novel(db,user)
            target=add_channel(db,user);source=event(db,user,novel)
            target.created_at=now-timedelta(seconds=2)
            source.created_at=now-timedelta(seconds=1)
            db.commit()
            assert source.created_at>target.created_at
        def race(function):
            barrier=Barrier(2)
            def one():
                with sessions() as db:
                    barrier.wait(timeout=5)
                    return function(db)
            with ThreadPoolExecutor(max_workers=2) as pool:return list(pool.map(lambda _:one(),range(2)))
        snapshots=race(delivery.snapshot_due_notifications)
        assert sorted(result[0] for result in snapshots)==[0,1]
        claims=race(delivery.claim_delivery)
        assert sum(claim is not None for claim in claims)==1
        claim=next(value for value in claims if value)
        calls=[];monkeypatch.setattr(delivery,'send_apprise',lambda *args:calls.append(args) or True)
        race(lambda db:delivery.process_delivery(db,*claim))
        assert len(calls)==1
        with sessions() as db:
            row=db.query(NotificationDelivery).one()
            assert row.status=='succeeded' and row.attempt_count==1
    finally:
        if engine is not None:engine.dispose()
        with admin.begin() as connection:connection.execute(text(f'DROP SCHEMA IF EXISTS {schema} CASCADE'))
        admin.dispose()
