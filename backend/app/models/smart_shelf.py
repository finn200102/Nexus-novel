"""Private query definitions; evaluated membership is never persisted/shared."""
from uuid import uuid4
import secrets
from sqlalchemy import Column, ForeignKey, Integer, JSON, String, UniqueConstraint
from app.models.base import BaseModel


class SmartShelf(BaseModel):
    __tablename__ = 'smart_shelves'
    __table_args__ = (UniqueConstraint('user_id', 'name_key', name='uq_smart_shelf_user_name'),)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    identity_key = Column(String(36), nullable=False, unique=True, default=lambda: str(uuid4()))
    name = Column(String(120), nullable=False)
    name_key = Column(String(360), nullable=False)
    definition = Column(JSON, nullable=False)
    bindings = Column(JSON, nullable=False, default=dict)
    revision = Column(String(64), nullable=False, default=lambda: secrets.token_hex(32))
