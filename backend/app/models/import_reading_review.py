"""Private imported reading material awaiting an explicit chapter binding."""
from sqlalchemy import Column, ForeignKey, Integer, JSON, String, UniqueConstraint
from app.models.base import BaseModel


class ImportReadingReview(BaseModel):
    __tablename__ = 'import_reading_reviews'
    __table_args__ = (UniqueConstraint('user_id','novel_id','fingerprint',name='uq_import_reading_document_story'),)
    user_id = Column(Integer,ForeignKey('users.id',ondelete='CASCADE'),nullable=False,index=True)
    novel_id = Column(Integer,ForeignKey('novels.id',ondelete='CASCADE'),nullable=False,index=True)
    fingerprint = Column(String(64),nullable=False)
    revision = Column(Integer,nullable=False,default=1)
    payload = Column(JSON,nullable=False)
    applied_refs = Column(JSON,nullable=False,default=list)
    preview = Column(JSON,nullable=True)


class ImportReadingOperation(BaseModel):
    __tablename__ = 'import_reading_operations'
    __table_args__ = (UniqueConstraint('user_id','operation_id',name='uq_import_reading_operation'),)
    user_id = Column(Integer,ForeignKey('users.id',ondelete='CASCADE'),nullable=False)
    review_id = Column(Integer,ForeignKey('import_reading_reviews.id',ondelete='CASCADE'),nullable=False)
    operation_id = Column(String(128),nullable=False)
    fingerprint = Column(String(64),nullable=False)
    response = Column(JSON,nullable=False)


# Older SQLite installations may have foreign keys disabled. ORM story/library
# deletion must still erase this private raw material and its receipts.
from sqlalchemy import event,delete,select
from app.models.novel import Novel


@event.listens_for(Novel,'before_delete')
def erase_imported_reading_before_story_delete(mapper,connection,target):
    ids=select(ImportReadingReview.id).where(ImportReadingReview.novel_id==target.id)
    connection.execute(delete(ImportReadingOperation).where(ImportReadingOperation.review_id.in_(ids)))
    connection.execute(delete(ImportReadingReview).where(ImportReadingReview.novel_id==target.id))
