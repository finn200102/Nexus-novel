"""Import every model so ``Base.metadata`` knows all tables.

Alembic autogenerate and the schema tests rely on this module; add new model
modules here.
"""

from .account import AuthAttempt, InstanceSetting, InviteCode, PasswordResetToken, RefreshToken, UserSession
from .audio_job import ChapterAudioJob, ChapterAudioPart
from .author import Author
from .chapter import Chapter
from .download_job import ChapterDownloadJob
from .follow import UserNovelFollow
from .genre import Genre
from .library import Library
from .metadata_webhook_delivery import MetadataWebhookDelivery
from .notification import NotificationChannel, PushSubscription
from .novel import Novel, novel_tag
from .reading_annotation import ReadingAnnotation
from .reading_history import ReadingHistory
from .reading_progress import ReadingProgress
from .saved_search import SavedSearch
from .tag import Tag
from .update_event import NovelUpdateEvent
from .user import User

__all__ = [
    "AuthAttempt",
    "InstanceSetting",
    "InviteCode",
    "PasswordResetToken",
    "RefreshToken",
    "UserSession",
    "Author",
    "Chapter",
    "ChapterAudioJob",
    "ChapterAudioPart",
    "ChapterDownloadJob",
    "Genre",
    "Library",
    "MetadataWebhookDelivery",
    "NotificationChannel",
    "PushSubscription",
    "Novel",
    "NovelUpdateEvent",
    "ReadingAnnotation",
    "ReadingHistory",
    "ReadingProgress",
    "SavedSearch",
    "Tag",
    "User",
    "UserNovelFollow",
    "novel_tag",
]
