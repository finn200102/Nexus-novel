"""Versioned, bounded internal chapter wake-up evidence; never deletion authority."""
from typing import Annotated,Literal
from pydantic import BaseModel,ConfigDict,Field,StrictInt,field_validator

CanonicalUUID=Annotated[str,Field(strict=True,pattern=r'^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$')]
Digest=Annotated[str,Field(strict=True,pattern=r'^[a-f0-9]{64}$')]


class MetadataEventSource(BaseModel):
    model_config=ConfigDict(extra='forbid')
    site:Annotated[str,Field(strict=True,max_length=64)]|None
    story_id:Annotated[StrictInt,Field(ge=-(2**63),lt=2**63)]|None
    source_url:Annotated[str,Field(strict=True,max_length=10000)]|None


class MetadataEventChapterProof(BaseModel):
    model_config=ConfigDict(extra='forbid')
    chapter_key:CanonicalUUID
    chapter_number:Annotated[StrictInt,Field(ge=-(2**31),lt=2**31)]


class MetadataEventManifestProof(BaseModel):
    model_config=ConfigDict(extra='forbid')
    protocol:Literal[1]
    manifest_key:CanonicalUUID
    revision:Digest
    fingerprint:Digest
    source:MetadataEventSource
    chapters:list[MetadataEventChapterProof]=Field(max_length=1000)

    @field_validator('protocol',mode='before')
    @classmethod
    def strict_protocol(cls,value):
        if type(value) is not int:raise ValueError('The manifest event protocol must be an integer')
        return value
