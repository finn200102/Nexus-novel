-- Update site_chapter_id to BIGINT to support large IDs from external sites
ALTER TABLE chapters
    ALTER COLUMN site_chapter_id TYPE BIGINT USING site_chapter_id::bigint;
