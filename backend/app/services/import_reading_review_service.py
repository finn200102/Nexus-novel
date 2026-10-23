"""Imported labels are evidence for a review, never a chapter address authority."""
from copy import deepcopy
from datetime import UTC,date,datetime,timedelta
from hashlib import sha256
import json
import re
from uuid import uuid4
from fastapi import HTTPException
from sqlalchemy import or_
from app.models import Chapter,Library,Novel,User,ReadingProgress,ReadingHistory,ReadingAnnotation
from app.models.import_reading_review import ImportReadingReview,ImportReadingOperation
from app.services import chapter_identity_service as identities


def digest(value):return sha256(json.dumps(value,sort_keys=True,separators=(',',':'),default=str).encode()).hexdigest()
def conflict(message):raise HTTPException(409,detail={'code':'import_reading_changed','message':message})


def _restored_document(raw, content, expected_version):
    """Sanitize each block while preserving verified stable local block IDs."""
    from app.services.chapter_document import content_version,from_html,from_text
    if not raw:
        document=from_text(content)
        if document['content_version']!=expected_version:raise ValueError
        return document
    blocks=raw.get('blocks')
    if not isinstance(blocks,list) or not blocks:raise ValueError
    clean=[];seen_ids=set()
    for block in blocks:
        if not isinstance(block,dict) or not isinstance(block.get('html'),str):raise ValueError
        identity=block.get('id')
        if not isinstance(identity,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',identity) or identity in seen_ids:raise ValueError
        seen_ids.add(identity)
        fragment=from_html(block['html'])['blocks']
        if len(fragment)!=1:raise ValueError
        safe=fragment[0];safe['id']=identity
        if block.get('role')=='author_note':
            provenance=block.get('role_provenance')
            if provenance not in ('source','heuristic'):raise ValueError
            safe.update(role='author_note',role_provenance=provenance)
        elif block.get('role') is not None:raise ValueError
        clean.append(safe)
    version=content_version(clean)
    if version!=expected_version:raise ValueError
    return {'schema_version':1,'blocks':clean,'content_version':version,
        'source_format':raw['source_format'] if isinstance(raw.get('source_format'),str) and len(raw['source_format'])<=32 else 'html',
        'plain_text':'\n\n'.join(block['text'] for block in clean)}


def owned(db,user,review_id,lock=False):
    query=db.query(ImportReadingReview).join(Novel,Novel.id==ImportReadingReview.novel_id).join(Library,Library.id==Novel.library_id).filter(ImportReadingReview.id==review_id,ImportReadingReview.user_id==user.id,Library.user_id==user.id)
    if lock:query=query.populate_existing().with_for_update(of=ImportReadingReview)
    row=query.first()
    if row is None:raise HTTPException(404,'Imported reading review not found')
    return row


def locations(payload):
    if payload.get('progress'):yield 'progress',payload['progress']
    for i,row in enumerate(payload.get('history',[])):yield f'history:{i}',row
    for i,row in enumerate(payload.get('annotations',[])):yield f'annotation:{i}',row
    for i,run in enumerate(payload.get('reading_runs',[])):
        if run.get('progress'):yield f'run:{i}',run['progress']


def normalize_payload(value):
    value=deepcopy(value)
    refs={row['ref']:row for row in value.get('chapter_refs',[])}
    if len(refs)!=len(value.get('chapter_refs',[])):raise HTTPException(422,'Chapter references must be unique')
    for name,row in locations(value):
        for field,number in (('chapter_ref','chapter_number'),('furthest_chapter_ref','furthest_chapter_number')):
            if field=='furthest_chapter_ref' and not row.get(field) and row.get(number)==0 and not row.get('furthest_percent'):
                row[number]=None
            if row.get(number) is None and (field!='chapter_ref' or not name.startswith('annotation:')):continue
            key=row.get(field)
            if key is not None:
                if key not in refs:raise HTTPException(422,'A reading item references an unknown chapter reference')
            else:
                key=f'legacy:{name}:{number}'
                refs[key]={'ref':key,'chapter_number':row.get(number),'source_version':row.get('locator_content_version') if field=='chapter_ref' else None,'title':None,'archived':False}
                row[field]=key
    from app.schemas.user_data import ExportChapterReference
    value['chapter_refs']=[ExportChapterReference.model_validate(ref).model_dump(mode='json') for ref in refs.values()]
    value.pop('pending_reading_imports',None)
    if len(json.dumps(value,default=str).encode())>32*1024*1024:raise HTTPException(422,'Imported reading review exceeds 32 MiB; split this story export before importing')
    return value


def stage(db,user,novel,item,run_mapping,private_originals=None,backup_placeholder_keys=None):
    payload=normalize_payload(item.model_dump(mode='json',by_alias=True))
    if not payload['chapter_refs']:return None
    if private_originals:
        payload['_private_originals']=deepcopy(private_originals)
        if backup_placeholder_keys:payload['_backup_placeholder_keys']=deepcopy(backup_placeholder_keys)
        if len(json.dumps(payload,ensure_ascii=False,default=str).encode())>32*1024*1024:
            raise HTTPException(413,'This story’s backup chapter material exceeds the 32 MiB review limit; split the backup by story.')
    fingerprint=digest(payload)
    from app.models.reading_run import ReadingRun
    row=db.query(ImportReadingReview).filter_by(user_id=user.id,novel_id=novel.id,fingerprint=fingerprint).first()
    if row is None:
        payload['_run_mapping']=run_mapping
        payload['_run_fingerprints']={key:digest(run.progress_snapshot) for key in run_mapping.values() if (run:=db.query(ReadingRun).filter_by(user_id=user.id,novel_id=novel.id,run_key=key).first()) is not None}
        row=ImportReadingReview(user_id=user.id,novel_id=novel.id,fingerprint=fingerprint,payload=payload,applied_refs={})
        db.add(row);db.flush()
    # Automatic binding is restricted to exact existing owned lifecycle AND
    # captured source version. Foreign source/hash candidates require review.
    state=identities.manifest_state(db,novel.id)
    automatic=[]
    for ref in payload['chapter_refs']:
        if ref['ref'] in (row.applied_refs or {}) or ref.get('manifest_epoch')!=state.manifest_epoch or not ref.get('chapter_key') or not ref.get('source_version'):continue
        chapter=db.query(Chapter).execution_options(include_archived_chapters=True).filter_by(novel_id=novel.id,chapter_key=ref['chapter_key']).first()
        if chapter is not None and identities.source_version(chapter)==ref['source_version']:
            automatic.append(dict(ref=ref['ref'],chapter_key=chapter.chapter_key))
    existing=db.query(ReadingProgress).filter_by(user_id=user.id,novel_id=novel.id).first()
    incoming=payload.get('progress')
    if existing is not None and incoming and (existing.chapter_key!=next((ref.get('chapter_key') for ref in payload['chapter_refs'] if ref['ref']==incoming.get('chapter_ref')),None) or existing.position!=incoming.get('position',0) or existing.percent!=incoming.get('percent',0)):
        automatic=[]
    if automatic:
        from app.schemas.import_reading_review import ImportReadingPreviewInput,ImportReadingApplyInput
        # Bound per review action; subsequent chunks keep the same transaction.
        for offset in range(0,len(automatic),1000):
            value=preview(db,user,row,ImportReadingPreviewInput(expected_revision=row.revision,mappings=automatic[offset:offset+1000],keep_existing_place=existing is not None),commit=False)
            apply(db,user,row,ImportReadingApplyInput(review_token=value['review_token'],operation_id=f'auto-import:{row.id}:{row.revision}'),commit=False)
    return row


def _chapter(db,novel_id,key,lock=False):
    query=db.query(Chapter).execution_options(include_archived_chapters=True).filter_by(novel_id=novel_id,chapter_key=key)
    if lock:query=query.populate_existing().with_for_update()
    chapter=query.first()
    if chapter is None:raise HTTPException(404,'The selected owned chapter no longer exists')
    return chapter


def candidates(db,novel_id,ref):
    clauses=[]
    if ref.get('chapter_key'):clauses.append(Chapter.chapter_key==ref['chapter_key'])
    if ref.get('metadata_chapter_key') and ref.get('metadata_manifest_key'):clauses.append((Chapter.metadata_chapter_key==ref['metadata_chapter_key'])&(Chapter.metadata_manifest_key==ref['metadata_manifest_key']))
    if ref.get('chapter_number') is not None:clauses.append(Chapter.chapter_number==ref['chapter_number'])
    if ref.get('title'):clauses.append(Chapter.title==ref['title'])
    if not clauses:return [],False
    rows=db.query(Chapter).execution_options(include_archived_chapters=True).filter(Chapter.novel_id==novel_id,or_(*clauses)).order_by(Chapter.chapter_number,Chapter.id).limit(21).all()
    result=[]
    for chapter in rows[:20]:
        evidence=[]
        if chapter.chapter_key==ref.get('chapter_key'):evidence.append('same_local_key')
        if chapter.metadata_manifest_key==ref.get('metadata_manifest_key') and chapter.metadata_chapter_key==ref.get('metadata_chapter_key') and chapter.metadata_chapter_key:evidence.append('same_remote_namespace')
        if identities.source_version(chapter)==ref.get('source_version'):evidence.append('same_content_version')
        if chapter.chapter_number==ref.get('chapter_number'):evidence.append('same_numeric_label_only')
        if chapter.title==ref.get('title') and chapter.title:evidence.append('same_title_only')
        result.append(dict(chapter_key=chapter.chapter_key,chapter_number=chapter.chapter_number,title=chapter.title,source_version=identities.source_version(chapter),archived=chapter.archived,evidence=evidence))
    return result,len(rows)>20


def view(db,row,offset=0,limit=50):
    refs=row.payload['chapter_refs'];applied=row.applied_refs or {};items=[]
    def valid(ref):
        bound=applied.get(ref['ref'])
        if not bound:return False
        chapter=db.query(Chapter).execution_options(include_archived_chapters=True).filter_by(novel_id=row.novel_id,chapter_key=bound['chapter_key']).first()
        return chapter is not None and chapter.manifest_epoch==bound.get('manifest_epoch') and identities.source_version(chapter)==bound.get('source_version') and bool(chapter.archived)==bool(bound.get('archived'))
    for ref in refs[offset:offset+limit]:
        choices,truncated=candidates(db,row.novel_id,ref)
        original=(row.payload.get('_private_originals') or {}).get(ref['ref'])
        items.append(dict(reference=ref,applied=valid(ref),candidates=choices,candidates_truncated=truncated,
            archived_body_available=bool(original and original.get('kind')=='current'),
            retained_originals=len(original.get('versions',[])) if original else 0,
            backup_placeholder_key=(row.payload.get('_backup_placeholder_keys') or {}).get(ref['ref'])))
    novel=db.query(Novel).filter_by(id=row.novel_id).first()
    awaiting_warning=(['A full backup contains chapter text. Match each archived chapter to an empty owned chapter and explicitly choose which bodies to restore.'] if row.payload.get('_private_originals') else ['This private original is not stored here yet. For an EPUB, upload the same EPUB into this library, then explicitly match its restored chapters. No original files or sources are fetched by this review.']) if novel and novel.scrape_status=='awaiting_original' else []
    return dict(id=row.id,novel_id=row.novel_id,novel_title=novel.title if novel else None,library_name=novel.library.name if novel and novel.library else None,revision=row.revision,total=len(refs),applied=len(applied),offset=offset,limit=limit,items=items,warnings=awaiting_warning+(["You kept the existing reading place. The imported place remains preserved in this review and future exports."] if row.payload.get('_progress_outcome')=='kept_by_reader' else [])+['Imported checkpoints are inferred history, never verified reading evidence.','Chapter numbers, titles and matching text only suggest candidates. Review each foreign binding.','Unselected material stays private in this review, including its original locators.'])


def target_fingerprint(db,row):
    progress=db.query(ReadingProgress).filter_by(user_id=row.user_id,novel_id=row.novel_id).first()
    return digest({'progress':{field:getattr(progress,field) for field in ('chapter_key','chapter_number','revision','reading_run_key')} if progress else None})


def preview(db,user,row,body,*,commit=True):
    identities.sqlite_transaction(db,write=True)
    fresh=db.query(User).filter_by(id=user.id).populate_existing().with_for_update().first()
    if fresh is None or fresh.is_disabled:raise HTTPException(401,'Account is unavailable')
    from app.auth.dependencies import require_current_session
    require_current_session(db,user.id)
    row=owned(db,user,row.id,True)
    if row.revision!=body.expected_revision:conflict('This imported review changed. Refresh before choosing chapter bindings.')
    refs={ref['ref']:ref for ref in row.payload['chapter_refs']};mapping={};versions={};warnings=[]
    private_originals=row.payload.get('_private_originals') or {}
    restoring_targets={}
    for choice in body.mappings:
        if not choice.restore_archived_content:continue
        archived=private_originals.get(choice.ref)
        if not archived or archived.get('kind')!='current' or archived.get('source_version')!=refs.get(choice.ref,{}).get('source_version'):
            raise HTTPException(422,'This reference has no verified full-backup chapter body to restore')
        previous=restoring_targets.get(str(choice.chapter_key))
        if previous and previous!=archived['source_version']:
            raise HTTPException(422,'Choose at most one archived body for each owned chapter')
        restoring_targets[str(choice.chapter_key)]=archived['source_version']
    for choice in body.mappings:
        if choice.ref in mapping or choice.ref not in refs:raise HTTPException(422,'Select each unresolved chapter reference once')
        chapter=_chapter(db,row.novel_id,str(choice.chapter_key),True);version=identities.source_version(chapter)
        original=private_originals.get(choice.ref)
        restoring=bool(choice.restore_archived_content)
        if restoring:
            from app.models.chapter import ContentStatus
            if not original or original.get('kind')!='current':raise HTTPException(422,'This reference has no restorable full-backup chapter body')
            if chapter.content_status not in (ContentStatus.MISSING,ContentStatus.FAILED) or (chapter.content or '').strip() or chapter.document:
                raise HTTPException(409,'This chapter already has original content. Full-backup restore never replaces existing text.')
            if original.get('source_version')!=refs[choice.ref].get('source_version'):
                raise HTTPException(422,'The archived chapter body does not match its immutable source-version evidence')
        restored_version=restoring_targets.get(chapter.chapter_key)
        changed=(refs[choice.ref].get('source_version')!=restored_version) if restored_version else (not refs[choice.ref].get('source_version') or refs[choice.ref]['source_version']!=version)
        if changed and not (restoring or choice.confirm_changed_content):raise HTTPException(422,'Review changed or unknown source text explicitly; original annotation quotes and version provenance will be retained')
        mapping[choice.ref]=dict(chapter_key=chapter.chapter_key,changed_content=False if restoring else changed,
            source_version=restored_version or version,
            target_version_before=version,restore_archived_content=restoring,
            manifest_epoch=chapter.manifest_epoch,archived=bool(chapter.archived))
        versions[chapter.chapter_key]=version
        if restoring:warnings.append('The selected empty owned chapter will receive its archived text and retained originals after you confirm this review.')
        elif changed:warnings.append('Changed or unknown text: block locators will not be attached to the selected current original.')
    if not mapping:raise HTTPException(422,'Choose at least one unresolved chapter reference')
    state=identities.manifest_state(db,row.novel_id,lock=True)
    existing=db.query(ReadingProgress).filter_by(user_id=user.id,novel_id=row.novel_id).first()
    if existing is not None and row.payload.get('progress') and not row.payload.get('_progress_applied') and not body.keep_existing_place:
        raise HTTPException(422,'This story already has a saved reading place. Explicitly choose to keep it before applying imported bindings; the imported place remains in this review.')
    value=dict(keep_existing_place=body.keep_existing_place,token=str(uuid4()),expires_at=(datetime.now(UTC)+timedelta(minutes=15)).isoformat(),revision=row.revision,mappings=mapping,versions=versions,restoring_targets=restoring_targets,manifest_epoch=state.manifest_epoch,manifest_revision=str(state.revision),target=target_fingerprint(db,row))
    row.preview=value
    db.flush()
    if commit:db.commit()
    return dict(review_id=row.id,review_token=value['token'],expires_at=value['expires_at'],manifest_epoch=value['manifest_epoch'],manifest_revision=value['manifest_revision'],selected=len(mapping),warnings=list(dict.fromkeys(warnings)))


def _locators(source,changed):
    fields=('block_id','text_offset','text_quote','quote_prefix','quote_suffix','locator_content_version','locator_variant')
    result={key:source.get(key) for key in fields if source.get(key) is not None}
    if changed:
        # Preserve the original quote and original version in the durable review;
        # do not relabel that old locator as a current-version annotation.
        result={key:value for key,value in result.items() if key in ('text_quote','quote_prefix','quote_suffix','locator_content_version')}
        result['text_offset']=0
    return result


def apply(db,user,row,body,*,commit=True):
    identities.sqlite_transaction(db,write=True)
    fresh=db.query(User).filter_by(id=user.id).populate_existing().with_for_update().first()
    if fresh is None or fresh.is_disabled:raise HTTPException(401,'Account is unavailable')
    from app.auth.dependencies import require_current_session
    require_current_session(db,user.id)
    row=owned(db,user,row.id,True);fingerprint=digest({'review_id':row.id,**body.model_dump()})
    receipt=db.query(ImportReadingOperation).filter_by(user_id=user.id,operation_id=body.operation_id).first()
    if receipt:
        if receipt.fingerprint!=fingerprint:conflict('This operation identifier belongs to a different import action')
        return receipt.response
    plan=row.preview
    if not plan or plan['token']!=body.review_token or plan['revision']!=row.revision or datetime.fromisoformat(plan['expires_at'])<datetime.now(UTC):conflict('The import preview expired or changed. Review these bindings again.')
    selected=plan['mappings'];known={**(row.applied_refs or {}),**selected}
    chapters={key:_chapter(db,row.novel_id,key,True) for key in sorted({entry['chapter_key'] for entry in known.values()})}
    state=identities.manifest_state(db,row.novel_id,lock=True)
    if state.manifest_epoch!=plan['manifest_epoch'] or str(state.revision)!=plan['manifest_revision'] or target_fingerprint(db,row)!=plan['target']:conflict('The chapter list or saved reading place changed. Review the import again.')
    if any(identities.source_version(chapters[key])!=version for key,version in plan['versions'].items()):conflict('Source text changed after the import preview. Review its original version again.')
    payload=deepcopy(row.payload);runmap=payload.get('_run_mapping',{})
    # Every previously bound prerequisite is checked again when a later partial
    # review uses it. A cached UUID alone never blesses a new body or archive.
    for ref,bound in known.items():
        if ref in selected and bound['chapter_key'] in plan.get('restoring_targets',{}):
            continue
        original=chapters[bound['chapter_key']]
        if bound.get('manifest_epoch')!=state.manifest_epoch or bound.get('source_version')!=identities.source_version(original) or bool(bound.get('archived'))!=bool(original.archived):
            conflict('An earlier imported binding changed. Select that original reference again and review the new source text before continuing.')
    # Recheck and restore only explicitly selected archived bodies. Validation
    # precedes all writes, and the selected target must still be an empty slot.
    from app.models.chapter import ContentStatus
    from app.models.chapter_version import ChapterVersion
    for ref,entry in selected.items():
        if not entry.get('restore_archived_content'):continue
        archived_body=payload.get('_private_originals',{}).get(ref)
        chapter=chapters[entry['chapter_key']]
        if not archived_body or archived_body.get('kind')!='current' or archived_body.get('source_version')!=row.payload['chapter_refs'][next(i for i,item in enumerate(row.payload['chapter_refs']) if item['ref']==ref)].get('source_version'):
            conflict('The archived chapter evidence is incomplete. Its text remains in this private review.')
        if chapter.content_status not in (ContentStatus.MISSING,ContentStatus.FAILED) or (chapter.content or '').strip() or chapter.document:
            conflict('The selected chapter now contains text. Its existing original was preserved; review another empty chapter.')
        try:
            content=archived_body.get('content','')
            document=_restored_document(archived_body.get('document'),content,archived_body['source_version'])
        except Exception:
            raise HTTPException(422,'The archived chapter did not pass sanitization and source-version checks; nothing was restored.') from None
        archived_body['_validated_document']=document
        archived_body['_validated_content']=content
    for ref,entry in selected.items():
        if not entry.get('restore_archived_content'):continue
        archived_body=payload['_private_originals'][ref]
        chapter=chapters[entry['chapter_key']]
        chapter.content=archived_body['_validated_content'];chapter.document=archived_body['_validated_document']
        chapter.content_status=ContentStatus.PRESENT;chapter.word_count=archived_body.get('word_count')
        chapter.download_error=None;chapter.download_finished_at=datetime.now(UTC).replace(tzinfo=None)
        archived_body.pop('_validated_document',None);archived_body.pop('_validated_content',None)
        for saved in archived_body.get('versions',[]):
            if not isinstance(saved,dict) or not re.fullmatch(r'[0-9a-f]{64}',str(saved.get('source_version',''))):
                raise HTTPException(422,'A retained chapter original is malformed; no restore was applied')
            exists=db.query(ChapterVersion).filter_by(chapter_key=chapter.chapter_key,content_version=saved['source_version']).first()
            if exists:continue
            try:
                restored=_restored_document(saved.get('document'),saved.get('content',''),saved['source_version'])
                saved_content=saved.get('content','')
            except Exception:
                raise HTTPException(422,'A retained chapter original failed sanitization; no restore was applied') from None
            db.add(ChapterVersion(chapter_id=chapter.id,chapter_key=chapter.chapter_key,content_version=saved['source_version'],
                title=(saved.get('title') or chapter.title),source_url=saved.get('source_url'),content=saved_content,document=restored,
                byte_count=len(saved_content.encode()),reason=saved.get('version_reason') or 'backup_restore'))
    if any(entry.get('restore_archived_content') for entry in selected.values()):
        for entry in selected.values():
            version=plan.get('restoring_targets',{}).get(entry['chapter_key'])
            if version:
                entry['source_version']=version
                entry['manifest_epoch']=state.manifest_epoch
                entry['archived']=bool(chapters[entry['chapter_key']].archived)
        known={**(row.applied_refs or {}),**selected}
        db.flush()
    for index,item in enumerate(payload.get('history',[])):
        ref=item.get('chapter_ref')
        if ref not in selected:continue
        chapter=chapters[selected[ref]['chapter_key']];runkey=runmap.get(str(item.get('reading_run_key'))) if item.get('reading_run_key') else None
        when=datetime.combine(date.fromisoformat(item['date']),datetime.min.time())
        existing=db.query(ReadingHistory).filter_by(user_id=user.id,novel_id=row.novel_id,chapter_key=chapter.chapter_key,reading_date=when,reading_run_key=runkey).first()
        if existing is None:db.add(ReadingHistory(user_id=user.id,novel_id=row.novel_id,chapter_key=chapter.chapter_key,chapter_number=item['chapter_number'],reading_date=when,max_percent=max(0,min(100,int(item.get('max_percent',0)))),reading_run_key=runkey,identity_inferred=True,verified_percent=0))
        else:existing.max_percent=max(existing.max_percent,int(item.get('max_percent',0)))
    unresolved_note_numbers=[]
    for item in payload.get('annotations',[]):
        ref=item.get('chapter_ref')
        if ref not in selected:continue
        choice=selected[ref];chapter=chapters[choice['chapter_key']]
        match=dict(user_id=user.id,novel_id=row.novel_id,chapter_key=chapter.chapter_key,annotation_type=item.get('annotation_type','bookmark'),quote=item.get('quote'),note=item.get('note'),position=int(item.get('position',0)),locator_content_version=item.get('locator_content_version'))
        if db.query(ReadingAnnotation).filter_by(**match).first() is None:
            note=ReadingAnnotation(**{**match,'chapter_id':chapter.id,'chapter_number':item.get('chapter_number'),'percent':item.get('percent',0),**_locators(item,choice['changed_content'])})
            db.add(note)
            if item.get('chapter_number') is None:unresolved_note_numbers.append(note)
    outcome='not_selected';position=payload.get('progress')
    if position and not payload.get('_progress_applied') and position.get('chapter_ref') in known and (not position.get('furthest_chapter_ref') or position['furthest_chapter_ref'] in known):
        current=db.query(ReadingProgress).filter_by(user_id=user.id,novel_id=row.novel_id).first()
        if current is not None:
            if not plan.get('keep_existing_place'):conflict('Review the existing saved place before applying imported bindings.')
            outcome='kept_by_reader'
        else:
            entry=known[position['chapter_ref']];chapter=_chapter(db,row.novel_id,entry['chapter_key']);farentry=known.get(position.get('furthest_chapter_ref'));far=_chapter(db,row.novel_id,farentry['chapter_key']) if farentry else None
            if chapter.archived or far is not None and far.archived:outcome='kept_local'
            else:
                progress=ReadingProgress(revision=1,user_id=user.id,novel_id=row.novel_id,chapter_id=chapter.id,chapter_key=chapter.chapter_key,chapter_number=chapter.chapter_number,manifest_epoch=state.manifest_epoch,manifest_revision=str(state.revision),current_identity_inferred=True,furthest_identity_inferred=True,position=0 if entry['changed_content'] else int(position.get('position',0)),percent=position.get('percent',0),furthest_chapter_key=far.chapter_key if far else None,furthest_chapter_number=far.chapter_number if far else 0,furthest_percent=position.get('furthest_percent',0) if far else 0,reading_run_key=None,**_locators(position,entry['changed_content']))
                db.add(progress);outcome='applied'
        payload['_progress_applied']=True
        payload['_progress_outcome']=outcome
    # Restore historical run snapshots only after their own references were
    # reviewed. Native runs remain authoritative and are never overwritten.
    from app.models.reading_run import ReadingRun
    from app.services.reading_run_service import snapshot_progress
    for original in payload.get('reading_runs',[]):
        saved=original.get('progress')
        key=runmap.get(str(original['reading_run_key']))
        run=db.query(ReadingRun).filter_by(user_id=user.id,novel_id=row.novel_id,run_key=key).first() if key else None
        if not saved or not run or not run.archived_at or not (run.progress_snapshot or {}).get('_portable_source_key'):continue
        if digest(run.progress_snapshot)!=payload.get('_run_fingerprints',{}).get(key):continue
        if saved.get('chapter_ref') not in known or saved.get('furthest_chapter_ref') and saved['furthest_chapter_ref'] not in known:continue
        current=_chapter(db,row.novel_id,known[saved['chapter_ref']]['chapter_key'])
        furthest=_chapter(db,row.novel_id,known[saved['furthest_chapter_ref']]['chapter_key']) if saved.get('furthest_chapter_ref') else None
        snapshot=dict(run.progress_snapshot or {})
        snapshot.update(chapter_key=current.chapter_key,chapter_number=current.chapter_number,furthest_chapter_key=furthest.chapter_key if furthest else None,furthest_chapter_number=furthest.chapter_number if furthest else 0,manifest_epoch=state.manifest_epoch,manifest_revision=str(state.revision),percent=saved.get('percent',0),furthest_percent=saved.get('furthest_percent',saved.get('percent',0)),position=0 if known[saved['chapter_ref']]['changed_content'] else saved.get('position',0),current_identity_inferred=True,furthest_identity_inferred=True,**_locators(saved,known[saved['chapter_ref']]['changed_content']))
        run.progress_snapshot=snapshot
        payload.setdefault('_run_fingerprints',{})[key]=digest(snapshot)
    db.flush()
    for note in unresolved_note_numbers:note.chapter_number=None
    if outcome=='applied' and position and position.get('reading_run_key'):
        key=runmap.get(str(position['reading_run_key']))
        run=db.query(ReadingRun).filter_by(user_id=user.id,novel_id=row.novel_id,run_key=key).first() if key else None
        active=db.query(ReadingRun).filter_by(user_id=user.id,novel_id=row.novel_id,archived_at=None).first()
        if run and active is None and (run.progress_snapshot or {}).get('_portable_source_key') and digest(run.progress_snapshot)==payload.get('_run_fingerprints',{}).get(key):
            progress=db.query(ReadingProgress).filter_by(user_id=user.id,novel_id=row.novel_id).first()
            run.archived_at=None;run.requires_run_key=True;progress.reading_run_key=run.run_key
            run.progress_snapshot={**run.progress_snapshot,**snapshot_progress(run,progress)}
    row.payload=payload;row.applied_refs=known;row.revision+=1;row.preview=None
    response=dict(id=row.id,revision=row.revision,applied=len(selected),remaining=len(payload['chapter_refs'])-len(known),progress='kept_local' if outcome=='kept_by_reader' else outcome)
    db.add(ImportReadingOperation(user_id=user.id,review_id=row.id,operation_id=body.operation_id,fingerprint=fingerprint,response=response))
    db.flush()
    if commit:db.commit()
    return response


def enrich_export(db,user,novel,document,progress,history,annotations):
    """Export only recorded immutable bindings, never recover keys from labels."""
    state=identities.manifest_state(db,novel.id)
    refs={}
    def reference(key,number,version=None):
        token='ref:'+digest({'chapter_key':key,'epoch':state.manifest_epoch if key else None,'number':None if key else number,'source_version':version})
        chapter=db.query(Chapter).execution_options(include_archived_chapters=True).filter_by(novel_id=novel.id,chapter_key=key).first() if key else None
        # A recycled FK or missing UUID stays unbound even if its label matches.
        refs[token]=dict(ref=token,chapter_key=key,manifest_epoch=state.manifest_epoch if chapter else None,
            metadata_manifest_key=chapter.metadata_manifest_key if chapter else None,metadata_chapter_key=chapter.metadata_chapter_key if chapter else None,
            chapter_number=number,title=chapter.title if chapter else None,source_version=version,
            archived=bool(chapter.archived) if chapter else False,source_site=novel.novel_site,source_story_id=str(novel.site_story_id) if novel.site_story_id is not None else None,source_url=novel.url)
        return token
    if progress and document.get('progress'):
        row=document['progress'];row['chapter_ref']=reference(progress.chapter_key,progress.chapter_number,progress.source_content_version)
        has_furthest=bool(progress.furthest_chapter_key) or progress.furthest_percent>0 or progress.furthest_chapter_number!=0
        row['furthest_chapter_number']=progress.furthest_chapter_number if has_furthest else None
        row['furthest_percent']=progress.furthest_percent if has_furthest else 0
        row['furthest_chapter_ref']=reference(progress.furthest_chapter_key,progress.furthest_chapter_number,progress.furthest_content_version) if has_furthest else None
    for item,row in zip(document.get('history',[]),history):item['chapter_ref']=reference(row.chapter_key,row.chapter_number,row.verified_content_version)
    # Original annotation iteration is sorted by presentation, not row identity.
    for item in document.get('annotations',[]):
        key=item.get('chapter_ref');item['chapter_ref']=reference(key,item.get('chapter_number'),item.get('locator_content_version'))
    from app.models.reading_run import ReadingRun
    for run in document.get('reading_runs',[]):
        original=db.query(ReadingRun).filter_by(user_id=user.id,novel_id=novel.id,run_key=run['reading_run_key']).first()
        snapshot=original.progress_snapshot if original else {}
        if run.get('progress'):
            for field,keyfield,numfield,versionfield in [('chapter_ref','chapter_key','chapter_number','source_content_version'),('furthest_chapter_ref','furthest_chapter_key','furthest_chapter_number','furthest_content_version')]:
                run['progress'][field]=reference(snapshot.get(keyfield),snapshot.get(numfield),snapshot.get(versionfield)) if field=='chapter_ref' or snapshot.get(keyfield) or snapshot.get(numfield) not in (None,0) or snapshot.get('furthest_percent',0)>0 else None
                if field=='furthest_chapter_ref' and run['progress'][field] is None:run['progress']['furthest_chapter_number']=None
    document['chapter_refs']=list(refs.values())
    document['pending_reading_imports']=[]
    for review in db.query(ImportReadingReview).filter_by(user_id=user.id,novel_id=novel.id).order_by(ImportReadingReview.id):
        if len(review.applied_refs or {})>=len(review.payload['chapter_refs']) and review.payload.get('_progress_outcome') not in ('kept_local','kept_by_reader'):continue
        original={key:value for key,value in review.payload.items() if not key.startswith('_') and key!='pending_reading_imports'}
        document['pending_reading_imports'].append(original)
