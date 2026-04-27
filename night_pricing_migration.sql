-- SQL Migration for Night Pricing Feature
-- Run these commands on your Neon/Postgres console to update the schema

ALTER TABLE turf ADD COLUMN night_start_time INTEGER;
ALTER TABLE turf ADD COLUMN night_price_per_hour FLOAT;

-- Optional: Set default values if needed, though they are nullable
-- UPDATE turf SET night_start_time = NULL, night_price_per_hour = NULL;
