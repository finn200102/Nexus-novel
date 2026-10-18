from datetime import datetime, UTC
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator


class ActivityValues(BaseModel):
    model_config=ConfigDict(extra='forbid')
    tracking_enabled:StrictBool=True


class GoalValues(BaseModel):
    model_config=ConfigDict(extra='forbid')
    target_readings:StrictInt|None=Field(None,ge=1,le=10000)


class ActivityWrite(BaseModel):
    model_config=ConfigDict(extra='forbid')
    expected_revision:int=Field(ge=0)
    operation_id:str=Field(min_length=1,max_length=128)
    values:ActivityValues


class GoalWrite(BaseModel):
    model_config=ConfigDict(extra='forbid')
    expected_revision:int=Field(ge=0)
    operation_id:str=Field(min_length=1,max_length=128)
    values:GoalValues


class ExportReadingGoal(BaseModel):
    year:StrictInt=Field(ge=1900)
    values:GoalValues

    @field_validator('year')
    @classmethod
    def supported_year(cls,value):
        if value>datetime.now(UTC).year+1:raise ValueError('Reading goals support at most next year')
        return value


# Response contracts are separate from writes: defaults and sparse legacy
# responses must not acquire new JSON fields during response validation.
class ReadingResponse(BaseModel):
    model_config=ConfigDict(extra='allow')


class ReadingTimeResponse(ReadingResponse):
    recorded_seconds:int


class DailyStatResponse(ReadingResponse):
    date:str
    seconds:int
    words:int
    chapters_finished:int


class StatsTotalsResponse(ReadingResponse):
    seconds:int
    words:int
    chapters_finished:int
    stories_finished:int
    reading_runs_finished:int|None=None
    rereads_finished:int|None=None


class CompletionHistoryResponse(ReadingResponse):
    undated_runs:int
    undated_runs_included:bool


class ReadingStreakResponse(ReadingResponse):
    current:int
    longest:int
    min_seconds:int


class TopStoryResponse(ReadingResponse):
    novel_id:int
    title:str
    seconds:int
    words:int


class SiteStatResponse(ReadingResponse):
    site:str
    seconds:int


class TagStatResponse(ReadingResponse):
    tag:str
    seconds:int


class StatsSummaryResponse(ReadingResponse):
    range:Literal['week','month','year','all']
    start:str|None
    end:str
    totals:StatsTotalsResponse
    completion_history:CompletionHistoryResponse|None=None
    daily:list[DailyStatResponse]
    streak:ReadingStreakResponse
    top_stories:list[TopStoryResponse]
    by_site:list[SiteStatResponse]
    by_tag:list[TagStatResponse]


class CalendarStatsSummaryResponse(StatsSummaryResponse):
    range:Literal['calendar_year']
    end:str|None


class ActivityValuesResponse(ReadingResponse):
    tracking_enabled:bool


class GoalValuesResponse(ReadingResponse):
    target_readings:int|None


class ReadingActivityPreferenceResponse(ReadingResponse):
    revision:int
    values:ActivityValuesResponse


class ReadingGoalResponse(ReadingResponse):
    revision:int
    values:GoalValuesResponse


class CalendarReviewMonthResponse(ReadingResponse):
    month:int
    seconds:int
    words:int
    chapters_finished:int
    stories_finished:int
    reading_runs_finished:int
    rereads_finished:int


class CalendarReviewGoalResponse(ReadingResponse):
    target_readings:int|None
    completed_readings:int


class CalendarYearReviewResponse(ReadingResponse):
    year:int
    start:str
    end:str
    through:str|None
    tracking_enabled:bool
    summary:CalendarStatsSummaryResponse
    months:list[CalendarReviewMonthResponse]
    goal:CalendarReviewGoalResponse
