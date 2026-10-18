from concurrent.futures import ThreadPoolExecutor,TimeoutError
from threading import Barrier,Event

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import sessionmaker
from app.db_migrations import upgrade_database
from app.models import User,Library,Novel,ReaderPreference
from app.models.reading_session import ReadingSessionDaily
from app.schemas.reading_activity import ActivityWrite,GoalWrite
from app.services import reading_activity_service as activity,reading_stats_service as stats
from tests.database.test_reading_run_migration import run_engine


def seed(engine):
    upgrade_database(engine)
    factory=sessionmaker(bind=engine)
    with factory() as db:
        user=User(username='activity-race-owner',password='unused');db.add(user);db.flush()
        library=Library(user_id=user.id,name='Private');db.add(library);db.flush()
        novel=Novel(library_id=library.id,title='Activity race');db.add(novel);db.commit()
        return factory,user.id,novel.id


@pytest.mark.parametrize('goal',[False,True])
@pytest.mark.parametrize('same_operation',[False,True])
def test_postgres_goal_and_activity_first_writes_serialize(run_engine,goal,same_operation):
    if run_engine.dialect.name!='postgresql':pytest.skip('PostgreSQL row lock qualification')
    factory,user_id,_=seed(run_engine);barrier=Barrier(2)
    scope='reading_goal:2026' if goal else 'reading_activity'
    def change(index):
        with factory() as db:
            value=(GoalWrite if goal else ActivityWrite)(expected_revision=0,operation_id='same' if same_operation else f'device-{index}',
                values={'target_readings':12} if goal else {'tracking_enabled':False})
            barrier.wait()
            try:return activity.write(db,user_id,scope,value)
            except HTTPException as error:return error.status_code
    with ThreadPoolExecutor(max_workers=2) as executor:results=list(executor.map(change,[0,1]))
    if same_operation:assert isinstance(results[0],dict) and results[0]==results[1]
    else:assert sum(isinstance(result,dict) for result in results)==1 and 409 in results
    with factory() as db:
        assert db.query(ReaderPreference).count()==1 and db.query(ReaderPreference).one().revision==1


def test_postgres_disable_owns_lock_before_late_heartbeat_can_measure(run_engine):
    if run_engine.dialect.name!='postgresql':pytest.skip('PostgreSQL row lock qualification')
    factory,user_id,novel_id=seed(run_engine)
    with factory() as owner:
        owner.add(ReaderPreference(user_id=user_id,scope='reading_activity',revision=1,values={'tracking_enabled':True}));owner.commit()
        owner.query(User).filter_by(id=user_id).with_for_update().first()
        preference=owner.query(ReaderPreference).one();preference.values={'tracking_enabled':False};preference.revision=2
        owner.flush()
        started=Event()
        def late_heartbeat():
            with factory() as device:
                # This session sees the previously committed choice, then must
                # wait behind the opt-out transaction and check it again.
                assert device.query(ReaderPreference).one().values['tracking_enabled'] is True
                started.set()
                return stats.record_reading_time(device,user_id=user_id,novel_id=novel_id,seconds=60,words=200)
        with ThreadPoolExecutor(max_workers=1) as executor:
            future=executor.submit(late_heartbeat)
            assert started.wait(5)
            try:
                with pytest.raises(TimeoutError):future.result(timeout=.1)
            finally:owner.commit()
            assert future.result(timeout=5)==0
    with factory() as db:assert db.query(ReadingSessionDaily).count()==0
