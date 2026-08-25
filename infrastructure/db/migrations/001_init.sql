-- AlphaGasIQ initial schema (see docs/database-schema.md for the authoritative spec).
-- Applied automatically in dev via docker-entrypoint-initdb.d (see docker-compose.yml).
-- Idempotent: safe to re-run against an already-initialized database.

CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS vector;

-- ---------------------------------------------------------------------------
-- Canonical time-series observation (the audit backbone of the whole platform)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS observations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source TEXT NOT NULL,
    source_type TEXT NOT NULL CHECK (source_type IN ('PUBLIC', 'LICENSED', 'USER_PROVIDED', 'SIMULATED')),
    series_id TEXT NOT NULL,
    symbol TEXT,
    commodity TEXT NOT NULL DEFAULT 'NATURAL_GAS',
    category TEXT NOT NULL,
    sub_category TEXT,
    geography TEXT,
    location TEXT,
    value DOUBLE PRECISION NOT NULL,
    unit TEXT NOT NULL,
    observation_time TIMESTAMPTZ NOT NULL,
    publication_time TIMESTAMPTZ NOT NULL,
    received_time TIMESTAMPTZ NOT NULL DEFAULT now(),
    revision_number INTEGER NOT NULL DEFAULT 0,
    quality_score DOUBLE PRECISION,
    confidence DOUBLE PRECISION,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    lineage JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
SELECT create_hypertable('observations', 'observation_time', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS ix_observations_series_time ON observations (series_id, observation_time DESC);
CREATE INDEX IF NOT EXISTS ix_observations_cat_time ON observations (commodity, category, observation_time DESC);
CREATE INDEX IF NOT EXISTS ix_observations_source_pub ON observations (source, publication_time DESC);

-- ---------------------------------------------------------------------------
-- Agent execution audit trail
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS agent_executions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_id TEXT NOT NULL,
    agent_name TEXT NOT NULL,
    agent_type TEXT NOT NULL,
    version TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('SUCCESS', 'PARTIAL', 'FAILED', 'SKIPPED')),
    inputs JSONB NOT NULL DEFAULT '{}'::jsonb,
    outputs JSONB NOT NULL DEFAULT '{}'::jsonb,
    tools JSONB NOT NULL DEFAULT '[]'::jsonb,
    data_sources JSONB NOT NULL DEFAULT '[]'::jsonb,
    confidence DOUBLE PRECISION,
    last_execution_time TIMESTAMPTZ NOT NULL,
    execution_duration_ms DOUBLE PRECISION NOT NULL DEFAULT 0,
    reasoning_summary TEXT NOT NULL DEFAULT '',
    citations JSONB NOT NULL DEFAULT '[]'::jsonb,
    errors JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_agent_executions_agent_time ON agent_executions (agent_id, last_execution_time DESC);

-- ---------------------------------------------------------------------------
-- Trading objects
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS trade_ideas (
    trade_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    strategy TEXT NOT NULL,
    instrument TEXT NOT NULL,
    instrument_type TEXT NOT NULL,
    direction TEXT NOT NULL,
    entry DOUBLE PRECISION NOT NULL,
    target DOUBLE PRECISION NOT NULL,
    stop_or_invalidation DOUBLE PRECISION NOT NULL,
    time_horizon TEXT NOT NULL,
    expected_return DOUBLE PRECISION NOT NULL,
    expected_loss DOUBLE PRECISION NOT NULL,
    probability_success DOUBLE PRECISION NOT NULL,
    confidence DOUBLE PRECISION NOT NULL,
    thesis TEXT NOT NULL,
    catalysts JSONB NOT NULL DEFAULT '[]'::jsonb,
    risks JSONB NOT NULL DEFAULT '[]'::jsonb,
    invalidation_conditions JSONB NOT NULL DEFAULT '[]'::jsonb,
    supporting_data JSONB NOT NULL DEFAULT '[]'::jsonb,
    source_citations JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS committee_decisions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    original_trade_id UUID NOT NULL REFERENCES trade_ideas (trade_id),
    bull_case TEXT NOT NULL,
    bear_case TEXT NOT NULL,
    skeptic_case TEXT NOT NULL,
    data_quality_assessment TEXT NOT NULL,
    portfolio_effect TEXT NOT NULL,
    consensus_score DOUBLE PRECISION NOT NULL,
    unresolved_questions JSONB NOT NULL DEFAULT '[]'::jsonb,
    recommended_action TEXT NOT NULL
        CHECK (recommended_action IN ('APPROVE_FOR_REVIEW', 'REJECT', 'WAIT_FOR_MORE_DATA', 'REDUCE_SIZE')),
    decided_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS risk_checks (
    check_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    trade_id UUID NOT NULL REFERENCES trade_ideas (trade_id),
    verdict TEXT NOT NULL
        CHECK (verdict IN ('ALLOW', 'BLOCK', 'BLOCK_NEW_RISK', 'HALT', 'REJECT', 'REQUIRE_HUMAN')),
    rule_results JSONB NOT NULL DEFAULT '[]'::jsonb,
    governor_version TEXT NOT NULL,
    evaluated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS approvals (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    trade_id UUID NOT NULL REFERENCES trade_ideas (trade_id),
    state TEXT NOT NULL CHECK (state IN (
        'DRAFT', 'AI_REVIEW', 'RISK_REVIEW', 'HUMAN_REVIEW',
        'APPROVED_FOR_PAPER_TRADING', 'REJECTED', 'EXPIRED', 'EXECUTED_SIMULATION', 'CLOSED'
    )),
    actions JSONB NOT NULL DEFAULT '[]'::jsonb,
    current_user_id TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Paper trading / portfolio accounting
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS paper_orders (
    order_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    trade_id UUID REFERENCES trade_ideas (trade_id),
    instrument TEXT NOT NULL,
    order_type TEXT NOT NULL CHECK (order_type IN ('MARKET', 'LIMIT')),
    side TEXT NOT NULL CHECK (side IN ('BUY', 'SELL')),
    quantity DOUBLE PRECISION NOT NULL,
    limit_price DOUBLE PRECISION,
    status TEXT NOT NULL DEFAULT 'PENDING',
    filled_quantity DOUBLE PRECISION NOT NULL DEFAULT 0,
    submitted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    is_simulated BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS paper_fills (
    fill_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    order_id UUID NOT NULL REFERENCES paper_orders (order_id),
    instrument TEXT NOT NULL,
    side TEXT NOT NULL,
    quantity DOUBLE PRECISION NOT NULL,
    fill_price DOUBLE PRECISION NOT NULL,
    slippage DOUBLE PRECISION NOT NULL,
    commission DOUBLE PRECISION NOT NULL,
    spread_cost DOUBLE PRECISION NOT NULL,
    latency_ms DOUBLE PRECISION NOT NULL,
    filled_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    is_simulated BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS positions (
    instrument TEXT PRIMARY KEY,
    quantity DOUBLE PRECISION NOT NULL DEFAULT 0,
    avg_price DOUBLE PRECISION NOT NULL DEFAULT 0,
    delta DOUBLE PRECISION NOT NULL DEFAULT 0,
    gamma DOUBLE PRECISION NOT NULL DEFAULT 0,
    vega DOUBLE PRECISION NOT NULL DEFAULT 0,
    realized_pnl DOUBLE PRECISION NOT NULL DEFAULT 0,
    unrealized_pnl DOUBLE PRECISION NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Decision journal (append-only) and post-trade analysis
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS decision_journal (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    trade_id UUID NOT NULL REFERENCES trade_ideas (trade_id),
    data_snapshot_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    market_state JSONB NOT NULL DEFAULT '{}'::jsonb,
    news_state JSONB NOT NULL DEFAULT '{}'::jsonb,
    weather_state JSONB NOT NULL DEFAULT '{}'::jsonb,
    model_versions JSONB NOT NULL DEFAULT '{}'::jsonb,
    agent_versions JSONB NOT NULL DEFAULT '{}'::jsonb,
    thesis TEXT,
    counter_thesis TEXT,
    risk_analysis JSONB NOT NULL DEFAULT '{}'::jsonb,
    human_decision JSONB,
    paper_execution JSONB,
    outcome JSONB,
    supersedes_id UUID REFERENCES decision_journal (id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- Append-only by convention: application code must never UPDATE this table, only INSERT
-- (corrections reference `supersedes_id`). Enforced at the application layer; a
-- database-level trigger can be added once the write path is finalized.

CREATE TABLE IF NOT EXISTS post_trade_analyses (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    trade_id UUID NOT NULL REFERENCES trade_ideas (trade_id),
    expected_outcome JSONB NOT NULL DEFAULT '{}'::jsonb,
    actual_outcome JSONB NOT NULL DEFAULT '{}'::jsonb,
    forecast_error DOUBLE PRECISION,
    thesis_accuracy DOUBLE PRECISION,
    timing_accuracy DOUBLE PRECISION,
    risk_accuracy DOUBLE PRECISION,
    model_contribution JSONB NOT NULL DEFAULT '{}'::jsonb,
    unexpected_events JSONB NOT NULL DEFAULT '[]'::jsonb,
    lessons TEXT,
    quadrant TEXT CHECK (quadrant IN (
        'GOOD_DECISION_GOOD_OUTCOME', 'GOOD_DECISION_BAD_OUTCOME',
        'BAD_DECISION_GOOD_OUTCOME', 'BAD_DECISION_BAD_OUTCOME'
    )),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Domain reference tables
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS news_events (
    event_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    headline TEXT NOT NULL,
    source TEXT NOT NULL,
    source_url TEXT,
    published_at TIMESTAMPTZ NOT NULL,
    detected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    event_type TEXT NOT NULL,
    entities JSONB NOT NULL DEFAULT '[]'::jsonb,
    locations JSONB NOT NULL DEFAULT '[]'::jsonb,
    summary TEXT,
    supply_impact_bcf_day DOUBLE PRECISION NOT NULL DEFAULT 0,
    demand_impact_bcf_day DOUBLE PRECISION NOT NULL DEFAULT 0,
    expected_duration TEXT,
    affected_markets JSONB NOT NULL DEFAULT '[]'::jsonb,
    bullish_bearish TEXT,
    magnitude DOUBLE PRECISION,
    confidence DOUBLE PRECISION,
    citations JSONB NOT NULL DEFAULT '[]'::jsonb
);
CREATE INDEX IF NOT EXISTS ix_news_events_published ON news_events (published_at DESC);

CREATE TABLE IF NOT EXISTS weather_demand_impacts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    model TEXT NOT NULL,
    run TEXT NOT NULL,
    comparison_run TEXT NOT NULL,
    hdd_delta DOUBLE PRECISION NOT NULL,
    cdd_delta DOUBLE PRECISION NOT NULL,
    estimated_rescom_delta_bcf DOUBLE PRECISION NOT NULL,
    estimated_power_burn_delta_bcf DOUBLE PRECISION NOT NULL,
    total_demand_delta_bcf DOUBLE PRECISION NOT NULL,
    price_direction TEXT NOT NULL,
    confidence DOUBLE PRECISION NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
SELECT create_hypertable('weather_demand_impacts', 'created_at', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS storage_forecasts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    week_ending DATE NOT NULL,
    forecast_bcf DOUBLE PRECISION NOT NULL,
    market_consensus_bcf DOUBLE PRECISION,
    five_year_average_bcf DOUBLE PRECISION NOT NULL,
    last_year_bcf DOUBLE PRECISION NOT NULL,
    forecast_range_low DOUBLE PRECISION NOT NULL,
    forecast_range_high DOUBLE PRECISION NOT NULL,
    confidence DOUBLE PRECISION NOT NULL,
    drivers JSONB NOT NULL DEFAULT '[]'::jsonb,
    regional_breakdown JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS gas_balance_daily (
    flow_date DATE PRIMARY KEY,
    production_bcf DOUBLE PRECISION NOT NULL,
    canadian_imports_bcf DOUBLE PRECISION NOT NULL,
    lng_sendout_bcf DOUBLE PRECISION NOT NULL,
    other_supply_bcf DOUBLE PRECISION NOT NULL,
    rescom_demand_bcf DOUBLE PRECISION NOT NULL,
    industrial_demand_bcf DOUBLE PRECISION NOT NULL,
    power_burn_bcf DOUBLE PRECISION NOT NULL,
    lng_feedgas_bcf DOUBLE PRECISION NOT NULL,
    mexico_exports_bcf DOUBLE PRECISION NOT NULL,
    other_exports_bcf DOUBLE PRECISION NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Pipeline digital twin (graph model; portable to Neo4j later per docs/architecture.md)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pipeline_nodes (
    id TEXT PRIMARY KEY,
    node_type TEXT NOT NULL CHECK (node_type IN (
        'production_basin', 'processing_plant', 'pipeline_interconnect', 'storage_facility',
        'city_gate', 'power_plant', 'LNG_terminal', 'export_point', 'hub'
    )),
    name TEXT NOT NULL,
    geography JSONB NOT NULL DEFAULT '{}'::jsonb,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS pipeline_edges (
    id TEXT PRIMARY KEY,
    edge_type TEXT NOT NULL CHECK (edge_type IN ('pipeline', 'transport_contract', 'interconnect')),
    from_node_id TEXT NOT NULL REFERENCES pipeline_nodes (id),
    to_node_id TEXT NOT NULL REFERENCES pipeline_nodes (id),
    capacity_bcf_d DOUBLE PRECISION,
    scheduled_flow_bcf_d DOUBLE PRECISION,
    actual_flow_bcf_d DOUBLE PRECISION,
    utilization DOUBLE PRECISION,
    direction TEXT,
    maintenance JSONB NOT NULL DEFAULT '{}'::jsonb,
    constraint_info JSONB NOT NULL DEFAULT '{}'::jsonb,
    tariff JSONB NOT NULL DEFAULT '{}'::jsonb,
    basis_relationship JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS lng_terminals (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name TEXT NOT NULL,
    location TEXT NOT NULL,
    capacity_bcf_d DOUBLE PRECISION NOT NULL,
    feedgas_bcf_d DOUBLE PRECISION NOT NULL,
    utilization DOUBLE PRECISION,
    maintenance_status TEXT,
    outage_status TEXT,
    estimated_cargo_loadings INTEGER,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Market data
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS market_ticks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    symbol TEXT NOT NULL,
    continuous_contract TEXT,
    price DOUBLE PRECISION NOT NULL,
    volume DOUBLE PRECISION,
    open_interest DOUBLE PRECISION,
    bid DOUBLE PRECISION,
    ask DOUBLE PRECISION,
    settlement DOUBLE PRECISION,
    implied_volatility DOUBLE PRECISION,
    tick_time TIMESTAMPTZ NOT NULL,
    source TEXT NOT NULL,
    source_type TEXT NOT NULL
);
SELECT create_hypertable('market_ticks', 'tick_time', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS ix_market_ticks_symbol_time ON market_ticks (symbol, tick_time DESC);

-- ---------------------------------------------------------------------------
-- Risk configuration
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS risk_limits (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    max_position_size DOUBLE PRECISION NOT NULL,
    max_risk_per_trade DOUBLE PRECISION NOT NULL,
    max_daily_loss DOUBLE PRECISION NOT NULL,
    max_drawdown DOUBLE PRECISION NOT NULL,
    max_portfolio_var DOUBLE PRECISION NOT NULL,
    max_sector_exposure DOUBLE PRECISION NOT NULL,
    max_contract_exposure DOUBLE PRECISION NOT NULL,
    max_correlated_exposure DOUBLE PRECISION NOT NULL,
    effective_from TIMESTAMPTZ NOT NULL DEFAULT now(),
    effective_to TIMESTAMPTZ,
    set_by_user_id TEXT
);

-- ---------------------------------------------------------------------------
-- Identity, RBAC, audit
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    password_hash TEXT,
    is_mfa_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS roles (
    user_id UUID NOT NULL REFERENCES users (id),
    role TEXT NOT NULL CHECK (role IN ('ADMIN', 'TRADER', 'RISK_MANAGER', 'RESEARCHER', 'VIEWER')),
    PRIMARY KEY (user_id, role)
);

CREATE TABLE IF NOT EXISTS audit_log (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users (id),
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT,
    before JSONB,
    after JSONB,
    at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_audit_log_entity ON audit_log (entity_type, entity_id, at DESC);
