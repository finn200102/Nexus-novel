from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.models.user import User
from app.services import highlights_export_service as export
from config.database import get_db

router = APIRouter(prefix="/export", tags=["highlights export"], responses={404: {"description": "Not found"}})


class ReadwiseTokenBody(BaseModel):
    token: str = Field(min_length=8, max_length=255)


class ReadwiseSyncBody(BaseModel):
    novel_id: int | None = None


def _readwise_error(exc: export.ReadwiseError) -> HTTPException:
    return HTTPException(status_code=502, detail=str(exc))


@router.get("/highlights")
def export_highlights(
    format: str = Query("markdown", pattern="^(markdown|json)$"),
    novel_id: int | None = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if novel_id is not None and not export.user_novels(db, current_user, novel_id):
        raise HTTPException(status_code=404, detail="Novel not found")
    if format == "json":
        return export.json_export(db, current_user, novel_id)

    documents = export.markdown_documents(db, current_user, novel_id)
    if novel_id is not None:
        return Response(
            content=next(iter(documents.values())),
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="highlights.md"'},
        )

    return Response(
        content=export.build_zip(documents),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="nexus-highlights.zip"'},
    )


@router.get("/readwise")
def readwise_status(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return {"connected": export.get_readwise_token(db, current_user) is not None}


@router.put("/readwise")
def connect_readwise(
    body: ReadwiseTokenBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    token = body.token.strip()
    try:
        valid = export.verify_readwise_token(token)
    except export.ReadwiseError as exc:
        raise _readwise_error(exc) from exc
    if not valid:
        raise HTTPException(status_code=422, detail="Readwise rejected this token")
    export.save_readwise_token(db, current_user, token)
    return {"connected": True}


@router.delete("/readwise", status_code=204)
def disconnect_readwise(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    export.delete_readwise_token(db, current_user)
    return Response(status_code=204)


@router.post("/readwise/sync")
def sync_readwise(
    body: ReadwiseSyncBody | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    token = export.get_readwise_token(db, current_user)
    if token is None:
        raise HTTPException(status_code=409, detail="Readwise is not connected")
    novel_id = body.novel_id if body else None
    try:
        sent = export.sync_readwise(db, current_user, token, novel_id)
    except export.ReadwiseError as exc:
        raise _readwise_error(exc) from exc
    return {"exported": sent}
