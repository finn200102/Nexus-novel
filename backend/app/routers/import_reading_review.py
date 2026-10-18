"""Owner-only review of imported reading references; no source/provider access."""
from fastapi import APIRouter,Depends,Query,Response
from sqlalchemy.orm import Session
from config.database import get_db
from app.auth.dependencies import get_current_user
from app.models import Library,Novel,User
from app.models.import_reading_review import ImportReadingReview
from app.schemas.import_reading_review import ImportReadingReviewView,ImportReadingReviewPage,ImportReadingPreview,ImportReadingPreviewInput,ImportReadingApplyInput,ImportReadingApplied,ImportReadingChapterPage
from app.services import import_reading_review_service as service

router=APIRouter(prefix='/me/import-reading-reviews',tags=['user data'])


def private(response:Response):response.headers['Cache-Control']='private, no-store'


@router.get('',response_model=ImportReadingReviewPage)
def list_reviews(response:Response,offset:int=Query(0,ge=0),limit:int=Query(20,ge=1,le=50),db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    private(response)
    query=db.query(ImportReadingReview).join(Novel,Novel.id==ImportReadingReview.novel_id).join(Library,Library.id==Novel.library_id).filter(ImportReadingReview.user_id==user.id,Library.user_id==user.id)
    return dict(items=[service.view(db,row,0,1) for row in query.order_by(ImportReadingReview.id.desc()).offset(offset).limit(limit)],total=query.count(),offset=offset,limit=limit)


@router.get('/{review_id}',response_model=ImportReadingReviewView)
def get_review(review_id:int,response:Response,offset:int=Query(0,ge=0),limit:int=Query(50,ge=1,le=100),db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    private(response);return service.view(db,service.owned(db,user,review_id),offset,limit)


@router.post('/{review_id}/preview',response_model=ImportReadingPreview)
def preview(review_id:int,body:ImportReadingPreviewInput,response:Response,db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    private(response);return service.preview(db,user,service.owned(db,user,review_id),body)


@router.post('/{review_id}/apply',response_model=ImportReadingApplied)
def apply(review_id:int,body:ImportReadingApplyInput,response:Response,db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    private(response);return service.apply(db,user,service.owned(db,user,review_id),body)


@router.get('/{review_id}/chapters',response_model=ImportReadingChapterPage)
def chapter_choices(review_id:int,response:Response,q:str=Query('',max_length=200),offset:int=Query(0,ge=0),limit:int=Query(50,ge=1,le=100),db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    private(response);row=service.owned(db,user,review_id)
    from app.models import Chapter
    from sqlalchemy import or_
    query=db.query(Chapter).execution_options(include_archived_chapters=True).filter_by(novel_id=row.novel_id)
    if q.strip():
        literal=q.strip().replace('\\','\\\\').replace('%','\\%').replace('_','\\_')
        clauses=[Chapter.title.ilike(f'%{literal}%',escape='\\')]
        try:
            number=int(q)
            if -(2**31)<=number<=2**31-1:clauses.append(Chapter.chapter_number==number)
        except ValueError:pass
        query=query.filter(or_(*clauses))
    return dict(items=[dict(chapter_key=chapter.chapter_key,chapter_number=chapter.chapter_number,title=chapter.title,source_version=service.identities.source_version(chapter),archived=chapter.archived,evidence=[]) for chapter in query.order_by(Chapter.chapter_number,Chapter.id).offset(offset).limit(limit)],total=query.count(),offset=offset,limit=limit)
