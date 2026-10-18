"""Translate a bounded, verified copy of one original block; never save a variant."""
from fastapi import HTTPException
from app.services.chapter_version_service import document_for
from app.services.translation_service import glossary_for, translate_block

MAX_PASSAGE_CHARACTERS = 3_000
MAX_PASSAGE_BYTES = 12_000


def selected_original(chapter, selection):
    document = document_for(chapter)
    if document.get("content_version") != selection.content_version:
        raise HTTPException(409, detail="The original chapter changed. Select the passage again.")
    blocks = [block for block in document.get("blocks", []) if block.get("id") == selection.block_id]
    if len(blocks) != 1:
        raise HTTPException(409, detail="The original passage is no longer available. Select it again.")
    text = blocks[0].get("text", "")
    # Browser offsets are UTF-16 units, not Python Unicode character indexes.
    encoded = text.encode("utf-16-le")
    start, end = selection.text_offset * 2, (selection.text_offset + selection.text_length) * 2
    if end > len(encoded):
        raise HTTPException(422, detail="Select a passage inside one original paragraph.")
    try:
        original = encoded[start:end].decode("utf-16-le")
    except UnicodeDecodeError as exc:
        raise HTTPException(422, detail="The selection splits a character. Select the passage again.") from exc
    if original != selection.quote:
        raise HTTPException(409, detail="The selected text no longer matches the original. Select it again.")
    if not original.strip() or len(original) > MAX_PASSAGE_CHARACTERS or len(original.encode("utf-8")) > MAX_PASSAGE_BYTES:
        raise HTTPException(422, detail="Select 1–3,000 characters of original text (at most 12,000 bytes).")
    return original


def translate_selected_passage(db, user, novel, chapter, provider, selection):
    from app.services.translation_identity_service import capture,require_captured
    from app.schemas.translation_identity import TranslationChapterIdentity
    from app.services import processing_permissions
    captured=capture(db,user.id,chapter,selection.model_dump(include=set(TranslationChapterIdentity.model_fields)))
    def authorize():
        require_captured(db,user.id,chapter.id,novel.id,captured)
        processing_permissions.check(db,user.id,novel,provider,'translation',
            consent=selection.external_consent,ao3_consent=selection.ao3_consent)
    original = selected_original(chapter, selection)
    translated, incoming, outgoing, charged = translate_block(db, provider, original, selection.language,
        glossary_for(db, user.id, novel.id, selection.language, chapter.chapter_number),authorize=authorize)
    # The response must still name the current original when a provider returns.
    authorize()
    db.refresh(chapter)
    selected_original(chapter, selection)
    from app.services.chapter_identity_service import identity
    return {**identity(chapter),"source_version":captured["source_version"],"current_content_version":captured["source_version"],"original": original, "translation": translated,
        "anchor": {name: getattr(selection, name) for name in ("content_version", "block_id", "text_offset", "text_length", "quote")},
        "provider_id": provider.id, "language": selection.language,
        "input_tokens": incoming, "output_tokens": outgoing, "charged_usd": charged / 1_000_000}
