from urllib.parse import urlsplit
from app.models.story_processing_permission import StoryProcessingPermission


def is_ao3(novel):
    provenance=getattr(novel,'manifest_state',None)
    return bool(provenance and getattr(provenance,'ao3_material',False)) or novel.novel_site in {"archive", "ao3"} or any(
        (urlsplit(value or "").hostname or "").lower() in {"archiveofourown.org", "www.archiveofourown.org"}
        for value in (novel.url, novel.source_url))


def check(db, user_id, novel, provider, purpose, *, consent=False, ao3_consent=False):
    if purpose == "portrait":
        from app.services.reader_provider_usage import snapshot
        row = db.query(StoryProcessingPermission).filter_by(user_id=user_id, novel_id=novel.id, provider_id=provider.id).populate_existing().first()
        if row is None or not row.portrait or row.portrait_provider_snapshot != snapshot(provider):
            raise PermissionError("Explicitly grant private portraits for this story and current provider configuration")
        if is_ao3(novel) and not row.portrait_ao3_consent:
            raise PermissionError("Explicitly grant AO3 portrait processing separately from text processing")
        return
    if provider.kind in {"local", "local_translation"}:
        return
    row = db.query(StoryProcessingPermission).filter_by(user_id=user_id, novel_id=novel.id, provider_id=provider.id).populate_existing().first()
    if row is not None and getattr(row, purpose) is False:
        raise PermissionError("External processing is blocked for this story and provider")
    if not consent and not (row is not None and getattr(row, purpose)):
        raise PermissionError("Explicitly allow sending this material to the selected external provider")
    if is_ao3(novel) and not (ao3_consent or (row is not None and row.ao3_consent)):
        raise PermissionError("Explicitly allow sending AO3 material to this external provider")


def revoke_provider_permissions(db, provider_id):
    db.query(StoryProcessingPermission).filter_by(provider_id=provider_id).update(
        {"translation": False, "companion": False, "ao3_consent": False, "portrait": False, "portrait_ao3_consent": False, "portrait_provider_snapshot": None}, synchronize_session=False)
