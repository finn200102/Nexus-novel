"""Private reading attempts and immutable journal facts."""
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint, false
from app.models.base import BaseModel
from sqlalchemy.orm import relationship


class ReadingRun(BaseModel):
    __tablename__='reading_runs'
    __table_args__=(UniqueConstraint('user_id','novel_id','ordinal',name='uq_reading_run_ordinal'),)
    continuity=relationship('ReadingContinuity')
    continuity_key=Column(String(36),ForeignKey('reading_continuities.continuity_key'),nullable=True,index=True)
    run_key=Column(String(36),nullable=False,unique=True)
    user_id=Column(Integer,ForeignKey('users.id',ondelete='CASCADE'),nullable=False,index=True)
    novel_id=Column(Integer,ForeignKey('novels.id',ondelete='CASCADE'),nullable=False,index=True)
    ordinal=Column(Integer,nullable=False)
    status=Column(String(20),nullable=False,default='active',server_default='active')
    requires_run_key=Column(Boolean,nullable=False,default=False,server_default=false())
    started_at=Column(DateTime,nullable=True)
    started_at_inferred=Column(Boolean,nullable=False,default=False,server_default=false())
    completed_at=Column(DateTime,nullable=True)
    completed_at_inferred=Column(Boolean,nullable=False,default=False,server_default=false())
    abandoned_at=Column(DateTime,nullable=True)
    abandon_reason=Column(String(500),nullable=True)
    archived_at=Column(DateTime,nullable=True)
    progress_snapshot=Column(JSON,nullable=False,default=dict,server_default='{}')


class ReadingRunEvent(BaseModel):
    __tablename__='reading_run_events'
    user_id=Column(Integer,ForeignKey('users.id',ondelete='CASCADE'),nullable=False,index=True)
    novel_id=Column(Integer,ForeignKey('novels.id',ondelete='CASCADE'),nullable=False,index=True)
    run_key=Column(String(36),ForeignKey('reading_runs.run_key',ondelete='CASCADE'),nullable=False,index=True)
    kind=Column(String(20),nullable=False)
    occurred_at=Column(DateTime,nullable=True)
    inferred=Column(Boolean,nullable=False,default=False,server_default=false())
    reason=Column(String(500),nullable=True)
