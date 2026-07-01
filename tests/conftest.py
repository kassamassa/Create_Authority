import os
import uuid
from datetime import datetime, timezone

import pytest
from dotenv import load_dotenv
from fastapi.testclient import TestClient
from supabase import create_client

from app.db import get_db
from app.main import app

load_dotenv()


@pytest.fixture
def staging_supabase():
    url = os.getenv("SUPABASE_STAGING_URL")
    key = os.getenv("SUPABASE_STAGING_KEY")
    if not url or not key:
        pytest.skip("SUPABASE_STAGING_URL / SUPABASE_STAGING_KEY が未設定のためスキップ")

    client = create_client(url, key)
    client.created_article_ids = []

    yield client

    if client.created_article_ids:
        client.table("articles").delete().in_("id", client.created_article_ids).execute()


@pytest.fixture
def test_client(staging_supabase):
    app.dependency_overrides[get_db] = lambda: staging_supabase
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
def dummy_article():
    now = datetime.now(timezone.utc).isoformat()
    return {
        "id": str(uuid.uuid4()),
        "title": "DX事例：製造業におけるAI活用事例",
        "content": "本文サンプルテキストです。" * 5,
        "summary": None,
        "source_url": f"https://example.com/articles/{uuid.uuid4()}",
        "source_type": "rss",
        "category": "manufacturing",
        "tags": ["AI", "DX"],
        "author": "Example News",
        "image_url": None,
        "status": "collected",
        "error_message": None,
        "retry_count": 0,
        "published_at": now,
        "newsletter_sent_at": None,
        "slack_notified_at": None,
        "created_at": now,
        "updated_at": now,
    }
