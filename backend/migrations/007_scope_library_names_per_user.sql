-- Library names are private to a user, so two users may both have a "Library".
ALTER TABLE libraries DROP CONSTRAINT IF EXISTS libraries_name_key;
DROP INDEX IF EXISTS ix_libraries_name;
CREATE INDEX IF NOT EXISTS ix_libraries_name ON libraries (name);
ALTER TABLE libraries
    ADD CONSTRAINT uq_libraries_user_name UNIQUE (user_id, name);
