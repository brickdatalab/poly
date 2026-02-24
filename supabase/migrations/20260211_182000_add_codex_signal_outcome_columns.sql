-- Add realized outcome columns to codex_signals and keep them updated from ohlcv_15m.

alter table indicators.codex_signals
  add column if not exists opening_price numeric,
  add column if not exists closing_price numeric,
  add column if not exists actual_direction text,
  add column if not exists is_accurate boolean,
  add column if not exists resolved_at timestamptz;

do $$
begin
  if not exists (
    select 1
    from pg_constraint c
    join pg_class t on t.oid = c.conrelid
    join pg_namespace n on n.oid = t.relnamespace
    where n.nspname = 'indicators'
      and t.relname = 'codex_signals'
      and c.conname = 'codex_signals_actual_direction_check'
  ) then
    alter table indicators.codex_signals
      add constraint codex_signals_actual_direction_check
      check (actual_direction in ('up', 'down', 'flat') or actual_direction is null);
  end if;
end
$$;

create index if not exists idx_codex_signals_bucket_accuracy
  on indicators.codex_signals (bucket_time desc, is_accurate);

comment on column indicators.codex_signals.opening_price is
  'Open price of the 15m candle at bucket_time used to evaluate realized outcome.';
comment on column indicators.codex_signals.closing_price is
  'Close price of the 15m candle at bucket_time used to evaluate realized outcome.';
comment on column indicators.codex_signals.actual_direction is
  'Realized direction of the 15m candle at bucket_time: up/down/flat.';
comment on column indicators.codex_signals.is_accurate is
  'Whether prediction matched realized direction (null when actual_direction is flat).';
comment on column indicators.codex_signals.resolved_at is
  'Timestamp when outcome is fully known (bucket_time + 15 minutes).';

create or replace function indicators.fn_refresh_codex_signal_outcomes(
  p_lookback interval default interval '30 days'
)
returns integer
language plpgsql
as $$
declare
  v_rows integer := 0;
begin
  with src as (
    select
      s.id,
      o.open::numeric as opening_price,
      o.close::numeric as closing_price,
      case
        when o.close > o.open then 'up'
        when o.close < o.open then 'down'
        else 'flat'
      end as actual_direction,
      case
        when o.close > o.open then (s.prediction = 'up')
        when o.close < o.open then (s.prediction = 'down')
        else null
      end as is_accurate,
      (o.bucket_time + interval '15 minutes') as resolved_at
    from indicators.codex_signals s
    join indicators.ohlcv_15m o
      on o.pair = s.pair
     and o.bucket_time = s.bucket_time
    where s.bucket_time >= date_trunc('minute', now()) - p_lookback
  )
  update indicators.codex_signals dst
  set
    opening_price = src.opening_price,
    closing_price = src.closing_price,
    actual_direction = src.actual_direction,
    is_accurate = src.is_accurate,
    resolved_at = src.resolved_at
  from src
  where dst.id = src.id
    and (
      dst.opening_price is distinct from src.opening_price
      or dst.closing_price is distinct from src.closing_price
      or dst.actual_direction is distinct from src.actual_direction
      or dst.is_accurate is distinct from src.is_accurate
      or dst.resolved_at is distinct from src.resolved_at
    );

  get diagnostics v_rows = row_count;
  return v_rows;
end;
$$;

comment on function indicators.fn_refresh_codex_signal_outcomes(interval) is
  'Backfills/refreshes codex signal realized outcomes by joining to ohlcv_15m.';

create or replace function indicators.fn_emit_codex_signals_for_bucket(
  p_pair text,
  p_bucket_time timestamptz
)
returns integer
language plpgsql
as $$
declare
  v_rows integer := 0;
begin
  with matched as (
    select
      r.rule_id,
      r.pair,
      p_bucket_time as bucket_time,
      r.prediction,
      count(*) over (
        partition by r.pair, p_bucket_time, r.prediction
      )::integer as signals_passed,
      r.base_accuracy,
      s.v1 as indicator_value,
      r.config_id,
      now() as fired_at,
      p_bucket_time + interval '2 minutes' as decision_minute,
      o.open::numeric as opening_price,
      o.close::numeric as closing_price,
      case
        when o.open is null or o.close is null then null
        when o.close > o.open then 'up'
        when o.close < o.open then 'down'
        else 'flat'
      end as actual_direction,
      case
        when o.open is null or o.close is null then null
        when o.close > o.open then (r.prediction = 'up')
        when o.close < o.open then (r.prediction = 'down')
        else null
      end as is_accurate,
      case
        when o.bucket_time is null then null
        else o.bucket_time + interval '15 minutes'
      end as resolved_at
    from indicators.codex_signal_rules r
    join indicators.synthetic_indicator_values s
      on s.pair = r.pair
     and s.bucket_time = p_bucket_time
     and s.config_id = r.config_id
    left join indicators.ohlcv_15m o
      on o.pair = r.pair
     and o.bucket_time = p_bucket_time
    where r.is_active
      and r.pair = p_pair
      and s.v1 is not null
      and (
        (r.operator = '>=' and s.v1 >= r.threshold)
        or
        (r.operator = '<=' and s.v1 <= r.threshold)
      )
  )
  insert into indicators.codex_signals (
    pair,
    bucket_time,
    rule_id,
    prediction,
    signals_passed,
    base_accuracy,
    indicator_value,
    config_id,
    fired_at,
    decision_minute,
    opening_price,
    closing_price,
    actual_direction,
    is_accurate,
    resolved_at
  )
  select
    pair,
    bucket_time,
    rule_id,
    prediction,
    signals_passed,
    base_accuracy,
    indicator_value,
    config_id,
    fired_at,
    decision_minute,
    opening_price,
    closing_price,
    actual_direction,
    is_accurate,
    resolved_at
  from matched
  on conflict (pair, bucket_time, rule_id) do update
  set
    prediction = excluded.prediction,
    signals_passed = excluded.signals_passed,
    base_accuracy = excluded.base_accuracy,
    indicator_value = excluded.indicator_value,
    config_id = excluded.config_id,
    fired_at = excluded.fired_at,
    decision_minute = excluded.decision_minute,
    opening_price = excluded.opening_price,
    closing_price = excluded.closing_price,
    actual_direction = excluded.actual_direction,
    is_accurate = excluded.is_accurate,
    resolved_at = excluded.resolved_at;

  get diagnostics v_rows = row_count;
  return v_rows;
end;
$$;

comment on function indicators.fn_emit_codex_signals_for_bucket(text,timestamptz) is
  'Evaluates active codex rules for pair/bucket and upserts fired signals with realized outcome fields when available.';

create or replace function indicators.fn_run_realtime_signal_tick(
  p_lookback interval default interval '45 minutes',
  p_syn_batch_size integer default 5000,
  p_codex_batch_size integer default 5000
)
returns jsonb
language plpgsql
as $$
declare
  v_syn_refreshed integer := 0;
  v_syn_enq bigint := 0;
  v_syn_done integer := 0;
  v_codex_enq bigint := 0;
  v_codex_done integer := 0;
  v_outcomes_refreshed integer := 0;
begin
  v_syn_refreshed := indicators.fn_refresh_recent_synthetic(greatest(p_lookback, interval '45 minutes'));
  v_syn_enq := indicators.fn_enqueue_synthetic_jobs(p_lookback);
  v_syn_done := indicators.fn_process_synthetic_jobs(p_syn_batch_size);
  v_codex_enq := indicators.fn_enqueue_codex_signal_jobs(p_lookback);
  v_codex_done := indicators.fn_process_codex_signal_jobs(p_codex_batch_size);
  v_outcomes_refreshed := indicators.fn_refresh_codex_signal_outcomes(greatest(p_lookback, interval '7 days'));

  return jsonb_build_object(
    'ran_at_utc', now(),
    'lookback', p_lookback::text,
    'synthetic_refreshed', v_syn_refreshed,
    'synthetic_enqueued', v_syn_enq,
    'synthetic_processed', v_syn_done,
    'codex_enqueued', v_codex_enq,
    'codex_processed', v_codex_done,
    'outcomes_refreshed', v_outcomes_refreshed
  );
end;
$$;

comment on function indicators.fn_run_realtime_signal_tick(interval,integer,integer) is
  'Realtime tick: refresh/enqueue/process synthetic jobs, enqueue/process codex jobs, and refresh realized outcomes.';

-- Backfill outcomes for all existing codex signal rows (since launch date).
select indicators.fn_refresh_codex_signal_outcomes(interval '365 days');
