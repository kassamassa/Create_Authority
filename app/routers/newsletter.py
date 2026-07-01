from fastapi import APIRouter, Depends

from app.db import get_db
from app.services.newsletter import mark_newsletter_sent, send_newsletter

router = APIRouter(prefix="/newsletter", tags=["newsletter"])


@router.post("/send")
def send(recipients: list[str], db=Depends(get_db)):
    result = db.table("articles").select("*").eq("status", "published").is_("newsletter_sent_at", "null").execute()
    articles = result.data
    if not articles:
        return {"sent": 0}

    send_newsletter(articles, recipients)
    mark_newsletter_sent(db, [a["id"] for a in articles])
    return {"sent": len(articles)}
