from sqlalchemy import Column, String, Text, Integer, ForeignKey, Table
from sqlalchemy.orm import relationship
from app.models.base import BaseModel

# Many to many relationships
novel_tag = Table(
    'novel_tag',
    BaseModel.metadata,
    Column('novel_id', Integer, ForeignKey('novels.id'),
           primary_key=True),
    Column('tag_id', Integer, ForeignKey('tags.id'),
           primary_key=True)
)

class Novel(BaseModel):
    __tablename__ =  "novels"

    title = Column(String(255), nullable=False, index=True)
    author_id = Column(Integer, ForeignKey('authors.id'))
    url = Column(String(255))
    description = Column(Text)
    cover_image = Column(String(255))
    file_path = Column(String(255)
    num_chapters = Column(Integer)
    genre_id = Column(Integer, ForeignKey('genres.id')) 
    library_id = Column(Integer, ForeignKey('libraries.id'),
                        nullable=False)


    # Relationships
    author = relationship("Author", back_populates="novels")
    genre = relationship("Genre", back_populates="novels")
    library = relationship("Library", back_populates="novels")
    chapters = relationship("Chapter",
                            back_populates="novel",
                            cascade="all, delete-orphan")
    tags = relationship("Tag", secondary=novel_tag,
                        back_populates="novels")

    def __repr__(self):
        return f"<Novel {self.title} by {self.author}>"
    
            
    
