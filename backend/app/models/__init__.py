"""Import every model so ``Base.metadata`` knows all tables.

Alembic autogenerate and the schema tests rely on this module; add new model
modules here.
"""

from .podcast import PodcastFeedToken
from .podcast_audio import PodcastAudioJob
from .audio_export import AudioExportJob
from .account import AuthAttempt, InstanceSetting, InviteCode, PasswordResetToken, RefreshToken, UserSession
from .voice_profile import VoiceProfile
from .audio_job import ChapterAudioJob, ChapterAudioPart
from .author import Author
from .blocklist import BlocklistEntry
from .chapter import Chapter
from .chapter_version import ChapterVersion
from .creator_follow import CreatorFollow
from .download_job import ChapterDownloadJob
from .ereader import AppPassword, EpubBuild, KosyncProgress
from .feedback_event import ReaderFeedbackEvent
from .follow import UserNovelFollow
from .genre import Genre
from .import_job import ImportJob, ImportJobItem
from .library import Library
from .metadata_webhook_delivery import MetadataWebhookDelivery
from .notification import NotificationChannel, PushSubscription
from .novel import Novel, novel_tag
from .novel_personal import NovelPersonalData, NovelUserTag
from .reading_annotation import ReadingAnnotation
from .reader_preference import ReaderPreference, ReaderPreferenceOperation
from .readwise import ReadwiseConnection
from .reading_history import ReadingHistory
from .reading_run import ReadingRun, ReadingRunEvent
from .reading_continuity import ReadingContinuity
from .source_migration import SourceMigration, SourceMigrationOperation
from .reading_progress import ReadingProgress, ReadingProgressOperation
from .translation import ReaderProvider, StoryGlossary, TranslationJob, ReaderProviderRequest, ReaderProviderReconciliationOperation
from .companion_answer import CompanionAnswer
from .chapter_read_receipt import ChapterReadReceipt
from .story_processing_permission import StoryProcessingPermission
from .local_cover import LocalBookCover
from .reading_session import ReadingSessionDaily
from .saved_search import SavedSearch
from .shelf import Shelf, ShelfNovel, ShelfShare
from .smart_shelf import SmartShelf
from .catalog_watch import CatalogWatch, CatalogWatchSeen, CatalogMatch
from .notification_delivery import NotificationDelivery
from .tag import Tag
from .personal_feed import UserFeedToken
from .update_event import NovelUpdateEvent
from .webhook import Webhook, WebhookDelivery
from .user import User

__all__ = [
    "PodcastFeedToken",
    "PodcastAudioJob",
    "AudioExportJob",
    "VoiceProfile",
    "AuthAttempt",
    "BlocklistEntry",
    "ReaderFeedbackEvent",
    "InstanceSetting",
    "InviteCode",
    "PasswordResetToken",
    "RefreshToken",
    "UserSession",
    "Author",
    "Chapter",
    "ChapterVersion",
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
    "ReadwiseConnection",
    "UserFeedToken",
    "Webhook",
    "WebhookDelivery",
    "ReadingProgress",
    "ReadingContinuity",
    "SourceMigration",
    "SourceMigrationOperation",
    "ReadingRun",
    "ReadingRunEvent",
    "ReadingProgressOperation",
    "ReaderPreference",
    "ReaderPreferenceOperation",
    "CompanionAnswer",
    "ChapterReadReceipt",
    "StoryProcessingPermission",
    "ReaderProvider",
    "ReaderProviderRequest",
    "ReaderProviderReconciliationOperation",
    "StoryGlossary",
    "TranslationJob",
    "LocalBookCover",
    "SavedSearch",
    "Shelf",
    "SmartShelf",
    "CatalogWatch",
    "CatalogWatchSeen",
    "CatalogMatch",
    "NotificationDelivery",
    "ShelfNovel",
    "ShelfShare",
    "Tag",
    "User",
    "UserNovelFollow",
    "novel_tag",
]

from app.models.reader_guide import PrivateGuideJob, PrivateGuideArtifact, PrivateGuideOperation

from app.models.chapter_manifest import ChapterManifestState, ChapterManifestReview, ChapterManifestOperation, ChapterManifestReviewItem
from .import_reading_review import ImportReadingReview, ImportReadingOperation

__all__ += ["PrivateGuideJob", "PrivateGuideArtifact", "PrivateGuideOperation", "ChapterManifestState", "ChapterManifestReview", "ChapterManifestOperation", "ChapterManifestReviewItem", "ImportReadingReview", "ImportReadingOperation"]
from .portable_story_link import PortableStoryLink
