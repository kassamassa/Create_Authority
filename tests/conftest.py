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
    # service_role keyはRLSを完全にバイパスするため優先的に使用する。
    # PostgRESTのスキーマキャッシュがRLS変更を拾わないケースがあり、
    # anon keyだとDB側でRLSを無効化してもブロックされることがあるため。
    key = os.getenv("SUPABASE_STAGING_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_STAGING_KEY")
    if not url or not key:
        pytest.skip(
            "SUPABASE_STAGING_URL / "
            "SUPABASE_STAGING_SERVICE_ROLE_KEY(またはSUPABASE_STAGING_KEY) "
            "が未設定のためスキップ"
        )

    client = create_client(url, key)
    client.created_article_ids = []
    client.created_feedback_ids = []

    yield client

    if client.created_feedback_ids:
        client.table("feedback").delete().in_("id", client.created_feedback_ids).execute()
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
        "category": "manufacturing",
        "difficulty": "中",
        "quality_score": None,
        "source_url": f"https://example.com/articles/{uuid.uuid4()}",
        "source_type": "rss",
        "status": "collected",
        "retry_count": 0,
        "failed_channel": None,
        "failed_at": None,
        "processed_at": None,
        "published_at": None,
        "archived_at": None,
        "metadata": {},
        "created_at": now,
    }
