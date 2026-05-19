SELECT format('CREATE ROLE %I WITH LOGIN PASSWORD %L', :'readonly_user', :'readonly_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'readonly_user')
\gexec

DROP SCHEMA IF EXISTS aiinfra CASCADE;
CREATE SCHEMA aiinfra;

CREATE TABLE aiinfra.gpu_card_models (
    id BIGSERIAL PRIMARY KEY,
    pool_type TEXT NOT NULL UNIQUE,
    card_model TEXT NOT NULL,
    vendor TEXT NOT NULL,
    memory_gb INTEGER NOT NULL CHECK (memory_gb > 0),
    architecture TEXT NOT NULL,
    compute_capability TEXT,
    notes TEXT
);

CREATE TABLE aiinfra.resource_pools (
    id BIGSERIAL PRIMARY KEY,
    pool_name TEXT NOT NULL UNIQUE,
    pool_type TEXT NOT NULL REFERENCES aiinfra.gpu_card_models(pool_type),
    region TEXT NOT NULL,
    environment TEXT NOT NULL CHECK (environment IN ('prod', 'staging', 'research')),
    owner_team TEXT NOT NULL,
    total_cards INTEGER NOT NULL CHECK (total_cards >= 0),
    available_cards INTEGER NOT NULL CHECK (available_cards >= 0),
    status TEXT NOT NULL CHECK (status IN ('active', 'maintenance', 'offline')),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (available_cards <= total_cards)
);

COMMENT ON TABLE aiinfra.resource_pools IS 'Business resource pools. pool_type joins to gpu_card_models.pool_type.';
COMMENT ON TABLE aiinfra.gpu_card_models IS 'GPU card model dictionary for each business pool_type.';
COMMENT ON COLUMN aiinfra.resource_pools.pool_type IS 'Business pool specification such as Xlarge; joins to gpu_card_models.pool_type.';
COMMENT ON COLUMN aiinfra.resource_pools.total_cards IS 'Total GPU card count in the resource pool.';
COMMENT ON COLUMN aiinfra.resource_pools.available_cards IS 'Currently available GPU card count in the resource pool.';
COMMENT ON COLUMN aiinfra.gpu_card_models.card_model IS 'Actual GPU card model represented by the pool_type.';

INSERT INTO aiinfra.gpu_card_models (
    pool_type,
    card_model,
    vendor,
    memory_gb,
    architecture,
    compute_capability,
    notes
) VALUES
    ('Xlarge', 'A100-80GB', 'NVIDIA', 80, 'Ampere', '8.0', 'High-memory training and large inference workloads.'),
    ('Large', 'V100-32GB', 'NVIDIA', 32, 'Volta', '7.0', 'Legacy training and batch inference workloads.'),
    ('Medium', 'L40S-48GB', 'NVIDIA', 48, 'Ada Lovelace', '8.9', 'Graphics-heavy inference and embedding workloads.'),
    ('Small', 'T4-16GB', 'NVIDIA', 16, 'Turing', '7.5', 'Low-cost inference and development workloads.');

INSERT INTO aiinfra.resource_pools (
    pool_name,
    pool_type,
    region,
    environment,
    owner_team,
    total_cards,
    available_cards,
    status,
    updated_at
) VALUES
    ('roma-training-xlarge-sh', 'Xlarge', 'cn-east', 'prod', 'foundation-models', 64, 12, 'active', '2026-05-18 08:00:00+08'),
    ('roma-infer-xlarge-sg', 'Xlarge', 'ap-southeast', 'prod', 'inference-platform', 32, 4, 'active', '2026-05-18 08:05:00+08'),
    ('roma-batch-large-sh', 'Large', 'cn-east', 'prod', 'data-platform', 48, 18, 'active', '2026-05-18 08:10:00+08'),
    ('roma-research-medium-tokyo', 'Medium', 'ap-northeast', 'research', 'research-lab', 24, 9, 'active', '2026-05-18 08:15:00+08'),
    ('roma-dev-small-sh', 'Small', 'cn-east', 'staging', 'developer-experience', 16, 10, 'active', '2026-05-18 08:20:00+08'),
    ('roma-legacy-large-maint', 'Large', 'cn-east', 'prod', 'data-platform', 16, 0, 'maintenance', '2026-05-18 08:25:00+08');

CREATE INDEX resource_pools_pool_type_idx ON aiinfra.resource_pools(pool_type);
CREATE INDEX resource_pools_status_idx ON aiinfra.resource_pools(status);
CREATE INDEX resource_pools_region_idx ON aiinfra.resource_pools(region);
CREATE INDEX gpu_card_models_card_model_idx ON aiinfra.gpu_card_models(card_model);

GRANT USAGE ON SCHEMA aiinfra TO :"readonly_user";
GRANT SELECT ON ALL TABLES IN SCHEMA aiinfra TO :"readonly_user";
ALTER DEFAULT PRIVILEGES IN SCHEMA aiinfra GRANT SELECT ON TABLES TO :"readonly_user";
