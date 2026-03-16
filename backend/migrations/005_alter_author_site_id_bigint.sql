-- Update author_site_id to BIGINT to support large IDs from external sites
ALTER TABLE novels
    ALTER COLUMN author_site_id TYPE BIGINT USING author_site_id::bigint;
