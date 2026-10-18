"""Lossless query storage, conservative legacy decoding and edit fencing."""
import hashlib
import json

from pydantic import ValidationError

from app.schemas.saved_search import SavedSearchDefinition


def revision(row):
    value = [row.id, row.name, row.filters, bool(row.notify_on_match), str(row.updated_at)]
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def decode(raw):
    raw = raw if isinstance(raw, dict) else {}
    if 'unresolved_similarity' in raw or 'unresolved_canonical' in raw:
        local = {key:value for key,value in raw.items() if key not in {'unresolved_similarity', 'unresolved_canonical'}}
        warnings = []
        if 'unresolved_similarity' in raw:
            local['similar_to'] = None
            warnings.append('The similar-story filter belongs to another installation and is paused. Select that story again in Discover and replace the criteria, or review and save without this filter.')
        if 'unresolved_canonical' in raw:
            local['canonical_include'] = []
            local['canonical_exclude'] = []
            warnings.append('Reviewed vocabulary references belong to another installation and are paused. Select the matching vocabulary here and replace the criteria before using this search.')
        try:
            result = SavedSearchDefinition.model_validate(local)
        except ValidationError:
            return None, True, ['This imported search contains unsupported criteria; its original data is retained.']
        return result, True, warnings
    if 'version' in raw or 'scope' in raw:
        try:
            return SavedSearchDefinition.model_validate(raw), False, []
        except ValidationError:
            return None, True, ['This search contains unsupported criteria. Review it before opening.']
    # Legacy queries never stored their text/source. Do not claim recovery.
    filters = dict(raw)
    if 'tags' in filters and 'tag' not in filters:
        filters['tag'] = filters.pop('tags')
    for key in ('tag', 'fandom', 'genre', 'excludeTag', 'excludeFandom', 'excludeGenre', 'excludeAuthor', 'excludeText', 'language'):
        if isinstance(filters.get(key), str): filters[key] = [filters[key]]
    for key in ('minWordCount', 'minFavorites', 'minFollows', 'minReviews', 'minChapterCount', 'maxWordCount', 'updatedSinceDays'):
        if isinstance(filters.get(key), int) and not isinstance(filters[key], bool): filters[key] = str(filters[key])
    if isinstance(filters.get('completeOnly'), bool): filters['completeOnly'] = 'true' if filters['completeOnly'] else ''
    if isinstance(filters.get('crossover'), bool): filters['crossover'] = str(filters['crossover']).lower()
    try:
        result = SavedSearchDefinition(filters=filters)
    except ValidationError:
        return None, True, ['This legacy search contains unsupported criteria. Its original data is retained; replace it with a reviewed search.']
    return result, True, ['This legacy search did not retain its query or source. Confirm them before opening.']


def stored(payload):
    return payload.definition.model_dump(mode='json') if payload.definition is not None else payload.filters


def imported(raw):
    """Catalog IDs are instance-local; retain an unresolved seed for review."""
    if isinstance(raw, dict) and raw.get('version') in (1, 2) and raw.get('scope') == 'catalog':
        raw = dict(raw)
        if raw.get('similar_to') is not None:
            raw['unresolved_similarity'] = {'previous_catalog_id':raw.pop('similar_to')}
        if raw.get('canonical_include') or raw.get('canonical_exclude'):
            raw['unresolved_canonical'] = {
                'canonical_include': raw.pop('canonical_include', []),
                'canonical_exclude': raw.pop('canonical_exclude', []),
            }
    return raw


def present(row):
    definition, needs_review, warnings = decode(row.filters)
    return dict(id=row.id, name=row.name,
        filters=definition.filters.model_dump() if definition is not None else row.filters or {},
        definition=definition.model_dump(mode='json') if definition is not None else None,
        revision=revision(row), needs_review=needs_review, warnings=warnings,
        notify_on_match=bool(row.notify_on_match), alert_state='paused' if row.notify_on_match else 'off',
        created_at=row.created_at.isoformat(), updated_at=row.updated_at.isoformat())
