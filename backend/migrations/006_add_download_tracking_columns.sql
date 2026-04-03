-- Add download tracking fields to chapters table
ALTER TABLE chapters ADD COLUMN IF NOT EXISTS download_started_at TIMESTAMP;
ALTER TABLE chapters ADD COLUMN IF NOT EXISTS download_finished_at TIMESTAMP;
ALTER TABLE chapters ADD COLUMN IF NOT EXISTS download_error VARCHAR(1000);
ALTER TABLE chapters ADD COLUMN IF NOT EXISTS retry_count INTEGER NOT NULL DEFAULT 0;
