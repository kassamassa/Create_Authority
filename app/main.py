from fastapi import FastAPI

from app.routers import articles, monitor, newsletter, pipeline, webhook

app = FastAPI(title="Create Authority")

app.include_router(pipeline.router)
app.include_router(articles.router)
app.include_router(newsletter.router)
app.include_router(monitor.router)
app.include_router(webhook.router)


@app.get("/")
def root():
    return {"service": "create-authority", "status": "running"}
