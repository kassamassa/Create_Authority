from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import articles, monitor, newsletter, pipeline, webhook

app = FastAPI(title="Create Authority")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://create-authority.vercel.app",
        "https://create-authority-gcu4t08rn-kassamassas-projects.vercel.app",
        "http://localhost:5175",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(pipeline.router)
app.include_router(articles.router)
app.include_router(newsletter.router)
app.include_router(monitor.router)
app.include_router(webhook.router)


@app.get("/")
def root():
    return {"service": "create-authority", "status": "running"}


@app.get("/health")
def health():
    return {"status": "ok"}
