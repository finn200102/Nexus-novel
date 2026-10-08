from datetime import datetime

from pydantic import BaseModel

from app.schemas.novel import NovelFollowUpdate


class FollowSummary(BaseModel):
    novel_id: int
    library_id: int
    title: str
    author: str | None = None
    state: str
    followed_at: datetime | None = None
    download_policy: str
    download_count: int
    notification_policy: str
    notification_count: int


class FollowUpdate(NovelFollowUpdate):
    pass
