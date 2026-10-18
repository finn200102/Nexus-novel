"""Private edition selection with refreshed visibility after upstream requests."""
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from uuid import UUID
from config.database import get_db
from app.auth.dependencies import get_current_auth, Authenticated
from app.models.user import User
from app.models.account import UserSession
from app.services import catalog_read_service
from app.services.blocklist_service import merged_exclusions, apply_blocklist
from app.services.catalog_watch_service import fingerprint
from app.schemas.reviewed_edition_review import EditionGroupResponse
from app.schemas.reviewed_vocabulary import Kind, TermPage

router = APIRouter(prefix='/discovery', tags=['reviewed catalog'])


def snapshot(db, user_id, session_id=None):
    db.expire_all()
    user = db.get(User, user_id)
    if user is None or user.is_disabled:
        raise HTTPException(403, detail='Account is unavailable')
    if session_id is not None:
        session=db.get(UserSession,session_id)
        if session is None or session.user_id!=user_id or session.revoked_at is not None:
            raise HTTPException(401, detail='Session ended. Sign in again.')
    rules = merged_exclusions(db, user)
    result = (user.storage_id, fingerprint(rules), rules)
    db.commit()
    return result


def editions_allowed(db, user_id, proof, data, novel_id, session_id=None):
    if snapshot(db, user_id, session_id) != proof:
        raise HTTPException(409, detail={'code':'catalog_visibility_changed','message':'Your content rules changed. Reopen editions.'})
    user = db.get(User, user_id)
    # Only visible editions contribute labels, selection and counts. The seed
    # must itself be visible; an endpoint cannot reveal siblings of a hidden ID.
    members = apply_blocklist(db, user, data['editions'])
    if not any(member['novel_id'] == novel_id for member in members):
        raise HTTPException(404, detail='Story is unavailable')
    data['editions'] = members
    data['edition_count'] = len(members)
    selected = next(member for member in members if member['novel_id']==novel_id)
    data['title'] = selected['title']
    db.commit()
    return data


@router.get('/edition-groups/{novel_id}', response_model=EditionGroupResponse)
async def editions(novel_id: int, response: Response, db: Session = Depends(get_db), auth: Authenticated = Depends(get_current_auth)):
    response.headers['Cache-Control']='private, no-store'
    user_id=auth.user.id
    session_id=auth.session.id
    proof=await run_in_threadpool(snapshot, db, user_id, session_id)
    remote=await catalog_read_service.request(f'/edition-groups/by-novel/{novel_id}')
    data=EditionGroupResponse.model_validate(remote).model_dump(mode='json')
    return await run_in_threadpool(editions_allowed, db, user_id, proof, data, novel_id, session_id)


@router.get('/vocabulary/terms', response_model=TermPage)
async def terms(response: Response, kind: Kind | None = None, q: str | None = Query(None,max_length=200),
    ids: list[UUID] | None = Query(None,max_length=100), fandom_term_id: UUID | None = None,
    story_key: UUID | None = None, offset: int = Query(0,ge=0,le=1000000), limit: int = Query(50,ge=1,le=100),
    db: Session = Depends(get_db), auth: Authenticated = Depends(get_current_auth)):
    response.headers['Cache-Control']='private, no-store'
    user_id=auth.user.id
    session_id=auth.session.id
    proof=await run_in_threadpool(snapshot, db, user_id, session_id)
    params={k:v for k,v in dict(kind=kind,q=q,ids=[str(i) for i in ids] if ids else None,
        fandom_term_id=str(fandom_term_id) if fandom_term_id else None, story_key=str(story_key) if story_key else None,
        offset=offset,limit=limit,**proof[2]).items() if v is not None}
    remote=await catalog_read_service.request('/vocabulary/reader-terms',params=params)
    if await run_in_threadpool(snapshot,db,user_id,session_id) != proof:
        raise HTTPException(409, detail={'code':'catalog_visibility_changed','message':'Your content rules changed. Search again.'})
    return TermPage.model_validate(remote)
