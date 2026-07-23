from sqlalchemy import (
    Column,
    String,
    Text,
    Integer,
    BigInteger,
    ForeignKey,
    Table,
    DateTime,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from app.models.base import BaseModel

novel_tag = Table(
    "novel_tag",
    BaseModel.metadata,
    Column("novel_id", Integer, ForeignKey("novels.id"), primary_key=True),
    Column("tag_id", Integer, ForeignKey("tags.id"), primary_key=True),
)


class Novel(BaseModel):
    __tablename__ = "novels"
    __table_args__ = (
        UniqueConstraint("library_id", "url", name="uq_novels_library_url"),
    )

    title = Column(String(255), nullable=False, index=True)
    author_id = Column(Integer, ForeignKey("authors.id"))
    site_story_id = Column(BigInteger)
    site = Column(String(255))
    url = Column(String(255))
    description = Column(Text)
    cover_image = Column(String(255))
    file_path = Column(String(255))
    num_chapters = Column(Integer)
    genre_id = Column(Integer, ForeignKey("genres.id"))
    library_id = Column(Integer, ForeignKey("libraries.id"), nullable=False)

    # Metadata records are shared catalog facts. A user may add the same work
    # to more than one library, so this must not be globally unique.
    metadata_id = Column(Integer, index=True)
    scrape_status = Column(String(20), default="pending")  # pending, completed, failed
    scrape_error = Column(String(500), nullable=True)
    author = Column(String(255))
    author_site_id = Column(BigInteger)
    source_url = Column(String(500))
    story_id = Column(BigInteger)
    novel_site = Column(String(50))
    img_url = Column(String(500))
    word_count = Column(Integer)
    reviews = Column(Integer)
    favorites = Column(Integer)
    follows = Column(Integer)
    status = Column(String(50))
    views = Column(Integer)
    rating = Column(Integer)
    publish_date = Column(DateTime)
    updated_date = Column(DateTime)
    chapter_count = Column(Integer)
    analyzed_at = Column(DateTime)
    analysis_type = Column(String(50))
    analyzed_chapter_count = Column(Integer)
    parsed_at = Column(DateTime)
    follow_state = Column(String(20), nullable=False, default="plan_to_read", server_default="plan_to_read")
    followed_at = Column(DateTime, nullable=True)

    # Relationships
    author_obj = relationship("Author", back_populates="novels")
    genre = relationship("Genre", back_populates="novels")
    library = relationship("Library", back_populates="novels")
    chapters = relationship(
        "Chapter", back_populates="novel", cascade="all, delete-orphan"
    )
    tags = relationship("Tag", secondary=novel_tag, back_populates="novels")

    def __repr__(self):
        data = object.__getattribute__(self, "__dict__")
        title = data.get("title", "Unknown")
        author = data.get("author", "Unknown")
        return f"<Novel {title} by {author}>"
