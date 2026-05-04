-- Migration: 005_add_tool_vote_goal_rating
-- Replace the pill-flag feedback UI with a 1-5 goal-attainment rating per side.
-- The 14 vote_<pref>_<side> BOOLEANs from migration 004 are kept (NOT dropped):
-- existing rows still carry their pref data, queryable from the HF dataset.
-- New votes populate vote_goal_rating_<side> instead.
-- Run manually: psql $COMPARIA_DB_URI -f backend/tool_arena/migrations/005_add_tool_vote_goal_rating.sql

ALTER TABLE tool_votes
    ADD COLUMN IF NOT EXISTS vote_goal_rating_a SMALLINT
        CHECK (vote_goal_rating_a IS NULL OR vote_goal_rating_a BETWEEN 1 AND 5),
    ADD COLUMN IF NOT EXISTS vote_goal_rating_b SMALLINT
        CHECK (vote_goal_rating_b IS NULL OR vote_goal_rating_b BETWEEN 1 AND 5);
