import base64
import os
from datetime import datetime, timezone

import httpx
from dotenv import load_dotenv

from app.services.publisher import notify_slack

load_dotenv()

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "kassamassa/Create_Authority")
GITHUB_API_URL = "https://api.github.com"
REQUEST_TIMEOUT = 30.0


def build_markdown(article: dict) -> str:
    faq = (article.get("metadata") or {}).get("faq") or []
    faq_md = "\n".join(f"**Q. {item.get('q')}**\n\nA. {item.get('a')}\n" for item in faq)
    return f"# {article['title']}\n\n{article.get('summary') or ''}\n\n{faq_md}"


def save_to_github(article: dict) -> dict:
    markdown = build_markdown(article)
    path = f"archive/{article['id']}.md"
    content_b64 = base64.b64encode(markdown.encode("utf-8")).decode("utf-8")

    response = httpx.put(
        f"{GITHUB_API_URL}/repos/{GITHUB_REPO}/contents/{path}",
        headers={
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json",
        },
        json={"message": f"archive: {article['id']}", "content": content_b64},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()


def archive_article(supabase_client, article: dict) -> dict:
    """GitHubへのMarkdown保存が成功した場合のみ、DBのcontentをNULL化する。"""
    article_id = article["id"]
    try:
        save_to_github(article)
    except Exception as exc:
        notify_slack(
            f"[archiver] GitHubアーカイブに失敗したため本文は保持されます: "
            f"article_id={article_id}: {exc}"
        )
        raise

    now = datetime.now(timezone.utc).isoformat()
    result = (
        supabase_client.table("articles")
        .update({"status": "archived", "archived_at": now, "content": None})
        .eq("id", article_id)
        .execute()
    )
    return result.data[0] if result.data else None


def reject_article(supabase_client, article_id: str) -> dict:
    result = (
        supabase_client.table("articles")
        .update({"status": "rejected"})
        .eq("id", article_id)
        .execute()
    )
    return result.data[0] if result.data else None


def cleanup_temp_file(path: str) -> None:
    if path and os.path.exists(path):
        os.remove(path)
