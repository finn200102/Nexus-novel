from fastapi import APIRouter,Depends,Response
from sqlalchemy.orm import Session
from config.database import get_db
from app.auth.dependencies import get_current_user
from app.models.user import User
from app.schemas.library_views import LibraryViewPreviewInput,LibraryStoryPage,LibraryViewOptions
from app.services import library_view_service

router=APIRouter(prefix='/library-views',tags=['private library views'])


@router.post('/preview',response_model=LibraryStoryPage)
def preview(value:LibraryViewPreviewInput,response:Response,db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    response.headers['Cache-Control']='private, no-store'
    return library_view_service.page(db,user.id,value.definition,value.offset,value.limit)


@router.get('/options',response_model=LibraryViewOptions)
def options(response:Response,db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    response.headers['Cache-Control']='private, no-store'
    return library_view_service.options(db,user.id)
