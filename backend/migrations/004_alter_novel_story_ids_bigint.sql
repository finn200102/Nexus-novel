-- Expand novel story ID columns to BIGINT to support large remote IDs
ALTER TABLE novels
    ALTER COLUMN site_story_id TYPE BIGINT USING site_story_id::bigint;

ALTER TABLE novels
    ALTER COLUMN story_id TYPE BIGINT USING story_id::bigint;
