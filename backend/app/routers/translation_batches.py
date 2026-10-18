from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session
from app.auth.dependencies import get_current_user
from app.models.user import User
from app.schemas.translation_batches import TranslationBatchSelection, TranslationBatchSubmission, TranslationPermissionPatch
from app.schemas.translation_workspace import TranslationChapterPage
from app.services import translation_batch_service as service
from config.database import get_db

router=APIRouter(prefix='/reader',tags=['reviewed translation batches'])


def private(response):response.headers.update({'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'})


@router.get('/stories/{novel_id}/translation-chapters',response_model=TranslationChapterPage)
def chapters(novel_id:int,response:Response,offset:int=Query(0,ge=0),limit:int=Query(50,ge=1,le=200),db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    private(response)
    return service.chapter_list(db,user.id,novel_id,offset,limit)


@router.post('/stories/{novel_id}/translation-batch/preview')
def preview(novel_id:int,value:TranslationBatchSelection,response:Response,db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    private(response)
    return service.preview(db,user,novel_id,value)


@router.post('/stories/{novel_id}/translation-batch/jobs',status_code=202)
def queue(novel_id:int,value:TranslationBatchSubmission,response:Response,db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    private(response)
    return service.submit(db,user,novel_id,value)




@router.patch('/permissions/{novel_id}/{provider_id}/translation')
def translation_permission(novel_id:int,provider_id:int,value:TranslationPermissionPatch,response:Response,db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    private(response)
    return service.patch_translation_permission(db,user,novel_id,provider_id,value)
