-- feedback / newsletter_queueでRLSが有効化されておりポリシー未設定のため
-- 書き込みがすべて拒否されていた(postgrest.exceptions.APIError 42501)。
-- 開発フェーズ(Phase 1)ではRLSを無効化する。認証基盤の整備に合わせて
-- Phase 3以降で改めて有効化・ポリシー設計を行う想定。

ALTER TABLE IF EXISTS articles DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS feedback DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS newsletter_queue DISABLE ROW LEVEL SECURITY;
