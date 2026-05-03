-- Migration: 004_add_tool_vote_preferences
-- Add per-side preference flags to tool_votes for parity with the LLM ranking pipeline.
-- 7 prefs (useful/complete/creative/clear_formatting/incorrect/superficial/instructions_not_followed)
-- × 2 sides (a, b) = 14 BOOLEAN columns. DEFAULT FALSE backfills existing rows safely.
-- Run manually: psql $COMPARIA_DB_URI -f backend/tool_arena/migrations/004_add_tool_vote_preferences.sql

ALTER TABLE tool_votes
    ADD COLUMN IF NOT EXISTS vote_useful_a                  BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS vote_useful_b                  BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS vote_complete_a                BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS vote_complete_b                BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS vote_creative_a                BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS vote_creative_b                BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS vote_clear_formatting_a        BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS vote_clear_formatting_b        BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS vote_incorrect_a               BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS vote_incorrect_b               BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS vote_superficial_a             BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS vote_superficial_b             BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS vote_instructions_not_followed_a BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS vote_instructions_not_followed_b BOOLEAN NOT NULL DEFAULT FALSE;
