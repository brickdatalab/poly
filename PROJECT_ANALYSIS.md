# Project Analysis — `poly`

**Generated**: February 10, 2026
**Analyst**: Claude (automated codebase analysis)

---

## Overview

`poly` is a **15-minute crypto price prediction system** built on Supabase Postgres. It ingests real-time trade data from Coinbase Exchange via WebSocket streamers running on GCP, computes multi-timeframe OHLCV rollups and 156 technical indicators in-database, and feeds curated feature sets into ML models that predict short-term price direction for BTC-USD, ETH-USD, and SOL-USD. The ultimate execution target is Polymarket prediction markets.

The repository itself is an **ops + analysis workspace** — not the full application codebase. It contains operational scripts (healthchecks, backfills, schema docs), GCP streamer shadow deployments, historical model post-mortems, and documentation. The live computation engine (triggers, stored functions, indicator configs) lives inside the Supabase database itself.

---

## Tech Stack

| Category | Technology | Details |
|----------|------------|---------|
| **Database** | PostgreSQL 17.6 (Supabase) | AWS us-east-2, project ref `cxvntzszdkyggjjenefn` |
| **Schemas** | 6 active | `public`, `indicators`, `training`, `polymarket`, `alpha`, `mining` |
| **Ingestion runtime** | Node.js 20 (ESM) | WebSocket streamers via `coinbase-api` SDK |
| **Ops scripting** | Python 3.11 | `psql` subprocess calls, no ORM |
| **Containerization** | Docker + docker-compose | `node:20-slim` base images |
| **Cloud** | GCP (Cloud Run implied) | Shadow streamers with health endpoints |
| **API layer** | Supabase PostgREST | Auto-generated REST; OpenAPI specs in `docs/api/` |
| **ML (historical)** | XGBoost, LightGBM, Neural Net | Walk-forward CV, purged temporal splits |
| **Prediction markets** | Polymarket CLOB | `py-clob-client` for trade execution |
| **External data** | Coinbase Exchange, Binance Futures | Trades (real-time), OI (15m cadence) |

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                        GCP Cloud Run                         │
│  ┌──────────────────────┐  ┌──────────────────────────────┐  │
│  │ crypto-streamer-     │  │ market-context-streamer-     │  │
│  │ shadow               │  │ shadow                       │  │
│  │ (Coinbase matches    │  │ (Coinbase ticker best bid/   │  │
│  │  → raw_trades)       │  │  ask → market_context)       │  │
│  └──────────┬───────────┘  └──────────────┬───────────────┘  │
│             │ WebSocket → batch INSERT     │                  │
└─────────────┼─────────────────────────────┼──────────────────┘
              │                             │
              ▼                             ▼
┌──────────────────────────────────────────────────────────────┐
│                   Supabase Postgres 17.6                      │
│                                                              │
│  PUBLIC SCHEMA (raw ingestion layer)                         │
│  ├─ raw_trades (36M+ rows, monthly partitions)               │
│  ├─ ohlcv_1m, market_context, order_book_snapshots           │
│  ├─ price_intervals_15m_live (live interval state)           │
│  ├─ websocket_heartbeat (streamer liveness)                  │
│  └─ gpt52-predictions, sfm-predictions, smash (legacy)      │
│                                                              │
│  INDICATORS SCHEMA (real-time computation)      ┌──────────┐ │
│  ├─ ohlcv_{1m..12h} (9 timeframe tables)       │ 55 funcs │ │
│  ├─ indicator_values (weekly partitions, 1.4M+) │ 37 trigs │ │
│  ├─ indicator_configs (156 active)              │ 48 tables│ │
│  ├─ open_interest, oi_features                  │ 8 views  │ │
│  ├─ order_book_indicators                       └──────────┘ │
│  └─ job_queue, computation_log                               │
│                                                              │
│  TRAINING SCHEMA (historical ML features)                    │
│  ├─ spot_{1m,15m,1h} (4.5M+ rows in 1m)                    │
│  ├─ spot_{15m,1h}_indicators (wide enriched tables)          │
│  ├─ unified_{15m,1h} (curated training-ready)                │
│  ├─ synthetic_features (153K rows)                           │
│  └─ polymarket_ticks (reserved, empty)                       │
│                                                              │
│  ALPHA SCHEMA (feature store + predictions)                  │
│  ├─ 8 tables + 4 views                                      │
│  └─ Stale since 2026-02-02                                   │
│                                                              │
│  POLYMARKET SCHEMA (live market snapshots)                   │
│  └─ markets_live_15m, markets_live_1h                        │
│                                                              │
│  MINING SCHEMA (offline analysis)                            │
│  └─ 7 tables, not in live path                               │
└──────────────────────────────────────────────────────────────┘
              │
              ▼
┌──────────────────────────────────────────────────────────────┐
│  ML Inference (currently being rebuilt as V5)                 │
│  ├─ V1: LLM-based (54.1% accuracy) — retired                │
│  ├─ V2: SFM rule-based (57.98% live) — retired              │
│  ├─ V3: XGBoost 53-feat (47% live) — retired                │
│  ├─ V4: Ensemble 272-feat (37-54% live) — retired            │
│  └─ V5: Proposed — 12-feature XGBoost with online learning   │
│                                                              │
│  Execution Target: Polymarket CLOB (py-clob-client)          │
└──────────────────────────────────────────────────────────────┘
```

---

## Project Structure

```
poly/
├── README.md                           # Ops notes + script index + schema changelog
├── .env                                # Supabase creds, OI API key (SENSITIVE)
├── gcp_credentials.json                # GCP service account (SENSITIVE)
├── INDICATORS_SCHEMA.md                # Auto-generated indicators schema reference
├── TRAINING_SCHEMA.md                  # Auto-generated training schema reference
├── BINANCE-OI.md                       # Open Interest integration recap
├── training_ready.md                   # ML-ready dataset spec (108 safe features)
├── base-project-analysis-2-6-2026.md   # Previous full project analysis
├── convo.md                            # Session conversation log
│
├── scripts/                            # Active operational scripts (~3,400 LOC)
│   ├── healthcheck_all.py              # Full pipeline healthcheck (756 LOC)
│   ├── generate_schema_reference_docs.py # Auto-gen schema Markdown (656 LOC)
│   ├── backfill_raw_trades_from_coinbase.py # Idempotent trade backfill (346 LOC)
│   ├── report_missing_ohlcv_lookback_7d.py  # Missing-candle report (271 LOC)
│   ├── ops_snapshot_ohlcv_state.py     # OHLCV health snapshot (259 LOC)
│   ├── compare_training_vs_indicators_15m.py # Schema alignment validation (244 LOC)
│   ├── export_missing_ohlcv_1m_minutes.py    # Missing-minute CSV export (193 LOC)
│   │
│   ├── training_schema_review/         # Training analysis framework (~940 LOC)
│   │   ├── run_all.py                  # Orchestrator (ThreadPoolExecutor, 5 sections)
│   │   ├── generate_training_ready_md.py # JSON→Markdown post-processor
│   │   ├── queries.py                  # SQL query library
│   │   ├── db.py                       # DB connection helper
│   │   ├── sections/                   # Analysis modules
│   │   │   ├── inventory.py, candles.py, indicators.py
│   │   │   ├── alignment_with_indicators.py, ambiguities.py
│   │   └── tests/                      # Smoke + env tests
│   │
│   ├── gcp_streamer_shadow/            # GCP-deployed WebSocket streamers (~674 LOC JS)
│   │   ├── crypto-streamer-shadow/     # Coinbase matches → raw_trades
│   │   │   ├── index.js, package.json, Dockerfile, docker-compose.yml
│   │   └── market-context-streamer-shadow/ # Coinbase ticker → market_context
│   │       ├── index.js, package.json, Dockerfile, docker-compose.yml
│   │
│   ├── scripts_past/                   # Retired V3/V4 model scripts (~2,400 LOC)
│   │   ├── train_models.py             # V4 ensemble training
│   │   ├── run_tick.py                 # V4 real-time inference
│   │   ├── check_success_criteria.py   # Post-deploy validation (889 LOC)
│   │   ├── backfill_rollups_missing_only.py # Historical rollup backfill
│   │   └── tests/                      # 7 test files (unit + integration)
│   │
│   └── output/                         # Generated reports, CSVs, SQL artifacts
│
├── docs/
│   ├── plans/                          # Operational runbooks
│   │   ├── 2026-02-09-training-rt-alignment.md
│   │   └── 2026-02-08-ohlcv-ingestion-migration-and-backfill.md
│   └── api/                            # OpenAPI 3.1 specifications
│       ├── indicators.openapi.yaml
│       └── training.openapi.yaml
│
├── previous_models/                    # Model version post-mortems
│   ├── v1_analysis.md                  # LLM-based (54.1%)
│   ├── v2_analysis.md                  # SFM rule-based (57.98%)
│   ├── v3_analysis.md                  # XGBoost 53-feat (47% live)
│   ├── v4_analysis.md                  # Ensemble 272-feat (37-54% live)
│   └── v5-proposal.md                  # Next-gen design (12-feature + online learning)
│
├── possible-trading-view-indicators/   # Indicator research notes
│   ├── i1-predicta.md, i2-flawless.md, i3-waves.md, i4-rsimulti.md
│   └── more-info-1.md, more-info-2.md
│
└── supabase/                           # Supabase CLI metadata only
    └── .temp/                          # project-ref, version files
```

**Total codebase**: ~7,400 lines of active code (Python + JS), plus ~2,400 lines of retired scripts.

---

## Key Patterns

### Database Architecture
The database uses a **multi-schema event-driven pipeline**: raw trades land in `public`, trigger `indicators.fn_process_new_trade` (a `SECURITY DEFINER` trigger function) which cascades through OHLCV rollups and indicator computation via a job queue. This is a **stored-procedure-heavy architecture** — 55 functions and 37 triggers in `indicators` alone do the heavy lifting. The application layer is thin by design.

Notable patterns:
- **Weekly partitioning** on `indicator_values` keeps recent-query performance stable as historical data grows.
- **Config-driven indicators**: 156 active configs in `indicator_configs` (JSONB params) define what gets computed, making indicator additions a data change rather than a code change.
- **Long-table design** for indicators (`pair, bucket_time, config_id, v1..v5`) trades query flexibility for storage density.
- **Separate OHLCV tables per timeframe** (9 tables from 1m to 12h) for query isolation — no filter on timeframe column needed.

### Ingestion Layer
Two parallel WebSocket streamers (Node.js, Dockerized) connect to Coinbase Exchange:
- `crypto-streamer-shadow`: subscribes to `matches` channel, buffers trades in-memory, batch-flushes to `public.raw_trades` every 3 seconds. Includes disk-backup fallback after 3 consecutive DB failures and automatic restore on reconnect.
- `market-context-streamer-shadow`: subscribes to `ticker` channel, writes best bid/ask to `public.market_context` every 2 seconds.

Both implement: health endpoints (`GET /health`), heartbeat writes to `public.websocket_heartbeat`, watchdog timers for reconnection, graceful shutdown with buffer drain, and overflow-to-disk protection.

### ML Pipeline Evolution
Four model versions have been tried and retired, each with a thorough post-mortem:

| Version | Approach | Validation | Live | Gap | Core Failure |
|---------|----------|-----------|------|-----|-------------|
| V1 | LLM (GPT-5.2) | N/A | 54.1% | N/A | Wrong tool; language reasoning ≠ price prediction |
| V2 | SFM rule-based | 65.3% | 58.0% | -7.3pp | Static thresholds; overfitting to training regime |
| V3 | XGBoost 53-feat | 75-80% | 47% | -28 to -33pp | Temporal leakage in walk-forward CV; CVD data freeze |
| V4 | Ensemble 272-feat | 62-65% | 37-54% | -7 to -13pp | Curse of dimensionality; weak ensemble members |

V5 is proposed but not yet implemented. It targets 12 hand-curated features, XGBoost with Platt-scaled calibration, walk-forward CV with 48h embargo, and 24h expanding-window online retraining.

### Operational Tooling
The project has strong operational tooling for a single-developer system:
- **healthcheck_all.py**: Comprehensive pipeline healthcheck covering DB connectivity, heartbeats, raw trade freshness, market context, order book, OHLCV freshness + gaps, rollup alignment, indicator completeness, job queue backlog, and PostgREST availability. Outputs JSON reports.
- **backfill_raw_trades_from_coinbase.py**: Idempotent trade recovery with `ON CONFLICT DO NOTHING`, trigger bypass during bulk insert, and automatic OHLCV rebuild.
- **generate_schema_reference_docs.py**: Self-documenting schema via Postgres metadata queries → Markdown.
- **training_schema_review/**: Parallel analysis framework (ThreadPoolExecutor with heavy-query semaphore) that generates training-readiness reports.

### API Layer
Two OpenAPI 3.1 specs define logical read APIs over `indicators` and `training` schemas. In practice, the Supabase PostgREST auto-generated API serves as the runtime. The specs document intended query patterns and response shapes for downstream consumers (models, dashboards).

### Security
- Authentication: Supabase JWT + API key (via PostgREST)
- RLS: **Disabled everywhere** (noted as a known gap in the project analysis)
- Secrets: `.env` file with Supabase DB credentials, service keys, and OI API keys
- GCP credentials: `gcp_credentials.json` at repo root (sensitive; should be in a secret manager)
- Open Interest API: `X-API-Key` header authentication
- DB connections: SSL required (`rejectUnauthorized: false` in Node streamers — accepts self-signed)

### Testing
Tests exist for the retired V3/V4 models (7 test files under `scripts_past/tests/`) and for the training schema review framework (2 smoke tests). The healthcheck and backfill scripts are implicitly tested via production runs. There is no formal CI pipeline, test runner configuration, or linting setup in the repository.

---

## Entry Points

| Purpose | Entry Point |
|---------|------------|
| **Live trade ingestion** | `scripts/gcp_streamer_shadow/crypto-streamer-shadow/index.js` |
| **Live market context** | `scripts/gcp_streamer_shadow/market-context-streamer-shadow/index.js` |
| **Pipeline healthcheck** | `python3 scripts/healthcheck_all.py` |
| **OHLCV state snapshot** | `python3 scripts/ops_snapshot_ohlcv_state.py` |
| **Missing candle report** | `python3 scripts/report_missing_ohlcv_lookback_7d.py` |
| **Trade backfill** | `python3 scripts/backfill_raw_trades_from_coinbase.py` |
| **Schema doc generation** | `python3 scripts/generate_schema_reference_docs.py` |
| **Training readiness review** | `python3 scripts/training_schema_review/run_all.py` |
| **Schema alignment check** | `python3 scripts/compare_training_vs_indicators_15m.py` |

---

## Conventions

- **Naming**: snake_case for Python, camelCase for JS. SQL objects use snake_case. Pairs are hyphenated (`BTC-USD`).
- **DB interaction**: All Python scripts use `psql` subprocess calls (no Python ORM or DB library). This keeps dependencies minimal but couples to `psql` binary availability.
- **Environment**: All scripts load from `/Users/vitolo/Desktop/projects/poly/.env` with a custom `load_dotenv()` (no `python-dotenv` dependency).
- **Output**: Scripts write JSON reports to `scripts/output/` with UTC timestamps in filenames.
- **Hardcoded paths**: Scripts reference `/Users/vitolo/Desktop/projects/poly/` directly — not portable without modification.
- **Schema changes**: Tracked in `README.md` changelog table (manual, not migration-file-based).
- **Model versions**: Each version gets a post-mortem analysis in `previous_models/`.

---

## Current System Status (as of Feb 10, 2026)

| Component | Status | Notes |
|-----------|--------|-------|
| Trade ingestion (crypto-streamer) | **Live** | Current through 2026-02-10 00:44Z |
| Market context (ticker streamer) | **Live** | Streaming best bid/ask |
| OHLCV 1m rollup | **Live** | Current through 2026-02-10 00:45Z |
| Multi-timeframe rollups (5m–12h) | **Live** | 9 timeframe tables maintained |
| Indicator computation (156 configs) | **Live** | 1.4M+ indicator value rows |
| Open interest (Binance) | **Live** | 6K rows; OI features computed |
| Order book indicators | **Live** | 147K rows |
| Training data (historical) | **Stale** | Through 2026-02-01 only |
| Training data (RT-aligned) | **New** | Being built per 2026-02-09 plan |
| ML predictions (V4) | **Stale** | Last prediction ~2026-02-02 |
| ML predictions (V5) | **Not started** | Proposal exists |
| Polymarket execution | **Inactive** | Tables exist; trading paused |

---

## Data Scale

| Table/Partition | Estimated Rows | Size |
|-----------------|---------------|------|
| `public.raw_trades` (all partitions) | ~36.3M | Multi-GB |
| `training.spot_1m` | 4.55M | 1,007 MB |
| `indicators.indicator_values` (active weeks) | 1.4M | ~419 MB |
| `training.unified_15m` | 634K | 793 MB |
| `training.spot_15m_indicators` | 634K | 573 MB |
| `training.spot_1h_indicators` | 159K | 143 MB |
| `training.synthetic_features` | 154K | 45 MB |
| `indicators.order_book_indicators` | 147K | 58 MB |
| `indicators.ohlcv_1m` | 80K | 65 MB |
| `indicators.job_queue` | 85K | 28 MB |

---

## Risks and Technical Debt

1. **No primary keys on raw_trade partitions**: Duplicates possible if upstream replays aren't deduped. The `ON CONFLICT (trade_id, executed_at) DO NOTHING` in the streamer mitigates but doesn't eliminate the risk for other insertion paths.

2. **RLS disabled everywhere**: All Supabase schemas operate without Row Level Security. The PostgREST API is exposed with service-key-level access. Any client with the anon key could potentially query unrestricted data.

3. **Hardcoded absolute paths**: Every Python script references `/Users/vitolo/Desktop/projects/poly/`. Not portable to another developer or CI environment without modification.

4. **No CI/CD pipeline**: No `.github/workflows/`, no linting configuration, no automated test runner. Quality gates are manual.

5. **No migration tracking**: Schema changes are logged in README.md manually. The `supabase/` directory has only `.temp/` metadata — no migration files. This makes rollbacks and reproducibility fragile.

6. **SSL certificate validation disabled**: Both Node.js streamers use `ssl: { rejectUnauthorized: false }`. This accepts any certificate, including MITM. Standard for Supabase's self-signed Postgres certs, but worth noting.

7. **Credentials in repo**: `.env` and `gcp_credentials.json` are in the workspace. While `.gitignore` excludes `.env`, the GCP credentials file at repo root is a supply-chain risk if this directory is ever pushed.

8. **Training-serving skew**: The historical training data (`training.*`) uses Binance spot data, while live serving (`indicators.*`) uses Coinbase Exchange data. The 2026-02-09 RT-alignment plan addresses this, but it's the project's most critical data quality challenge.

9. **Stale prediction infrastructure**: V4 model predictions stopped 2026-02-02. The alpha schema, SMASH execution engine, and prediction tables are all effectively dormant. Dead code creates confusion about what's actually running.

10. **Single-person bus factor**: All scripts, all operational knowledge, and all secret access are concentrated on one developer. No runbooks exist for someone else to take over operations.

---

## What's Working Well

- **Ingestion resilience**: The streamer design (disk backup on failure, automatic restore, watchdog reconnection, graceful shutdown with buffer drain) is production-grade for a single-developer project.
- **Healthcheck depth**: `healthcheck_all.py` is genuinely comprehensive — 10 distinct checks covering the full pipeline from WebSocket to indicator computation, with PASS/WARN/FAIL semantics and JSON reports.
- **Post-mortem discipline**: Four model versions, four honest post-mortems with quantified failure modes. This iterative learning is rare and valuable.
- **Schema documentation**: Auto-generated from live metadata, so it never drifts from reality.
- **Config-driven indicators**: Adding a new indicator is a database INSERT, not a code change. This is a strong design pattern for a rapidly evolving feature set.
