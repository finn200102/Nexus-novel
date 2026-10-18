"""Portable smart rules resolve owned names; uncertain references stay paused."""
from app.models import Library, Shelf, SmartShelf
from app.schemas.library_views import OwnedLibraryDefinition
from app.schemas.smart_shelf import SmartShelfWrite
from app.services.smart_shelf_service import bindings_for, decode
from pydantic import ValidationError
from fastapi import HTTPException


def export_rows(db, user_id):
    result = []
    for row in db.query(SmartShelf).filter_by(user_id=user_id).order_by(SmartShelf.name_key, SmartShelf.id):
        definition, warnings = decode(db, row)
        refs = row.bindings or {}
        if warnings and refs.get('portable'):
            result.append({**refs['portable'], 'name': row.name, 'needs_review': True})
            continue
        raw = dict(row.definition or {})
        selected = raw.pop('library_ids', [])
        shelf_id = raw.pop('shelf_id', None)
        libraries = None
        if selected:
            libraries = []
            live = {row.id: row for row in db.query(Library).filter(Library.user_id == user_id, Library.id.in_(selected))}
            for id in selected:
                bound = refs.get('libraries', {}).get(str(id), {})
                current = live.get(id)
                if current is not None and current.identity_key == bound.get('identity'):
                    libraries.append(current.name)
                else:
                    libraries.append(bound.get('name', f'Missing library {id}'))
                    warnings.append('A selected library is missing or has been replaced.')
        static = None
        if shelf_id is not None:
            bound = refs.get('shelf') or {}
            current = db.query(Shelf).filter_by(id=shelf_id, user_id=user_id).first()
            if current is not None and current.identity_key == bound.get('identity'):
                static = current.name
            else:
                static = bound.get('name')
                warnings.append('The selected static shelf is missing or has been replaced.')
        result.append(dict(name=row.name, definition=raw, libraries=libraries, static_shelf=static, needs_review=bool(warnings)))
    return result


def import_rows(db, user_id, entries):
    existing = {row.name_key: row for row in db.query(SmartShelf).filter_by(user_id=user_id)}
    reports = []
    for item in entries:
        raw = dict(item.definition)
        unresolved = bool(item.needs_review)
        # Raw database identifiers are never portable, even if they currently
        # happen to identify one of this destination account's own objects.
        raw_libraries = raw.pop('library_ids', [])
        raw_shelf = raw.pop('shelf_id', None)
        if raw_libraries or raw_shelf is not None:
            unresolved = True
        libraries = []
        if item.libraries is not None:
            if not item.libraries:
                unresolved = True
            for name in item.libraries:
                rows = db.query(Library).filter_by(user_id=user_id, name=name).limit(2).all()
                if len(rows) != 1:
                    unresolved = True
                else:
                    libraries.append(rows[0].id)
        shelf_id = None
        if item.static_shelf is not None:
            rows = db.query(Shelf).filter_by(user_id=user_id, name=item.static_shelf).limit(2).all()
            if len(rows) != 1:
                unresolved = True
            else:
                shelf_id = rows[0].id
        raw.update(library_ids=sorted(set(libraries)), shelf_id=shelf_id)
        refs = {'libraries': {}, 'shelf': None}
        try:
            payload = SmartShelfWrite(name=item.name, definition=raw)
            definition, refs = bindings_for(db, user_id, payload.definition)
            raw = definition.model_dump(mode='json')
            name = payload.name
        except (ValidationError, HTTPException):
            name = ' '.join(item.name.split())
            unresolved = True
        if not name:
            reports.append({'name': item.name, 'status': 'invalid'})
            continue
        if unresolved:
            refs = {**refs, 'import_review': True, 'portable': item.model_dump(mode='json')}
        key = name.casefold()
        row = existing.get(key)
        if row is not None:
            state = 'unchanged' if row.name == name and row.definition == raw and row.bindings == refs else 'conflict'
        elif len(existing) >= 500:
            state = 'limit_reached'
        else:
            row = SmartShelf(user_id=user_id, name=name, name_key=key, definition=raw, bindings=refs)
            db.add(row)
            db.flush()
            existing[key] = row
            state = 'created'
        reports.append({'name': name, 'status': state, 'needs_review': unresolved})
    return reports
