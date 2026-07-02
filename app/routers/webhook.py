from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from app.db import get_db
from app.services.feedback import analyze_intent
from app.services.publisher import notify_slack

router = APIRouter(prefix="/webhook", tags=["webhook"])


@router.post("/dify")
async def dify_callback(request: Request, db=Depends(get_db)):
    payload = await request.json()
    article_id = payload.get("article_id")
    outputs = payload.get("outputs", {})
    if not article_id:
        return {"received": True, "updated": False}

    db.table("articles").update({
        "summary": outputs.get("summary"),
        "category": outputs.get("category"),
        "status": "processed",
    }).eq("id", article_id).execute()
    return {"received": True, "updated": True}


class FeedbackPayload(BaseModel):
    article_id: Optional[str] = None
    sender_email: str
    content: str


@router.post("/feedback")
def receive_feedback(payload: FeedbackPayload, db=Depends(get_db)):
    """Resendからの還信式返信を受け取りfeedbackテーブルに保存する(外部自動呼び出し専用)。"""
    intent = analyze_intent(payload.content)

    record = {
        "article_id": payload.article_id,
        "sender_email": payload.sender_email,
        "content": payload.content,
        "intent": intent,
        "is_responded": False,
        "applied_to_score": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    result = db.table("feedback").insert(record).execute()
    saved = result.data[0] if result.data else None

    if intent == "consultation":
        notify_slack(f"[feedback] consultation意図の返信を検知しました: sender={payload.sender_email}")

    return saved
