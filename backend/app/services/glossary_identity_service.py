"""Preferred terms have explicit immutable prerequisites, never numeric authority."""
import json
from sqlalchemy import func,cast,Text
from fastapi import HTTPException
from app.models import User,Library,Novel,Chapter
from app.models.translation import StoryGlossary
from app.services.chapter_identity_service import check_write,manifest_state,sqlite_transaction,source_version

MAX_PREREQUISITES=20_000
MAX_BYTES=32*1024**2


def owned(db,user_id,novel_id,*,lock=False):
    if lock:sqlite_transaction(db,write=True)
    query=db.query(User).filter_by(id=user_id).populate_existing()
    if lock:query=query.with_for_update()
    user=query.first()
    if not user or user.is_disabled:raise HTTPException(404,'Story not found')
    query=db.query(Novel).join(Library).filter(Novel.id==novel_id,Library.user_id==user_id).populate_existing()
    if lock:query=query.with_for_update(of=Novel)
    novel=query.first()
    if novel is None:raise HTTPException(404,'Story not found')
    return novel


class Versions:
    def __init__(self,db,novel_id,*,lock=False):
        self.db=db;self.novel_id=novel_id;self.lock=lock;self.cache={};self.bytes=0

    def load(self,keys):
        missing=list(set(keys)-self.cache.keys())
        for offset in range(0,len(missing),500):
            part=missing[offset:offset+500]
            for key in part:self.cache[key]=None
            query=self.db.query(Chapter.id,Chapter.chapter_key,Chapter.chapter_number,
                Chapter.document['content_version'].as_string().label('version'),
                func.length(Chapter.content).label('text_size'),func.length(cast(Chapter.document,Text)).label('document_size')).filter(
                    Chapter.novel_id==self.novel_id,Chapter.archived.is_(False),Chapter.chapter_key.in_(part))
            if self.lock:query=query.with_for_update(of=Chapter)
            for row in query:
                version=row.version
                if not isinstance(version,str) or len(version)!=64:
                    cost=4*((row.text_size or 0)+(row.document_size or 0));self.bytes+=cost
                    if self.bytes>MAX_BYTES:
                        raise HTTPException(422,'Legacy glossary prerequisite content exceeds 32 MiB; download and review a smaller chapter scope.')
                    value=self.db.query(Chapter).filter_by(id=row.id,novel_id=self.novel_id).populate_existing().first()
                    try:version=source_version(value)
                    except (TypeError,KeyError):version=None
                self.cache[row.chapter_key]=(row.chapter_number,version)
        return self.cache


def capture_prerequisites(db,novel_id,floor):
    rows=db.query(Chapter.chapter_key).filter(Chapter.novel_id==novel_id,Chapter.chapter_number<=floor.chapter_number).order_by(
        Chapter.chapter_number,Chapter.id).limit(MAX_PREREQUISITES+1).with_for_update(of=Chapter).all()
    if len(rows)>MAX_PREREQUISITES:
        raise HTTPException(422,'A glossary approval supports up to 20,000 prerequisite chapters; no term was changed.')
    keys=[row.chapter_key for row in rows]
    checker=Versions(db,novel_id,lock=True)
    versions=checker.load(keys)
    if any(versions[key] is None or not isinstance(versions[key][1],str) for key in keys):
        raise HTTPException(409,'A glossary prerequisite is unavailable. Review its original before approving this term.')
    return [{'chapter_key':key,'source_version':versions[key][1]} for key in keys],checker


def inspect_entry(row,state,versions):
    if row.identity_inferred or not row.chapter_key or not row.manifest_epoch or not row.source_version:
        return None,'legacy_identity_unknown'
    if row.manifest_epoch!=state.manifest_epoch:return None,'manifest_epoch_changed'
    proof=row.prerequisites
    if (not isinstance(proof,list) or not 1<=len(proof)<=MAX_PREREQUISITES
            or any(not isinstance(value,dict) or set(value)!={'chapter_key','source_version'}
                or not isinstance(value['chapter_key'],str) or not isinstance(value['source_version'],str) for value in proof)):
        return None,'prerequisites_unknown'
    expected={value['chapter_key']:value['source_version'] for value in proof}
    if len(expected)!=len(proof) or expected.get(row.chapter_key)!=row.source_version:return None,'prerequisites_unknown'
    current=versions.load(expected)
    for key,version in expected.items():
        if current[key] is None:return None,'prerequisite_missing_or_archived'
        if current[key][1]!=version:return None,'prerequisite_content_changed'
    return max(current[key][0] for key in expected),None


def entry_view(row,state,versions):
    effective,reason=inspect_entry(row,state,versions)
    current=versions.load([row.chapter_key]).get(row.chapter_key) if row.chapter_key else None
    return dict(id=row.id,source=row.source,target=row.target,language=row.language,through_chapter=row.through_chapter,
        chapter_key=row.chapter_key,manifest_epoch=row.manifest_epoch,manifest_revision=row.manifest_revision,source_version=row.source_version,
        current_number=current[0] if current else None,effective_through_chapter=effective,
        prerequisite_count=len(row.prerequisites) if isinstance(row.prerequisites,list) else 0,
        binding_state='review_required' if reason else 'verified',reason=reason)


def upsert(db,user_id,novel_id,*,source,target,language,through_chapter,expected_chapter_key=None,expected_manifest_epoch=None,
           expected_manifest_revision=None,expected_content_version=None,entry_id=None):
    owned(db,user_id,novel_id,lock=True)
    if any(value is None for value in (expected_chapter_key,expected_manifest_epoch,expected_manifest_revision,expected_content_version)):
        raise HTTPException(409,detail={'code':'chapter_identity_required','message':'Select and review the exact glossary floor chapter.'})
    chapter=db.query(Chapter).filter_by(novel_id=novel_id,chapter_number=through_chapter,archived=False).first()
    if chapter is None:raise HTTPException(409,detail={'code':'chapter_manifest_changed','message':'The glossary floor address changed. Select its current immutable chapter before reviewing this term.'})
    prerequisites,checker=capture_prerequisites(db,novel_id,chapter)
    proof=check_write(db,user_id,chapter,expected_chapter_key=expected_chapter_key,expected_manifest_epoch=expected_manifest_epoch,
        expected_manifest_revision=expected_manifest_revision,expected_content_version=expected_content_version,require_content_version=True)
    chapter=db.query(Chapter).filter_by(novel_id=novel_id,chapter_key=proof['chapter_key']).first()
    query=db.query(StoryGlossary).filter_by(user_id=user_id,novel_id=novel_id,source=source,language=language,
        chapter_key=proof['chapter_key'],manifest_epoch=proof['manifest_epoch'],identity_inferred=False)
    duplicate=query.first()
    if entry_id is not None:
        entry=db.query(StoryGlossary).filter_by(id=entry_id,user_id=user_id,novel_id=novel_id).with_for_update().first()
        if entry is None:raise HTTPException(404,'Glossary entry not found')
        if duplicate and duplicate.id!=entry.id:raise HTTPException(409,'An approved term already exists for this chapter; edit that entry instead.')
    else:entry=duplicate
    if entry is None:entry=StoryGlossary(user_id=user_id,novel_id=novel_id);db.add(entry)
    entry.source=source;entry.target=target;entry.language=language;entry.through_chapter=chapter.chapter_number
    entry.chapter_key=proof['chapter_key'];entry.manifest_epoch=proof['manifest_epoch'];entry.manifest_revision=proof['manifest_revision']
    entry.source_version=proof['source_version'];entry.prerequisites=prerequisites;entry.identity_inferred=False
    db.flush()
    return entry_view(entry,manifest_state(db,novel_id),checker)


def entries(db,user_id,novel_id,*,language=None,offset=0,limit=50):
    if type(offset) is not int or not 0<=offset<=2147483647 or type(limit) is not int or not 1<=limit<=100:raise HTTPException(422,'Choose a glossary page size between 1 and 100.')
    owned(db,user_id,novel_id)
    query=db.query(StoryGlossary).filter_by(user_id=user_id,novel_id=novel_id)
    if language is not None:query=query.filter_by(language=language)
    total=query.count();state=manifest_state(db,novel_id);versions=Versions(db,novel_id)
    return dict(items=[entry_view(row,state,versions) for row in query.order_by(StoryGlossary.id).offset(offset).limit(limit)],total=total,offset=offset,limit=limit)


def approved(db,user_id,novel_id,language,chapter_number):
    owned(db,user_id,novel_id)
    target=db.query(Chapter).filter_by(novel_id=novel_id,chapter_number=chapter_number,archived=False).first()
    if target is None:return {}
    state=manifest_state(db,novel_id);versions=Versions(db,novel_id);selected={};size=0
    query=db.query(StoryGlossary).filter_by(user_id=user_id,novel_id=novel_id,language=language,identity_inferred=False,
        manifest_epoch=state.manifest_epoch).order_by(StoryGlossary.id).yield_per(1)
    for count,row in enumerate(query,1):
        if count>2000:raise HTTPException(422,'More than 2,000 glossary scopes require a smaller active term set before translation.')
        size+=len(json.dumps(row.prerequisites or [],ensure_ascii=False).encode())
        if size>MAX_BYTES:raise HTTPException(422,'Glossary prerequisite proofs exceed 32 MiB; review a smaller active term set.')
        effective,reason=inspect_entry(row,state,versions)
        if reason or effective>target.chapter_number:continue
        rank=(effective,row.id)
        if row.source not in selected or selected[row.source][0]<rank:selected[row.source]=(rank,row.target)
    return {source:value[1] for source,value in sorted(selected.items(),key=lambda pair:pair[1][0],reverse=True)[:40]}
