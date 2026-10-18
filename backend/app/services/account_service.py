"""Instance sign-up policy, invites, password resets and account removal."""
from app.models.reader_guide import PrivateGuideJob, PrivateGuideArtifact, PrivateGuideOperation

import logging
import shutil
from datetime import timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from app.auth.passwords import hash_password
from app.auth.sessions import hash_secret, new_secret, revoke_user_sessions, utcnow
from app.models.account import InstanceSetting, InviteCode, PasswordResetToken, RefreshToken, UserSession
from app.models.voice_profile import VoiceProfile
from app.models.audio_job import ChapterAudioJob, ChapterAudioPart
from app.models.audio_export import AudioExportJob
from app.models.podcast import PodcastFeedToken
from app.models.podcast_audio import PodcastAudioJob
from app.models.download_job import ChapterDownloadJob
from app.models.follow import UserNovelFollow
from app.models.ereader import EpubBuild
from app.models.library import Library
from app.models.novel import Novel
from app.models.reading_annotation import ReadingAnnotation
from app.models.reading_history import ReadingHistory
from app.models.reading_run import ReadingRun, ReadingRunEvent
from app.models.reading_continuity import ReadingContinuity
from app.models.chapter_manifest import ChapterManifestReview, ChapterManifestReviewItem, ChapterManifestOperation
from app.models.source_migration import SourceMigration, SourceMigrationOperation
from app.models.import_reading_review import ImportReadingReview, ImportReadingOperation
from app.models.portable_story_link import PortableStoryLink
from app.models.smart_shelf import SmartShelf
from app.models.catalog_watch import CatalogMatch, CatalogWatchSeen, CatalogWatch
from app.models.notification_delivery import NotificationDelivery
from app.models.reading_progress import ReadingProgress
from app.models.saved_search import SavedSearch
from app.models.update_event import NovelUpdateEvent
from app.models.user import User
from app.models.story_processing_permission import StoryProcessingPermission
from app.models.translation import ReaderProviderRequest, ReaderProviderReconciliationOperation, TranslationJob, StoryGlossary, ReaderProvider
from app.services.epub_service import epub_dir
from config.settings import settings

SIGNUP_MODES = ("open", "invite", "closed")
SIGNUP_MODE_KEY = "signup_mode"
# Once an administrator exists, nobody else can sign up unless they change it.
DEFAULT_SIGNUP_MODE = "closed"


class AccountError(Exception):
    """A request that breaks an account rule; the message is user-facing."""


# Instance settings

def get_setting(db: Session, key: str) -> str | None:
    row = db.query(InstanceSetting).filter(InstanceSetting.key == key).first()
    return row.value if row else None


def set_setting(db: Session, key: str, value: str) -> None:
    row = db.query(InstanceSetting).filter(InstanceSetting.key == key).first()
    if row is None:
        db.add(InstanceSetting(key=key, value=value))
    else:
        row.value = value


def get_signup_mode(db: Session) -> str:
    mode = get_setting(db, SIGNUP_MODE_KEY)
    return mode if mode in SIGNUP_MODES else DEFAULT_SIGNUP_MODE


def set_signup_mode(db: Session, mode: str) -> None:
    if mode not in SIGNUP_MODES:
        raise AccountError(f"Sign-up mode must be one of: {', '.join(SIGNUP_MODES)}")
    set_setting(db, SIGNUP_MODE_KEY, mode)


def has_users(db: Session) -> bool:
    return db.query(User.id).first() is not None


# Invites

def invite_status(invite: InviteCode) -> str:
    if invite.revoked_at is not None:
        return "revoked"
    if invite.expires_at is not None and invite.expires_at <= utcnow():
        return "expired"
    if invite.max_uses is not None and invite.use_count >= invite.max_uses:
        return "used"
    return "active"


def create_invite(
    db: Session, created_by: User, label: str | None, max_uses: int | None, expires_in_days: int | None
) -> tuple[InviteCode, str]:
    code = new_secret(9)
    invite = InviteCode(
        code_hash=hash_secret(code),
        label=(label or "").strip() or None,
        created_by_id=created_by.id,
        max_uses=max_uses,
        use_count=0,
        expires_at=utcnow() + timedelta(days=expires_in_days) if expires_in_days else None,
    )
    db.add(invite)
    db.commit()
    db.refresh(invite)
    return invite, code


def consume_invite(db: Session, code: str | None) -> InviteCode:
    """Count one use of an invite code; the caller commits with the new user."""
    invite = db.query(InviteCode).filter(InviteCode.code_hash == hash_secret((code or "").strip())).first()
    if invite is None or invite_status(invite) != "active":
        raise AccountError("This invite code is not valid.")
    # Conditional update so two sign-ups cannot both take the last use.
    query = db.query(InviteCode).filter(InviteCode.id == invite.id)
    if invite.max_uses is not None:
        query = query.filter(InviteCode.use_count < invite.max_uses)
    if query.update({InviteCode.use_count: InviteCode.use_count + 1}, synchronize_session=False) != 1:
        raise AccountError("This invite code is not valid.")
    return invite


# Passwords

def set_password(db: Session, user: User, password: str) -> None:
    user.password = hash_password(password)
    user.password_changed_at = utcnow()


def create_password_reset(db: Session, user: User, created_by: User, expires_in_hours: int) -> tuple[PasswordResetToken, str]:
    """Issue a one-time reset token; earlier unused tokens stop working."""
    now = utcnow()
    db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None)
    ).update({PasswordResetToken.used_at: now}, synchronize_session=False)
    raw = new_secret()
    reset = PasswordResetToken(
        user_id=user.id,
        token_hash=hash_secret(raw),
        created_by_id=created_by.id,
        expires_at=now + timedelta(hours=expires_in_hours),
    )
    db.add(reset)
    db.commit()
    db.refresh(reset)
    return reset, raw


def reset_password(db: Session, raw: str, new_password: str) -> User:
    """Use a reset token: set the password and sign the user out everywhere."""
    now = utcnow()
    reset = db.query(PasswordResetToken).filter(PasswordResetToken.token_hash == hash_secret(raw or "")).first()
    if reset is None or reset.used_at is not None or reset.expires_at <= now:
        raise AccountError("This password reset link is invalid or has expired.")
    user = db.get(User, reset.user_id)
    if user is None:
        raise AccountError("This password reset link is invalid or has expired.")
    claimed = db.query(PasswordResetToken).filter(
        PasswordResetToken.id == reset.id, PasswordResetToken.used_at.is_(None)
    ).update({PasswordResetToken.used_at: now}, synchronize_session=False)
    if claimed != 1:
        raise AccountError("This password reset link is invalid or has expired.")
    set_password(db, user, new_password)
    revoke_user_sessions(db, user.id)
    db.commit()
    return user


# Administration

def active_admin_count(db: Session) -> int:
    return db.query(User).filter(User.is_admin.is_(True), User.is_disabled.is_(False)).count()


def ensure_admin_remains(db: Session, user: User) -> None:
    """Refuse a change that would leave no active administrator."""
    if user.is_admin and not user.is_disabled and active_admin_count(db) <= 1:
        raise AccountError("Nexus needs at least one active administrator.")


def delete_user_account(db: Session, user: User) -> None:
    """Delete a user and everything they own.

    The rows are removed explicitly rather than relying on ON DELETE CASCADE,
    which SQLite only honours when foreign keys are switched on.
    """
    user_id = user.id
    # Collect the on-disk files first: their rows disappear with the user.
    disk_files = _user_disk_files(db, user)
    download_dirs = _user_download_dirs(db, user)
    session_ids = [row.id for row in db.query(UserSession.id).filter(UserSession.user_id == user_id)]
    if session_ids:
        db.query(RefreshToken).filter(RefreshToken.session_id.in_(session_ids)).delete(synchronize_session=False)
    audio_job_ids = [row.id for row in db.query(ChapterAudioJob.id).filter(ChapterAudioJob.user_id == user_id)]
    if audio_job_ids:
        db.query(ChapterAudioPart).filter(ChapterAudioPart.job_id.in_(audio_job_ids)).delete(synchronize_session=False)
    review_ids = db.query(ChapterManifestReview.id).filter(ChapterManifestReview.user_id == user_id)
    db.query(ChapterManifestReviewItem).filter(ChapterManifestReviewItem.review_id.in_(review_ids)).delete(synchronize_session=False)
    for model in (
        ChapterManifestOperation,
        ChapterManifestReview,
        ImportReadingOperation,
        ImportReadingReview,
        PortableStoryLink,
        NotificationDelivery,
        CatalogMatch,
        CatalogWatchSeen,
        CatalogWatch,
        SourceMigrationOperation,
        SourceMigration,
        PrivateGuideArtifact,
        PrivateGuideJob,
        PrivateGuideOperation,
        ReaderProviderReconciliationOperation,
        ReaderProviderRequest,
        TranslationJob,
        StoryGlossary,
        StoryProcessingPermission,
        ReaderProvider,
        UserSession,
        PasswordResetToken,
        ChapterAudioJob,
        AudioExportJob,
        PodcastAudioJob,
        PodcastFeedToken,
        VoiceProfile,
        ChapterDownloadJob,
        UserNovelFollow,
        NovelUpdateEvent,
        ReadingRunEvent,
        ReadingRun,
        ReadingContinuity,
        ReadingProgress,
        ReadingHistory,
        ReadingAnnotation,
        SavedSearch,
        SmartShelf,
    ):
        db.query(model).filter(model.user_id == user_id).delete(synchronize_session=False)
    db.query(InviteCode).filter(InviteCode.created_by_id == user_id).update(
        {InviteCode.created_by_id: None}, synchronize_session=False
    )
    db.query(PasswordResetToken).filter(PasswordResetToken.created_by_id == user_id).update(
        {PasswordResetToken.created_by_id: None}, synchronize_session=False
    )
    # Libraries cascade to their novels and chapters through the ORM.
    for library in db.query(Library).filter(Library.user_id == user_id).all():
        db.delete(library)
    db.flush()
    db.delete(user)
    db.commit()
    # Files go only once the rows are gone for good.
    _remove_user_files(disk_files, download_dirs)
    # The owner row is gone before artifacts disappear, fencing active encoders.
    from app.services.audio_export_service import ExportError, purge_export_files
    from app.services.podcast_audio_service import purge_podcast_audio_files
    try:
        purge_export_files(user_id)
        purge_podcast_audio_files(user_id)
    except (ExportError, OSError):
        logging.getLogger(__name__).warning("Private audiobook cleanup needs administrator attention for deleted account %s", user_id)


def _user_disk_files(db: Session, user: User) -> list[Path]:
    """Audio files and cached EPUBs that belong to ``user``."""
    user_id = user.id
    paths = [Path(row.audio_path) for row in db.query(ChapterAudioJob.audio_path).filter(
        ChapterAudioJob.user_id == user_id, ChapterAudioJob.audio_path.isnot(None))]
    paths += [Path(row.audio_path) for row in db.query(AudioExportJob.audio_path).filter(
        AudioExportJob.user_id == user_id, AudioExportJob.audio_path.isnot(None))]
    job_ids = [row.id for row in db.query(ChapterAudioJob.id).filter(ChapterAudioJob.user_id == user_id)]
    if job_ids:
        paths += [Path(row.audio_path) for row in db.query(ChapterAudioPart.audio_path).filter(
            ChapterAudioPart.job_id.in_(job_ids), ChapterAudioPart.audio_path.isnot(None))]
    novel_ids = [row.id for row in db.query(Novel.id).join(Library, Novel.library_id == Library.id).filter(
        Library.user_id == user_id)]
    if novel_ids:
        paths += [epub_dir() / row.file_name for row in db.query(EpubBuild.file_name).filter(
            EpubBuild.novel_id.in_(novel_ids))]
    return paths


def _user_download_dirs(db: Session, user: User) -> list[Path]:
    """Per-library download folders (DOWNLOAD_PATH/<username>/<library_id>).

    Only folders strictly inside DOWNLOAD_PATH are kept, so a strange username
    can never point the cleanup at the download root or outside it.
    """
    root = Path(settings.DOWNLOAD_PATH).resolve()
    dirs = []
    for row in db.query(Library.id).filter(Library.user_id == user.id):
        target = (root / str(user.username) / str(row.id)).resolve()
        if target.is_relative_to(root) and len(target.relative_to(root).parts) >= 2:
            dirs.append(target)
    return dirs


def _remove_user_files(files: list[Path], download_dirs: list[Path]) -> None:
    for path in files:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
    for directory in download_dirs:
        shutil.rmtree(directory, ignore_errors=True)
        # Drop the user's folder too once its last library folder is gone.
        try:
            directory.parent.rmdir()
        except OSError:
            pass
