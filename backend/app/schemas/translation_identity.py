"""Captured original identity, separate from translated document anchors."""
from pydantic import ConfigDict, Field
from app.schemas.chapter_identity import ChapterWriteIdentity


class TranslationChapterIdentity(ChapterWriteIdentity):
    pass

class SelectedTranslationChapterIdentity(TranslationChapterIdentity):
    chapter_id: int = Field(gt=0, le=2147483647, strict=True)
    model_config = ConfigDict(extra='forbid')
