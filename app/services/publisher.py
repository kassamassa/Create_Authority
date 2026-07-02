import asyncio
import os
from datetime import datetime, timedelta, timezone

import httpx
from dotenv import load_dotenv

load_dotenv()

SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")
SIGNED_URL_EXPIRES_IN = 1800  # 30分

POSTIZ_API_URL = os.getenv("POSTIZ_API_URL", "https://api.postiz.com/v1")
POSTIZ_API_KEY = os.getenv("POSTIZ_API_KEY", "")
VERCEL_API_URL = os.getenv("VERCEL_API_URL", "https://api.vercel.com")
VERCEL_TOKEN = os.getenv("VERCEL_TOKEN", "")

REQUEST_TIMEOUT = 30.0
RETRY_DELAY_SECONDS = 3600  # 1時間後リトライ


class PublishConfigError(Exception):
    """4xx系の設定ミスなど、リトライ対象外のエラー"""


class PublishTemporaryError(Exception):
    """5xx・タイムアウトなど、リトライ対象の一時障害"""


def notify_slack(message: str) -> None:
    if not SLACK_WEBHOOK_URL:
        return
    try:
        httpx.post(SLACK_WEBHOOK_URL, json={"text": message}, timeout=10.0)
    except httpx.HTTPError:
        pass


def generate_signed_url(supabase_client, bucket: str, path: str, expires_in: int = SIGNED_URL_EXPIRES_IN) -> str:
    result = supabase_client.storage.from_(bucket).create_signed_url(path, expires_in)
    return result.get("signedURL") or result.get("signedUrl", "")


def publish_article(supabase_client, article_id: str) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    result = (
        supabase_client.table("articles")
        .update({"status": "published", "published_at": now})
        .eq("id", article_id)
        .execute()
    )
    return result.data[0] if result.data else None


# --- ステップ⑤ カルーセル画像生成 ---

def build_carousel_html(article: dict) -> str:
    return f"""<html><body>
<h1>{article['title']}</h1>
<p>{article.get('summary') or ''}</p>
</body></html>"""


def render_html_to_png(html: str) -> bytes:
    """HTML→PNG変換。レンダリングライブラリは未選定のため実装はTODO。"""
    raise NotImplementedError("HTML→PNG変換のレンダリングライブラリは未選定です(要選定・実装)")


def generate_carousel_image(article: dict) -> bytes:
    html = build_carousel_html(article)
    return render_html_to_png(html)


# --- 共通エラー判別・リトライ記録 ---

def _classify_error(exc: Exception, channel: str, context: str) -> Exception:
    if isinstance(exc, httpx.TimeoutException):
        notify_slack(f"[publisher] {channel}: 一時障害(タイムアウト)が発生しました: {context}")
        return PublishTemporaryError(str(exc))
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status >= 500:
            notify_slack(f"[publisher] {channel}: 一時障害(サーバーエラー{status})が発生しました: {context}")
            return PublishTemporaryError(str(exc))
        notify_slack(f"[publisher] {channel}: 設定ミスの可能性があります({status}): {context}")
        return PublishConfigError(str(exc))
    return exc


def _record_channel_failure(supabase_client, article_id: str, channel: str, retry_count: int) -> None:
    now = datetime.now(timezone.utc).isoformat()
    supabase_client.table("articles").update({
        "failed_channel": channel,
        "failed_at": now,
        "retry_count": retry_count + 1,
    }).eq("id", article_id).execute()


def schedule_retry(article_id: str, channel: str, delay_seconds: int = RETRY_DELAY_SECONDS) -> dict:
    run_at = datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)
    return {"article_id": article_id, "channel": channel, "run_at": run_at.isoformat()}


# --- ステップ⑥ SNS投稿(Postiz) ---

async def publish_to_sns(supabase_client, article: dict, image: bytes) -> dict:
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{POSTIZ_API_URL}/posts",
                headers={"Authorization": f"Bearer {POSTIZ_API_KEY}"},
                files={"image": ("carousel.png", image, "image/png")},
                data={"content": article.get("title", "")},
                timeout=REQUEST_TIMEOUT,
            )
        response.raise_for_status()
    except (httpx.TimeoutException, httpx.HTTPStatusError) as exc:
        mapped = _classify_error(exc, "sns", f"article_id={article['id']}")
        if isinstance(mapped, PublishTemporaryError):
            _record_channel_failure(supabase_client, article["id"], "sns", article.get("retry_count", 0))
            schedule_retry(article["id"], "sns")
        raise mapped from exc

    now = datetime.now(timezone.utc).isoformat()
    result = (
        supabase_client.table("articles")
        .update({"status": "published", "published_at": now})
        .eq("id", article["id"])
        .execute()
    )
    return result.data[0] if result.data else None


# --- ステップ⑦ サイト公開(Vercel・SEO/AEO記事) ---

def build_jsonld(article: dict) -> dict:
    faq = (article.get("metadata") or {}).get("faq") or []
    return {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": article["title"],
        "description": article.get("summary") or "",
        "articleSection": article.get("category"),
        "mainEntity": [
            {
                "@type": "Question",
                "name": item.get("q"),
                "acceptedAnswer": {"@type": "Answer", "text": item.get("a")},
            }
            for item in faq
        ],
    }


async def publish_to_site(supabase_client, article: dict) -> dict:
    payload = {
        "title": article["title"],
        "content": article.get("content") or article.get("summary") or "",
        "jsonld": build_jsonld(article),
    }
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{VERCEL_API_URL}/v1/content",
                headers={"Authorization": f"Bearer {VERCEL_TOKEN}"},
                json=payload,
                timeout=REQUEST_TIMEOUT,
            )
        response.raise_for_status()
    except (httpx.TimeoutException, httpx.HTTPStatusError) as exc:
        mapped = _classify_error(exc, "site", f"article_id={article['id']}")
        if isinstance(mapped, PublishTemporaryError):
            _record_channel_failure(supabase_client, article["id"], "site", article.get("retry_count", 0))
            schedule_retry(article["id"], "site")
        raise mapped from exc

    now = datetime.now(timezone.utc).isoformat()
    result = (
        supabase_client.table("articles")
        .update({"status": "published", "published_at": now})
        .eq("id", article["id"])
        .execute()
    )
    return result.data[0] if result.data else None


# --- 投稿分岐フロー(①②を並列実行) ---

async def publish_article_parallel(supabase_client, article: dict) -> dict:
    try:
        image = generate_carousel_image(article)
    except Exception as exc:
        notify_slack(
            f"[publisher] カルーセル画像生成に失敗したためSNS投稿をスキップします: "
            f"article_id={article['id']}: {exc}"
        )
        image = None

    async def _skipped_sns() -> dict:
        return {"skipped": True, "reason": "carousel image generation failed"}

    sns_coro = publish_to_sns(supabase_client, article, image) if image is not None else _skipped_sns()
    site_coro = publish_to_site(supabase_client, article)

    sns_result, site_result = await asyncio.gather(sns_coro, site_coro, return_exceptions=True)

    return {
        "sns": sns_result if not isinstance(sns_result, Exception) else {"error": str(sns_result)},
        "site": site_result if not isinstance(site_result, Exception) else {"error": str(site_result)},
    }
