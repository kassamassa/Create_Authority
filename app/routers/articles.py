from fastapi import APIRouter, Depends, HTTPException

from app.db import get_db
from app.models.article import ArticleUpdate

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


@router.patch("/{article_id}")
def update_article(article_id: str, payload: ArticleUpdate, db=Depends(get_db)):
    update_data = payload.model_dump(exclude_none=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="更新内容がありません")

    result = db.table("articles").update(update_data).eq("id", article_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="記事が見つかりません")
    return result.data[0]
