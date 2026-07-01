import os
from datetime import datetime, timezone
from typing import Optional

import feedparser
import httpx
from dotenv import load_dotenv
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    NoTranscriptFound,
    TranscriptsDisabled,
    VideoUnavailable,
)

from app.services.dify import translate_to_japanese
from app.services.publisher import notify_slack

load_dotenv()

NEWSAPI_URL = "https://newsapi.org/v2/everything"
REQUEST_TIMEOUT = 10.0


class CollectorConfigError(Exception):
    """4xx系の設定ミスなど、リトライ対象外のエラー"""


class CollectorTemporaryError(Exception):
    """5xx・タイムアウトなど、リトライ対象の一時障害"""


def _handle_http_error(exc: Exception, context: str) -> None:
    if isinstance(exc, httpx.TimeoutException):
        notify_slack(f"[collector] タイムアウトが発生しました: {context}")
        raise CollectorTemporaryError(str(exc)) from exc
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status >= 500:
            notify_slack(f"[collector] サーバーエラー({status}): {context}")
            raise CollectorTemporaryError(str(exc)) from exc
        notify_slack(f"[collector] 設定ミスの可能性があります({status}): {context}")
        raise CollectorConfigError(str(exc)) from exc
    raise exc


def collect_from_rss(feed_url: str) -> list[dict]:
    try:
        response = httpx.get(feed_url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
    except (httpx.TimeoutException, httpx.HTTPStatusError) as exc:
        _handle_http_error(exc, f"RSS取得失敗: {feed_url}")

    feed = feedparser.parse(response.content)
    articles = []
    for entry in feed.entries:
        articles.append({
            "title": entry.get("title", ""),
            "content": entry.get("summary", entry.get("description", "")),
            "source_url": entry.get("link", ""),
            "source_type": "rss",
            "published_at": entry.get("published", None),
        })
    return articles


def collect_from_newsapi(query: str, api_key: Optional[str] = None) -> list[dict]:
    api_key = api_key or os.getenv("NEWSAPI_KEY", "")
    try:
        response = httpx.get(
            NEWSAPI_URL,
            params={"q": query, "language": "en", "apiKey": api_key},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
    except (httpx.TimeoutException, httpx.HTTPStatusError) as exc:
        _handle_http_error(exc, f"NewsAPI取得失敗: query={query}")

    payload = response.json()
    articles = []
    for item in payload.get("articles", []):
        title_ja = translate_to_japanese(item.get("title", ""))
        content_ja = translate_to_japanese(item.get("description") or item.get("content") or "")
        articles.append({
            "title": title_ja,
            "content": content_ja,
            "source_url": item.get("url", ""),
            "source_type": "newsapi",
            "published_at": item.get("publishedAt"),
        })
    return articles


def collect_youtube_transcript(video_id: str) -> Optional[str]:
    try:
        transcript = YouTubeTranscriptApi().fetch(video_id, languages=["ja", "en"])
    except (NoTranscriptFound, TranscriptsDisabled, VideoUnavailable):
        return None
    return " ".join(snippet.text for snippet in transcript)


def save_article(supabase_client, article: dict) -> Optional[dict]:
    existing = (
        supabase_client.table("articles")
        .select("id")
        .eq("source_url", article["source_url"])
        .execute()
    )
    if existing.data:
        return None

    now = datetime.now(timezone.utc).isoformat()
    record = {
        **article,
        "status": "collected",
        "created_at": now,
        "updated_at": now,
    }
    result = supabase_client.table("articles").insert(record).execute()
    return result.data[0] if result.data else None
