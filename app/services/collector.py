import calendar
import logging
import os
import uuid
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

from app.services.publisher import notify_slack

load_dotenv()

logger = logging.getLogger(__name__)

NEWSAPI_URL = "https://newsapi.org/v2/everything"
REQUEST_TIMEOUT = 10.0

RSS_FEEDS = [
    "https://rss.itmedia.co.jp/rss/2.0/itmedia_all.xml",
    "https://xtech.nikkei.com/rss/index.rdf",
    "https://japan.zdnet.com/rss/index.rdf",
    "https://jp.techcrunch.com/feed/",
]

NEWSAPI_KEYWORDS = [
    "DX 中小企業",
    "業務自動化 AI",
    "デジタルトランスフォーメーション 事例",
]


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


def _parse_published(entry: dict) -> Optional[str]:
    """feedparserのエントリから published_at を ISO 8601 文字列に変換する。"""
    parsed = entry.get("published_parsed")
    if parsed:
        try:
            ts = calendar.timegm(parsed)  # UTC struct_time → Unix timestamp
            return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
        except Exception:
            pass
    return None


def collect_from_rss(feed_url: str) -> list[dict]:
    logger.info("[rss] 取得開始: %s", feed_url)
    try:
        response = httpx.get(feed_url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
    except (httpx.TimeoutException, httpx.HTTPStatusError) as exc:
        logger.error("[rss] HTTP エラー: %s — %s", feed_url, exc)
        _handle_http_error(exc, f"RSS取得失敗: {feed_url}")
    except Exception as exc:
        logger.error("[rss] 接続エラー: %s — %s", feed_url, exc)
        raise

    feed = feedparser.parse(response.content)
    articles = []
    for entry in feed.entries:
        source_url = entry.get("link", "")
        if not source_url:
            continue
        articles.append({
            "title": entry.get("title", ""),
            "content": entry.get("summary", entry.get("description", "")),
            "source_url": source_url,
            "source_type": "rss",
            "published_at": _parse_published(entry),
        })
    logger.info("[rss] 取得完了: %d 件 (%s)", len(articles), feed_url)
    return articles


def collect_all_rss() -> tuple[list[dict], list[dict]]:
    """全 RSS_FEEDS から収集する。1フィードが失敗しても他は継続。"""
    articles: list[dict] = []
    errors: list[dict] = []
    for url in RSS_FEEDS:
        try:
            articles.extend(collect_from_rss(url))
        except Exception as exc:
            logger.error("[rss] フィード収集失敗 url=%s: %s", url, exc)
            errors.append({"source": url, "error": str(exc)})
    logger.info("[rss] 全フィード収集完了: %d 件 (エラー %d 件)", len(articles), len(errors))
    return articles, errors


async def collect_from_newsapi(query: str, api_key: Optional[str] = None) -> list[dict]:
    api_key = api_key or os.getenv("NEWSAPI_KEY", "")
    if not api_key:
        logger.info("[newsapi] NEWSAPI_KEY 未設定のためスキップ")
        return []

    logger.info("[newsapi] 取得開始: query=%s", query)
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                NEWSAPI_URL,
                params={"q": query, "language": "en", "apiKey": api_key},
                timeout=REQUEST_TIMEOUT,
            )
        response.raise_for_status()
    except (httpx.TimeoutException, httpx.HTTPStatusError) as exc:
        logger.error("[newsapi] HTTP エラー: query=%s — %s", query, exc)
        _handle_http_error(exc, f"NewsAPI取得失敗: query={query}")
    except Exception as exc:
        logger.error("[newsapi] 接続エラー: query=%s — %s", query, exc)
        raise

    payload = response.json()
    articles = []
    for item in payload.get("articles", []):
        source_url = item.get("url", "")
        if not source_url or source_url == "[Removed]":
            continue
        # 英語のまま保存し、Dify処理ステップで要約・カテゴリ分類する
        articles.append({
            "title": item.get("title", ""),
            "content": item.get("description") or item.get("content") or "",
            "source_url": source_url,
            "source_type": "newsapi",
            "published_at": item.get("publishedAt"),
        })
    logger.info("[newsapi] 取得完了: %d 件 (query=%s)", len(articles), query)
    return articles


async def collect_all_newsapi() -> tuple[list[dict], list[dict]]:
    """全 NEWSAPI_KEYWORDS で収集する。NEWSAPI_KEY 未設定時は空を返す。"""
    articles: list[dict] = []
    errors: list[dict] = []
    for keyword in NEWSAPI_KEYWORDS:
        try:
            results = await collect_from_newsapi(keyword)
            articles.extend(results)
        except Exception as exc:
            logger.error("[newsapi] キーワード収集失敗: keyword=%s: %s", keyword, exc)
            errors.append({"source": f"newsapi:{keyword}", "error": str(exc)})
    logger.info("[newsapi] 全キーワード収集完了: %d 件 (エラー %d 件)", len(articles), len(errors))
    return articles, errors


def collect_youtube_transcript(video_id: str) -> Optional[str]:
    try:
        transcript = YouTubeTranscriptApi().fetch(video_id, languages=["ja", "en"])
    except (NoTranscriptFound, TranscriptsDisabled, VideoUnavailable):
        return None
    return " ".join(snippet.text for snippet in transcript)


def save_article(supabase_client, article: dict) -> Optional[dict]:
    source_url = article.get("source_url", "")
    existing = (
        supabase_client.table("articles")
        .select("id")
        .eq("source_url", source_url)
        .execute()
    )
    if existing.data:
        logger.debug("[save] 重複スキップ: %s", source_url[:80])
        return None

    record = {
        **article,
        "id": article.get("id") or str(uuid.uuid4()),  # NOT NULL なので明示生成
        "category": article.get("category") or "未分類",
        "difficulty": article.get("difficulty") or "低",
        "status": "collected",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    logger.info(
        "[save] INSERT開始 id=%s category=%s difficulty=%s source_type=%s url=%s",
        record["id"],
        record["category"],
        record["difficulty"],
        record.get("source_type"),
        source_url[:80],
    )

    result = supabase_client.table("articles").insert(record).execute()
    if not result.data:
        # 例外なしで data が空 → RLS ブロックまたはスキーマ不一致の silent failure
        logger.error(
            "[save] INSERT失敗（data空）id=%s url=%s raw=%s",
            record["id"],
            source_url[:80],
            str(result)[:300],
        )
        return None
    saved = result.data[0]
    logger.info("[save] 保存完了: id=%s", saved.get("id"))
    return saved
