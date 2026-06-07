-- scripts/init_db.sql
-- Runs automatically on first PostgreSQL container startup.

-- Enable pgvector extension for embedding storage and similarity search
CREATE EXTENSION IF NOT EXISTS vector;

-- Raw log lines table (we'll fill this in Day 2-3)
CREATE TABLE IF NOT EXISTS raw_logs (
    id BIGSERIAL PRIMARY KEY,
    log_timestamp TIMESTAMP,
    component VARCHAR(255),
    level VARCHAR(50),
    message TEXT NOT NULL,
    is_anomaly BOOLEAN DEFAULT FALSE,
    source_dataset VARCHAR(50),
    ingested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_raw_logs_timestamp ON raw_logs(log_timestamp);
CREATE INDEX IF NOT EXISTS idx_raw_logs_anomaly ON raw_logs(is_anomaly);

-- Log templates table (Day 2-3: Drain output)
CREATE TABLE IF NOT EXISTS log_templates (
    id BIGSERIAL PRIMARY KEY,
    template TEXT UNIQUE NOT NULL,
    occurrence_count INTEGER DEFAULT 0,
    first_seen TIMESTAMP,
    last_seen TIMESTAMP
);

-- Incidents table - synthesized incident summaries (Day 8-9: source for RAG)
CREATE TABLE IF NOT EXISTS incidents (
    id BIGSERIAL PRIMARY KEY,
    title VARCHAR(500) NOT NULL,
    summary TEXT NOT NULL,
    severity VARCHAR(50),
    start_time TIMESTAMP,
    end_time TIMESTAMP,
    cluster_label INTEGER,
    root_cause_pattern TEXT,
    embedding vector(384),  -- 384-dim for all-MiniLM-L6-v2
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Vector similarity index (created after we have data; commented out for now)
-- CREATE INDEX ON incidents USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- Verification query (you can run this to confirm everything is set up)
DO $$
BEGIN
    RAISE NOTICE 'incident_db schema initialized successfully';
    RAISE NOTICE 'Tables: raw_logs, log_templates, incidents';
    RAISE NOTICE 'pgvector extension: enabled';
END $$;
