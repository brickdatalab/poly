-- Pipeline health watchdog for freshness/continuity drift detection.
-- Uses cron job failure as an alert signal when SLOs are violated.

create table if not exists indicators.pipeline_health_audit (
  id bigserial primary key,
  ran_at_utc timestamptz not null default (now() at time zone 'utc'),
  violation_count integer not null,
  report jsonb not null
);

create index if not exists idx_pipeline_health_audit_ran_at
  on indicators.pipeline_health_audit (ran_at_utc desc);

create index if not exists idx_pipeline_health_audit_violation_count
  on indicators.pipeline_health_audit (violation_count, ran_at_utc desc);

comment on table indicators.pipeline_health_audit is
  'Append-only audit log of pipeline health snapshots and violation counts.';

create or replace function indicators.fn_pipeline_health_snapshot(
  p_pairs text[] default array['BTC-USD', 'ETH-USD', 'SOL-USD'],
  p_raw_trades_max_lag interval default interval '90 seconds',
  p_ohlcv_1m_max_lag interval default interval '2 minutes',
  p_ohlcv_5m_max_lag interval default interval '30 minutes',
  p_ohlcv_15m_max_lag interval default interval '45 minutes',
  p_indicator_values_max_lag interval default interval '45 minutes',
  p_order_book_max_lag interval default interval '2 minutes',
  p_open_interest_max_lag interval default interval '45 minutes',
  p_oi_features_max_lag interval default interval '45 minutes',
  p_stale_running_max_age interval default interval '10 minutes',
  p_ohlcv_1m_missing_lookback interval default interval '24 hours',
  p_ohlcv_1m_missing_minutes_max integer default 0
)
returns jsonb
language plpgsql
security definer
set search_path = indicators, public
as $$
declare
  v_now timestamptz := now();
  v_min_raw_trades timestamptz;
  v_min_ohlcv_1m timestamptz;
  v_min_ohlcv_5m timestamptz;
  v_min_ohlcv_15m timestamptz;
  v_min_indicator_values timestamptz;
  v_min_order_book timestamptz;
  v_min_open_interest timestamptz;
  v_min_oi_features timestamptz;
  v_pending int := 0;
  v_running int := 0;
  v_failed int := 0;
  v_stale_running int := 0;
  v_missing_1m_total int := 0;
  v_missing_1m_by_pair jsonb := '{}'::jsonb;
  v_violations jsonb := '[]'::jsonb;
begin
  select min(x.max_ts) into v_min_raw_trades
  from (
    select max(executed_at) as max_ts
    from public.raw_trades
    where pair = any(p_pairs)
    group by pair
  ) x;

  select min(x.max_ts) into v_min_ohlcv_1m
  from (
    select max(bucket_time) as max_ts
    from indicators.ohlcv_1m
    where pair = any(p_pairs)
    group by pair
  ) x;

  select min(x.max_ts) into v_min_ohlcv_5m
  from (
    select max(bucket_time) as max_ts
    from indicators.ohlcv_5m
    where pair = any(p_pairs)
    group by pair
  ) x;

  select min(x.max_ts) into v_min_ohlcv_15m
  from (
    select max(bucket_time) as max_ts
    from indicators.ohlcv_15m
    where pair = any(p_pairs)
    group by pair
  ) x;

  select min(x.max_ts) into v_min_indicator_values
  from (
    select max(bucket_time) as max_ts
    from indicators.indicator_values
    where pair = any(p_pairs)
    group by pair
  ) x;

  select min(x.max_ts) into v_min_order_book
  from (
    select max(captured_at) as max_ts
    from indicators.order_book_indicators
    where pair = any(p_pairs)
    group by pair
  ) x;

  select min(x.max_ts) into v_min_open_interest
  from (
    select max(bucket_time) as max_ts
    from indicators.open_interest
    where pair = any(p_pairs)
    group by pair
  ) x;

  select min(x.max_ts) into v_min_oi_features
  from (
    select max(bucket_time) as max_ts
    from indicators.oi_features
    where pair = any(p_pairs)
    group by pair
  ) x;

  select
    count(*) filter (where status = 'pending'),
    count(*) filter (where status = 'running'),
    count(*) filter (where status = 'failed')
  into v_pending, v_running, v_failed
  from indicators.job_queue;

  select count(*)
    into v_stale_running
  from indicators.job_queue
  where status = 'running'
    and started_at is not null
    and started_at < v_now - p_stale_running_max_age;

  with bounds as (
    select
      date_trunc('minute', v_now - p_ohlcv_1m_missing_lookback) as start_ts,
      date_trunc('minute', v_now - interval '1 minute') as end_ts
  ), expected as (
    select p as pair, gs as bucket_time
    from unnest(p_pairs) p
    cross join bounds b
    cross join generate_series(b.start_ts, b.end_ts, interval '1 minute') gs
  ), actual as (
    select o.pair, o.bucket_time
    from indicators.ohlcv_1m o
    cross join bounds b
    where o.pair = any(p_pairs)
      and o.bucket_time >= b.start_ts
      and o.bucket_time <= b.end_ts
  ), missing as (
    select e.pair, count(*)::int as missing_minutes
    from expected e
    left join actual a
      on a.pair = e.pair
     and a.bucket_time = e.bucket_time
    where a.bucket_time is null
    group by e.pair
  )
  select
    coalesce(sum(missing_minutes), 0)::int,
    coalesce(jsonb_object_agg(pair, missing_minutes), '{}'::jsonb)
  into v_missing_1m_total, v_missing_1m_by_pair
  from missing;

  if v_min_raw_trades is null or v_now - v_min_raw_trades > p_raw_trades_max_lag then
    v_violations := v_violations || jsonb_build_array(jsonb_build_object(
      'check', 'raw_trades_freshness',
      'min_latest_ts', v_min_raw_trades,
      'max_lag_seconds', extract(epoch from p_raw_trades_max_lag),
      'actual_lag_seconds', case when v_min_raw_trades is null then null else extract(epoch from (v_now - v_min_raw_trades)) end
    ));
  end if;

  if v_min_ohlcv_1m is null or v_now - v_min_ohlcv_1m > p_ohlcv_1m_max_lag then
    v_violations := v_violations || jsonb_build_array(jsonb_build_object(
      'check', 'ohlcv_1m_freshness',
      'min_latest_ts', v_min_ohlcv_1m,
      'max_lag_seconds', extract(epoch from p_ohlcv_1m_max_lag),
      'actual_lag_seconds', case when v_min_ohlcv_1m is null then null else extract(epoch from (v_now - v_min_ohlcv_1m)) end
    ));
  end if;

  if v_min_ohlcv_5m is null or v_now - v_min_ohlcv_5m > p_ohlcv_5m_max_lag then
    v_violations := v_violations || jsonb_build_array(jsonb_build_object(
      'check', 'ohlcv_5m_freshness',
      'min_latest_ts', v_min_ohlcv_5m,
      'max_lag_seconds', extract(epoch from p_ohlcv_5m_max_lag),
      'actual_lag_seconds', case when v_min_ohlcv_5m is null then null else extract(epoch from (v_now - v_min_ohlcv_5m)) end
    ));
  end if;

  if v_min_ohlcv_15m is null or v_now - v_min_ohlcv_15m > p_ohlcv_15m_max_lag then
    v_violations := v_violations || jsonb_build_array(jsonb_build_object(
      'check', 'ohlcv_15m_freshness',
      'min_latest_ts', v_min_ohlcv_15m,
      'max_lag_seconds', extract(epoch from p_ohlcv_15m_max_lag),
      'actual_lag_seconds', case when v_min_ohlcv_15m is null then null else extract(epoch from (v_now - v_min_ohlcv_15m)) end
    ));
  end if;

  if v_min_indicator_values is null or v_now - v_min_indicator_values > p_indicator_values_max_lag then
    v_violations := v_violations || jsonb_build_array(jsonb_build_object(
      'check', 'indicator_values_freshness',
      'min_latest_ts', v_min_indicator_values,
      'max_lag_seconds', extract(epoch from p_indicator_values_max_lag),
      'actual_lag_seconds', case when v_min_indicator_values is null then null else extract(epoch from (v_now - v_min_indicator_values)) end
    ));
  end if;

  if v_min_order_book is null or v_now - v_min_order_book > p_order_book_max_lag then
    v_violations := v_violations || jsonb_build_array(jsonb_build_object(
      'check', 'order_book_freshness',
      'min_latest_ts', v_min_order_book,
      'max_lag_seconds', extract(epoch from p_order_book_max_lag),
      'actual_lag_seconds', case when v_min_order_book is null then null else extract(epoch from (v_now - v_min_order_book)) end
    ));
  end if;

  if v_min_open_interest is null or v_now - v_min_open_interest > p_open_interest_max_lag then
    v_violations := v_violations || jsonb_build_array(jsonb_build_object(
      'check', 'open_interest_freshness',
      'min_latest_ts', v_min_open_interest,
      'max_lag_seconds', extract(epoch from p_open_interest_max_lag),
      'actual_lag_seconds', case when v_min_open_interest is null then null else extract(epoch from (v_now - v_min_open_interest)) end
    ));
  end if;

  if v_min_oi_features is null or v_now - v_min_oi_features > p_oi_features_max_lag then
    v_violations := v_violations || jsonb_build_array(jsonb_build_object(
      'check', 'oi_features_freshness',
      'min_latest_ts', v_min_oi_features,
      'max_lag_seconds', extract(epoch from p_oi_features_max_lag),
      'actual_lag_seconds', case when v_min_oi_features is null then null else extract(epoch from (v_now - v_min_oi_features)) end
    ));
  end if;

  if v_stale_running > 0 then
    v_violations := v_violations || jsonb_build_array(jsonb_build_object(
      'check', 'job_queue_stale_running',
      'stale_running_count', v_stale_running,
      'max_age_seconds', extract(epoch from p_stale_running_max_age)
    ));
  end if;

  if v_missing_1m_total > p_ohlcv_1m_missing_minutes_max then
    v_violations := v_violations || jsonb_build_array(jsonb_build_object(
      'check', 'ohlcv_1m_missing_minutes',
      'lookback_seconds', extract(epoch from p_ohlcv_1m_missing_lookback),
      'missing_minutes_total', v_missing_1m_total,
      'missing_minutes_by_pair', v_missing_1m_by_pair,
      'max_allowed_missing_minutes', p_ohlcv_1m_missing_minutes_max
    ));
  end if;

  return jsonb_build_object(
    'ran_at_utc', v_now,
    'pairs', to_jsonb(p_pairs),
    'metrics', jsonb_build_object(
      'min_latest_raw_trades', v_min_raw_trades,
      'min_latest_ohlcv_1m', v_min_ohlcv_1m,
      'min_latest_ohlcv_5m', v_min_ohlcv_5m,
      'min_latest_ohlcv_15m', v_min_ohlcv_15m,
      'min_latest_indicator_values', v_min_indicator_values,
      'min_latest_order_book', v_min_order_book,
      'min_latest_open_interest', v_min_open_interest,
      'min_latest_oi_features', v_min_oi_features,
      'job_queue_pending', v_pending,
      'job_queue_running', v_running,
      'job_queue_failed', v_failed,
      'job_queue_stale_running', v_stale_running,
      'ohlcv_1m_missing_minutes_total', v_missing_1m_total,
      'ohlcv_1m_missing_minutes_by_pair', v_missing_1m_by_pair
    ),
    'violations', v_violations
  );
end;
$$;

comment on function indicators.fn_pipeline_health_snapshot(
  text[], interval, interval, interval, interval, interval, interval, interval, interval, interval, interval, integer
) is
  'Returns pipeline freshness/continuity snapshot with violations array for operational guardrails.';


create or replace function indicators.fn_assert_pipeline_health()
returns jsonb
language plpgsql
security definer
set search_path = indicators, public
as $$
declare
  v_report jsonb;
  v_violation_count int;
begin
  v_report := indicators.fn_pipeline_health_snapshot();
  v_violation_count := coalesce(jsonb_array_length(v_report->'violations'), 0);
  insert into indicators.pipeline_health_audit (violation_count, report)
  values (v_violation_count, v_report);

  if v_violation_count > 0 then
    raise exception 'pipeline_health_violation count=% report=%', v_violation_count, v_report::text;
  end if;
  return v_report;
end;
$$;

comment on function indicators.fn_assert_pipeline_health() is
  'Raises an exception when pipeline health snapshot contains any violation.';

do $$
declare
  v_jobid bigint;
begin
  select jobid into v_jobid from cron.job where jobname = 'pipeline-health-watchdog';
  if v_jobid is not null then
    perform cron.unschedule(v_jobid);
  end if;

  perform cron.schedule(
    'pipeline-health-watchdog',
    '*/5 * * * *',
    $cron$select indicators.fn_assert_pipeline_health();$cron$
  );
end $$;
