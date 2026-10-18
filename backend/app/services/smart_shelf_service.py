"""Owner-only dynamic shelves, with immutable bindings and conditional edits."""
from datetime import datetime, timezone
from uuid import uuid4
import secrets
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from app.models import Library, Shelf, SmartShelf, User
from app.schemas.library_views import OwnedLibraryDefinition
from app.services import library_view_service


def failure(code, message):
    raise HTTPException(409, detail={'code': code, 'message': message})


def lock_user(db, user_id):
    if db.query(User.id).filter_by(id=user_id).with_for_update().first() is None:
        raise HTTPException(404, 'Account not found')
    db.expire_all()


def owned(db, user_id, shelf_id):
    row = db.query(SmartShelf).filter_by(user_id=user_id, id=shelf_id).populate_existing().first()
    if row is None:
        raise HTTPException(404, 'Smart shelf not found')
    return row


def bindings_for(db, user_id, definition):
    definition = library_view_service.validate_definition(db, user_id, definition)
    refs = {'libraries': {}, 'shelf': None}
    for library in db.query(Library).filter(Library.user_id == user_id, Library.id.in_(definition.library_ids)).order_by(Library.id).with_for_update():
        if not library.identity_key:
            library.identity_key = str(uuid4())
        refs['libraries'][str(library.id)] = {'identity': library.identity_key, 'name': library.name}
    if definition.shelf_id is not None:
        shelf = db.query(Shelf).filter_by(user_id=user_id, id=definition.shelf_id).with_for_update().first()
        if shelf is None:
            raise HTTPException(404, 'Shelf not found')
        if not shelf.identity_key:
            shelf.identity_key = str(uuid4())
        refs['shelf'] = {'id': shelf.id, 'identity': shelf.identity_key, 'name': shelf.name}
    # A deletion between validation and locking must never turn a selected
    # library query into a wider query, including with SQLite foreign keys off.
    if set(refs['libraries']) != {str(id) for id in definition.library_ids}:
        raise HTTPException(404, 'Library not found')
    db.flush()
    return definition, refs


def decode(db, row, *, lock=False):
    try:
        definition = OwnedLibraryDefinition.model_validate(row.definition)
    except (ValidationError, TypeError):
        return None, ['This smart shelf contains unsupported criteria. The original definition is retained; review and replace it before opening.']
    refs = row.bindings or {}
    warnings = []
    if refs.get('import_review'):
        warnings.append('This imported smart shelf needs review. Choose the intended libraries and shelf before saving.')
    query = db.query(Library.id, Library.identity_key).filter(Library.user_id == row.user_id, Library.id.in_(definition.library_ids)).order_by(Library.id)
    if lock:
        query = query.with_for_update()
    actual = {str(id): identity for id, identity in query.all()}
    expected = refs.get('libraries', {})
    if (set(expected) != {str(id) for id in definition.library_ids}
            or set(actual) != set(expected)
            or any(not identity or identity != expected.get(id, {}).get('identity') for id, identity in actual.items())):
        warnings.append('A selected library is missing or has been replaced. Review this rule before opening it.')
    if definition.shelf_id is not None:
        query = db.query(Shelf).filter_by(user_id=row.user_id, id=definition.shelf_id)
        if lock:
            query = query.with_for_update()
        shelf = query.first()
        bound = refs.get('shelf') or {}
        if shelf is None or bound.get('id') != definition.shelf_id or not shelf.identity_key or bound.get('identity') != shelf.identity_key:
            warnings.append('The selected static shelf is missing or has been replaced. Review this rule before opening it.')
    elif refs.get('shelf'):
        warnings.append('This smart shelf has inconsistent saved criteria. Review it before opening.')
    return definition, warnings


def present(db, row):
    definition, warnings = decode(db, row)
    return dict(id=row.id, name=row.name, definition=definition.model_dump(mode='json') if definition else None,
                revision=row.revision, needs_review=bool(warnings), warnings=warnings,
                created_at=row.created_at, updated_at=row.updated_at)


def commit(db):
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        failure('smart_shelf_name_taken', 'A smart shelf with this name already exists. Choose another name.')


def create(db, user_id, payload):
    lock_user(db, user_id)
    if db.query(SmartShelf.id).filter_by(user_id=user_id).count() >= 500:
        raise HTTPException(422, 'This account already has 500 smart shelves. Remove an unused rule before adding another.')
    definition, refs = bindings_for(db, user_id, payload.definition)
    row = SmartShelf(user_id=user_id, name=payload.name, name_key=payload.name.casefold(),
                     definition=definition.model_dump(mode='json'), bindings=refs)
    db.add(row)
    commit(db)
    db.refresh(row)
    return present(db, row)


def update(db, user_id, shelf_id, payload):
    lock_user(db, user_id)
    row = owned(db, user_id, shelf_id)
    if row.revision != payload.expected_revision:
        failure('smart_shelf_changed', 'This smart shelf changed on another device. Refresh it before editing.')
    definition, refs = bindings_for(db, user_id, payload.definition)
    row.name, row.name_key = payload.name, payload.name.casefold()
    row.definition, row.bindings = definition.model_dump(mode='json'), refs
    row.revision = secrets.token_hex(32)
    row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    commit(db)
    db.refresh(row)
    return present(db, row)


def delete(db, user_id, shelf_id, revision):
    lock_user(db, user_id)
    row = owned(db, user_id, shelf_id)
    if row.revision != revision:
        failure('smart_shelf_changed', 'This smart shelf changed on another device. Refresh it before deleting.')
    db.delete(row)
    db.commit()
    return {'deleted': True}


def results(db, user_id, shelf_id, offset=0, limit=50):
    lock_user(db, user_id)
    row = owned(db, user_id, shelf_id)
    definition, warnings = decode(db, row, lock=True)
    if warnings or definition is None:
        failure('smart_shelf_review_required', 'Review this smart shelf before opening its results.')
    result = library_view_service.page(db, user_id, definition, offset, limit)
    return {**result, 'definition_revision': row.revision}
