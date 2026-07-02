from fastapi import APIRouter, Depends, HTTPException

from app.db import get_db
from app.models.article import ArticleStatusUpdate

router = APIRouter(prefix="/articles", tags=["articles"])


@router.get("")
def list_articles(status: str | None = None, db=Depends(get_db)):
    query = db.table("articles").select("*")
    if status:
        query = query.eq("status", status)
    result = query.order("created_at", desc=True).execute()
    return result.data


@router.get("/{article_id}")
def get_article(article_id: str, db=Depends(get_db)):
    result = db.table("articles").select("*").eq("id", article_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="記事が見つかりません")
    return result.data[0]


@router.patch("/{article_id}/status")
def update_article_status(article_id: str, payload: ArticleStatusUpdate, db=Depends(get_db)):
    result = (
        db.table("articles")
        .update({"status": payload.status})
        .eq("id", article_id)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="記事が見つかりません")
    return result.data[0]
