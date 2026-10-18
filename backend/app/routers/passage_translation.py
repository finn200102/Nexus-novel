"""Explicit selected-passage previews share ordinary translation safeguards."""
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import ConfigDict, Field, StrictInt
from sqlalchemy.orm import Session
from config.database import get_db
from app.auth.dependencies import get_current_user
from app.models.chapter import Chapter
from app.models.user import User
from app.routers.reader_tools import own_novel, own_provider
from app.services import processing_permissions
from app.services.passage_translation_service import translate_selected_passage
from app.schemas.translation_identity import TranslationChapterIdentity

router = APIRouter(prefix="/reader", tags=["reader tools"])


class PassageTranslationInput(TranslationChapterIdentity):
    model_config = ConfigDict(extra="forbid")
    provider_id: StrictInt = Field(gt=0)
    language: str = Field(pattern=r"^[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})?$", max_length=20)
    content_version: str = Field(min_length=1, max_length=128)
    block_id: str = Field(min_length=1, max_length=160)
    text_offset: StrictInt = Field(ge=0)
    text_length: StrictInt = Field(gt=0, le=6_000)
    quote: str = Field(min_length=1, max_length=3_000)
    external_consent: bool = False
    ao3_consent: bool = False


@router.post("/translations/{novel_id}/{chapter_number}/passage-preview")
def passage_preview(novel_id: int, chapter_number: int, value: PassageTranslationInput, response: Response,
                    db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    response.headers["Cache-Control"] = "private, no-store"
    novel = own_novel(db, user, novel_id)
    chapter = db.query(Chapter).filter_by(novel_id=novel_id, chapter_number=chapter_number).first()
    if not chapter or not chapter.content:
        raise HTTPException(409, detail="Download this chapter before translating a passage.")
    provider = own_provider(db, user, value.provider_id)
    try:
        processing_permissions.check(db, user.id, novel, provider, "translation",
            consent=value.external_consent, ao3_consent=value.ao3_consent)
        return translate_selected_passage(db, user, novel, chapter, provider, value)
    except PermissionError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, detail="Provider unavailable; no alternative provider was used.") from exc
