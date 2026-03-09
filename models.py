from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Index
from sqlalchemy.orm import DeclarativeBase, relationship
from datetime import datetime, timezone

class Base(DeclarativeBase):
    pass

class Song(Base):
    __tablename__ = "songs"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String, nullable=False)
    artist = Column(String)
    youtube_id = Column(String, unique=True, index=True)
    file_path = Column(String, nullable=False)
    lyrics = Column(Text)
    duration = Column(Integer)
    media_type = Column(String) 
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    rank = Column(Integer, default=0)
    # Added index=True for fast Chinese/Pinyin searching
    meta = Column(String, index=True) 
    
    # Added cascade so if a song is deleted, its queue history is cleaned up
    queue_entries = relationship(
        "Queue", 
        back_populates="song", 
        lazy="selectin", 
        cascade="all, delete-orphan"
    )

class Queue(Base):
    __tablename__ = "queue"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    song_id = Column(Integer, ForeignKey("songs.id", ondelete="CASCADE"))
    user_name = Column(String)  
    status = Column(String, default="pending", index=True) 
    # Added index=True for fast playlist sorting
    position = Column(Integer, index=True) 
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    
    song = relationship("Song", back_populates="queue_entries", lazy="selectin")

# Explicitly index common search combinations if you want to be extra thorough
Index('ix_song_title_artist', Song.title, Song.artist)