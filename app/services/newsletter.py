import os
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import resend
from dotenv import load_dotenv

load_dotenv()

resend.api_key = os.getenv("RESEND_API_KEY", "")
NEWSLETTER_FROM = os.getenv("NEWSLETTER_FROM", "Create Authority <news@create-authority.jp>")


def current_week_start(today: Optional[date] = None) -> date:
    today = today or date.today()
    return today - timedelta(days=today.weekday())  # その週の月曜日


def get_weekly_candidate(supabase_client, week_start: Optional[date] = None) -> Optional[dict]:
    """newsletter_queueからis_sent=falseかつ指定週のレコードを取得し、quality_scoreが最も高い記事を1本選ぶ。"""
    week_start = week_start or current_week_start()
    result = (
        supabase_client.table("newsletter_queue")
        .select("*, articles(*)")
        .eq("is_sent", False)
        .eq("week_start", week_start.isoformat())
        .execute()
    )
    candidates = [row for row in result.data if row.get("articles")]
    if not candidates:
        return None
    return max(candidates, key=lambda row: row["articles"].get("quality_score") or 0)


def build_newsletter_html(article: dict) -> str:
    return f"""<html><body>
<h1>{article['title']}</h1>
<p>{article.get('summary') or ''}</p>
<p><a href="{article['source_url']}">元記事を読む</a></p>
<hr>
<p>個別に詳しく知りたい方・DX導入を検討中の方はこのメールに返信してください。全て読んでいます。</p>
</body></html>"""


def send_newsletter_email(article: dict, recipients: list[str]) -> dict:
    html = build_newsletter_html(article)
    return resend.Emails.send({
        "from": NEWSLETTER_FROM,
        "to": recipients,
        "subject": article["title"],
        "html": html,
    })


def mark_queue_sent(supabase_client, queue_id: str) -> Optional[dict]:
    now = datetime.now(timezone.utc).isoformat()
    result = (
        supabase_client.table("newsletter_queue")
        .update({"is_sent": True, "sent_at": now})
        .eq("id", queue_id)
        .execute()
    )
    return result.data[0] if result.data else None


def add_to_newsletter_queue(supabase_client, article_id: str, week_start: Optional[date] = None) -> Optional[dict]:
    """公開済み記事を今週のnewsletter_queueに追加する。"""
    week_start = week_start or current_week_start()
    result = (
        supabase_client.table("newsletter_queue")
        .insert({
            "article_id": article_id,
            "week_start": week_start.isoformat(),
            "is_sent": False,
        })
        .execute()
    )
    return result.data[0] if result.data else None


def send_weekly_newsletter(supabase_client, recipients: list[str], week_start: Optional[date] = None) -> dict:
    queue_entry = get_weekly_candidate(supabase_client, week_start)
    if not queue_entry:
        return {"sent": False, "reason": "配信候補の記事がありません"}

    article = queue_entry["articles"]
    send_newsletter_email(article, recipients)
    mark_queue_sent(supabase_client, queue_entry["id"])
    return {"sent": True, "article_id": article["id"], "queue_id": queue_entry["id"]}
