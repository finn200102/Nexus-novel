"""Bounded private metadata for copying existing content; never starts work."""
from pathlib import Path
from fastapi import HTTPException
from sqlalchemy import func, tuple_
from sqlalchemy.orm import load_only
from app.models import Chapter, User
from app.models.chapter import ContentStatus
from app.models.audio_job import ChapterAudioJob
from app.models.translation import TranslationJob
from app.models.novel_personal import NovelPersonalData
from app.services.library_organization_service import followed_categories_of
from app.services.translation_export_service import owned_story, byte_length, current_version, MAX_INPUT_BYTES
from app.services.translation_service import job_view

MAX_TRANSLATIONS_PER_CHAPTER = 20


def manifest(db, user_id, novel_id, offset, limit, *, followed_only=False, from_chapter=None, downloaded_only=False,
             expected_manifest_epoch=None, expected_manifest_revision=None):
    from app.services.chapter_identity_service import manifest_state, state_fields, conflict, sqlite_transaction
    sqlite_transaction(db)
    db.query(User.id).filter_by(id=user_id).with_for_update().first()
    novel = owned_story(db, user_id, novel_id)
    header = state_fields(manifest_state(db, novel_id, lock=True))
    if expected_manifest_epoch is not None or expected_manifest_revision is not None:
        if expected_manifest_epoch != header['manifest_epoch'] or expected_manifest_revision != header['manifest_revision']:
            conflict('chapter_manifest_changed', 'The chapter list changed while preparing offline copies. Refresh before continuing.', header)
    query = db.query(Chapter).filter(Chapter.novel_id == novel_id)
    if followed_only:
        personal = db.query(NovelPersonalData).filter_by(user_id=user_id, novel_id=novel_id).first()
        query = query.filter(Chapter.category.in_(followed_categories_of(personal)))
    if downloaded_only:
        query = query.filter(Chapter.content_status == ContentStatus.PRESENT)
    if from_chapter is not None:
        query = query.filter(Chapter.chapter_number >= from_chapter)
    total = query.count()
    rows = query.with_entities(Chapter.id, Chapter.chapter_key, Chapter.chapter_number, Chapter.title, Chapter.content_status,
        Chapter.document['content_version'].as_string(), byte_length(db, Chapter.content),
        byte_length(db, Chapter.document)).order_by(Chapter.chapter_number, Chapter.id).offset(offset).limit(limit).all()
    budget = [MAX_INPUT_BYTES]
    chapters = []
    for identity, chapter_key, number, title, state, version, text_size, document_size in rows:
        downloaded = state == ContentStatus.PRESENT
        version = current_version(db, identity, version, budget) if downloaded else None
        chapters.append(dict(id=identity, chapter_key=chapter_key, **header, chapter_number=number, title=title, downloaded=downloaded,
            source_version=version, text_bytes_estimate=(text_size or 0) + (document_size or 0) if downloaded else 0,
            audio=None, translations=[], translations_limited=False))
    indexed = {row['id']: row for row in chapters}
    if indexed:
        audio_versions = [(row['id'], row['chapter_key'], row['source_version']) for row in chapters if row['source_version']]
        # Only successful recordings of the currently stored original qualify.
        ranked = db.query(ChapterAudioJob.id.label('job_id'), func.row_number().over(
            partition_by=ChapterAudioJob.chapter_id, order_by=ChapterAudioJob.id.desc()).label('rank')).filter(
            ChapterAudioJob.user_id == user_id, ChapterAudioJob.novel_id == novel_id,
            ChapterAudioJob.manifest_epoch == header['manifest_epoch'],
            ChapterAudioJob.chapter_id.in_(indexed), ChapterAudioJob.status == 'completed',
            tuple_(ChapterAudioJob.chapter_id, ChapterAudioJob.chapter_key, ChapterAudioJob.source_version).in_(audio_versions)).subquery()
        for job in db.query(ChapterAudioJob).join(ranked, ranked.c.job_id == ChapterAudioJob.id).filter(ranked.c.rank == 1):
            chapter = indexed[job.chapter_id]
            if not chapter['source_version'] or job.source_version != chapter['source_version'] or not job.audio_path:
                continue
            try:
                path = Path(job.audio_path)
                size = path.stat().st_size if path.is_file() else 0
            except OSError:
                size = 0
            if size > 0:
                chapter['audio'] = dict(job_id=job.id, bytes=size, source_version=job.source_version)
        # Window before fetching payload-free rows: bound even stories with many
        # old variants or languages. Exact source matching is checked again below.
        candidates = db.query(TranslationJob.id.label('job_id'), TranslationJob.chapter_id.label('chapter_id'),
            TranslationJob.language.label('language'), func.row_number().over(partition_by=(TranslationJob.chapter_id, TranslationJob.language),
                order_by=TranslationJob.id.desc()).label('language_rank')).filter(
            TranslationJob.user_id == user_id, TranslationJob.novel_id == novel_id,
            TranslationJob.manifest_epoch == header['manifest_epoch'],
            TranslationJob.chapter_id.in_(indexed), TranslationJob.status == 'completed',
            tuple_(TranslationJob.chapter_id, TranslationJob.chapter_key, TranslationJob.source_version).in_(audio_versions)).subquery()
        newest = db.query(candidates.c.job_id, func.row_number().over(partition_by=candidates.c.chapter_id,
            order_by=candidates.c.language).label('chapter_rank')).filter(candidates.c.language_rank == 1).subquery()
        values = db.query(TranslationJob.id, TranslationJob.chapter_id, TranslationJob.language, TranslationJob.source_version,
            byte_length(db, TranslationJob.translated_blocks), func.json_array_length(TranslationJob.source_blocks),
            func.json_array_length(TranslationJob.translated_blocks), newest.c.chapter_rank).join(
            newest, newest.c.job_id == TranslationJob.id).filter(newest.c.chapter_rank <= MAX_TRANSLATIONS_PER_CHAPTER + 1).all()
        for identity, chapter_id, language, version, size, source_count, translated_count, rank in values:
            chapter = indexed[chapter_id]
            if rank > MAX_TRANSLATIONS_PER_CHAPTER:
                chapter['translations_limited'] = True
            elif chapter['source_version'] and version == chapter['source_version'] and source_count and source_count == translated_count:
                chapter['translations'].append(dict(job_id=identity, language=language, bytes_estimate=size or 0, source_version=version))
    return dict(novel_id=novel.id, **header, library_id=novel.library_id, novel_title=novel.title or '', total=total,
        offset=offset, limit=limit, chapters=chapters)


def translation_content(db, user_id, job_id):
    # Inspect identifiers/size before loading a potentially large private JSON body.
    item = db.query(TranslationJob.id, TranslationJob.novel_id, TranslationJob.chapter_id, TranslationJob.status,
        TranslationJob.source_version, byte_length(db, TranslationJob.translated_blocks),
        byte_length(db, TranslationJob.source_blocks), byte_length(db, TranslationJob.provider_snapshot),
        TranslationJob.chapter_key, TranslationJob.manifest_epoch).filter(
        TranslationJob.id == job_id, TranslationJob.user_id == user_id).first()
    if item is None:
        raise HTTPException(404, 'Translation not found')
    owned_story(db, user_id, item.novel_id)
    if item.status != 'completed' or sum(size or 0 for size in item[5:8]) > MAX_INPUT_BYTES:
        raise HTTPException(409, 'This translation is incomplete or too large for one offline copy')
    chapter = db.query(Chapter.id, Chapter.chapter_number, Chapter.document['content_version'].as_string()).filter(
        Chapter.id == item.chapter_id, Chapter.novel_id == item.novel_id, Chapter.chapter_key == item.chapter_key).first()
    if chapter is None or current_version(db, chapter.id, chapter[2], [MAX_INPUT_BYTES]) != item.source_version:
        raise HTTPException(409, 'The original changed; review the current translation before saving offline')
    from app.services.chapter_identity_service import manifest_state, state_fields
    header = state_fields(manifest_state(db, item.novel_id))
    if not item.chapter_key or item.manifest_epoch != header['manifest_epoch']:
        raise HTTPException(409, 'Review the original chapter identity before saving this translation offline')
    job = db.query(TranslationJob).options(load_only(TranslationJob.id, TranslationJob.novel_id, TranslationJob.chapter_id,
        TranslationJob.language, TranslationJob.source_version, TranslationJob.status, TranslationJob.source_blocks,
        TranslationJob.translated_blocks, TranslationJob.provider_snapshot, TranslationJob.fingerprint,
        TranslationJob.input_tokens, TranslationJob.output_tokens, TranslationJob.charged_microusd, TranslationJob.error)).filter_by(id=job_id).one()
    if not job.source_blocks or len(job.source_blocks) != len(job.translated_blocks):
        raise HTTPException(409, 'Finish the entire translation before saving it offline')
    return {**job_view(job), **header, 'chapter_key': item.chapter_key, 'chapter_number': chapter.chapter_number}
