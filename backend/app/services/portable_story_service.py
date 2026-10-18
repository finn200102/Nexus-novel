"""An opaque export reference identifies a private book, never a fetch URL."""
import json
from uuid import uuid4
from fastapi import HTTPException
from app.models import Novel,Library
from app.models.chapter_manifest import ChapterManifestState
from app.models.portable_story_link import PortableStoryLink
from app.services.chapter_identity_service import manifest_state


def export_identity(db,user,novel):
    # Preserve an imported private origin through further portable exports.
    # An origin is a deduplication label only, never permission to read another
    # account or an assertion that an original file is present.
    link=db.query(PortableStoryLink).filter_by(user_id=user.id,library_id=novel.library_id,novel_id=novel.id).order_by(PortableStoryLink.id).first()
    state=manifest_state(db,novel.id)
    library=db.get(Library,novel.library_id)
    if link and link.destination_account_key==user.storage_id and link.destination_library_key==library.identity_key and link.target_story_epoch==state.manifest_epoch:
        return {'source_account_key':link.source_account_key,'story_epoch':link.source_story_epoch}
    return {'source_account_key':user.storage_id,'story_epoch':state.manifest_epoch}


def resolve(db,user,library,item):
    origin=item.portable_story
    if origin is None:raise HTTPException(422,'A private story without a URL needs a portable story identity')
    library=db.query(Library).filter_by(id=library.id,user_id=user.id).populate_existing().with_for_update().first()
    if library is None:raise HTTPException(404,'Library not found')
    if library.identity_key is None:
        library.identity_key=str(uuid4());db.flush()
    account,epoch=str(origin.source_account_key),str(origin.story_epoch)
    link=db.query(PortableStoryLink).filter_by(user_id=user.id,library_id=library.id,source_account_key=account,source_story_epoch=epoch).populate_existing().with_for_update().first()
    if link:
        target=db.query(Novel).join(Library,Novel.library_id==Library.id).join(ChapterManifestState,ChapterManifestState.novel_id==Novel.id).filter(Novel.id==link.novel_id,Novel.library_id==library.id,Library.user_id==user.id,ChapterManifestState.manifest_epoch==link.target_story_epoch).first() if link.novel_id is not None else None
        if link.destination_account_key!=user.storage_id or link.destination_library_key!=library.identity_key or target is None:
            payload=item.model_dump(mode='json',by_alias=True)
            if len(json.dumps(payload).encode())>32*1024*1024:raise HTTPException(422,'Private story reading material exceeds 32 MiB; split this export before importing')
            link.pending_payload=payload
            return None,'conflict',link.id,'The original destination was deleted, moved or replaced. Its imported material is retained for review; no similarly named book or reused identifier was selected.'
        return target,'linked',link.id,None
    target=None
    if account==user.storage_id:
        target=db.query(Novel).join(Library,Novel.library_id==Library.id).join(ChapterManifestState,ChapterManifestState.novel_id==Novel.id).filter(Novel.library_id==library.id,Library.user_id==user.id,ChapterManifestState.manifest_epoch==epoch).first()
    state='linked'
    if target is None:
        target=Novel(library_id=library.id,url=None,title=(item.title or 'Private original awaiting restoration')[:255],novel_site='local',site='local',scrape_status='awaiting_original',num_chapters=0,chapter_count=0)
        db.add(target);db.flush();state='created'
    target_epoch=manifest_state(db,target.id).manifest_epoch
    link=PortableStoryLink(user_id=user.id,library_id=library.id,destination_account_key=user.storage_id,destination_library_key=library.identity_key,source_account_key=account,source_story_epoch=epoch,novel_id=target.id,target_story_epoch=target_epoch)
    db.add(link);db.flush()
    return target,state,link.id,None


def retained_conflicts(db,user,library):
    return [row.pending_payload for row in db.query(PortableStoryLink).filter_by(user_id=user.id,library_id=library.id).order_by(PortableStoryLink.id) if row.destination_account_key==user.storage_id and row.destination_library_key==library.identity_key and row.pending_payload]


def find_existing(db,user,library,origin):
    """Read-only identity resolution for continuity planning, never URL NULL."""
    if library is None or origin is None:return None
    account,epoch=str(origin.source_account_key),str(origin.story_epoch)
    link=db.query(PortableStoryLink).filter_by(user_id=user.id,library_id=library.id,source_account_key=account,source_story_epoch=epoch).first()
    if link:
        if link.destination_account_key!=user.storage_id or link.destination_library_key!=library.identity_key or link.novel_id is None:return None
        return db.query(Novel).join(Library,Library.id==Novel.library_id).join(ChapterManifestState,ChapterManifestState.novel_id==Novel.id).filter(Novel.id==link.novel_id,Novel.library_id==library.id,Library.user_id==user.id,ChapterManifestState.manifest_epoch==link.target_story_epoch).first()
    if account==user.storage_id:
        return db.query(Novel).join(Library,Library.id==Novel.library_id).join(ChapterManifestState,ChapterManifestState.novel_id==Novel.id).filter(Novel.library_id==library.id,Library.user_id==user.id,ChapterManifestState.manifest_epoch==epoch).first()
    return None


def reference_key(library_name,url,origin=None):
    if url is not None:return library_name,('url',url)
    if origin is None:return None
    value=origin if isinstance(origin,dict) else origin.model_dump(mode='json')
    return library_name,('private',str(value['source_account_key']),str(value['story_epoch']))
