-- Codex realtime signals subsystem.
-- This is isolated from existing indicator and synthetic compute pipelines.

create schema if not exists indicators;

create table if not exists indicators.codex_signal_rules (
  rule_id text primary key,
  pair text not null,
  config_id text not null references indicators.synthetic_indicator_configs(config_id) on delete restrict,
  operator text not null check (operator in ('>=', '<=')),
  threshold numeric not null,
  prediction text not null check (prediction in ('up', 'down')),
  base_accuracy numeric not null,
  support_n integer not null check (support_n > 0),
  support_pct numeric not null check (support_pct > 0 and support_pct <= 1),
  is_active boolean not null default true,
  created_at timestamptz not null default now(),
  unique (pair, config_id, operator, threshold, prediction)
);

create index if not exists idx_codex_signal_rules_active_pair
  on indicators.codex_signal_rules (is_active, pair);

create table if not exists indicators.codex_signals (
  id bigint generated always as identity primary key,
  pair text not null,
  bucket_time timestamptz not null,
  rule_id text not null references indicators.codex_signal_rules(rule_id) on delete restrict,
  prediction text not null check (prediction in ('up', 'down')),
  signals_passed integer not null default 1 check (signals_passed >= 1),
  base_accuracy numeric not null,
  indicator_value numeric not null,
  config_id text not null,
  fired_at timestamptz not null default now(),
  decision_minute timestamptz not null,
  unique (pair, bucket_time, rule_id)
);

create index if not exists idx_codex_signals_pair_bucket
  on indicators.codex_signals (pair, bucket_time desc);

create index if not exists idx_codex_signals_bucket_prediction
  on indicators.codex_signals (bucket_time desc, prediction);

create table if not exists indicators.codex_signal_job_queue (
  id bigint generated always as identity primary key,
  pair text not null,
  bucket_time timestamptz not null,
  status text not null default 'pending' check (status in ('pending', 'running', 'done', 'failed')),
  attempts integer not null default 0,
  error_message text,
  created_at timestamptz not null default now(),
  started_at timestamptz,
  completed_at timestamptz,
  unique (pair, bucket_time)
);

create index if not exists idx_codex_signal_job_queue_status_created
  on indicators.codex_signal_job_queue (status, created_at);

comment on table indicators.codex_signal_rules is
  'Catalog of deterministic threshold rules used to emit codex realtime prediction signals.';
comment on column indicators.codex_signal_rules.rule_id is
  'Stable unique identifier for each codex threshold rule.';
comment on column indicators.codex_signal_rules.pair is
  'Pair this rule applies to (BTC-USD, ETH-USD, SOL-USD).';
comment on column indicators.codex_signal_rules.config_id is
  'Synthetic indicator config this rule evaluates against.';
comment on column indicators.codex_signal_rules.operator is
  'Threshold operator: >= or <=.';
comment on column indicators.codex_signal_rules.threshold is
  'Threshold value for the synthetic indicator v1.';
comment on column indicators.codex_signal_rules.prediction is
  'Predicted 15m market direction when rule condition passes.';
comment on column indicators.codex_signal_rules.base_accuracy is
  'Historical precision for this rule on the training window.';
comment on column indicators.codex_signal_rules.support_n is
  'Historical number of events where this rule condition passed.';
comment on column indicators.codex_signal_rules.support_pct is
  'Historical support ratio where this rule condition passed.';
comment on column indicators.codex_signal_rules.is_active is
  'Whether this rule is active for realtime emission.';

comment on table indicators.codex_signals is
  'Realtime emitted codex prediction signals for each pair and 15m bucket.';
comment on column indicators.codex_signals.bucket_time is
  '15m prediction window start time (t0) for the market event.';
comment on column indicators.codex_signals.rule_id is
  'Rule that fired and created this signal row.';
comment on column indicators.codex_signals.prediction is
  'Direction to bet for the 15m market: up or down.';
comment on column indicators.codex_signals.signals_passed is
  'Count of fired rules in the same pair/bucket/prediction direction.';
comment on column indicators.codex_signals.base_accuracy is
  'Base historical precision of the specific fired rule.';
comment on column indicators.codex_signals.indicator_value is
  'Synthetic indicator v1 value observed at evaluation time.';
comment on column indicators.codex_signals.config_id is
  'Synthetic config id used to evaluate this fired rule.';
comment on column indicators.codex_signals.decision_minute is
  'Decision timestamp associated with this event (bucket_time + 2 minutes).';

comment on table indicators.codex_signal_job_queue is
  'Forward-only queue for codex signal emission jobs keyed by pair and 15m bucket.';
comment on column indicators.codex_signal_job_queue.status is
  'Queue status: pending, running, done, or failed.';
comment on column indicators.codex_signal_job_queue.attempts is
  'Number of processing attempts for this queued job.';
