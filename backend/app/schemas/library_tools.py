from pydantic import BaseModel, Field
from app.schemas.chapter import NovelDownloadStatusResponse


class LibraryDownloadNovel(BaseModel):
    novel_id: int
    library_id: int
    title: str | None
    status: NovelDownloadStatusResponse


class LibraryDownloadPage(BaseModel):
    total: int
    offset: int
    limit: int
    novels: list[LibraryDownloadNovel]


class TextSearchMatch(BaseModel):
    novel_id: int
    library_id: int
    novel_title: str | None
    chapter_id: int
    chapter_number: int
    chapter_title: str | None
    snippet: str = Field(max_length=400)
    chapter_key: str
    manifest_epoch: str
    manifest_revision: str
    content_version: str | None


class TextSearchPage(BaseModel):
    total: int
    offset: int
    limit: int
    matches: list[TextSearchMatch]
