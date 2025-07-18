from pydantic import BaseModel
from enum import Enum

class ContentStatus(str, Enum):
    MISSING = "MISSING"
    PRESENT = "PRESENT"
    PROCESSING = "PROCESSING"

class AudioStatus(str, Enum):
    MISSING = "MISSING"
    PRESENT = "PRESENT"
    PROCESSING = "PROCESSING"
    FAILED = "FAILED"

class ChapterCreate(BaseModel):
    novel_id: int
    chapter_number: int
    title: str = None
    content_status: ContentStatus = ContentStatus.MISSING


class Chapter(BaseModel):
    id: int
    novel_id: int
    chapter_number: int
    title: str
    content_status: ContentStatus
    audio_status: AudioStatus
    
    

    class Config:
        orm_mode = True


class ChapterContent(BaseModel):
    id: int
    novel_id: int
    chapter_number: int
    title: str
    content: str


class ChapterUpdate(BaseModel):
    id: int
    novel_id: int
    title: str
    content_status: ContentStatus
