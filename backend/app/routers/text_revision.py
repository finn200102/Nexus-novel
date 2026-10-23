"""Local chapter editing is an explicit preview, never a source write."""
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session
from config.database import get_db
from app.auth.dependencies import get_current_user
from app.models.chapter import Chapter
from app.models.user import User
from app.routers.reader_tools import own_novel, own_provider
from app.schemas.text_revision import (TextRevisionInput, StoryTextStyleWrite,
    StoryTextStyleResponse, LocalTextModelDefaultsResponse, TextRevisionPreviewResponse)
from app.services.text_revision_service import preview_revision, read_style

router = APIRouter(prefix="/reader", tags=["reader tools"])


@router.post("/text-revisions/{novel_id}/{chapter_number}/preview", response_model=TextRevisionPreviewResponse)
def text_revision_preview(novel_id: int, chapter_number: int, value: TextRevisionInput, response: Response,
                          db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    response.headers["Cache-Control"] = "private, no-store"
    novel = own_novel(db, user, novel_id)
    chapter = db.query(Chapter).filter_by(novel_id=novel_id, chapter_number=chapter_number).first()
    if not chapter or not chapter.content:
        raise HTTPException(409, "Download this chapter before requesting an editing preview.")
    provider = own_provider(db, user, value.provider_id)
    if provider.kind != "local":
        raise HTTPException(422, "Editing previews require a configured local language model.")
    try:
        return preview_revision(db, user, novel, chapter, provider, value)
    except HTTPException:
        raise
    except (ValueError, PermissionError) as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, "Local editing provider unavailable; the original was preserved.") from exc


@router.get("/text-revisions/local-defaults", response_model=LocalTextModelDefaultsResponse)
def local_defaults(response: Response, user: User = Depends(get_current_user)):
    import os
    response.headers["Cache-Control"] = "private, no-store"
    from app.services.reader_provider import validate_destination
    url = os.getenv("NEXUS_LOCAL_AI_BASE_URL", "").rstrip("/")
    try:
        validate_destination("local", url)
    except ValueError:
        url = ""
    return {"base_url": url, "model": os.getenv("NEXUS_LOCAL_AI_MODEL", "")}


@router.get("/text-revisions/stories/{novel_id}/style", response_model=StoryTextStyleResponse)
def story_style(novel_id: int, response: Response, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    response.headers["Cache-Control"] = "private, no-store"
    own_novel(db, user, novel_id)
    return read_style(db, user.id, novel_id)


@router.put("/text-revisions/stories/{novel_id}/style", response_model=StoryTextStyleResponse)
def save_story_style(novel_id: int, value: StoryTextStyleWrite, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from app.models.reader_preference import ReaderPreference
    db.query(User).filter_by(id=user.id).with_for_update().first()
    own_novel(db, user, novel_id)
    current = read_style(db, user.id, novel_id)
    if current["revision"] != value.expected_revision:
        raise HTTPException(409, "The story style guide changed on another device. Reload before saving.")
    scope = f"textstyle:{novel_id}"
    row = db.query(ReaderPreference).filter_by(user_id=user.id, scope=scope).first()
    if row is None:
        row = ReaderPreference(user_id=user.id, novel_id=novel_id, scope=scope, revision=0)
        db.add(row)
    row.values = {"style_guide": value.style_guide.strip()}
    row.revision += 1
    db.commit()
    return read_style(db, user.id, novel_id)
