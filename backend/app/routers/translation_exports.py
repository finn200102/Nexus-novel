from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session
from app.auth.dependencies import get_current_user
from app.models.user import User
from app.schemas.translation_exports import StoryTranslationExport
from app.schemas.translation_workspace import TranslationWorkspacePage
from app.services import translation_export_service as service
from config.database import get_db

router = APIRouter(prefix='/reader', tags=['private translation exports'])
PRIVATE_HEADERS = {'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff'}


@router.get('/stories/{novel_id}/translations',response_model=TranslationWorkspacePage,response_model_exclude_unset=True)
def story_translations(novel_id: int, response: Response, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200),
                       db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    response.headers.update(PRIVATE_HEADERS)
    return service.list_variants(db, user.id, novel_id, offset, limit)


@router.post('/stories/{novel_id}/translations/epub')
def story_translated_epub(novel_id: int, value: StoryTranslationExport, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    data, language = service.export_variants(db, user.id, novel_id, value.translation_job_ids)
    return Response(data, media_type='application/epub+zip', headers={**PRIVATE_HEADERS,
        'Content-Disposition': f'attachment; filename="translated-story-{novel_id}-{language}.epub"'})
