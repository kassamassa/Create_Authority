from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from app.db import get_db
from app.services import archiver, collector, dify, publisher

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


@router.post("/collect")
async def run_collect(feed_url: Optional[str] = None, db=Depends(get_db)):
    """RSS・NewsAPIから記事を収集し、Difyで処理する。
    feed_url を指定すると指定フィードのみ収集。省略すると全ソースを収集。
    """
    all_articles: list[dict] = []
    errors: list[dict] = []

    if feed_url:
        try:
            all_articles.extend(collector.collect_from_rss(feed_url))
        except Exception as exc:
            errors.append({"source": feed_url, "error": str(exc)})
    else:
        rss_articles, rss_errors = collector.collect_all_rss()
        all_articles.extend(rss_articles)
        errors.extend(rss_errors)

        news_articles, news_errors = await collector.collect_all_newsapi()
        all_articles.extend(news_articles)
        errors.extend(news_errors)

    saved = []
    for article in all_articles:
        article.setdefault("category", "uncategorized")
        article.setdefault("difficulty", "中")
        result = collector.save_article(db, article)
        if result:
            saved.append(result)

    processed = []
    for article in saved:
        try:
            result = dify.process_article(db, article)
            if result:
                processed.append(result)
        except Exception:
            # process_article が status 更新・Slack 通知済みのため継続
            continue

    return {
        "collected": len(all_articles),
        "saved": len(saved),
        "processed": len(processed),
        "errors": errors,
    }


@router.post("/collect/youtube/{video_id}")
def run_collect_youtube(video_id: str, db=Depends(get_db)):
    """YouTube動画の字幕を収集してDifyで処理する。"""
    transcript = collector.collect_youtube_transcript(video_id)
    if transcript is None:
        raise HTTPException(
            status_code=404,
            detail="字幕が見つかりません（非公開・字幕無効・非対応言語）",
        )

    article = {
        "title": f"YouTube: {video_id}",
        "content": transcript,
        "source_url": f"https://www.youtube.com/watch?v={video_id}",
        "source_type": "youtube",
        "category": "uncategorized",
        "difficulty": "中",
    }
    saved = collector.save_article(db, article)
    if not saved:
        return {"message": "既に保存済みです", "saved": 0, "processed": 0}

    try:
        result = dify.process_article(db, saved)
        return {"collected": 1, "saved": 1, "processed": 1, "article": result}
    except Exception as exc:
        return {"collected": 1, "saved": 1, "processed": 0, "error": str(exc)}


@router.post("/process/{article_id}")
def run_process(article_id: str, db=Depends(get_db)):
    result = db.table("articles").select("*").eq("id", article_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="記事が見つかりません")
    return dify.process_article(db, result.data[0])


@router.post("/publish/{article_id}")
async def run_publish(article_id: str, db=Depends(get_db)):
    result = db.table("articles").select("*").eq("id", article_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="記事が見つかりません")
    return await publisher.publish_article_parallel(db, result.data[0])


@router.post("/archive/{article_id}")
def run_archive(article_id: str, db=Depends(get_db)):
    result = db.table("articles").select("*").eq("id", article_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="記事が見つかりません")

    try:
        return archiver.archive_article(db, result.data[0])
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"GitHubアーカイブに失敗しました: {exc}")
