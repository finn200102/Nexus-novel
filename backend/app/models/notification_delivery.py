"""Durable private notification attempts; destinations keep their secrets."""
from sqlalchemy import Column,String,Integer,DateTime,JSON,ForeignKey,Index
from app.models.base import BaseModel


class NotificationDelivery(BaseModel):
    __tablename__='notification_deliveries'
    __table_args__=(Index('ix_notification_deliveries_due','status','next_attempt_at','lease_expires_at'),)
    user_id=Column(Integer,ForeignKey('users.id',ondelete='CASCADE'),nullable=False,index=True)
    account_key=Column(String(36),nullable=False)
    delivery_key=Column(String(36),nullable=False,unique=True)
    destination_kind=Column(String(16),nullable=False)
    destination_id=Column(Integer,nullable=False)
    destination_fingerprint=Column(String(64),nullable=False)
    payload=Column(JSON,nullable=False)
    event_ids=Column(JSON,nullable=False)
    status=Column(String(24),nullable=False,default='queued',server_default='queued')
    attempt_count=Column(Integer,nullable=False,default=0,server_default='0')
    next_attempt_at=Column(DateTime,nullable=True)
    lease_owner=Column(String(36),nullable=True)
    lease_expires_at=Column(DateTime,nullable=True)
    finished_at=Column(DateTime,nullable=True)
    last_error_code=Column(String(64),nullable=True)
