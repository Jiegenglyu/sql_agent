SELECT format('CREATE ROLE %I WITH LOGIN PASSWORD %L', :'readonly_user', :'readonly_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'readonly_user')
\gexec

DROP SCHEMA IF EXISTS circle CASCADE;
DROP SCHEMA IF EXISTS aiinfra CASCADE;
CREATE SCHEMA aiinfra;

CREATE TABLE aiinfra.clusters (
    id BIGSERIAL PRIMARY KEY,
    cluster_name TEXT NOT NULL UNIQUE,
    region TEXT NOT NULL,
    provider TEXT NOT NULL CHECK (provider IN ('aws', 'gcp', 'azure', 'onprem')),
    environment TEXT NOT NULL CHECK (environment IN ('prod', 'staging', 'research')),
    power_capacity_kw NUMERIC(10, 2) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE aiinfra.gpu_nodes (
    id BIGSERIAL PRIMARY KEY,
    cluster_id BIGINT NOT NULL REFERENCES aiinfra.clusters(id),
    node_name TEXT NOT NULL UNIQUE,
    gpu_model TEXT NOT NULL,
    gpu_count INTEGER NOT NULL CHECK (gpu_count > 0),
    gpu_memory_gb INTEGER NOT NULL CHECK (gpu_memory_gb > 0),
    status TEXT NOT NULL CHECK (status IN ('active', 'maintenance', 'offline')),
    hourly_cost_usd NUMERIC(10, 2) NOT NULL,
    installed_at DATE NOT NULL
);

CREATE TABLE aiinfra.teams (
    id BIGSERIAL PRIMARY KEY,
    team_name TEXT NOT NULL UNIQUE,
    business_unit TEXT NOT NULL,
    priority_tier TEXT NOT NULL CHECK (priority_tier IN ('tier1', 'tier2', 'tier3'))
);

CREATE TABLE aiinfra.workloads (
    id BIGSERIAL PRIMARY KEY,
    team_id BIGINT NOT NULL REFERENCES aiinfra.teams(id),
    workload_name TEXT NOT NULL,
    workload_type TEXT NOT NULL CHECK (workload_type IN ('training', 'inference', 'batch', 'embedding')),
    framework TEXT NOT NULL,
    priority TEXT NOT NULL CHECK (priority IN ('low', 'normal', 'high', 'critical')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE aiinfra.gpu_allocations (
    id BIGSERIAL PRIMARY KEY,
    workload_id BIGINT NOT NULL REFERENCES aiinfra.workloads(id),
    node_id BIGINT NOT NULL REFERENCES aiinfra.gpu_nodes(id),
    started_at TIMESTAMPTZ NOT NULL,
    ended_at TIMESTAMPTZ,
    allocated_gpus INTEGER NOT NULL CHECK (allocated_gpus > 0),
    avg_gpu_utilization_pct NUMERIC(5, 2) NOT NULL CHECK (avg_gpu_utilization_pct >= 0 AND avg_gpu_utilization_pct <= 100),
    avg_memory_utilization_pct NUMERIC(5, 2) NOT NULL CHECK (avg_memory_utilization_pct >= 0 AND avg_memory_utilization_pct <= 100),
    gpu_hours NUMERIC(12, 2) NOT NULL CHECK (gpu_hours >= 0),
    status TEXT NOT NULL CHECK (status IN ('running', 'completed', 'failed', 'canceled'))
);

CREATE TABLE aiinfra.daily_gpu_metrics (
    id BIGSERIAL PRIMARY KEY,
    metric_date DATE NOT NULL,
    cluster_id BIGINT NOT NULL REFERENCES aiinfra.clusters(id),
    team_id BIGINT REFERENCES aiinfra.teams(id),
    gpu_model TEXT NOT NULL,
    total_gpus INTEGER NOT NULL CHECK (total_gpus >= 0),
    available_gpus INTEGER NOT NULL CHECK (available_gpus >= 0),
    allocated_gpu_hours NUMERIC(12, 2) NOT NULL CHECK (allocated_gpu_hours >= 0),
    idle_gpu_hours NUMERIC(12, 2) NOT NULL CHECK (idle_gpu_hours >= 0),
    avg_gpu_utilization_pct NUMERIC(5, 2) NOT NULL CHECK (avg_gpu_utilization_pct >= 0 AND avg_gpu_utilization_pct <= 100),
    p95_gpu_utilization_pct NUMERIC(5, 2) NOT NULL CHECK (p95_gpu_utilization_pct >= 0 AND p95_gpu_utilization_pct <= 100),
    queue_wait_minutes NUMERIC(10, 2) NOT NULL CHECK (queue_wait_minutes >= 0),
    spot_interruptions INTEGER NOT NULL CHECK (spot_interruptions >= 0),
    cost_usd NUMERIC(12, 2) NOT NULL CHECK (cost_usd >= 0),
    UNIQUE (metric_date, cluster_id, team_id, gpu_model)
);

CREATE TABLE aiinfra.capacity_events (
    id BIGSERIAL PRIMARY KEY,
    cluster_id BIGINT NOT NULL REFERENCES aiinfra.clusters(id),
    event_time TIMESTAMPTZ NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('info', 'warning', 'critical')),
    event_type TEXT NOT NULL CHECK (event_type IN ('capacity_shortage', 'node_failure', 'maintenance', 'quota_limit')),
    message TEXT NOT NULL,
    affected_gpus INTEGER NOT NULL CHECK (affected_gpus >= 0),
    resolved_at TIMESTAMPTZ
);

COMMENT ON TABLE aiinfra.clusters IS 'AI infrastructure GPU clusters across regions and environments.';
COMMENT ON TABLE aiinfra.gpu_nodes IS 'Physical or cloud GPU nodes. Total card count comes from SUM(gpu_count).';
COMMENT ON TABLE aiinfra.daily_gpu_metrics IS 'Daily GPU capacity, card-hour usage, utilization, queue wait, and cost metrics.';
COMMENT ON TABLE aiinfra.gpu_allocations IS 'Workload-level GPU allocations with utilization and consumed GPU-hours.';
COMMENT ON TABLE aiinfra.capacity_events IS 'Operational capacity incidents such as shortages, node failures, and quota limits.';

COMMENT ON COLUMN aiinfra.daily_gpu_metrics.allocated_gpu_hours IS 'Used card-hours for the day. One GPU running for one hour equals one GPU-hour.';
COMMENT ON COLUMN aiinfra.daily_gpu_metrics.idle_gpu_hours IS 'Idle card-hours for the day.';
COMMENT ON COLUMN aiinfra.daily_gpu_metrics.avg_gpu_utilization_pct IS 'Average GPU core utilization percent for allocated GPUs.';
COMMENT ON COLUMN aiinfra.gpu_nodes.gpu_count IS 'Number of GPU cards installed on the node.';

INSERT INTO aiinfra.clusters (cluster_name, region, provider, environment, power_capacity_kw, created_at) VALUES
    ('shanghai-prod-a', 'cn-east', 'onprem', 'prod', 920.00, '2025-11-01 08:00:00+00'),
    ('singapore-prod-gpu', 'ap-southeast', 'aws', 'prod', 540.00, '2025-12-10 09:00:00+00'),
    ('tokyo-research-lab', 'ap-northeast', 'gcp', 'research', 310.00, '2026-01-15 10:00:00+00');

INSERT INTO aiinfra.gpu_nodes (cluster_id, node_name, gpu_model, gpu_count, gpu_memory_gb, status, hourly_cost_usd, installed_at) VALUES
    (1, 'sha-a-h100-001', 'H100-80GB', 8, 80, 'active', 31.60, '2025-11-02'),
    (1, 'sha-a-h100-002', 'H100-80GB', 8, 80, 'active', 31.60, '2025-11-02'),
    (1, 'sha-a-a100-001', 'A100-80GB', 8, 80, 'maintenance', 18.40, '2025-09-10'),
    (2, 'sg-h100-spot-001', 'H100-80GB', 8, 80, 'active', 35.20, '2025-12-11'),
    (2, 'sg-l40s-001', 'L40S-48GB', 8, 48, 'active', 9.60, '2026-01-07'),
    (3, 'tyo-a100-001', 'A100-80GB', 8, 80, 'active', 20.80, '2026-01-20'),
    (3, 'tyo-l40s-001', 'L40S-48GB', 4, 48, 'offline', 4.80, '2026-02-01');

INSERT INTO aiinfra.teams (team_name, business_unit, priority_tier) VALUES
    ('foundation-models', 'research', 'tier1'),
    ('recommendation', 'product', 'tier1'),
    ('search-ranking', 'product', 'tier2'),
    ('data-platform', 'platform', 'tier2'),
    ('experiments', 'research', 'tier3');

INSERT INTO aiinfra.workloads (team_id, workload_name, workload_type, framework, priority, created_at) VALUES
    (1, 'llm-pretrain-q2', 'training', 'pytorch', 'critical', '2026-05-01 03:00:00+00'),
    (2, 'recsys-daily-train', 'training', 'tensorflow', 'high', '2026-05-03 02:00:00+00'),
    (3, 'ranker-ab-batch', 'batch', 'pytorch', 'normal', '2026-05-03 05:30:00+00'),
    (4, 'embedding-refresh', 'embedding', 'pytorch', 'normal', '2026-05-04 01:00:00+00'),
    (1, 'eval-serving', 'inference', 'vllm', 'high', '2026-05-04 08:00:00+00');

INSERT INTO aiinfra.gpu_allocations (
    workload_id,
    node_id,
    started_at,
    ended_at,
    allocated_gpus,
    avg_gpu_utilization_pct,
    avg_memory_utilization_pct,
    gpu_hours,
    status
) VALUES
    (1, 1, '2026-05-07 00:00:00+00', '2026-05-07 12:00:00+00', 8, 86.40, 78.10, 96.00, 'completed'),
    (1, 2, '2026-05-07 00:00:00+00', NULL, 8, 91.30, 82.40, 142.00, 'running'),
    (2, 4, '2026-05-07 01:00:00+00', '2026-05-07 08:00:00+00', 6, 74.20, 68.90, 42.00, 'completed'),
    (3, 5, '2026-05-07 04:00:00+00', '2026-05-07 10:30:00+00', 4, 52.80, 47.10, 26.00, 'completed'),
    (4, 6, '2026-05-08 00:30:00+00', '2026-05-08 05:30:00+00', 8, 63.50, 71.20, 40.00, 'completed'),
    (5, 2, '2026-05-08 06:00:00+00', NULL, 2, 38.40, 55.60, 12.00, 'running');

INSERT INTO aiinfra.daily_gpu_metrics (
    metric_date,
    cluster_id,
    team_id,
    gpu_model,
    total_gpus,
    available_gpus,
    allocated_gpu_hours,
    idle_gpu_hours,
    avg_gpu_utilization_pct,
    p95_gpu_utilization_pct,
    queue_wait_minutes,
    spot_interruptions,
    cost_usd
) VALUES
    ('2026-05-07', 1, 1, 'H100-80GB', 16, 0, 356.00, 28.00, 88.20, 97.40, 42.00, 0, 14062.40),
    ('2026-05-07', 1, 2, 'A100-80GB', 8, 2, 76.00, 116.00, 61.50, 82.30, 18.00, 0, 1398.40),
    ('2026-05-07', 2, 2, 'H100-80GB', 8, 1, 134.00, 58.00, 74.20, 91.80, 24.00, 2, 4716.80),
    ('2026-05-07', 2, 3, 'L40S-48GB', 8, 4, 42.00, 150.00, 49.70, 72.20, 8.00, 0, 403.20),
    ('2026-05-07', 3, 5, 'A100-80GB', 8, 5, 38.00, 154.00, 43.10, 66.90, 5.00, 0, 790.40),
    ('2026-05-08', 1, 1, 'H100-80GB', 16, 0, 368.00, 16.00, 91.60, 98.80, 61.00, 0, 14540.80),
    ('2026-05-08', 1, 4, 'A100-80GB', 8, 3, 40.00, 152.00, 63.50, 80.50, 12.00, 0, 736.00),
    ('2026-05-08', 2, 2, 'H100-80GB', 8, 0, 174.00, 18.00, 82.30, 96.10, 39.00, 1, 6124.80),
    ('2026-05-08', 2, 3, 'L40S-48GB', 8, 3, 88.00, 104.00, 58.20, 77.90, 14.00, 0, 844.80),
    ('2026-05-08', 3, 5, 'A100-80GB', 8, 4, 54.00, 138.00, 47.60, 68.40, 7.00, 0, 1123.20);

INSERT INTO aiinfra.capacity_events (cluster_id, event_time, severity, event_type, message, affected_gpus, resolved_at) VALUES
    (1, '2026-05-08 03:20:00+00', 'warning', 'capacity_shortage', 'H100 queue wait exceeded 60 minutes for tier1 training jobs.', 16, NULL),
    (2, '2026-05-08 07:45:00+00', 'warning', 'quota_limit', 'AWS H100 spot quota near limit during recommendation training.', 8, NULL),
    (3, '2026-05-08 02:10:00+00', 'critical', 'node_failure', 'L40S node offline due to power supply alert.', 4, '2026-05-08 06:30:00+00'),
    (1, '2026-05-07 13:00:00+00', 'info', 'maintenance', 'A100 node reserved for scheduled driver maintenance.', 8, '2026-05-07 17:00:00+00');

CREATE INDEX gpu_nodes_cluster_model_idx ON aiinfra.gpu_nodes(cluster_id, gpu_model);
CREATE INDEX gpu_nodes_status_idx ON aiinfra.gpu_nodes(status);
CREATE INDEX daily_gpu_metrics_date_cluster_idx ON aiinfra.daily_gpu_metrics(metric_date, cluster_id);
CREATE INDEX daily_gpu_metrics_team_idx ON aiinfra.daily_gpu_metrics(team_id);
CREATE INDEX gpu_allocations_workload_started_idx ON aiinfra.gpu_allocations(workload_id, started_at);
CREATE INDEX capacity_events_open_idx ON aiinfra.capacity_events(severity, event_type) WHERE resolved_at IS NULL;

GRANT USAGE ON SCHEMA aiinfra TO :"readonly_user";
GRANT SELECT ON ALL TABLES IN SCHEMA aiinfra TO :"readonly_user";
ALTER DEFAULT PRIVILEGES IN SCHEMA aiinfra GRANT SELECT ON TABLES TO :"readonly_user";
