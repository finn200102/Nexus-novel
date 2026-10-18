"""A second provider call occurs only after an explicit reviewed-draft request."""
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import Field
from sqlalchemy.orm import Session
from config.database import get_db
from app.auth.dependencies import get_current_user
from app.models.chapter import Chapter
from app.models.user import User
from app.routers.passage_translation import PassageTranslationInput
from app.routers.reader_tools import own_novel, own_provider
from app.services import processing_permissions
from app.services.passage_revision_service import revise_selected_passage

router = APIRouter(prefix="/reader", tags=["reader tools"])


class PassageRevisionInput(PassageTranslationInput):
    draft: str = Field(min_length=1, max_length=6_000)


@router.post("/translations/{novel_id}/{chapter_number}/passage-revision")
def passage_revision(novel_id: int, chapter_number: int, value: PassageRevisionInput, response: Response,
                     db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    response.headers["Cache-Control"] = "private, no-store"
    novel = own_novel(db, user, novel_id)
    chapter = db.query(Chapter).filter_by(novel_id=novel_id, chapter_number=chapter_number).first()
    if not chapter or not chapter.content:
        raise HTTPException(409, detail="Download this chapter before revising a passage translation.")
    provider = own_provider(db, user, value.provider_id)
    try:
        processing_permissions.check(db, user.id, novel, provider, "translation",
            consent=value.external_consent, ao3_consent=value.ao3_consent)
        return revise_selected_passage(db, user, novel, chapter, provider, value)
    except PermissionError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, detail="Revision provider unavailable; no alternative provider was used.") from exc
