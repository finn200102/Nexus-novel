from typing import Any, Optional
from enum import Enum
from app.logging_config import get_logger, get_request_id

audit_logger = get_logger("audit")


class AuditAction(str, Enum):
    NOVEL_CREATED = "novel.created"
    NOVEL_UPDATED = "novel.updated"
    NOVEL_DELETED = "novel.deleted"
    NOVEL_REFRESHED = "novel.refreshed"
    CHAPTER_DOWNLOADED = "chapter.downloaded"
    CHAPTER_UPDATED = "chapter.updated"
    LIBRARY_CREATED = "library.created"
    LIBRARY_DELETED = "library.deleted"
    USER_LOGIN = "user.login"
    USER_LOGOUT = "user.logout"
    USER_SIGNUP = "user.signup"
    USER_UPDATED = "user.updated"
    USER_DELETED = "user.deleted"
    PASSWORD_CHANGED = "user.password_changed"
    PASSWORD_RESET_ISSUED = "user.password_reset_issued"
    INSTANCE_SETTINGS_CHANGED = "instance.settings_changed"
    INVITE_CREATED = "invite.created"
    INVITE_REVOKED = "invite.revoked"
    SCRAPE_STARTED = "scrape.started"
    SCRAPE_COMPLETED = "scrape.completed"
    SCRAPE_FAILED = "scrape.failed"


class AuditLogger:
    def __init__(self, logger_name: str = "audit"):
        self._logger = get_logger(logger_name)

    def log(
        self,
        action: AuditAction,
        user_id: Optional[int] = None,
        library_id: Optional[int] = None,
        novel_id: Optional[int] = None,
        chapter_id: Optional[int] = None,
        details: Optional[dict[str, Any]] = None,
        success: bool = True,
    ):
        request_id = get_request_id()

        log_data = {
            "action": action.value,
            "success": success,
        }

        if request_id:
            log_data["request_id"] = request_id
        if user_id:
            log_data["user_id"] = user_id
        if library_id:
            log_data["library_id"] = library_id
        if novel_id:
            log_data["novel_id"] = novel_id
        if chapter_id:
            log_data["chapter_id"] = chapter_id
        if details:
            log_data["details"] = details

        if success:
            self._logger.info(f"Audit: {action.value}", **log_data)
        else:
            self._logger.warning(f"Audit: {action.value} (FAILED)", **log_data)


audit = AuditLogger()
