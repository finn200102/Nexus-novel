-- Add scrape_status and scrape_error columns to novels table
-- Migration: add_scrape_status_columns

ALTER TABLE novels ADD COLUMN IF NOT EXISTS scrape_status VARCHAR(20) DEFAULT 'completed';
ALTER TABLE novels ADD COLUMN IF NOT EXISTS scrape_error VARCHAR(500);
