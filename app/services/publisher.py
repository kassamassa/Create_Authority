import os
from datetime import datetime, timezone

import httpx
from dotenv import load_dotenv

load_dotenv()

SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")
SIGNED_URL_EXPIRES_IN = 1800  # 30分


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
