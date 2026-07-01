from fastapi import APIRouter, Depends

from app.db import get_db
from app.services import collector, dify

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


@router.post("/collect")
def run_collect(feed_url: str, db=Depends(get_db)):
    articles = collector.collect_from_rss(feed_url)
    saved = []
    for article in articles:
        result = collector.save_article(db, article)
        if result:
            saved.append(result)
    return {"collected": len(articles), "saved": len(saved), "articles": saved}


@router.post("/process/{article_id}")
def run_process(article_id: str, db=Depends(get_db)):
    result = db.table("articles").select("*").eq("id", article_id).execute()
    if not result.data:
        return {"error": "記事が見つかりません"}

    article = result.data[0]
    summary = dify.summarize_article(article["title"], article["content"])
    update = {**summary, "status": "processed"}
    updated = db.table("articles").update(update).eq("id", article_id).execute()
    return updated.data[0] if updated.data else None
