from fastapi import APIRouter, Depends

from app.db import get_db
from app.services.newsletter import send_weekly_newsletter

router = APIRouter(prefix="/newsletter", tags=["newsletter"])


@router.post("/send")
def send(recipients: list[str], db=Depends(get_db)):
    return send_weekly_newsletter(db, recipients)
