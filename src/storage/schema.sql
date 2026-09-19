CREATE TABLE IF NOT EXISTS analyses (
    id              UUID PRIMARY KEY,
    created_at      TIMESTAMPTZ NOT NULL,
    image_filename  TEXT NOT NULL,
    status          TEXT NOT NULL CHECK (status IN ('ok', 'partial', 'unknown_meal')),
    ingredients     JSONB NOT NULL,
    totals          JSONB NOT NULL,
    warnings        JSONB NOT NULL DEFAULT '[]'
);

CREATE INDEX IF NOT EXISTS idx_analyses_created_at ON analyses (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_analyses_status ON analyses (status);