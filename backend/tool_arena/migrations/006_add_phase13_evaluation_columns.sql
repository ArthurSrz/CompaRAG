-- Migration: 006_add_phase13_evaluation_columns
-- Phase 13 needle-in-haystack arena — benchmark/sandbox + judgement
-- Adds four columns to tool_votes (all NULL-safe; legacy rows keep their state):
--   haystack_mode         — 'benchmark' | 'sandbox' (defaults 'sandbox' for legacy)
--   evaluation_query_id   — id from corpus/evaluation/queries.yaml (NULL for sandbox)
--   judgement_a / _b      — JudgementScore.to_dict() JSON per side (NULL for sandbox)
-- Run manually: psql $COMPARIA_DB_URI -f backend/tool_arena/migrations/006_add_phase13_evaluation_columns.sql

ALTER TABLE tool_votes
    ADD COLUMN IF NOT EXISTS haystack_mode TEXT NOT NULL DEFAULT 'sandbox',
    ADD COLUMN IF NOT EXISTS evaluation_query_id TEXT,
    ADD COLUMN IF NOT EXISTS judgement_a JSONB,
    ADD COLUMN IF NOT EXISTS judgement_b JSONB;

-- Optional check constraint: only benchmark votes carry an eval id.
-- (Commented — keep enforcement at the API layer for now; migrations should
-- be reversible without losing data, and a strict CHECK would block legacy
-- backfills that mix the two modes.)
-- ALTER TABLE tool_votes
--     ADD CONSTRAINT IF NOT EXISTS tool_votes_benchmark_xor_eval_id
--     CHECK (
--         (haystack_mode = 'benchmark' AND evaluation_query_id IS NOT NULL)
--         OR (haystack_mode = 'sandbox' AND evaluation_query_id IS NULL)
--     );
