"""Public management views retain unverified legacy terminology explicitly."""
from typing import Literal
from pydantic import BaseModel


class StoryGlossaryEntry(BaseModel):
    id:int
    source:str
    target:str
    language:str
    through_chapter:int
    chapter_key:str|None
    manifest_epoch:str|None
    manifest_revision:str|None
    source_version:str|None
    current_number:int|None
    effective_through_chapter:int|None
    prerequisite_count:int
    binding_state:Literal['verified','review_required']
    reason:str|None


class StoryGlossaryPage(BaseModel):
    items:list[StoryGlossaryEntry]
    total:int
    offset:int
    limit:int
