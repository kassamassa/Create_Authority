from fastapi import APIRouter, Depends

from app.db import get_db

router = APIRouter(prefix="/monitor", tags=["monitor"])


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/status")
def status(db=Depends(get_db)):
    result = db.table("articles").select("status").execute()
    counts: dict[str, int] = {}
    for row in result.data:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    return counts
