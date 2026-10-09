"""E-reader access: app passwords, built EPUB files, and KOReader progress.

E-readers cannot run the web sign-in, so each user creates app passwords for
them (Kobo devices get a path token instead, see ``KoboDevice``). The database stores only a bcrypt hash of the MD5 of the app password,
which is also what KOReader sends as its ``x-auth-key``.
"""

from sqlalchemy import JSON, Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import relationship

from app.models.base import BaseModel


class AppPassword(BaseModel):
    __tablename__ = "app_passwords"

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    label = Column(String(120), nullable=False, default="")
    # "opds" for catalog and EPUB downloads, "kosync" for reading progress sync.
    scope = Column(String(20), nullable=False)
    secret_hash = Column(String(255), nullable=False)
    last_used_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)

    user = relationship("User")


class EpubBuild(BaseModel):
    """One generated EPUB of a novel. ``partial_md5`` is KOReader's document id
    for that exact file, so progress from any copy we ever served can be
    matched back to the novel."""

    __tablename__ = "epub_builds"
    __table_args__ = (UniqueConstraint("novel_id", "fingerprint", name="uq_epub_build_novel_fingerprint"),)

    novel_id = Column(Integer, ForeignKey("novels.id", ondelete="CASCADE"), nullable=False, index=True)
    fingerprint = Column(String(64), nullable=False)
    # Two sampling variants: the first KOReader sample is at offset 256 (1024 >> 2,
    # used for partial_md5) or at 0 (what LuaJIT yields for 1024 << -2, used for
    # partial_md5_lua). Kosync accepts either.
    partial_md5 = Column(String(32), nullable=False, index=True)
    partial_md5_lua = Column(String(32), nullable=True, index=True)
    size_bytes = Column(Integer, nullable=False)
    file_name = Column(String(255), nullable=False)
    # Chapter numbers in spine order; spine index N is KOReader's DocFragment[N+1].
    spine = Column(JSON, nullable=False, default=list)


class KosyncProgress(BaseModel):
    __tablename__ = "kosync_progress"
    __table_args__ = (
        UniqueConstraint("user_id", "document", name="uq_kosync_progress_user_document"),
        Index("ix_kosync_progress_user_novel", "user_id", "novel_id"),
    )

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    document = Column(String(64), nullable=False)
    novel_id = Column(Integer, ForeignKey("novels.id", ondelete="CASCADE"), nullable=False)
    progress = Column(String(512), nullable=False, default="")
    percentage = Column(Float, nullable=False, default=0, server_default="0")
    device = Column(String(100), nullable=False, default="", server_default="")
    device_id = Column(String(100), nullable=False, default="", server_default="")


class KoboDevice(BaseModel):
    """A Kobo e-reader using native Kobo sync. The protocol puts the secret in
    the URL path (``/kobo/<token>/v1/...``); only ``sha256(token)`` is stored."""

    __tablename__ = "kobo_devices"

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    label = Column(String(120), nullable=False, default="")
    token_hash = Column(String(64), nullable=False, unique=True)
    # The shelf whose stories go to the device; NULL (shelf deleted) syncs nothing.
    shelf_id = Column(Integer, ForeignKey("shelves.id", ondelete="SET NULL"), nullable=True)
    last_used_at = Column(DateTime, nullable=True)
    last_sync_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)


class KoboSyncedBook(BaseModel):
    """What one device was last told about one novel, plus its last bookmark."""

    __tablename__ = "kobo_synced_books"
    __table_args__ = (
        UniqueConstraint("device_id", "novel_id", name="uq_kobo_synced_book_device_novel"),
        Index("ix_kobo_synced_books_device_entitlement", "device_id", "entitlement_id"),
    )

    device_id = Column(Integer, ForeignKey("kobo_devices.id", ondelete="CASCADE"), nullable=False)
    novel_id = Column(Integer, ForeignKey("novels.id", ondelete="CASCADE"), nullable=False)
    entitlement_id = Column(String(36), nullable=False)
    # EPUB fingerprint last sent; "" after a full resync so the book is sent again.
    fingerprint = Column(String(64), nullable=False, default="", server_default="")
    removed = Column(Boolean, nullable=False, default=False, server_default="0")
    # Nexus progress up to this time has been sent to (or came from) the device.
    state_sent_at = Column(DateTime, nullable=True)
    # The device's last bookmark, echoed back while it is the furthest position.
    bookmark_source = Column(String(255), nullable=True)
    bookmark_value = Column(String(255), nullable=True)
    bookmark_type = Column(String(40), nullable=True)
    progress_percent = Column(Float, nullable=True)
    content_percent = Column(Float, nullable=True)
    status = Column(String(20), nullable=True)
    bookmark_at = Column(DateTime, nullable=True)
