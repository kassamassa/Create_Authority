from fastapi import APIRouter, Depends, HTTPException

from app.db import get_db
from app.services import archiver, collector, dify, publisher

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


@router.post("/collect")
def run_collect(feed_url: str, db=Depends(get_db)):
    articles = collector.collect_from_rss(feed_url)
    saved = []
    for article in articles:
        article.setdefault("category", "uncategorized")
        article.setdefault("difficulty", "中")
        result = collector.save_article(db, article)
        if result:
            saved.append(result)

    processed = []
    for article in saved:
        try:
            processed.append(dify.process_article(db, article))
        except Exception:
            # process_articleが既にstatus更新・Slack通知を行っているため、
            # ここでは他の記事の処理を継続する
            continue

    return {"collected": len(articles), "saved": len(saved), "processed": processed}


@router.post("/process/{article_id}")
def run_process(article_id: str, db=Depends(get_db)):
    result = db.table("articles").select("*").eq("id", article_id).execute()
    if not result.data:
        return {"error": "記事が見つかりません"}

    article = result.data[0]
    return dify.process_article(db, article)


@router.post("/publish/{article_id}")
async def run_publish(article_id: str, db=Depends(get_db)):
    result = db.table("articles").select("*").eq("id", article_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="記事が見つかりません")

    article = result.data[0]
    return await publisher.publish_article_parallel(db, article)


@router.post("/archive/{article_id}")
def run_archive(article_id: str, db=Depends(get_db)):
    result = db.table("articles").select("*").eq("id", article_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="記事が見つかりません")

    article = result.data[0]
    try:
        return archiver.archive_article(db, article)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"GitHubアーカイブに失敗しました: {exc}")
