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
    content: str
    source_url: str
    source_type: str
    category: Optional[str] = None
    tags: Optional[list[str]] = None
    author: Optional[str] = None
    image_url: Optional[str] = None
    published_at: Optional[datetime] = None


class ArticleCreate(ArticleBase):
    pass


class ArticleUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    summary: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[list[str]] = None
    status: Optional[ArticleStatus] = None
    error_message: Optional[str] = None


class Article(ArticleBase):
    id: str
    summary: Optional[str] = None
    status: ArticleStatus = ArticleStatus.COLLECTED
    error_message: Optional[str] = None
    retry_count: int = 0
    newsletter_sent_at: Optional[datetime] = None
    slack_notified_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(use_enum_values=True)
