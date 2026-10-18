from pydantic import BaseModel


class PodcastEpisodeStatus(BaseModel):
    id: int | None = None
    source_audio_job_id: int
    chapter_number: int
    chapter_key: str | None = None
    manifest_epoch: str | None = None
    manifest_revision: str | None = None
    source_version: str | None = None
    status: str
    audio_bytes: int | None = None
    duration_seconds: float | None = None
    error_code: str | None = None
    error: str | None = None


class PodcastStatus(BaseModel):
    active: bool
    feed_url: str | None = None
    format: str = "mp3"
    ready: int = 0
    pending: int = 0
    failed: int = 0
    episodes_total: int = 0
    episodes_offset: int = 0
    episodes_limit: int = 50
    episodes: list[PodcastEpisodeStatus] = []
