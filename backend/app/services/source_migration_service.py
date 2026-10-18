"""Reviewed, private continuity copies. No fetching, parsing, or provider calls."""
from collections import Counter, defaultdict
from datetime import timedelta, timezone
from uuid import uuid4
from urllib.parse import urlsplit
import hashlib
import json
import re
import unicodedata

from fastapi import HTTPException
from jose import jwt, JWTError
from sqlalchemy import func, or_, cast, Text, JSON, String, Float, LargeBinary

from app.models import (Chapter, Novel, Library, User, ReadingProgress, ReadingRun, ReadingRunEvent,
    ReadingHistory, ReadingAnnotation, ChapterReadReceipt, ReaderPreference, ChapterDownloadJob, NovelPersonalData,
    ChapterAudioJob, TranslationJob, AudioExportJob, PodcastAudioJob)
from app.models.source_migration import SourceMigration, SourceMigrationOperation
from app.services import reading_run_service as runs
from app.services.reading_continuity_service import join_new_run, ensure_continuity
from app.services.job_lease import utcnow
from config.settings import settings

MAX_CHAPTERS = 20_000
MAX_ANCHOR_BYTES = 16 * 1024**2
ACTIVE = ('queued', 'processing', 'retry_wait')
LOCATORS = ('block_id', 'text_offset', 'text_quote', 'quote_prefix', 'quote_suffix', 'locator_content_version', 'locator_variant')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str, separators=(',', ':')).encode()).hexdigest()


def conflict(code, message):
    raise HTTPException(409, detail={'code': code, 'message': message})


def owned(db, user_id, novel_id):
    return runs.owned_story(db, user_id, novel_id)


def lock(db, user_id, *novel_ids):
    from app.services.chapter_identity_service import sqlite_transaction
    from app.auth.dependencies import require_current_session
    sqlite_transaction(db,write=True)
    user=db.query(User).filter_by(id=user_id).populate_existing().with_for_update().first()
    if user is None or user.is_disabled:raise HTTPException(401,'Account is unavailable')
    require_current_session(db,user_id)
    for novel_id in sorted(set(novel_ids)):
        owned(db, user_id, novel_id)
        db.query(Novel).filter_by(id=novel_id).with_for_update().first()
    # Terminal jobs may be retried without inserting a new FK row. Fence
    # existing jobs before chapters (workers finish job -> chapter), then body
    # updates and chapter renumbering, in a deterministic story/model order.
    for novel_id in sorted(set(novel_ids)):
        for model in (ChapterDownloadJob,ChapterAudioJob,TranslationJob,AudioExportJob,PodcastAudioJob):
            query=db.query(model.id).filter_by(user_id=user_id,novel_id=novel_id)
            if query.count()>200_000:raise HTTPException(422,'This story exceeds the 200,000-job review limit; no changes were made')
            for _ in query.order_by(model.id).with_for_update().yield_per(500):pass
        if db.query(Chapter.id).filter_by(novel_id=novel_id).count()>MAX_CHAPTERS:
            raise HTTPException(422,f'This preview supports up to {MAX_CHAPTERS:,} chapters per story; no changes were made')
        for _ in db.query(Chapter.id).filter_by(novel_id=novel_id).order_by(Chapter.id).with_for_update().yield_per(500):pass
    # Expire loaded snapshots after acquiring locks; do not silently reuse data
    # read before a concurrent progress save finished.
    db.expire_all()


def progress(db, user_id, novel_id):
    row = db.query(ReadingProgress).filter_by(user_id=user_id, novel_id=novel_id).first()
    run = runs.current_run(db, user_id, novel_id, row)
    return row or runs.restore_progress(run), run


def rows_state(query):
    """Bound private history before loading; hash a cursor, not an entire list."""
    model=query.column_descriptions[0]['entity']
    if query.count()>200_000:
        raise HTTPException(422,'This story has more than 200,000 private history records; migration needs a smaller history scope')
    text_columns=[column for column in model.__table__.columns if isinstance(column.type,(JSON,String))]
    lengths=sum((func.coalesce(func.length(cast(column,Text)),0) for column in text_columns),0)
    lengths+=sum((func.coalesce(func.length(column),0) for column in model.__table__.columns if isinstance(column.type,LargeBinary)),0)
    size=query.with_entities(func.sum(lengths)).scalar() or 0
    if size>32*1024**2:
        raise HTTPException(422,'Private reading history exceeds the 32 MiB review limit; no changes were made')
    checksum=hashlib.sha256()
    for row in query.populate_existing().order_by(model.id).yield_per(250):
        payload=json.dumps({column.name:(float(getattr(row,column.name)) if isinstance(column.type,Float) and getattr(row,column.name) is not None else getattr(row,column.name)) for column in model.__table__.columns},sort_keys=True,default=str,ensure_ascii=False,separators=(',',':')).encode()
        checksum.update(len(payload).to_bytes(8,'big'));checksum.update(payload)
    return checksum.hexdigest()


def manifest(db, novel_id):
    query = db.query(Chapter).filter_by(novel_id=novel_id)
    if query.with_entities(Chapter.id).count() > MAX_CHAPTERS:
        raise HTTPException(422, f'This preview supports up to {MAX_CHAPTERS:,} chapters per story; no changes were made')
    # JSON path is a SQL projection: never materialize book-sized rich bodies.
    # Hash in SQL so a same-size edit within timestamp precision still fences
    # the review, without transporting or retaining whole chapter bodies.
    if db.bind.dialect.name == 'sqlite':
        connection = db.connection().connection.driver_connection
        connection.create_function('nexus_source_sha256', 1, lambda value: hashlib.sha256((value or '').encode()).hexdigest(), deterministic=True)
        text_hash = func.nexus_source_sha256(Chapter.content)
        document_hash = func.nexus_source_sha256(cast(Chapter.document, Text))
    else:
        text_hash = func.encode(func.sha256(func.convert_to(func.coalesce(Chapter.content, ''), 'UTF8')), 'hex')
        document_hash = func.encode(func.sha256(func.convert_to(func.coalesce(cast(Chapter.document, Text), ''), 'UTF8')), 'hex')
    columns = (Chapter.id, Chapter.chapter_key, Chapter.chapter_number, Chapter.title, Chapter.site_chapter_id,
        Chapter.source_url, Chapter.category, Chapter.content_status, Chapter.audio_status,
        Chapter.document['content_version'].as_string(), func.length(Chapter.content),
        func.length(cast(Chapter.document, Text)), Chapter.updated_at, text_hash, document_hash)
    return [dict(id=id, chapter_key=key, chapter_number=number, title=title, site_chapter_id=stable,
        source_url=url, category=category, content_status=status.value, audio_status=audio.value,
        version=version, content_length=text_length, document_length=document_length, updated_at=updated, text_hash=plain_hash, document_hash=rich_hash)
        for id,key,number,title,stable,url,category,status,audio,version,text_length,document_length,updated,plain_hash,rich_hash
        in query.with_entities(*columns).order_by(Chapter.chapter_number, Chapter.id)]


def active_reason(db, user_id, novel_id):
    for model in (ChapterDownloadJob, ChapterAudioJob, TranslationJob, AudioExportJob, PodcastAudioJob):
        if db.query(model.id).filter_by(user_id=user_id, novel_id=novel_id).filter(model.status.in_(ACTIVE)).first():
            return 'Wait for active downloads, narration, translation and exports to finish before switching sources'
    if db.query(Chapter.id).filter_by(novel_id=novel_id).filter(or_(Chapter.content_status == 'PROCESSING', Chapter.audio_status == 'PROCESSING')).first():
        return 'Wait for active chapter processing to finish before switching sources'
    return None


def target_reason(db, user_id, novel_id):
    if active_reason(db, user_id, novel_id):
        return active_reason(db, user_id, novel_id)
    for model in (ReadingProgress, ReadingRun, ReadingHistory, ReadingAnnotation):
        if db.query(model.id).filter_by(user_id=user_id, novel_id=novel_id).first():
            # A known untouched undo tombstone is a safe empty target. Never
            # infer pristine ownership from an arbitrary zero-percent save.
            last = db.query(SourceMigration).filter_by(user_id=user_id, target_novel_id=novel_id, status='undone').order_by(SourceMigration.id.desc()).first()
            if last and last.target_guard == state_digest(db, user_id, novel_id):
                return None
            return 'Choose a target with no reading history, progress or annotations'
    if db.query(ChapterReadReceipt.id).join(Chapter, Chapter.id == ChapterReadReceipt.chapter_id).filter(
        ChapterReadReceipt.user_id == user_id, Chapter.novel_id == novel_id).first():
        return 'Choose a target with no existing read confirmations'
    return None


def story_ref(db, user_id, novel, *, target=False):
    point, run = progress(db, user_id, novel.id)
    reason = target_reason(db, user_id, novel.id) if target else active_reason(db, user_id, novel.id)
    return dict(novel_id=novel.id, library_id=novel.library_id, title=novel.title,
        site=novel.site or novel.novel_site, source_url=novel.source_url or novel.url,
        chapter_count=db.query(Chapter.id).filter_by(novel_id=novel.id).count(),
        current_progress=runs.progress_view(point), eligible=reason is None, blocked_reason=reason)


def state_digest(db, user_id, novel_id, chapters=None):
    from app.services.chapter_identity_service import manifest_state
    from app.models.translation import StoryGlossary
    from app.models.reader_guide import PrivateGuideJob, PrivateGuideArtifact
    from app.models.reading_progress import ReadingProgressOperation
    from app.models.import_reading_review import ImportReadingReview
    from app.models.portable_story_link import PortableStoryLink
    point, run = progress(db, user_id, novel_id)
    novel = owned(db, user_id, novel_id)
    tables = [ReadingProgress, ReadingRun, ReadingRunEvent, ReadingHistory, ReadingAnnotation, ReaderPreference, NovelPersonalData,
        ReadingProgressOperation, StoryGlossary, PrivateGuideJob, PrivateGuideArtifact,
        ImportReadingReview,
        PortableStoryLink,
        ChapterDownloadJob, ChapterAudioJob, TranslationJob, AudioExportJob, PodcastAudioJob]
    state = {model.__tablename__: rows_state(db.query(model).filter_by(user_id=user_id, novel_id=novel_id)) for model in tables}
    state['receipts'] = rows_state(db.query(ChapterReadReceipt).join(Chapter, Chapter.id == ChapterReadReceipt.chapter_id).filter(
        ChapterReadReceipt.user_id == user_id, Chapter.novel_id == novel_id))
    state['chapters'] = chapters if chapters is not None else manifest(db, novel_id)
    topology = manifest_state(db, novel_id)
    state['manifest'] = {column.name:getattr(topology,column.name) for column in topology.__table__.columns}
    state['novel'] = {key:getattr(novel,key) for key in ('id', 'library_id', 'title', 'site', 'novel_site', 'source_url', 'url', 'site_story_id', 'story_id', 'metadata_id', 'updated_at')}
    if run and run.continuity_key:
        group = ensure_existing_continuity(db, user_id, run.continuity_key)
        state['continuity'] = {column.name:getattr(group,column.name) for column in group.__table__.columns} if group else None
    return digest(state)


def ensure_existing_continuity(db, user_id, key):
    from app.models.reading_continuity import ReadingContinuity
    return db.query(ReadingContinuity).filter_by(user_id=user_id, continuity_key=key).first()


def namespace(novel):
    try:parsed = urlsplit(novel.source_url or novel.url or '')
    except ValueError:return None
    if parsed.scheme not in ('http', 'https') or not parsed.hostname:
        return None
    site = (novel.site or novel.novel_site or '').casefold()
    # URL path scopes bare chapter IDs to the source WORK, not the site.
    path = parsed.path.rstrip('/')
    if not path or not site:
        return None
    try:
        return site, parsed.scheme.casefold(), parsed.hostname.casefold(), parsed.port, path, parsed.query
    except ValueError:
        return None


def meaningful_title(value):
    normalized = ' '.join(re.findall(r'\w+', unicodedata.normalize('NFKC', value or '').casefold()))
    if normalized in {'untitled','chapter one','chapter two','chapter three','chapter four','chapter five','chapter six','chapter seven','chapter eight','chapter nine','chapter ten','author note','authors note','table of contents'}:return None
    if not normalized or re.fullmatch(r'(?:(?:chapter|ch|part|episode|book|prologue|epilogue)\s*)?[\divxlcdm]*', normalized):
        return None
    return normalized if len(normalized) >= 4 else None


def fingerprint(row):
    # Plaintext fingerprints also match legacy chapters without a rich version.
    # Tiny generic notices are insufficient identity evidence on their own.
    if (row['content_length'] or 0)>=32:return 'text:'+row['text_hash']
    return 'rich:'+row['version'] if row['version'] else None


def equivalent(left, right):
    return bool(left['version'] and left['version'] == right['version'] and left['document_hash'] == right['document_hash'] and left['text_hash'] == right['text_hash'])


def document(db, chapter_id, cache, remaining):
    if chapter_id not in cache:
        chapter = db.query(Chapter.document).filter_by(id=chapter_id).first()
        value = chapter[0] if chapter else None
        size = len(json.dumps(value, ensure_ascii=False).encode())
        remaining[0] -= size
        if remaining[0] < 0:
            raise HTTPException(422, 'Mapped annotation and position content exceeds the 16 MiB review limit; keep annotations on the original story')
        cache[chapter_id] = value
    return cache[chapter_id]


def anchor_ok(db, value, left, right, cache, remaining):
    if not equivalent(left, right) or value.locator_variant or value.locator_content_version != left['version'] or not value.block_id:
        return False
    source = document(db, left['id'], cache, remaining)
    target = document(db, right['id'], cache, remaining)
    if not isinstance(source, dict) or not isinstance(target, dict):
        return False
    source_blocks = {block.get('id'):block for block in source.get('blocks', []) if isinstance(block, dict)}
    target_blocks = {block.get('id'):block for block in target.get('blocks', []) if isinstance(block, dict)}
    left_block, right_block = source_blocks.get(value.block_id), target_blocks.get(value.block_id)
    if left_block is None or right_block is None or left_block != right_block:
        return False
    # Browser offsets count UTF-16 code units, including astral characters.
    text = right_block.get('text', '')
    limit = len(text.encode('utf-16-le')) // 2
    if not isinstance(value.text_offset, int) or not 0 <= value.text_offset <= limit:
        return False
    try:
        prefix = text.encode('utf-16-le')[:value.text_offset * 2].decode('utf-16-le')
        suffix = text[len(prefix):]
    except UnicodeDecodeError:
        return False
    return not value.text_quote or suffix.startswith(value.text_quote)


def compute(db, user_id, value):
    source = owned(db, user_id, value.source_novel_id)
    target = owned(db, user_id, value.target_novel_id)
    if source.id == target.id:
        raise HTTPException(422, 'Choose a different story copy')
    source_rows, target_rows = manifest(db, source.id), manifest(db, target.id)
    from app.services.chapter_identity_service import manifest_state
    source_state=manifest_state(db,source.id)
    point, run = progress(db, user_id, source.id)
    reasons = [reason for reason in (active_reason(db,user_id,source.id), target_reason(db,user_id,target.id)) if reason]
    if point is None or run is None or point.chapter_number is None:
        reasons.append('The original story needs a saved reading position before switching sources')
    if point is not None:
        for key,number,present in ((point.chapter_key,point.chapter_number,True),(point.furthest_chapter_key,point.furthest_chapter_number,bool(point.furthest_chapter_key or point.furthest_chapter_number!=0 or point.furthest_percent))):
            if not present:continue
            if key is None:
                if source_state.identity_required:
                    reasons.append('Review the original saved position against the current chapter identities before switching sources')
            elif not any(row['chapter_key']==key and row['chapter_number']==number for row in source_rows):
                reasons.append('A saved chapter identity no longer matches its position; review the original reading position first')
    sources, targets = {row['id']:row for row in source_rows}, {row['id']:row for row in target_rows}
    overrides = {row.source_chapter_id:row.target_chapter_id for row in value.mappings}
    if any(key not in sources or (destination is not None and destination not in targets) for key,destination in overrides.items()):
        raise HTTPException(404, 'A mapped chapter is unavailable in the selected owned story copies')
    title_index, version_index, stable_index = defaultdict(list), defaultdict(list), defaultdict(list)
    for row in target_rows:
        title = meaningful_title(row['title'])
        if title:title_index[title].append(row['id'])
        if fingerprint(row):version_index[fingerprint(row)].append(row['id'])
        if row['site_chapter_id'] is not None:stable_index[row['site_chapter_id']].append(row['id'])
    source_titles = Counter(meaningful_title(row['title']) for row in source_rows)
    source_versions = Counter(fingerprint(row) for row in source_rows if fingerprint(row))
    source_stable = Counter(row['site_chapter_id'] for row in source_rows if row['site_chapter_id'] is not None)
    same_namespace = namespace(source) is not None and namespace(source) == namespace(target)
    notes_query = db.query(ReadingAnnotation).filter_by(user_id=user_id, novel_id=source.id)
    if notes_query.count() > 20_000:
        raise HTTPException(422, 'There are more than 20,000 annotations in this story; no changes were made')
    note_size=notes_query.with_entities(func.sum(func.coalesce(func.length(ReadingAnnotation.note),0)+func.coalesce(func.length(ReadingAnnotation.quote),0))).scalar() or 0
    if note_size>MAX_ANCHOR_BYTES:
        raise HTTPException(422, 'Annotation text exceeds the 16 MiB review limit; no changes were made')
    notes=notes_query.order_by(ReadingAnnotation.id).all()
    if len(notes) > 20_000:
        raise HTTPException(422, 'There are more than 20,000 annotations in this story; no changes were made')
    by_chapter = defaultdict(list)
    for note in notes:
        chapter = sources.get(note.chapter_id)
        if chapter and note.chapter_key == chapter['chapter_key']:
            by_chapter[note.chapter_id].append(note)
    receipts = {row.chapter_id:row for row in db.query(ChapterReadReceipt).join(Chapter,Chapter.id==ChapterReadReceipt.chapter_id).filter(
        ChapterReadReceipt.user_id==user_id,Chapter.novel_id==source.id,ChapterReadReceipt.content_version==Chapter.document['content_version'].as_string(),ChapterReadReceipt.completed.is_(True),ChapterReadReceipt.requires_review.is_(False)).all()
        if row.content_version==sources[row.chapter_id]['version'] and row.chapter_key==sources[row.chapter_id]['chapter_key']}
    from app.services.reading_checkpoint_service import checkpoint_rows
    checkpoints=checkpoint_rows(db,user_id,source.id,point,run,strong_identity=True)
    confirmed={(row.chapter_key,row.content_version) for row in db.query(checkpoints).filter(checkpoints.c.max_percent>=100)}
    required = set()
    if point is not None:
        for row in source_rows:
            if row['chapter_number'] == point.chapter_number:
                required.add(row['id'])
            if not (point.furthest_chapter_number == 0 and (point.furthest_percent or 0) == 0) and row['chapter_number'] == point.furthest_chapter_number:
                required.add(row['id'])
        expected = 1 + int(not (point.furthest_chapter_number == 0 and (point.furthest_percent or 0) == 0) and point.chapter_number != point.furthest_chapter_number)
        if len(required) != expected:reasons.append('A saved current or furthest chapter is missing; repair the original reading position first')
    cache, remaining = {}, [MAX_ANCHOR_BYTES]
    items, copy_notes, copy_receipts = [], [], []
    for left in source_rows:
        evidence = defaultdict(list)
        title = meaningful_title(left['title'])
        if same_namespace and left['site_chapter_id'] is not None:
            for id in stable_index[left['site_chapter_id']][:21]:evidence[id].append('stable_id')
        if fingerprint(left):
            for id in version_index[fingerprint(left)][:21]:evidence[id].append('content_fingerprint')
        if title:
            for id in title_index[title][:21]:evidence[id].append('title')
        # An automatic match requires a unique source AND target evidence key.
        # Contradictory unique signals are ambiguous rather than ranked away.
        unique = set()
        if same_namespace and left['site_chapter_id'] is not None and source_stable[left['site_chapter_id']] == 1 and len(stable_index[left['site_chapter_id']]) == 1:
            unique.update(stable_index[left['site_chapter_id']])
        if fingerprint(left) and source_versions[fingerprint(left)] == 1 and len(version_index[fingerprint(left)]) == 1:
            unique.update(version_index[fingerprint(left)])
        if title and source_titles[title] == 1 and len(title_index[title]) == 1:
            unique.update(title_index[title])
        destination = next(iter(unique)) if len(unique) == 1 else None
        decision = 'matched' if destination is not None else ('ambiguous' if evidence else 'unmatched')
        if left['id'] in overrides:
            destination = overrides[left['id']]
            decision = 'manual' if destination is not None else 'skipped'
            if destination is not None:evidence[destination].append('manual')
        right = targets.get(destination)
        copyable = []
        if right:
            for note in by_chapter[left['id']]:
                if anchor_ok(db,note,left,right,cache,remaining):copyable.append(note.id)
        copy_notes.extend((id,destination) for id in copyable)
        receipt = bool(right and equivalent(left,right) and left['id'] in receipts and (left['chapter_key'],left['version']) in confirmed)
        if receipt:copy_receipts.append((left['id'],destination,left['version']))
        approximate = bool(point is not None and left['chapter_number'] == point.chapter_number and right and not anchor_ok(db,point,left,right,cache,remaining))
        candidates = sorted(evidence, key=lambda id:(targets[id]['chapter_number'],id))
        items.append(dict(source_chapter_id=left['id'], source_chapter_number=left['chapter_number'], source_title=left['title'],
            candidates=[dict(target_chapter_id=id, chapter_number=targets[id]['chapter_number'], title=targets[id]['title'], evidence=evidence[id],content_equal=equivalent(left,targets[id])) for id in candidates[:20]],
            candidates_truncated=len(candidates)>20, selected_target_chapter_id=destination, decision=decision,
            required_for_progress=left['id'] in required, annotation_count=len(by_chapter[left['id']]),annotations_copyable=len(copyable),
            approximate_position=approximate,receipt_copyable=receipt))
    selected = [row['selected_target_chapter_id'] for row in items if row['selected_target_chapter_id'] is not None]
    collisions = {key for key,count in Counter(selected).items() if count > 1}
    if collisions:
        for row in items:
            if row['selected_target_chapter_id'] in collisions:row['decision']='ambiguous'
        reasons.append('Multiple original chapters map to one target; choose distinct target chapters')
    target_order=[targets[row['selected_target_chapter_id']]['chapter_number'] for row in items if row['selected_target_chapter_id'] is not None]
    if target_order!=sorted(target_order):
        reasons.append('Chapter mappings reverse the story order; choose increasing target chapters before applying')
    source_preferences=db.query(ReaderPreference).filter_by(user_id=user_id,scope=f'story:{source.id}').first()
    target_preferences=db.query(ReaderPreference).filter_by(user_id=user_id,scope=f'story:{target.id}').first()
    copy_preferences=None
    if source_preferences is not None and target_preferences is None:
        from app.schemas.reader_preferences import PreferenceValues
        from pydantic import ValidationError
        try:
            copy_preferences=PreferenceValues.model_validate({key:val for key,val in source_preferences.values.items() if key in {'typography','layout','authorNotes','shortcuts'}}).model_dump(exclude_unset=True)
        except (ValidationError,AttributeError):pass
    source_personal=db.query(NovelPersonalData).filter_by(user_id=user_id,novel_id=source.id).first()
    target_personal=db.query(NovelPersonalData).filter_by(user_id=user_id,novel_id=target.id).first()
    copy_categories=source_personal.followed_categories if source_personal is not None and source_personal.followed_categories is not None and target_personal is None else None
    from app.services.library_organization_service import followed_categories_of
    effective_categories=copy_categories if copy_categories is not None else followed_categories_of(target_personal)
    required_targets={row['selected_target_chapter_id'] for row in items if row['required_for_progress'] and row['selected_target_chapter_id'] is not None}
    followed_targets={row['id'] for row in target_rows if row['category'] in effective_categories}
    if required_targets-followed_targets:
        reasons.append('Current and furthest target chapters must be included in the target story’s followed categories')
    mapped_keys={sources[row['source_chapter_id']]['chapter_key'] for row in items if row['selected_target_chapter_id'] is not None}
    history_count=0
    if run is not None:
        # Count exactly the current run. Lifetime rows from earlier readings
        # must never reintroduce future chapters after a reread.
        for key,count in db.query(ReadingHistory.chapter_key,func.count(ReadingHistory.id)).filter_by(user_id=user_id,novel_id=source.id,reading_run_key=run.run_key).group_by(ReadingHistory.chapter_key):
            if key in mapped_keys:history_count+=count
    if history_count>200_000:
        raise HTTPException(422,'This reading run exceeds 200,000 chapter checkpoints; no changes were made')
    unresolved = sum(row['decision'] in ('ambiguous','unmatched') or (row['required_for_progress'] and row['decision']=='skipped') for row in items)
    if unresolved:reasons.append('Map or explicitly skip every unresolved chapter; current and furthest chapters cannot be skipped')
    if not selected:reasons.append('Select at least one chapter mapping')
    # Only safe anchors/receipts copy. Original rows are never edited.
    counts = dict(mapped=len(selected), skipped=sum(row['decision']=='skipped' for row in items),unresolved=unresolved,
        annotations_copied=len(copy_notes),annotations_retained=len(notes)-len(copy_notes),receipts_copied=len(copy_receipts),history_copied=history_count,preferences_copied=int(copy_preferences is not None),followed_categories_copied=int(copy_categories is not None))
    guard = digest([state_digest(db,user_id,source.id,source_rows),state_digest(db,user_id,target.id,target_rows),
        value.model_dump(mode='json'),[(row['source_chapter_id'],row['selected_target_chapter_id']) for row in items],copy_notes,copy_receipts])
    return dict(source=story_ref(db,user_id,source),target=story_ref(db,user_id,target,target=True),items=items,counts=counts,
        warnings=list(dict.fromkeys(reasons + ['Original content, annotations, analysis and generated files stay on the original story.',
            'Changed text carries only an approximate percentage; translated positions and uncertain anchors are not copied.',
            'Reader settings and followed categories copy only when absent on the target. Existing settings stay unchanged; automatic downloads, notifications, notes and ratings are never copied.'])),
        can_apply=not reasons,guard=guard,copy_preferences=copy_preferences,copy_categories=copy_categories,copy_notes=copy_notes,copy_receipts=copy_receipts,point=point,run=run,sources=sources,targets=targets)


def preview(db,user_id,value,offset=0,limit=100):
    result=compute(db,user_id,value)
    expires=utcnow()+timedelta(minutes=15)
    token=jwt.encode({'type':'source_migration_review','sub':str(user_id),'guard':result['guard'],'exp':expires.replace(tzinfo=timezone.utc)},settings.SECRET_KEY,algorithm=settings.ALGORITHM) if result['can_apply'] else None
    return dict(total=len(result['items']),offset=offset,limit=limit,source=result['source'],target=result['target'],
        items=result['items'][offset:offset+limit],counts=result['counts'],warnings=result['warnings'],can_apply=result['can_apply'],
        review_token=token,expires_at=expires.isoformat()+'Z' if token else None)


def target_list(db,user_id,source_novel_id,q,offset,limit):
    owned(db,user_id,source_novel_id)
    query=db.query(Novel).join(Library).filter(Library.user_id==user_id,Novel.id!=source_novel_id)
    if q:query=query.filter(Novel.title.ilike('%'+q.replace('%','\\%').replace('_','\\_')+'%',escape='\\'))
    return dict(total=query.count(),offset=offset,limit=limit,items=[story_ref(db,user_id,row,target=True) for row in query.order_by(Novel.title,Novel.id).offset(offset).limit(limit)])


def chapter_list(db,user_id,novel_id,offset,limit):
    owned(db,user_id,novel_id)
    query=db.query(Chapter.id,Chapter.chapter_number,Chapter.title).filter_by(novel_id=novel_id)
    return dict(total=query.count(),offset=offset,limit=limit,items=[dict(id=id,chapter_number=number,title=title) for id,number,title in query.order_by(Chapter.chapter_number,Chapter.id).offset(offset).limit(limit)])


def replay(db,user_id,operation_id,fingerprint):
    receipt=db.query(SourceMigrationOperation).filter_by(user_id=user_id,operation_id=operation_id).first()
    if receipt:
        if receipt.fingerprint != fingerprint:conflict('operation_reused','This action identifier was used for a different change')
        record=db.query(SourceMigration).filter_by(id=receipt.migration_id,user_id=user_id).first()
        if record is None:raise HTTPException(404,'Source migration not found')
        return receipt.response
    return None


def store_receipt(db,user_id,row,operation_id,fingerprint,response):
    response=json.loads(json.dumps(response,default=lambda value:value.isoformat()))
    db.add(SourceMigrationOperation(user_id=user_id,migration_id=row.id,operation_id=operation_id,fingerprint=fingerprint,response=response))
    db.commit()
    return response


def apply(db,user_id,value):
    signature=digest(['source_migration_apply',value.model_dump(mode='json')])
    db.query(User).filter_by(id=user_id).with_for_update().first()
    old=replay(db,user_id,value.operation_id,signature)
    if old is not None:return old
    lock(db,user_id,value.source_novel_id,value.target_novel_id)
    try:
        token=jwt.decode(value.review_token,settings.SECRET_KEY,algorithms=[settings.ALGORITHM])
        if token.get('type')!='source_migration_review' or token.get('sub')!=str(user_id):raise ValueError()
    except (JWTError,ValueError):conflict('review_expired','This review expired or is unavailable; preview the selected chapters again')
    from app.schemas.source_migration import SourceMigrationPreviewInput
    selected=SourceMigrationPreviewInput.model_validate(value.model_dump(exclude={'review_token','operation_id'}))
    review=compute(db,user_id,selected)
    if not review['can_apply'] or token.get('guard')!=review['guard']:
        conflict('review_changed','Story content, reading state or chapter choices changed; review the migration again')
    source_run=review['run']
    ensure_continuity(db,source_run)
    # Undo tombstones are known pristine but must be archived before installing
    # the next continuity; keep their fences/history rather than reusing a key.
    old_point,old_run=progress(db,user_id,value.target_novel_id)
    revision=(old_point.revision or 0) if old_point else 0
    if old_run:old_run.archived_at=utcnow()
    run=ReadingRun(user_id=user_id,novel_id=value.target_novel_id,run_key=str(uuid4()),ordinal=runs.next_ordinal(db,user_id,value.target_novel_id),
        status='active',requires_run_key=True,started_at=utcnow(),started_at_inferred=False,progress_snapshot={})
    db.add(run);db.flush();join_new_run(db,source_run,run)
    source_point=review['point']
    number_map={review['sources'][item['source_chapter_id']]['chapter_number']:review['targets'][item['selected_target_chapter_id']]
        for item in review['items'] if item['selected_target_chapter_id'] is not None}
    current=number_map[source_point.chapter_number]
    point=db.query(ReadingProgress).filter_by(user_id=user_id,novel_id=value.target_novel_id).first()
    if point is None:
        point=ReadingProgress(user_id=user_id,novel_id=value.target_novel_id)
        db.add(point)
    point.chapter_id=current['id'];point.chapter_number=current['chapter_number'];point.percent=source_point.percent
    from app.services.chapter_identity_service import manifest_state
    target_state = manifest_state(db,value.target_novel_id,lock=True)
    point.chapter_key=current['chapter_key'];point.manifest_epoch=target_state.manifest_epoch
    point.manifest_revision=str(target_state.revision)
    original_current=next(row for row in review['sources'].values() if row['chapter_number']==source_point.chapter_number)
    current_proven=source_point.chapter_key==original_current['chapter_key'] and not source_point.current_identity_inferred and source_point.source_content_version==original_current['version']
    point.current_identity_inferred=not current_proven
    point.source_content_version=current['version'] if current_proven and equivalent(original_current,current) else None
    point.position=0;point.revision=revision+1;point.reading_run_key=run.run_key;point.device_id=None
    empty_boundary=source_point.furthest_chapter_number==0 and (source_point.furthest_percent or 0)==0
    point.furthest_chapter_number=0 if empty_boundary else number_map[source_point.furthest_chapter_number]['chapter_number']
    point.furthest_percent=0 if empty_boundary else source_point.furthest_percent
    furthest=None if empty_boundary else number_map[source_point.furthest_chapter_number]
    point.furthest_chapter_key=furthest['chapter_key'] if furthest else None
    original_furthest=next((row for row in review['sources'].values() if row['chapter_number']==source_point.furthest_chapter_number),None)
    furthest_proven=bool(original_furthest and source_point.furthest_chapter_key==original_furthest['chapter_key'] and not source_point.furthest_identity_inferred and source_point.furthest_content_version==original_furthest['version'])
    point.furthest_identity_inferred=int(bool(furthest) and not furthest_proven)
    point.furthest_content_version=furthest['version'] if furthest_proven and equivalent(original_furthest,furthest) else None
    source_current=next(row for row in review['items'] if row['source_chapter_number']==source_point.chapter_number)
    for name in LOCATORS:setattr(point,name,0 if name=='text_offset' else None)
    if not source_current['approximate_position']:
        point.position=source_point.position
        for name in LOCATORS:setattr(point,name,getattr(source_point,name))
    # No completion event or daily activity is copied or invented.
    db.flush();run.progress_snapshot=runs.snapshot_progress(run,point)
    preference_id=None;personal_id=None
    if review['copy_preferences'] is not None:
        preference=ReaderPreference(user_id=user_id,novel_id=value.target_novel_id,scope=f'story:{value.target_novel_id}',revision=1,values=review['copy_preferences'])
        db.add(preference);db.flush();preference_id=preference.id
    if review['copy_categories'] is not None:
        personal=NovelPersonalData(user_id=user_id,novel_id=value.target_novel_id,followed_categories=review['copy_categories'],auto_download=False,notify_when_complete=False)
        db.add(personal);db.flush();personal_id=personal.id
    created_notes=[];created_receipts=[]
    for note_id,target_id in review['copy_notes']:
        original=db.query(ReadingAnnotation).filter_by(id=note_id,user_id=user_id).one()
        fields={column.name:getattr(original,column.name) for column in original.__table__.columns if column.name not in ('id','created_at','updated_at','novel_id','chapter_id','chapter_key','chapter_number','exported_at','export_key')}
        target_chapter=review['targets'][target_id]
        note=ReadingAnnotation(**fields,novel_id=value.target_novel_id,chapter_id=target_id,
            chapter_key=target_chapter['chapter_key'],chapter_number=target_chapter['chapter_number'],exported_at=None)
        db.add(note);db.flush();created_notes.append(note.id)
    for source_id,target_id,version in review['copy_receipts']:
        receipt=ChapterReadReceipt(user_id=user_id,chapter_id=target_id,content_version=version,completed=True,requires_review=False)
        db.add(receipt);db.flush();created_receipts.append(receipt.id)
    created_history=[]
    original_history=db.query(ReadingHistory).filter_by(user_id=user_id,novel_id=value.source_novel_id,reading_run_key=source_run.run_key).order_by(ReadingHistory.id)
    sources_by_key={chapter['chapter_key']:chapter for chapter in review['sources'].values()}
    pending=[]
    for original in original_history.yield_per(500):
        source_history=sources_by_key.get(original.chapter_key)
        mapped=number_map.get(source_history['chapter_number']) if source_history else None
        # Old unbound history remains in the original reading. A display number
        # cannot authorize copying a completion onto another chapter lifecycle.
        if mapped is None:continue
        strong=not original.identity_inferred and original.verified_content_version==source_history['version'] and equivalent(source_history,mapped)
        copied=ReadingHistory(user_id=user_id,novel_id=value.target_novel_id,chapter_number=mapped['chapter_number'],chapter_key=mapped['chapter_key'],
            identity_inferred=not strong,verified_content_version=mapped['version'] if strong else None,verified_percent=original.verified_percent if strong else 0,
            reading_date=original.reading_date,max_percent=original.max_percent,reading_run_key=run.run_key)
        db.add(copied);pending.append(copied)
        if len(pending)>=500:
            db.flush();created_history.extend(item.id for item in pending);pending=[]
    db.flush();created_history.extend(item.id for item in pending)
    row=SourceMigration(user_id=user_id,source_novel_id=value.source_novel_id,target_novel_id=value.target_novel_id,status='applied',revision=1,
        plan={'source':review['source'],'target':review['target'],'source_novel_id':value.source_novel_id,'target_novel_id':value.target_novel_id,'mappings':[dict(source_chapter_id=item['source_chapter_id'],target_chapter_id=item['selected_target_chapter_id']) for item in review['items']],
              'source_guard':state_digest(db,user_id,value.source_novel_id)},counts=review['counts'],
        created_rows={'annotations':created_notes,'receipts':created_receipts,'history':created_history,'preference_id':preference_id,'personal_id':personal_id,'run_key':run.run_key,'prior_work_key':None},target_guard='')
    db.add(row);db.flush();row.target_guard=state_digest(db,user_id,value.target_novel_id);db.flush()
    return store_receipt(db,user_id,row,value.operation_id,signature,record_view(db,user_id,row))


def undo_reason(db,user_id,row):
    if row.source_novel_id is None or row.target_novel_id is None:return 'An original or target story was deleted; this audit remains available but cannot be undone'
    for novel_id in (row.source_novel_id,row.target_novel_id):
        if db.query(Novel.id).join(Library).filter(Novel.id==novel_id,Library.user_id==user_id).first() is None:return 'A story copy is no longer available to this account'
    if row.status!='applied':return 'This migration has already been undone'
    reason=active_reason(db,user_id,row.source_novel_id) or active_reason(db,user_id,row.target_novel_id)
    if reason:return reason
    if state_digest(db,user_id,row.target_novel_id)!=row.target_guard:
        return 'The target story or its reading state changed after migration; undo would overwrite later changes'
    return None


def record_view(db,user_id,row):
    def reference(key, novel_id, target=False):
        novel=db.query(Novel).join(Library).filter(Novel.id==novel_id,Library.user_id==user_id).first() if novel_id is not None else None
        if novel is not None:return story_ref(db,user_id,novel,target=target)
        return {**row.plan[key], 'current_progress':None,'eligible':False,'blocked_reason':'This story copy is no longer available'}
    source=reference('source',row.source_novel_id)
    target=reference('target',row.target_novel_id,target=True)
    reason=undo_reason(db,user_id,row)
    return dict(id=row.id,revision=row.revision,status=row.status,source=source,target=target,
        mappings=row.plan['mappings'],counts=row.counts,created_at=row.created_at.isoformat()+'Z',
        undone_at=row.undone_at.isoformat()+'Z' if row.undone_at else None,target_progress=target['current_progress'],
        can_undo=reason is None,undo_blocked_reason=reason)


def detail(db,user_id,id):
    row=db.query(SourceMigration).filter_by(user_id=user_id,id=id).first()
    if row is None:raise HTTPException(404,'Source migration not found')
    return record_view(db,user_id,row)


def history(db,user_id,novel_id,offset,limit):
    query=db.query(SourceMigration).filter_by(user_id=user_id)
    if novel_id is not None:
        owned(db,user_id,novel_id)
        query=query.filter(or_(SourceMigration.source_novel_id==novel_id,SourceMigration.target_novel_id==novel_id))
    return dict(total=query.count(),offset=offset,limit=limit,items=[record_view(db,user_id,row) for row in query.order_by(SourceMigration.id.desc()).offset(offset).limit(limit)])


def undo(db,user_id,id,value):
    row=db.query(SourceMigration).filter_by(user_id=user_id,id=id).first()
    if row is None:raise HTTPException(404,'Source migration not found')
    db.query(User).filter_by(id=user_id).with_for_update().first()
    signature=digest(['source_migration_undo',id,value.model_dump(mode='json')])
    old=replay(db,user_id,value.operation_id,signature)
    if old is not None:return old
    if row.source_novel_id is None or row.target_novel_id is None:conflict('undo_changed','A story copy was deleted; undo is unavailable')
    lock(db,user_id,row.source_novel_id,row.target_novel_id)
    row=db.query(SourceMigration).filter_by(user_id=user_id,id=id).populate_existing().one()
    signature=digest(['source_migration_undo',id,value.model_dump(mode='json')])
    old=replay(db,user_id,value.operation_id,signature)
    if old is not None:return old
    if row.revision!=value.expected_revision:conflict('migration_conflict','Migration state changed; reload before undoing')
    reason=undo_reason(db,user_id,row)
    if reason:conflict('undo_changed',reason)
    point,run=progress(db,user_id,row.target_novel_id)
    first=runs.followed_chapters(db,user_id,row.target_novel_id).order_by(Chapter.chapter_number,Chapter.id).first() or db.query(Chapter).filter_by(novel_id=row.target_novel_id).order_by(Chapter.chapter_number,Chapter.id).first()
    if first is None:conflict('undo_changed','The target no longer has followed chapters')
    # Remove only rows created by this migration. Keep the old run as archived
    # provenance; its key can never become current again.
    db.query(ReadingAnnotation).filter(ReadingAnnotation.user_id==user_id,ReadingAnnotation.id.in_(row.created_rows['annotations'])).delete(synchronize_session=False)
    db.query(ChapterReadReceipt).filter(ChapterReadReceipt.user_id==user_id,ChapterReadReceipt.id.in_(row.created_rows['receipts'])).delete(synchronize_session=False)
    for start in range(0,len(row.created_rows.get('history',[])),500):
        db.query(ReadingHistory).filter(ReadingHistory.user_id==user_id,ReadingHistory.id.in_(row.created_rows['history'][start:start+500])).delete(synchronize_session=False)
    if row.created_rows.get('preference_id') is not None:
        db.query(ReaderPreference).filter_by(user_id=user_id,id=row.created_rows['preference_id']).delete(synchronize_session=False)
    if row.created_rows.get('personal_id') is not None:
        db.query(NovelPersonalData).filter_by(user_id=user_id,id=row.created_rows['personal_id']).delete(synchronize_session=False)
    db.flush()
    first=runs.followed_chapters(db,user_id,row.target_novel_id).order_by(Chapter.chapter_number,Chapter.id).first() or db.query(Chapter).filter_by(novel_id=row.target_novel_id).order_by(Chapter.chapter_number,Chapter.id).first()
    if first is None:conflict('undo_changed','The original target settings have no followed chapters')
    run.archived_at=utcnow()
    blank=ReadingRun(user_id=user_id,novel_id=row.target_novel_id,run_key=str(uuid4()),ordinal=runs.next_ordinal(db,user_id,row.target_novel_id),
        status='active',requires_run_key=True,started_at=None,started_at_inferred=True,progress_snapshot={})
    db.add(blank);db.flush()
    # A blank undo is a fence, not a new reading. Do not manufacture a started
    # event or attach it to the source's completed canonical work.
    point.chapter_id=first.id;point.chapter_number=first.chapter_number;point.percent=0;point.position=0
    from app.services.chapter_identity_service import manifest_state
    target_state=manifest_state(db,row.target_novel_id,lock=True)
    point.chapter_key=first.chapter_key;point.current_identity_inferred=False;point.source_content_version=None
    point.manifest_epoch=target_state.manifest_epoch;point.manifest_revision=str(target_state.revision)
    point.furthest_chapter_key=None;point.furthest_content_version=None;point.furthest_identity_inferred=0
    point.furthest_chapter_number=0;point.furthest_percent=0;point.revision=(point.revision or 0)+1;point.reading_run_key=blank.run_key
    for name in LOCATORS:setattr(point,name,0 if name=='text_offset' else None)
    point.device_id=None
    db.flush();blank.progress_snapshot=runs.snapshot_progress(blank,point)
    db.query(ReadingRunEvent).filter_by(user_id=user_id,run_key=run.run_key).delete(synchronize_session=False)
    db.delete(run);db.flush()
    ensure_continuity(db,blank,logical_ordinal=1)
    row.status='undone';row.revision+=1;row.undone_at=utcnow()
    db.flush();row.target_guard=state_digest(db,user_id,row.target_novel_id);db.flush()
    return store_receipt(db,user_id,row,value.operation_id,signature,record_view(db,user_id,row))
