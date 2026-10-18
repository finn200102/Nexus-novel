"""Opaque portable story references, with destination lifecycle fences."""
from sqlalchemy import Column,ForeignKey,Integer,JSON,String,UniqueConstraint,event,delete,update,select,case
from app.models.base import BaseModel
from app.models.novel import Novel
from app.models.library import Library


class PortableStoryLink(BaseModel):
    __tablename__='portable_story_links'
    __table_args__=(UniqueConstraint('user_id','library_id','source_account_key','source_story_epoch',name='uq_portable_story_origin_destination'),)
    user_id=Column(Integer,ForeignKey('users.id',ondelete='CASCADE'),nullable=False,index=True)
    library_id=Column(Integer,ForeignKey('libraries.id',ondelete='CASCADE'),nullable=False,index=True)
    destination_account_key=Column(String(36),nullable=False)
    destination_library_key=Column(String(36),nullable=False)
    source_account_key=Column(String(36),nullable=False)
    source_story_epoch=Column(String(36),nullable=False)
    novel_id=Column(Integer,ForeignKey('novels.id',ondelete='SET NULL'),nullable=True,index=True)
    target_story_epoch=Column(String(36),nullable=False)
    # Empty on normal links/deletion; a later explicit import can retain its
    # newly supplied material here when the old destination no longer exists.
    pending_payload=Column(JSON,nullable=True)


@event.listens_for(Novel,'before_delete')
def keep_portable_identity_tombstone(mapper,connection,target):
    owner=connection.execute(select(Library.user_id).where(Library.id==target.library_id)).scalar()
    connection.execute(update(PortableStoryLink).where(PortableStoryLink.novel_id==target.id).values(novel_id=None,pending_payload=case((PortableStoryLink.user_id==owner,None),else_=PortableStoryLink.pending_payload)))


@event.listens_for(Library,'before_delete')
def erase_portable_links_with_library(mapper,connection,target):
    connection.execute(delete(PortableStoryLink).where(PortableStoryLink.library_id==target.id))
