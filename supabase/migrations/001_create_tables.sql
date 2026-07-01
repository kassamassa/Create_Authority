-- v2.4要件定義書 18-2-1〜18-2-3 に基づくテーブル作成
-- articles / feedback / newsletter_queue

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- 18-2-1. articles: 記事データの中心テーブル。statusで全パイプラインの状態を管理する。
CREATE TABLE articles (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    title           text NOT NULL,
    content         text,
    summary         text,
    category        text NOT NULL,
    difficulty      text NOT NULL,
    quality_score   float,
    source_url      text NOT NULL UNIQUE,
    source_type     text NOT NULL,
    status          text NOT NULL,
    retry_count     int NOT NULL DEFAULT 0,
    failed_channel  text,
    failed_at       timestamptz,
    processed_at    timestamptz,
    published_at    timestamptz,
    archived_at     timestamptz,
    metadata        jsonb NOT NULL DEFAULT '{}',
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_articles_status ON articles (status);
CREATE INDEX idx_articles_category ON articles (category);
CREATE INDEX idx_articles_published_at ON articles (published_at);
CREATE INDEX idx_articles_created_at ON articles (created_at);

-- 18-2-2. feedback: メルマガ還信式返信の保存先。
CREATE TABLE feedback (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    article_id          uuid REFERENCES articles (id) ON DELETE SET NULL,
    sender_email        text NOT NULL,
    content             text NOT NULL,
    intent              text,
    is_responded        boolean NOT NULL DEFAULT false,
    applied_to_score    boolean NOT NULL DEFAULT false,
    created_at          timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT feedback_intent_check CHECK (
        intent IS NULL OR intent IN ('interest', 'inquiry', 'consultation', 'other')
    )
);

CREATE INDEX idx_feedback_created_at ON feedback (created_at);

-- 18-2-3. newsletter_queue: 週次メルマガ配信の候補管理。
CREATE TABLE newsletter_queue (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    article_id  uuid NOT NULL REFERENCES articles (id) ON DELETE CASCADE,
    week_start  date NOT NULL,
    is_sent     boolean NOT NULL DEFAULT false,
    sent_at     timestamptz,
    created_at  timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT newsletter_queue_week_article_unique UNIQUE (week_start, article_id)
);

CREATE INDEX idx_newsletter_queue_week_start ON newsletter_queue (week_start);
