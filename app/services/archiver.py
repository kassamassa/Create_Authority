import os
from datetime import datetime, timezone


def archive_article(supabase_client, article_id: str) -> dict:
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
