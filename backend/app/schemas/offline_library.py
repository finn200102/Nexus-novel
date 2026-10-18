from pydantic import BaseModel
from app.schemas.chapter_document import ChapterDocumentResponse


class OfflineAudioChoice(BaseModel):
    job_id: int
    bytes: int
    source_version: str


class OfflineTranslationChoice(BaseModel):
    job_id: int
    language: str
    bytes_estimate: int
    source_version: str


class OfflineManifestChapter(BaseModel):
    id: int
    chapter_key: str
    manifest_epoch: str
    manifest_revision: str
    chapter_number: int
    title: str | None
    downloaded: bool
    source_version: str | None
    text_bytes_estimate: int
    audio: OfflineAudioChoice | None
    translations: list[OfflineTranslationChoice]
    translations_limited: bool


class OfflineManifestPage(BaseModel):
    novel_id: int
    manifest_epoch: str
    manifest_revision: str
    library_id: int
    novel_title: str
    total: int
    offset: int
    limit: int
    chapters: list[OfflineManifestChapter]


class OfflineTranslationContent(BaseModel):
    id: int
    novel_id: int
    chapter_key: str
    manifest_epoch: str
    manifest_revision: str
    chapter_number: int
    language: str
    source_version: str
    status: str
    completed_blocks: int
    total_blocks: int
    document: ChapterDocumentResponse
    charged_usd: float
