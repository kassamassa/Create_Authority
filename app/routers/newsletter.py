import os

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.db import get_db
from app.services.newsletter import send_weekly_newsletter

router = APIRouter(prefix="/newsletter", tags=["newsletter"])

RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
RESEND_AUDIENCE_ID = os.getenv("RESEND_AUDIENCE_ID", "")


class SubscribePayload(BaseModel):
    email: str
    name: str


@router.post("/subscribe")
def subscribe(payload: SubscribePayload):
    """Resend contacts APIにメールアドレスを登録する。Supabaseには保存しない。"""
    try:
        response = httpx.post(
            "https://api.resend.com/contacts",
            headers={
                "Authorization": f"Bearer {RESEND_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "email": payload.email,
                "first_name": payload.name,
                "unsubscribed": False,
                "audience_id": RESEND_AUDIENCE_ID,
            },
            timeout=10.0,
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail="メルマガ登録に失敗しました",
        )
    except Exception:
        raise HTTPException(status_code=502, detail="メルマガ登録に失敗しました")

    return {"message": "登録完了"}


@router.post("/send")
def send(recipients: list[str], db=Depends(get_db)):
    return send_weekly_newsletter(db, recipients)
