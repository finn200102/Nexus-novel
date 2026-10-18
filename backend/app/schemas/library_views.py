"""Strict, portable definitions for private owned-library queries."""
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field,field_validator
from app.schemas.novel import Novel

FollowState=Literal['plan_to_read','reading','on_hold','completed','dropped','ignored']
SOURCE_ALIASES={'ao3':'archive','archiveofourown':'archive','archiveofourown.org':'archive','ffn':'fanfiction','fanfiction.net':'fanfiction','rr':'royalroad','royalroad.com':'royalroad','epub':'local'}
SOURCES={'archive','fanfiction','royalroad','scribblehub','webnovel','spacebattles','sufficientvelocity','questionablequesting','local'}


class OwnedLibraryDefinition(BaseModel):
    model_config=ConfigDict(extra='forbid')
    version:Literal[1]=1
    scope:Literal['owned_library']='owned_library'
    library_ids:list[int]=Field(default_factory=list,max_length=100)
    q:str=Field('',max_length=500)
    source:str|None=None
    follow_states:list[FollowState]=Field(default_factory=list,max_length=6)
    user_tag:str|None=Field(None,max_length=60)
    min_rating:int|None=Field(None,ge=1,le=5,strict=True)
    shelf_id:int|None=Field(None,gt=0,le=2147483647,strict=True)
    sort_by:Literal['recent','title','chapters','updated_since_read','personal_rating']='recent'

    @field_validator('version',mode='before')
    @classmethod
    def exact_version(cls,value):
        if type(value) is not int or value!=1:raise ValueError('Unsupported library definition version')
        return value

    @field_validator('library_ids',mode='before')
    @classmethod
    def ids(cls,value):
        if not isinstance(value,list) or len(value)>100 or any(type(item) is not int or not 1<=item<=2147483647 for item in value):raise ValueError('Library IDs must be positive integers')
        return sorted(set(value))

    @field_validator('source')
    @classmethod
    def source_name(cls,value):
        if value is None:return None
        value=value.strip().lower();value=SOURCE_ALIASES.get(value,value)
        if value not in SOURCES:raise ValueError('Unsupported library source')
        return value

    @field_validator('user_tag')
    @classmethod
    def tag(cls,value):
        if value is None:return None
        value=' '.join(value.split()).casefold()
        if not value:raise ValueError('Choose a nonempty user tag')
        return value


class LibraryViewPreviewInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    definition:OwnedLibraryDefinition
    offset:int=Field(0,ge=0,strict=True)
    limit:int=Field(50,ge=1,le=100,strict=True)


class LibraryStoryItem(Novel):
    url:str|None
    library_name:str
    personal_rating:int|None


class LibraryStoryPage(BaseModel):
    items:list[LibraryStoryItem]
    total:int
    offset:int
    limit:int
    library_total:int
    status_counts:dict[FollowState,int]


class LibraryOption(BaseModel):
    id:int
    name:str


class LibrarySourceOption(BaseModel):
    id:str
    label:str


class LibraryViewOptions(BaseModel):
    libraries:list[LibraryOption]
    sources:list[LibrarySourceOption]
    user_tags:list[str]
    libraries_truncated:bool
    sources_truncated:bool
    user_tags_truncated:bool
