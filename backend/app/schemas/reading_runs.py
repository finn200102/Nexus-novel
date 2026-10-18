from uuid import UUID
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class ReadingRunAction(BaseModel):
    model_config=ConfigDict(extra='forbid')
    expected_revision:int=Field(ge=0)
    operation_id:str=Field(min_length=1,max_length=128)
    reading_run_key:UUID|None=None


class ReadingRunDrop(ReadingRunAction):
    reason:str|None=Field(None,max_length=500)


class ReadingRunProgressResponse(BaseModel):
    """Sparse historical snapshot, retaining portable/future metadata verbatim."""
    model_config=ConfigDict(extra='allow')
    novel_id:int|None=None
    chapter_number:int|None=None
    position:int|None=None
    percent:float|None=None
    revision:int|None=None
    furthest_chapter_number:int|None=None
    furthest_percent:float|None=None
    block_id:str|None=None
    text_offset:int|None=None
    text_quote:str|None=None
    quote_prefix:str|None=None
    quote_suffix:str|None=None
    locator_content_version:str|None=None
    locator_variant:str|None=None
    reading_run_key:str|None=None
    updated_at:str|None=None


class ReadingRunResponse(BaseModel):
    model_config=ConfigDict(extra='allow')
    reading_run_key:str
    ordinal:int
    status:Literal['active','completed','abandoned']
    started_at:datetime|None
    started_at_inferred:bool
    completed_at:datetime|None
    completed_at_inferred:bool
    abandoned_at:datetime|None
    abandon_reason:str|None
    archived_at:datetime|None
    progress:ReadingRunProgressResponse|None
    next_unread_chapter_id:int|None
    next_unread_chapter_number:int|None


class ReadingRunStateResponse(BaseModel):
    model_config=ConfigDict(extra='allow')
    novel_id:int
    current_run_key:str|None
    revision:int
    current_progress:ReadingRunProgressResponse|None
    first_chapter_number:int|None=None
    total:int
    offset:int
    limit:int
    items:list[ReadingRunResponse]


class ReadingJournalEventResponse(BaseModel):
    model_config=ConfigDict(extra='allow')
    id:int
    novel_id:int
    novel_title:str
    reading_run_key:str
    kind:Literal['started','completed','abandoned']
    occurred_at:datetime|None
    inferred:bool
    reason:str|None
    ordinal:int


class ReadingJournalPageResponse(BaseModel):
    model_config=ConfigDict(extra='allow')
    total:int
    offset:int
    limit:int
    items:list[ReadingJournalEventResponse]
