from fastapi import APIRouter, Depends, Request

from app.db import get_db

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
        "tags": outputs.get("tags"),
        "status": "processed",
    }).eq("id", article_id).execute()
    return {"received": True, "updated": True}
