import os
from datetime import datetime, timezone

import resend
from dotenv import load_dotenv

load_dotenv()

resend.api_key = os.getenv("RESEND_API_KEY", "")
NEWSLETTER_FROM = os.getenv("NEWSLETTER_FROM", "Create Authority <news@create-authority.jp>")


def build_newsletter_html(articles: list[dict]) -> str:
    items = "".join(
        f'<li><a href="{a["source_url"]}">{a["title"]}</a><p>{a.get("summary") or ""}</p></li>'
        for a in articles
    )
    return f"<html><body><ul>{items}</ul></body></html>"


def send_newsletter(articles: list[dict], recipients: list[str], subject: str = "DX事例まとめ") -> dict:
    html = build_newsletter_html(articles)
    response = resend.Emails.send({
        "from": NEWSLETTER_FROM,
        "to": recipients,
        "subject": subject,
        "html": html,
    })
    return response


def mark_newsletter_sent(supabase_client, article_ids: list[str]) -> None:
    now = datetime.now(timezone.utc).isoformat()
    supabase_client.table("articles").update({"newsletter_sent_at": now}).in_("id", article_ids).execute()
