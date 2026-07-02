from fastapi import APIRouter, Depends, HTTPException

from app.db import get_db
from app.models.article import ArticleStatusUpdate
from app.services import publisher

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


@router.post("/{article_id}/retry")
async def retry_article(article_id: str, db=Depends(get_db)):
    """失敗したチャネル(failed_channel)のみ再投稿し、retry_countを増やす。"""
    result = db.table("articles").select("*").eq("id", article_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="記事が見つかりません")

    article = result.data[0]
    channel = article.get("failed_channel")
    if not channel:
        raise HTTPException(status_code=400, detail="リトライ対象のチャネルがありません")

    new_retry_count = article.get("retry_count", 0) + 1
    db.table("articles").update({"retry_count": new_retry_count}).eq("id", article_id).execute()
    article["retry_count"] = new_retry_count

    if channel == "sns":
        image = publisher.generate_carousel_image(article)
        return await publisher.publish_to_sns(db, article, image)
    return await publisher.publish_to_site(db, article)
