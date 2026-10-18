from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Response, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from config.database import get_db
from app.auth.dependencies import get_current_user
from app.models.saved_search import SavedSearch
from app.models.user import User
from app.schemas.saved_search import SavedSearchWrite, SavedSearchUpdate, SavedSearchResponse, SavedSearchDeleted
from app.services.saved_search_service import present, revision, stored

def private(response:Response):
    response.headers['Cache-Control']='private, no-store'

router = APIRouter(prefix="/saved-searches", tags=["saved searches"], dependencies=[Depends(private)])

def commit(db):
    try: db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, detail={'code':'saved_search_name_taken','message':'A saved search with this name already exists'}) from exc

@router.get("", response_model=list[SavedSearchResponse])
def list_saved_searches(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return [present(item) for item in db.query(SavedSearch).filter(SavedSearch.user_id == current_user.id).order_by(SavedSearch.updated_at.desc()).all()]

@router.post("", status_code=201, response_model=SavedSearchResponse)
def create_saved_search(payload: SavedSearchWrite, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    db.query(User).filter_by(id=current_user.id).with_for_update().first()
    db.expire_all()
    item = SavedSearch(user_id=current_user.id, name=payload.name, filters=stored(payload), notify_on_match=payload.notify_on_match)
    db.add(item); commit(db); db.refresh(item)
    return present(item)

@router.put("/{search_id}", response_model=SavedSearchResponse)
def update_saved_search(search_id:int,payload:SavedSearchUpdate,db:Session=Depends(get_db),current_user:User=Depends(get_current_user)):
    db.query(User).filter_by(id=current_user.id).with_for_update().first()
    db.expire_all()
    item=db.query(SavedSearch).filter_by(id=search_id,user_id=current_user.id).with_for_update().first()
    if item is None: raise HTTPException(404,'Saved search not found')
    if revision(item)!=payload.expected_revision:
        raise HTTPException(409,detail={'code':'saved_search_changed','message':'This search changed on another device. Refresh before editing.'})
    item.name=payload.name; item.filters=stored(payload); item.notify_on_match=payload.notify_on_match
    from app.services.catalog_watch_service import invalidate_search
    invalidate_search(db,current_user.id,search_id)
    now=datetime.now(timezone.utc).replace(tzinfo=None)
    previous=item.updated_at.replace(tzinfo=None)
    item.updated_at=max(now,previous+timedelta(microseconds=1))
    commit(db); db.refresh(item)
    return present(item)

@router.delete("/{search_id}", response_model=SavedSearchDeleted)
def delete_saved_search(search_id: int, expected_revision:str|None=Query(None,min_length=64,max_length=64,pattern=r'^[0-9a-f]+$'),db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    db.query(User).filter_by(id=current_user.id).with_for_update().first()
    db.expire_all()
    item = db.query(SavedSearch).filter(SavedSearch.id == search_id, SavedSearch.user_id == current_user.id).first()
    if not item: raise HTTPException(status_code=404, detail="Saved search not found")
    if expected_revision is not None and revision(item)!=expected_revision:
        raise HTTPException(409,detail={'code':'saved_search_changed','message':'This search changed on another device. Refresh before deleting.'})
    from app.models.catalog_watch import CatalogWatch, CatalogWatchSeen, CatalogMatch
    watch_ids=[id for (id,) in db.query(CatalogWatch.id).filter_by(user_id=current_user.id,search_id=search_id).all()]
    if watch_ids:
        db.query(CatalogMatch).filter(CatalogMatch.watch_id.in_(watch_ids),CatalogMatch.user_id==current_user.id).delete(synchronize_session=False)
        db.query(CatalogWatchSeen).filter(CatalogWatchSeen.watch_id.in_(watch_ids),CatalogWatchSeen.user_id==current_user.id).delete(synchronize_session=False)
        db.query(CatalogWatch).filter(CatalogWatch.id.in_(watch_ids),CatalogWatch.user_id==current_user.id).delete(synchronize_session=False)
    db.delete(item); db.commit(); return {"deleted": True}
