"""Private EPUBs from exact saved variants; no translation/provider work occurs here."""
import hashlib
import json
import re
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import LargeBinary, Text, cast, func
from sqlalchemy.orm import load_only

from app.models import Chapter, Library, Novel
from app.models.translation import TranslationJob
from app.services.chapter_document import from_text
from app.services.epub_service import render_epub

MAX_INPUT_BYTES = 20 * 1024**2
MAX_OUTPUT_BYTES = 40 * 1024**2
MAX_BLOCKS = 20_000
MAX_LEGACY_SOURCE_BYTES = 8 * 1024**2


def owned_story(db, user_id, novel_id):
    novel = db.query(Novel).join(Library).filter(Novel.id == novel_id, Library.user_id == user_id).first()
    if novel is None:
        raise HTTPException(404, 'Story not found')
    return novel


def byte_length(db, column):
    text = cast(column, Text)
    return func.length(cast(text, LargeBinary)) if db.get_bind().dialect.name == 'sqlite' else func.octet_length(text)


def current_version(db, chapter_id, extracted_version, legacy_budget):
    if extracted_version is not None:
        return extracted_version
    # Legacy plain-text chapters need the original transformation to derive an
    # identical fingerprint. Bound this exceptional load before fetching it.
    sizes = db.query(byte_length(db, Chapter.content), byte_length(db, Chapter.document)).filter_by(id=chapter_id).execution_options(include_archived_chapters=True).one()
    size = sum(size or 0 for size in sizes)
    if size > MAX_LEGACY_SOURCE_BYTES or size > legacy_budget[0]:
        return None
    legacy_budget[0] -= size
    chapter = db.query(Chapter).options(load_only(Chapter.id, Chapter.content, Chapter.document)).filter_by(id=chapter_id).execution_options(include_archived_chapters=True).one()
    document = chapter.document or from_text(chapter.content or '')
    return document.get('content_version') if isinstance(document, dict) else None


def list_variants(db,user_id,novel_id,offset,limit):
    owned_story(db,user_id,novel_id)
    from app.models.chapter_manifest import ChapterManifestState
    state=db.query(ChapterManifestState).filter_by(novel_id=novel_id).populate_existing().first()
    query=db.query(TranslationJob).filter_by(user_id=user_id,novel_id=novel_id)
    total=query.count()
    rows=query.with_entities(TranslationJob.id,TranslationJob.chapter_id,TranslationJob.language,TranslationJob.status,
        TranslationJob.source_version,TranslationJob.error,TranslationJob.provider_snapshot,
        func.json_array_length(TranslationJob.source_blocks).label('total_blocks'),
        func.json_array_length(TranslationJob.translated_blocks).label('completed_blocks'),
        TranslationJob.chapter_key.label('source_chapter_key'),TranslationJob.manifest_epoch.label('source_manifest_epoch'),
        TranslationJob.manifest_revision.label('source_manifest_revision'),TranslationJob.identity_inferred,
        TranslationJob.chapter_title_snapshot,TranslationJob.chapter_number_snapshot,
        Chapter.chapter_number.label('current_number'),Chapter.title.label('current_title'),
        Chapter.chapter_key.label('current_key'),Chapter.archived,
        Chapter.document['content_version'].as_string().label('current_version')).outerjoin(
        Chapter,(Chapter.id==TranslationJob.chapter_id)&(Chapter.novel_id==TranslationJob.novel_id)).execution_options(
        include_archived_chapters=True).order_by(Chapter.chapter_number.nullslast(),TranslationJob.id.desc()).offset(offset).limit(limit).all()
    items=[];legacy_budget=[MAX_INPUT_BYTES]
    for row in rows:
        same=bool(not row.identity_inferred and state is not None and row.source_chapter_key and row.source_chapter_key==row.current_key
            and row.source_manifest_epoch==state.manifest_epoch)
        current=current_version(db,row.chapter_id,row.current_version,legacy_budget) if same else None
        source_current=bool(same and not row.archived and current==row.source_version)
        items.append(dict(id=row.id,chapter_id=row.chapter_id,chapter_number=row.current_number if same else None,
            chapter_title=row.current_title if same else None,chapter_key=row.current_key if same else None,
            manifest_epoch=state.manifest_epoch if same else None,manifest_revision=str(state.revision) if same else None,
            source_chapter_key=row.source_chapter_key,source_manifest_epoch=row.source_manifest_epoch,
            source_manifest_revision=row.source_manifest_revision,source_identity_inferred=bool(row.identity_inferred),
            source_identity_current=same,chapter_archived=bool(same and row.archived),
            chapter_title_snapshot=row.chapter_title_snapshot,chapter_number_snapshot=row.chapter_number_snapshot,
            language=row.language,status=row.status,source_version=row.source_version,current_source_version=current,
            current_content_version=current,source_current=source_current,
            exportable=row.status=='completed' and bool(row.total_blocks) and row.total_blocks==row.completed_blocks,
            completed_blocks=row.completed_blocks or 0,total_blocks=row.total_blocks or 0,
            provider={key:(row.provider_snapshot or {}).get(key) for key in ('kind','model')},error=row.error))
    return dict(novel_id=novel_id,total=total,offset=offset,limit=limit,items=items)


def export_variants(db, user_id, novel_id, ids):
    novel = owned_story(db, user_id, novel_id)
    query = db.query(TranslationJob).filter(TranslationJob.id.in_(ids), TranslationJob.user_id == user_id,
        TranslationJob.novel_id == novel_id)
    # Bound database payload before loading JSON chapter bodies into Python.
    sizes = query.with_entities(TranslationJob.id, byte_length(db, TranslationJob.source_blocks),
        byte_length(db, TranslationJob.translated_blocks)).all()
    if len(sizes) != len(ids):
        raise HTTPException(404, 'A selected translation is missing or does not belong to this story')
    if sum((source or 0) + (translated or 0) for _, source, translated in sizes) > MAX_INPUT_BYTES:
        raise HTTPException(422, 'Selected translations exceed the EPUB size limit; select fewer chapters')
    jobs = query.all()
    languages = {job.language for job in jobs}
    if len(languages) != 1:
        raise HTTPException(422, 'Select translations in one language per EPUB')
    language = jobs[0].language
    if not re.fullmatch(r'[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*', language):
        raise HTTPException(422, 'The saved translation language is invalid')
    if len({job.chapter_key or f'legacy:{job.chapter_id}' for job in jobs}) != len(jobs):
        raise HTTPException(422, 'Select only one translation variant for each chapter')
    chapters = []
    block_count = 0
    for job in jobs:
        chapter=SimpleNamespace(id=job.chapter_id,chapter_number=job.chapter_number_snapshot if job.chapter_number_snapshot is not None else ids.index(job.id)+1,
            title=job.chapter_title_snapshot if job.chapter_title_snapshot is not None else f'Saved translation {job.id}')
        if job.status!='completed':
            raise HTTPException(409,f'Finish translation {job.id} before exporting')
        source, translated = job.source_blocks, job.translated_blocks
        if not isinstance(source, list) or not isinstance(translated, list) or not source or len(source) != len(translated):
            raise HTTPException(409, f'Chapter {chapter.chapter_number} has incomplete translated blocks; retry its translation')
        block_count += len(translated)
        if block_count > MAX_BLOCKS:
            raise HTTPException(422, 'Selected translations contain too many blocks; select fewer chapters')
        source_ids = [block.get('id') if isinstance(block, dict) else None for block in source]
        if any(not isinstance(value, str) or not re.fullmatch(r'b-[a-f0-9]{24}-[0-9]+', value) for value in source_ids) or len(set(source_ids)) != len(source_ids):
            raise HTTPException(409, f'Chapter {chapter.chapter_number} has invalid source anchors; prepare a new translation')
        for original, block in zip(source, translated):
            if not isinstance(original, dict) or not isinstance(block, dict) or not isinstance(block.get('id'), str) or block['id'] != original.get('id') or not isinstance(block.get('html'), str) or not isinstance(block.get('text'), str):
                raise HTTPException(409, f'Chapter {chapter.chapter_number} has invalid block alignment; retry its translation')
        chapters.append(SimpleNamespace(chapter_number=chapter.chapter_number, title=chapter.title,
            content='\n\n'.join(block['text'] for block in translated), document={'blocks': translated}))
    # Independently enforce serialized UTF-8 bounds before rendering.
    if sum(len(json.dumps([job.source_blocks, job.translated_blocks], ensure_ascii=False).encode()) for job in jobs) > MAX_INPUT_BYTES:
        raise HTTPException(422, 'Selected translations exceed the EPUB size limit; select fewer chapters')
    chapters.sort(key=lambda chapter: chapter.chapter_number)
    # EPUB filenames/anchors use unique export ordinals even if archived originals
    # and replacements once shared a numeric source label. Titles stay original.
    for ordinal,chapter in enumerate(chapters,1):chapter.chapter_number=ordinal
    identity = hashlib.sha256(json.dumps(sorted((job.id, job.fingerprint) for job in jobs)).encode()).hexdigest()
    try:
        data = render_epub(novel, chapters, language=language, identifier=f'nexus-private-translation-{identity}')
    except (ValueError, TypeError, KeyError) as exc:
        raise HTTPException(422, 'A saved translation contains invalid formatting or image data; retry that chapter translation') from exc
    if len(data) > MAX_OUTPUT_BYTES:
        raise HTTPException(422, 'The EPUB exceeds the download size limit; select fewer chapters')
    return data, language
