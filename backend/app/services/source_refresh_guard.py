"""Reauthorize remote source results in a fresh local transaction."""
import json
from datetime import UTC, date, datetime, time
from fastapi import HTTPException

from app.models import Library, Novel, User
from app.models.chapter_manifest import ChapterManifestState
from app.services.chapter_identity_service import sqlite_transaction


def source_fields(novel):
    return (novel.metadata_id, novel.url, novel.source_url, novel.site, novel.novel_site,
            novel.story_id, novel.site_story_id)


def manifest_binding(state):
    return (state.metadata_manifest_key, state.metadata_revision, state.metadata_fingerprint,
            json.dumps(state.metadata_source, sort_keys=True, separators=(',', ':')))


def refresh_fields(db, novel, raw, fields):
    """A metadata refresh cannot silently relink a known source or erase omissions."""
    aliases = {'author_site_id': 'author_id', 'site_story_id': 'story_id'}
    result = {key: value for key, value in fields.items()
              if key in {'scrape_status', 'scrape_error'} or aliases.get(key, key) in raw}
    # Metadata travels as JSON; SQLAlchemy DateTime columns require Python
    # values. Validate before assigning any fields to the private original.
    for key in ('publish_date', 'updated_date', 'analyzed_at', 'parsed_at'):
        if key not in result or result[key] is None:
            continue
        value = result[key]
        try:
            if isinstance(value, str):
                value = datetime.fromisoformat(value)
            elif isinstance(value, date) and not isinstance(value, datetime):
                value = datetime.combine(value, time())
            if not isinstance(value, datetime):
                raise ValueError()
            if value.tzinfo is not None:
                value = value.astimezone(UTC).replace(tzinfo=None)
        except (ValueError, TypeError, OverflowError):
            raise ValueError(f'Metadata has an invalid {key}; no story fields were updated') from None
        result[key] = value
    state = db.query(ChapterManifestState).filter_by(novel_id=novel.id).first()
    recorded = state.metadata_source if state and isinstance(state.metadata_source, dict) else {}
    groups = {'site': ('site', 'novel_site'), 'story_id': ('story_id', 'site_story_id'), 'source_url': ('source_url',)}
    for canonical, local_names in groups.items():
        incoming = raw.get(canonical)
        if incoming is None:
            # Unknown source facts never unlink an established private original.
            for key in local_names:
                result.pop(key, None)
            continue
        known = [getattr(novel, key) for key in local_names if getattr(novel, key) is not None]
        if recorded.get(canonical) is not None:
            known.append(recorded[canonical])
        if any(value != incoming for value in known):
            raise HTTPException(409, detail={'code': 'chapter_review_required',
                'message': 'The source identity changed. Review its chapter list before accepting replacement metadata.'})
    return result


def capture_source(db, user_id, novel):
    """Capture authority and end the read transaction before network I/O."""
    account = db.query(User).filter_by(id=user_id).first()
    library = db.query(Library).filter_by(id=novel.library_id).first()
    state = db.query(ChapterManifestState).filter_by(novel_id=novel.id).first()
    if account is None or account.is_disabled or library is None or library.user_id != user_id or state is None:
        raise HTTPException(404, 'Story not found')
    selected = (account.storage_id, library.id, library.identity_key, state.manifest_epoch,
                source_fields(novel), manifest_binding(state))
    novel_id = novel.id
    db.rollback()
    return user_id, novel_id, selected


def revalidate_source(db, authority, *, allow_metadata_advance=False):
    """A fresh account lock fences publication, including failed refreshes."""
    user_id, novel_id, selected = authority
    sqlite_transaction(db, write=True)
    account = db.query(User).filter_by(id=user_id).populate_existing().with_for_update().first()
    if account is None or account.is_disabled or account.storage_id != selected[0]:
        raise HTTPException(401, 'Account unavailable')
    from app.auth.dependencies import require_current_session
    require_current_session(db, user_id)
    current = db.query(Novel).join(Library, Library.id == Novel.library_id).filter(
        Novel.id == novel_id, Library.user_id == user_id).populate_existing().with_for_update(of=Novel).first()
    if current is None:
        raise HTTPException(404, 'Story not found')
    library = db.query(Library).filter_by(id=current.library_id).populate_existing().first()
    state = db.query(ChapterManifestState).filter_by(novel_id=novel_id).populate_existing().first()
    current_binding = manifest_binding(state) if state is not None else None
    binding_matches = current_binding == selected[5]
    if allow_metadata_advance and current_binding is not None:
        # Only a fresh complete manifest consumer may accept pointer advance.
        # Namespace/source changes still require explicit review; the consumer
        # independently proves unchanged existing identities and append order.
        previous = selected[5]
        binding_matches = (previous[0] in (None, current_binding[0])
                           and previous[3] in ('null', current_binding[3]))
    if state is None or (account.storage_id, library.id, library.identity_key, state.manifest_epoch,
            source_fields(current)) != selected[:5] or not binding_matches:
        raise HTTPException(409, detail={'code': 'story_source_changed',
            'message': 'This story or its source changed while refreshing. Review it before trying again.'})
    return current


async def await_source(db, user_id, novel, call, *args):
    """No remote response or failure grants authority over a cached story."""
    authority = capture_source(db, user_id, novel)
    try:
        result = await call(*args)
    except Exception:
        revalidate_source(db, authority)
        raise
    return result, revalidate_source(db, authority)
