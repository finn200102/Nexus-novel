"""Import every model so ``Base.metadata`` knows all tables.

Alembic autogenerate and the schema tests rely on this module; add new model
modules here.
"""

from .account import AuthAttempt, InstanceSetting, InviteCode, PasswordResetToken, RefreshToken, UserSession
from .audio_job import ChapterAudioJob, ChapterAudioPart
from .author import Author
from .blocklist import BlocklistEntry
from .chapter import Chapter
from .creator_follow import CreatorFollow
from .download_job import ChapterDownloadJob
from .ereader import AppPassword, EpubBuild, KosyncProgress
from .follow import UserNovelFollow
from .genre import Genre
from .import_job import ImportJob, ImportJobItem
from .library import Library
from .metadata_webhook_delivery import MetadataWebhookDelivery
from .notification import NotificationChannel, PushSubscription
from .novel import Novel, novel_tag
from .novel_personal import NovelPersonalData, NovelUserTag
from .reading_annotation import ReadingAnnotation
from .reading_history import ReadingHistory
from .reading_progress import ReadingProgress
from .reading_session import ReadingSessionDaily
from .saved_search import SavedSearch
from .shelf import Shelf, ShelfNovel
from .tag import Tag
from .personal_feed import UserFeedToken
from .update_event import NovelUpdateEvent
from .webhook import Webhook, WebhookDelivery
from .user import User

__all__ = [
    "AuthAttempt",
    "BlocklistEntry",
    "InstanceSetting",
    "InviteCode",
    "PasswordResetToken",
    "RefreshToken",
    "UserSession",
    "Author",
    "Chapter",
    "CreatorFollow",
    "ChapterAudioJob",
    "ChapterAudioPart",
    "ChapterDownloadJob",
    "AppPassword",
    "EpubBuild",
    "ImportJob",
    "ImportJobItem",
    "KosyncProgress",
    "Genre",
    "Library",
    "MetadataWebhookDelivery",
    "NotificationChannel",
    "PushSubscription",
    "Novel",
    "NovelPersonalData",
    "NovelUserTag",
    "NovelUpdateEvent",
    "ReadingAnnotation",
    "ReadingHistory",
    "ReadingSessionDaily",
    "ReadingProgress",
    "SavedSearch",
    "Shelf",
    "ShelfNovel",
    "Tag",
    "User",
    "UserNovelFollow",
    "novel_tag",
]
