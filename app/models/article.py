from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict


class ArticleStatus(str, Enum):
    COLLECTED = "collected"
    PROCESSING = "processing"
    PROCESSED = "processed"
    PUBLISHED = "published"
    ARCHIVED = "archived"
    REJECTED = "rejected"


class ArticleBase(BaseModel):
    title: str
    content: Optional[str] = None
    category: str
    difficulty: str
    source_url: str
    source_type: str


class ArticleCreate(ArticleBase):
    pass


class ArticleStatusUpdate(BaseModel):
    status: ArticleStatus


class ArticleUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    summary: Optional[str] = None
    category: Optional[str] = None
    difficulty: Optional[str] = None
    quality_score: Optional[float] = None
    status: Optional[ArticleStatus] = None
    metadata: Optional[dict] = None


class Article(ArticleBase):
    id: str
    summary: Optional[str] = None
    quality_score: Optional[float] = None
    status: ArticleStatus = ArticleStatus.COLLECTED
    retry_count: int = 0
    failed_channel: Optional[str] = None
    failed_at: Optional[datetime] = None
    processed_at: Optional[datetime] = None
    published_at: Optional[datetime] = None
    archived_at: Optional[datetime] = None
    metadata: dict = {}
    created_at: datetime

    model_config = ConfigDict(use_enum_values=True)
