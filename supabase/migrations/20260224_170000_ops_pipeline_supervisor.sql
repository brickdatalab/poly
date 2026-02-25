-- Ops control-plane for autonomous data freshness and recovery.
-- This migration is additive and does not alter websocket ingestion paths.

create schema if not exists ops;

grant usage on schema ops to postgres, service_role, authenticator;

create table if not exists ops.pipeline_slo_config (
  source text primary key,
  enabled boolean not null default true,
  max_lag interval,
  max_missing integer,
  max_gap_windows integer,
  max_numeric double precision,
  notes text,
  updated_at timestamptz not null default (now() at time zone 'utc')
);

create table if not exists ops.pipeline_runtime_config (
  key text primary key,
  value_text text not null,
  updated_at timestamptz not null default (now() at time zone 'utc')
);

create table if not exists ops.pipeline_action_cooldowns (
  action_name text primary key,
  cooldown interval not null,
  last_started_at timestamptz,
  last_finished_at timestamptz,
  last_status text,
  last_details jsonb,
  updated_at timestamptz not null default (now() at time zone 'utc')
);

create table if not exists ops.pipeline_health_log (
  id bigserial primary key,
  captured_at_utc timestamptz not null default (now() at time zone 'utc'),
  mode text not null default 'snapshot',
  violation_count integer not null,
  snapshot jsonb not null,
  created_by text not null default current_user
);

create table if not exists ops.pipeline_action_log (
  id bigserial primary key,
  action_name text not null,
  triggered_by text not null,
  started_at_utc timestamptz not null default (now() at time zone 'utc'),
  finished_at_utc timestamptz,
  status text not null default 'running',
  details jsonb not null default '{}'::jsonb,
  error_text text
);

create table if not exists ops.pipeline_incident_log (
  id bigserial primary key,
  opened_at_utc timestamptz not null default (now() at time zone 'utc'),
  closed_at_utc timestamptz,
  status text not null default 'open',
  severity text not null default 'sev1',
  summary text not null,
  latest_snapshot jsonb,
  actions_summary jsonb,
  webhook_sent boolean not null default false,
  last_alert_at_utc timestamptz,
  notes text
);

create index if not exists idx_ops_pipeline_health_log_captured
  on ops.pipeline_health_log (captured_at_utc desc);

create index if not exists idx_ops_pipeline_action_log_started
  on ops.pipeline_action_log (started_at_utc desc);

create index if not exists idx_ops_pipeline_incident_status_opened
  on ops.pipeline_incident_log (status, opened_at_utc desc);

comment on table ops.pipeline_slo_config is
  'Per-source freshness/continuity thresholds used by the autonomous supervisor.';

comment on table ops.pipeline_runtime_config is
  'Runtime config for ops control-plane (URLs, lookbacks, retry budgets).';

comment on table ops.pipeline_action_cooldowns is
  'Per-action cooldown state to prevent remediation storms.';

comment on table ops.pipeline_health_log is
  'Append-only snapshots from health checks and supervisor ticks.';

comment on table ops.pipeline_action_log is
  'Append-only execution log of remediation actions.';

comment on table ops.pipeline_incident_log is
  'Open/closed incidents emitted by supervisor when violations remain unresolved.';

insert into ops.pipeline_slo_config (source, enabled, max_lag, max_missing, max_gap_windows, max_numeric, notes)
values
  ('raw_trades', true, interval '90 seconds', null, null, null, 'upstream trade freshness'),
  ('market_context', true, interval '120 seconds', null, null, null, 'market context freshness'),
  ('order_book_snapshots', true, interval '120 seconds', null, null, null, 'order book snapshot freshness'),
  ('order_book_indicators', true, interval '120 seconds', null, null, null, 'order book derived indicators freshness'),
  ('ohlcv_1m', true, interval '120 seconds', 0, null, null, '1m freshness and continuity'),
  ('ohlcv_5m', true, interval '30 minutes', null, 0, null, '5m freshness and gap windows'),
  ('ohlcv_10m', true, interval '45 minutes', null, 0, null, '10m freshness and gap windows'),
  ('ohlcv_15m', true, interval '45 minutes', null, 0, null, '15m freshness and gap windows'),
  ('ohlcv_30m', true, interval '90 minutes', null, 0, null, '30m freshness and gap windows'),
  ('ohlcv_45m', true, interval '2 hours', null, 0, null, '45m freshness and gap windows'),
  ('ohlcv_1h', true, interval '2 hours', null, 0, null, '1h freshness and gap windows'),
  ('ohlcv_2h', true, interval '4 hours', null, 0, null, '2h freshness and gap windows'),
  ('ohlcv_6h', true, interval '12 hours', null, 0, null, '6h freshness and gap windows'),
  ('ohlcv_12h', true, interval '24 hours', null, 0, null, '12h freshness and gap windows'),
  ('indicator_values', true, interval '45 minutes', null, null, null, 'computed indicators freshness'),
  ('open_interest', true, interval '45 minutes', null, null, null, 'raw OI freshness'),
  ('oi_features', true, interval '45 minutes', null, null, null, 'derived OI feature freshness'),
  ('job_queue_stale_running', true, null, null, null, 0, 'running jobs should not stay stale'),
  ('job_queue_pending', true, null, null, null, 4000, 'pending backlog upper bound')
on conflict (source) do update
set enabled = excluded.enabled,
    max_lag = excluded.max_lag,
    max_missing = excluded.max_missing,
    max_gap_windows = excluded.max_gap_windows,
    max_numeric = excluded.max_numeric,
    notes = excluded.notes,
    updated_at = now() at time zone 'utc';

insert into ops.pipeline_runtime_config (key, value_text)
values
  ('indicator_worker_url', 'https://cxvntzszdkyggjjenefn.supabase.co/functions/v1/indicator-worker'),
  ('oi_ingestor_url', 'https://cxvntzszdkyggjjenefn.supabase.co/functions/v1/oi-ingestor'),
  ('oi_backfill_url', 'https://cxvntzszdkyggjjenefn.supabase.co/functions/v1/oi-backfill'),
  ('incident_webhook_url', ''),
  ('pairs', 'BTC-USD,ETH-USD,SOL-USD'),
  ('supervisor_lookback_hours', '24'),
  ('recovery_ohlcv_backfill_hours', '48'),
  ('recovery_indicator_recompute_minutes', '360'),
  ('recovery_orderbook_backfill_hours', '48'),
  ('recovery_oi_reconcile_hours', '48'),
  ('incident_retry_budget', '3')
on conflict (key) do update
set value_text = excluded.value_text,
    updated_at = now() at time zone 'utc';

insert into ops.pipeline_action_cooldowns (action_name, cooldown)
values
  ('reclaim_stale_jobs', interval '2 minutes'),
  ('trigger_indicator_worker', interval '1 minute'),
  ('repair_ohlcv_chain', interval '5 minutes'),
  ('recompute_indicators', interval '10 minutes'),
  ('backfill_orderbook_indicators', interval '10 minutes'),
  ('ingest_open_interest', interval '5 minutes'),
  ('recompute_oi_features', interval '10 minutes'),
  ('send_alert', interval '5 minutes'),
  ('run_recovery_window', interval '15 minutes')
on conflict (action_name) do update
set cooldown = excluded.cooldown,
    updated_at = now() at time zone 'utc';

create or replace function ops.fn_cfg_text(p_key text, p_default text default null)
returns text
language sql
stable
as $$
  select coalesce((select c.value_text from ops.pipeline_runtime_config c where c.key = p_key), p_default)
$$;

create or replace function ops.fn_cfg_int(p_key text, p_default integer)
returns integer
language plpgsql
stable
as $$
declare
  v_text text;
begin
  v_text := ops.fn_cfg_text(p_key, p_default::text);
  begin
    return v_text::integer;
  exception when others then
    return p_default;
  end;
end;
$$;

create or replace function ops.fn_cfg_interval_hours(p_key text, p_default_hours integer)
returns interval
language plpgsql
stable
as $$
declare
  v_hours integer;
begin
  v_hours := ops.fn_cfg_int(p_key, p_default_hours);
  return make_interval(hours => greatest(1, v_hours));
end;
$$;

create or replace function ops.fn_pairs()
returns text[]
language plpgsql
stable
as $$
declare
  v_raw text;
  v_arr text[];
begin
  v_raw := coalesce(ops.fn_cfg_text('pairs', 'BTC-USD,ETH-USD,SOL-USD'), 'BTC-USD,ETH-USD,SOL-USD');
  select array_agg(x)
    into v_arr
  from (
    select upper(btrim(val)) as x
    from unnest(string_to_array(v_raw, ',')) val
    where btrim(val) <> ''
  ) s;
  if v_arr is null or cardinality(v_arr) = 0 then
    return array['BTC-USD','ETH-USD','SOL-USD'];
  end if;
  return v_arr;
end;
$$;

create or replace function ops.fn_log_health_snapshot(p_mode text, p_snapshot jsonb)
returns bigint
language plpgsql
as $$
declare
  v_id bigint;
begin
  insert into ops.pipeline_health_log (mode, violation_count, snapshot)
  values (coalesce(p_mode, 'snapshot'), coalesce(jsonb_array_length(p_snapshot->'violations'), 0), p_snapshot)
  returning id into v_id;
  return v_id;
end;
$$;

create or replace function ops.fn_begin_action(
  p_action_name text,
  p_triggered_by text,
  p_details jsonb default '{}'::jsonb
)
returns bigint
language plpgsql
as $$
declare
  v_cd ops.pipeline_action_cooldowns%rowtype;
  v_now timestamptz := now() at time zone 'utc';
  v_id bigint;
begin
  select * into v_cd
  from ops.pipeline_action_cooldowns
  where action_name = p_action_name
  for update;

  if not found then
    insert into ops.pipeline_action_cooldowns (action_name, cooldown, last_started_at, last_status, last_details, updated_at)
    values (p_action_name, interval '1 minute', v_now, 'running', coalesce(p_details, '{}'::jsonb), v_now);
  else
    if v_cd.last_started_at is not null and v_cd.last_started_at + v_cd.cooldown > v_now then
      return null;
    end if;
    update ops.pipeline_action_cooldowns
       set last_started_at = v_now,
           last_status = 'running',
           last_details = coalesce(p_details, '{}'::jsonb),
           updated_at = v_now
     where action_name = p_action_name;
  end if;

  insert into ops.pipeline_action_log (action_name, triggered_by, started_at_utc, status, details)
  values (p_action_name, coalesce(p_triggered_by, 'unknown'), v_now, 'running', coalesce(p_details, '{}'::jsonb))
  returning id into v_id;

  return v_id;
end;
$$;

create or replace function ops.fn_end_action(
  p_action_log_id bigint,
  p_status text,
  p_details jsonb default '{}'::jsonb,
  p_error text default null
)
returns void
language plpgsql
as $$
declare
  v_action text;
  v_now timestamptz := now() at time zone 'utc';
begin
  update ops.pipeline_action_log
     set finished_at_utc = v_now,
         status = coalesce(p_status, 'unknown'),
         details = coalesce(p_details, '{}'::jsonb),
         error_text = p_error
   where id = p_action_log_id
  returning action_name into v_action;

  if v_action is not null then
    update ops.pipeline_action_cooldowns
       set last_finished_at = v_now,
           last_status = coalesce(p_status, 'unknown'),
           last_details = coalesce(p_details, '{}'::jsonb),
           updated_at = v_now
     where action_name = v_action;
  end if;
end;
$$;

create or replace function ops.fn_invoke_edge(p_url text, p_body jsonb default '{}'::jsonb)
returns bigint
language plpgsql
as $$
declare
  v_request_id bigint;
begin
  if coalesce(btrim(p_url), '') = '' then
    return null;
  end if;

  select net.http_post(
    url := p_url,
    headers := '{"Content-Type":"application/json"}'::jsonb,
    body := coalesce(p_body, '{}'::jsonb)
  )
  into v_request_id;

  return v_request_id;
end;
$$;

create or replace function ops.fn_repair_ohlcv_1m_continuity(
  p_pairs text[] default array['BTC-USD','ETH-USD','SOL-USD'],
  p_start timestamptz default null,
  p_end timestamptz default null
)
returns integer
language plpgsql
as $$
declare
  v_inserted integer := 0;
begin
  with bounds as (
    select
      i.pair,
      date_trunc('minute', greatest(min(i.bucket_time), coalesce(date_trunc('minute', p_start), min(i.bucket_time)))) as mn,
      date_trunc('minute', least(max(i.bucket_time), coalesce(date_trunc('minute', p_end), max(i.bucket_time)))) as mx
    from indicators.ohlcv_1m i
    where i.pair = any(p_pairs)
    group by i.pair
  ), expected as (
    select b.pair, gs as bucket_time
    from bounds b
    cross join lateral generate_series(b.mn, b.mx, interval '1 minute') gs
    where b.mn <= b.mx
  ), missing as (
    select e.pair, e.bucket_time
    from expected e
    left join indicators.ohlcv_1m i
      on i.pair = e.pair
     and i.bucket_time = e.bucket_time
    where i.bucket_time is null
  ), seeded as (
    select
      m.pair,
      m.bucket_time,
      coalesce(prev.close, nxt.open)::numeric as px
    from missing m
    left join lateral (
      select i.close
      from indicators.ohlcv_1m i
      where i.pair = m.pair
        and i.bucket_time < m.bucket_time
      order by i.bucket_time desc
      limit 1
    ) prev on true
    left join lateral (
      select i.open
      from indicators.ohlcv_1m i
      where i.pair = m.pair
        and i.bucket_time > m.bucket_time
      order by i.bucket_time asc
      limit 1
    ) nxt on true
    where coalesce(prev.close, nxt.open) is not null
  ), inserted as (
    insert into indicators.ohlcv_1m (
      pair, bucket_time, open, high, low, close, volume, buy_volume, sell_volume, trade_count
    )
    select
      s.pair,
      s.bucket_time,
      s.px,
      s.px,
      s.px,
      s.px,
      0::numeric,
      0::numeric,
      0::numeric,
      0::integer
    from seeded s
    on conflict (pair, bucket_time) do nothing
    returning 1
  )
  select count(*)::integer into v_inserted from inserted;

  return coalesce(v_inserted, 0);
end;
$$;

create or replace function ops.fn_recompute_indicators_range(
  p_pairs text[] default array['BTC-USD','ETH-USD','SOL-USD'],
  p_start timestamptz default null,
  p_end timestamptz default null
)
returns integer
language plpgsql
as $$
declare
  v_count integer := 0;
begin
  if p_start is null or p_end is null or p_end < p_start then
    return 0;
  end if;

  with grid as (
    select p as pair, gs as ts
    from unnest(p_pairs) p
    cross join generate_series(date_trunc('minute', p_start), date_trunc('minute', p_end), interval '1 minute') gs
  )
  select count(*)::integer
    into v_count
  from (
    select indicators.fn_compute_all_indicators(g.pair, g.ts, null::text, null::text, null::text)
    from grid g
  ) x;

  return coalesce(v_count, 0);
end;
$$;

create or replace function ops.fn_pipeline_health_snapshot(
  p_pairs text[] default array['BTC-USD','ETH-USD','SOL-USD'],
  p_lookback interval default interval '24 hours'
)
returns jsonb
language plpgsql
as $$
declare
  v_now timestamptz := now() at time zone 'utc';
  v_slo_raw_lag interval := coalesce((select max_lag from ops.pipeline_slo_config where source='raw_trades' and enabled), interval '90 seconds');
  v_slo_market_context_lag interval := coalesce((select max_lag from ops.pipeline_slo_config where source='market_context' and enabled), interval '120 seconds');
  v_slo_order_book_snapshots_lag interval := coalesce((select max_lag from ops.pipeline_slo_config where source='order_book_snapshots' and enabled), interval '120 seconds');
  v_slo_order_book_indicators_lag interval := coalesce((select max_lag from ops.pipeline_slo_config where source='order_book_indicators' and enabled), interval '120 seconds');
  v_slo_1m_lag interval := coalesce((select max_lag from ops.pipeline_slo_config where source='ohlcv_1m' and enabled), interval '120 seconds');
  v_slo_5m_lag interval := coalesce((select max_lag from ops.pipeline_slo_config where source='ohlcv_5m' and enabled), interval '30 minutes');
  v_slo_10m_lag interval := coalesce((select max_lag from ops.pipeline_slo_config where source='ohlcv_10m' and enabled), interval '45 minutes');
  v_slo_15m_lag interval := coalesce((select max_lag from ops.pipeline_slo_config where source='ohlcv_15m' and enabled), interval '45 minutes');
  v_slo_30m_lag interval := coalesce((select max_lag from ops.pipeline_slo_config where source='ohlcv_30m' and enabled), interval '90 minutes');
  v_slo_45m_lag interval := coalesce((select max_lag from ops.pipeline_slo_config where source='ohlcv_45m' and enabled), interval '2 hours');
  v_slo_1h_lag interval := coalesce((select max_lag from ops.pipeline_slo_config where source='ohlcv_1h' and enabled), interval '2 hours');
  v_slo_2h_lag interval := coalesce((select max_lag from ops.pipeline_slo_config where source='ohlcv_2h' and enabled), interval '4 hours');
  v_slo_6h_lag interval := coalesce((select max_lag from ops.pipeline_slo_config where source='ohlcv_6h' and enabled), interval '12 hours');
  v_slo_12h_lag interval := coalesce((select max_lag from ops.pipeline_slo_config where source='ohlcv_12h' and enabled), interval '24 hours');
  v_slo_iv_lag interval := coalesce((select max_lag from ops.pipeline_slo_config where source='indicator_values' and enabled), interval '45 minutes');
  v_slo_oi_lag interval := coalesce((select max_lag from ops.pipeline_slo_config where source='open_interest' and enabled), interval '45 minutes');
  v_slo_oif_lag interval := coalesce((select max_lag from ops.pipeline_slo_config where source='oi_features' and enabled), interval '45 minutes');
  v_slo_1m_missing integer := coalesce((select max_missing from ops.pipeline_slo_config where source='ohlcv_1m' and enabled), 0);
  v_slo_queue_pending double precision := coalesce((select max_numeric from ops.pipeline_slo_config where source='job_queue_pending' and enabled), 4000);
  v_slo_queue_stale_running double precision := coalesce((select max_numeric from ops.pipeline_slo_config where source='job_queue_stale_running' and enabled), 0);

  v_min_raw_trades timestamptz;
  v_min_market_context timestamptz;
  v_min_order_book_snapshots timestamptz;
  v_min_order_book_indicators timestamptz;
  v_min_1m timestamptz;
  v_min_5m timestamptz;
  v_min_10m timestamptz;
  v_min_15m timestamptz;
  v_min_30m timestamptz;
  v_min_45m timestamptz;
  v_min_1h timestamptz;
  v_min_2h timestamptz;
  v_min_6h timestamptz;
  v_min_12h timestamptz;
  v_min_iv timestamptz;
  v_min_oi timestamptz;
  v_min_oif timestamptz;

  v_pending int := 0;
  v_running int := 0;
  v_failed int := 0;
  v_stale_running int := 0;

  v_missing_1m_total int := 0;
  v_missing_1m_by_pair jsonb := '{}'::jsonb;

  v_gap_5m int := 0;
  v_gap_10m int := 0;
  v_gap_15m int := 0;
  v_gap_30m int := 0;
  v_gap_45m int := 0;
  v_gap_1h int := 0;
  v_gap_2h int := 0;
  v_gap_6h int := 0;
  v_gap_12h int := 0;

  v_violations jsonb := '[]'::jsonb;
begin
  select min(x.max_ts) into v_min_raw_trades
  from (
    select max(executed_at) as max_ts
    from public.raw_trades
    where pair = any(p_pairs)
    group by pair
  ) x;

  select min(x.max_ts) into v_min_market_context
  from (
    select max("timestamp") as max_ts
    from public.market_context
    where pair = any(p_pairs)
    group by pair
  ) x;

  select min(x.max_ts) into v_min_order_book_snapshots
  from (
    select max(captured_at) as max_ts
    from public.order_book_snapshots
    where pair = any(p_pairs)
    group by pair
  ) x;

  select min(x.max_ts) into v_min_order_book_indicators
  from (
    select max(captured_at) as max_ts
    from indicators.order_book_indicators
    where pair = any(p_pairs)
    group by pair
  ) x;

  select min(x.max_ts) into v_min_1m
  from (
    select max(bucket_time) as max_ts from indicators.ohlcv_1m where pair = any(p_pairs) group by pair
  ) x;

  select min(x.max_ts) into v_min_5m
  from (
    select max(bucket_time) as max_ts from indicators.ohlcv_5m where pair = any(p_pairs) group by pair
  ) x;

  select min(x.max_ts) into v_min_10m
  from (
    select max(bucket_time) as max_ts from indicators.ohlcv_10m where pair = any(p_pairs) group by pair
  ) x;

  select min(x.max_ts) into v_min_15m
  from (
    select max(bucket_time) as max_ts from indicators.ohlcv_15m where pair = any(p_pairs) group by pair
  ) x;

  select min(x.max_ts) into v_min_30m
  from (
    select max(bucket_time) as max_ts from indicators.ohlcv_30m where pair = any(p_pairs) group by pair
  ) x;

  select min(x.max_ts) into v_min_45m
  from (
    select max(bucket_time) as max_ts from indicators.ohlcv_45m where pair = any(p_pairs) group by pair
  ) x;

  select min(x.max_ts) into v_min_1h
  from (
    select max(bucket_time) as max_ts from indicators.ohlcv_1h where pair = any(p_pairs) group by pair
  ) x;

  select min(x.max_ts) into v_min_2h
  from (
    select max(bucket_time) as max_ts from indicators.ohlcv_2h where pair = any(p_pairs) group by pair
  ) x;

  select min(x.max_ts) into v_min_6h
  from (
    select max(bucket_time) as max_ts from indicators.ohlcv_6h where pair = any(p_pairs) group by pair
  ) x;

  select min(x.max_ts) into v_min_12h
  from (
    select max(bucket_time) as max_ts from indicators.ohlcv_12h where pair = any(p_pairs) group by pair
  ) x;

  select min(x.max_ts) into v_min_iv
  from (
    select max(bucket_time) as max_ts from indicators.indicator_values where pair = any(p_pairs) group by pair
  ) x;

  select min(x.max_ts) into v_min_oi
  from (
    select max(bucket_time) as max_ts from indicators.open_interest where pair = any(p_pairs) group by pair
  ) x;

  select min(x.max_ts) into v_min_oif
  from (
    select max(bucket_time) as max_ts from indicators.oi_features where pair = any(p_pairs) group by pair
  ) x;

  select
    count(*) filter (where status='pending'),
    count(*) filter (where status='running'),
    count(*) filter (where status='failed')
  into v_pending, v_running, v_failed
  from indicators.job_queue;

  select count(*)
    into v_stale_running
  from indicators.job_queue
  where status='running'
    and started_at is not null
    and started_at < v_now - interval '10 minutes';

  with bounds as (
    select date_trunc('minute', v_now - p_lookback) as start_ts,
           date_trunc('minute', v_now) - interval '1 minute' as end_ts
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
    left join actual a on a.pair=e.pair and a.bucket_time=e.bucket_time
    where a.bucket_time is null
    group by e.pair
  )
  select coalesce(sum(missing_minutes),0)::int,
         coalesce(jsonb_object_agg(pair, missing_minutes), '{}'::jsonb)
    into v_missing_1m_total, v_missing_1m_by_pair
  from missing;

  with ordered as (
    select pair, bucket_time, lag(bucket_time) over(partition by pair order by bucket_time) as prev_bt
    from indicators.ohlcv_5m
    where pair = any(p_pairs) and bucket_time >= v_now - p_lookback
  )
  select coalesce(count(*),0)::int into v_gap_5m
  from ordered
  where prev_bt is not null and bucket_time - prev_bt > interval '5 minutes';

  with ordered as (
    select pair, bucket_time, lag(bucket_time) over(partition by pair order by bucket_time) as prev_bt
    from indicators.ohlcv_10m
    where pair = any(p_pairs) and bucket_time >= v_now - p_lookback
  )
  select coalesce(count(*),0)::int into v_gap_10m
  from ordered
  where prev_bt is not null and bucket_time - prev_bt > interval '10 minutes';

  with ordered as (
    select pair, bucket_time, lag(bucket_time) over(partition by pair order by bucket_time) as prev_bt
    from indicators.ohlcv_15m
    where pair = any(p_pairs) and bucket_time >= v_now - p_lookback
  )
  select coalesce(count(*),0)::int into v_gap_15m
  from ordered
  where prev_bt is not null and bucket_time - prev_bt > interval '15 minutes';

  with ordered as (
    select pair, bucket_time, lag(bucket_time) over(partition by pair order by bucket_time) as prev_bt
    from indicators.ohlcv_30m
    where pair = any(p_pairs) and bucket_time >= v_now - p_lookback
  )
  select coalesce(count(*),0)::int into v_gap_30m
  from ordered
  where prev_bt is not null and bucket_time - prev_bt > interval '30 minutes';

  with ordered as (
    select pair, bucket_time, lag(bucket_time) over(partition by pair order by bucket_time) as prev_bt
    from indicators.ohlcv_45m
    where pair = any(p_pairs) and bucket_time >= v_now - p_lookback
  )
  select coalesce(count(*),0)::int into v_gap_45m
  from ordered
  where prev_bt is not null and bucket_time - prev_bt > interval '45 minutes';

  with ordered as (
    select pair, bucket_time, lag(bucket_time) over(partition by pair order by bucket_time) as prev_bt
    from indicators.ohlcv_1h
    where pair = any(p_pairs) and bucket_time >= v_now - p_lookback
  )
  select coalesce(count(*),0)::int into v_gap_1h
  from ordered
  where prev_bt is not null and bucket_time - prev_bt > interval '1 hour';

  with ordered as (
    select pair, bucket_time, lag(bucket_time) over(partition by pair order by bucket_time) as prev_bt
    from indicators.ohlcv_2h
    where pair = any(p_pairs) and bucket_time >= v_now - p_lookback
  )
  select coalesce(count(*),0)::int into v_gap_2h
  from ordered
  where prev_bt is not null and bucket_time - prev_bt > interval '2 hours';

  with ordered as (
    select pair, bucket_time, lag(bucket_time) over(partition by pair order by bucket_time) as prev_bt
    from indicators.ohlcv_6h
    where pair = any(p_pairs) and bucket_time >= v_now - p_lookback
  )
  select coalesce(count(*),0)::int into v_gap_6h
  from ordered
  where prev_bt is not null and bucket_time - prev_bt > interval '6 hours';

  with ordered as (
    select pair, bucket_time, lag(bucket_time) over(partition by pair order by bucket_time) as prev_bt
    from indicators.ohlcv_12h
    where pair = any(p_pairs) and bucket_time >= v_now - p_lookback
  )
  select coalesce(count(*),0)::int into v_gap_12h
  from ordered
  where prev_bt is not null and bucket_time - prev_bt > interval '12 hours';

  if v_min_raw_trades is null or v_now - v_min_raw_trades > v_slo_raw_lag then
    v_violations := v_violations || jsonb_build_array(jsonb_build_object('check','raw_trades_freshness','latest',v_min_raw_trades,'max_lag_seconds',extract(epoch from v_slo_raw_lag),'actual_lag_seconds',case when v_min_raw_trades is null then null else extract(epoch from (v_now - v_min_raw_trades)) end));
  end if;

  if v_min_market_context is null or v_now - v_min_market_context > v_slo_market_context_lag then
    v_violations := v_violations || jsonb_build_array(jsonb_build_object('check','market_context_freshness','latest',v_min_market_context,'max_lag_seconds',extract(epoch from v_slo_market_context_lag),'actual_lag_seconds',case when v_min_market_context is null then null else extract(epoch from (v_now - v_min_market_context)) end));
  end if;

  if v_min_order_book_snapshots is null or v_now - v_min_order_book_snapshots > v_slo_order_book_snapshots_lag then
    v_violations := v_violations || jsonb_build_array(jsonb_build_object('check','order_book_snapshots_freshness','latest',v_min_order_book_snapshots,'max_lag_seconds',extract(epoch from v_slo_order_book_snapshots_lag),'actual_lag_seconds',case when v_min_order_book_snapshots is null then null else extract(epoch from (v_now - v_min_order_book_snapshots)) end));
  end if;

  if v_min_order_book_indicators is null or v_now - v_min_order_book_indicators > v_slo_order_book_indicators_lag then
    v_violations := v_violations || jsonb_build_array(jsonb_build_object('check','order_book_indicators_freshness','latest',v_min_order_book_indicators,'max_lag_seconds',extract(epoch from v_slo_order_book_indicators_lag),'actual_lag_seconds',case when v_min_order_book_indicators is null then null else extract(epoch from (v_now - v_min_order_book_indicators)) end));
  end if;

  if v_min_1m is null or v_now - v_min_1m > v_slo_1m_lag then
    v_violations := v_violations || jsonb_build_array(jsonb_build_object('check','ohlcv_1m_freshness','latest',v_min_1m,'max_lag_seconds',extract(epoch from v_slo_1m_lag),'actual_lag_seconds',case when v_min_1m is null then null else extract(epoch from (v_now - v_min_1m)) end));
  end if;

  if v_min_5m is null or v_now - v_min_5m > v_slo_5m_lag then
    v_violations := v_violations || jsonb_build_array(jsonb_build_object('check','ohlcv_5m_freshness','latest',v_min_5m,'max_lag_seconds',extract(epoch from v_slo_5m_lag),'actual_lag_seconds',case when v_min_5m is null then null else extract(epoch from (v_now - v_min_5m)) end));
  end if;

  if v_min_10m is null or v_now - v_min_10m > v_slo_10m_lag then
    v_violations := v_violations || jsonb_build_array(jsonb_build_object('check','ohlcv_10m_freshness','latest',v_min_10m,'max_lag_seconds',extract(epoch from v_slo_10m_lag),'actual_lag_seconds',case when v_min_10m is null then null else extract(epoch from (v_now - v_min_10m)) end));
  end if;

  if v_min_15m is null or v_now - v_min_15m > v_slo_15m_lag then
    v_violations := v_violations || jsonb_build_array(jsonb_build_object('check','ohlcv_15m_freshness','latest',v_min_15m,'max_lag_seconds',extract(epoch from v_slo_15m_lag),'actual_lag_seconds',case when v_min_15m is null then null else extract(epoch from (v_now - v_min_15m)) end));
  end if;

  if v_min_30m is null or v_now - v_min_30m > v_slo_30m_lag then
    v_violations := v_violations || jsonb_build_array(jsonb_build_object('check','ohlcv_30m_freshness','latest',v_min_30m,'max_lag_seconds',extract(epoch from v_slo_30m_lag),'actual_lag_seconds',case when v_min_30m is null then null else extract(epoch from (v_now - v_min_30m)) end));
  end if;

  if v_min_45m is null or v_now - v_min_45m > v_slo_45m_lag then
    v_violations := v_violations || jsonb_build_array(jsonb_build_object('check','ohlcv_45m_freshness','latest',v_min_45m,'max_lag_seconds',extract(epoch from v_slo_45m_lag),'actual_lag_seconds',case when v_min_45m is null then null else extract(epoch from (v_now - v_min_45m)) end));
  end if;

  if v_min_1h is null or v_now - v_min_1h > v_slo_1h_lag then
    v_violations := v_violations || jsonb_build_array(jsonb_build_object('check','ohlcv_1h_freshness','latest',v_min_1h,'max_lag_seconds',extract(epoch from v_slo_1h_lag),'actual_lag_seconds',case when v_min_1h is null then null else extract(epoch from (v_now - v_min_1h)) end));
  end if;

  if v_min_2h is null or v_now - v_min_2h > v_slo_2h_lag then
    v_violations := v_violations || jsonb_build_array(jsonb_build_object('check','ohlcv_2h_freshness','latest',v_min_2h,'max_lag_seconds',extract(epoch from v_slo_2h_lag),'actual_lag_seconds',case when v_min_2h is null then null else extract(epoch from (v_now - v_min_2h)) end));
  end if;

  if v_min_6h is null or v_now - v_min_6h > v_slo_6h_lag then
    v_violations := v_violations || jsonb_build_array(jsonb_build_object('check','ohlcv_6h_freshness','latest',v_min_6h,'max_lag_seconds',extract(epoch from v_slo_6h_lag),'actual_lag_seconds',case when v_min_6h is null then null else extract(epoch from (v_now - v_min_6h)) end));
  end if;

  if v_min_12h is null or v_now - v_min_12h > v_slo_12h_lag then
    v_violations := v_violations || jsonb_build_array(jsonb_build_object('check','ohlcv_12h_freshness','latest',v_min_12h,'max_lag_seconds',extract(epoch from v_slo_12h_lag),'actual_lag_seconds',case when v_min_12h is null then null else extract(epoch from (v_now - v_min_12h)) end));
  end if;

  if v_min_iv is null or v_now - v_min_iv > v_slo_iv_lag then
    v_violations := v_violations || jsonb_build_array(jsonb_build_object('check','indicator_values_freshness','latest',v_min_iv,'max_lag_seconds',extract(epoch from v_slo_iv_lag),'actual_lag_seconds',case when v_min_iv is null then null else extract(epoch from (v_now - v_min_iv)) end));
  end if;

  if v_min_oi is null or v_now - v_min_oi > v_slo_oi_lag then
    v_violations := v_violations || jsonb_build_array(jsonb_build_object('check','open_interest_freshness','latest',v_min_oi,'max_lag_seconds',extract(epoch from v_slo_oi_lag),'actual_lag_seconds',case when v_min_oi is null then null else extract(epoch from (v_now - v_min_oi)) end));
  end if;

  if v_min_oif is null or v_now - v_min_oif > v_slo_oif_lag then
    v_violations := v_violations || jsonb_build_array(jsonb_build_object('check','oi_features_freshness','latest',v_min_oif,'max_lag_seconds',extract(epoch from v_slo_oif_lag),'actual_lag_seconds',case when v_min_oif is null then null else extract(epoch from (v_now - v_min_oif)) end));
  end if;

  if v_missing_1m_total > v_slo_1m_missing then
    v_violations := v_violations || jsonb_build_array(jsonb_build_object('check','ohlcv_1m_missing_minutes','missing_total',v_missing_1m_total,'max_missing',v_slo_1m_missing,'by_pair',v_missing_1m_by_pair));
  end if;

  if v_gap_5m > coalesce((select max_gap_windows from ops.pipeline_slo_config where source='ohlcv_5m' and enabled), 0) then
    v_violations := v_violations || jsonb_build_array(jsonb_build_object('check','ohlcv_5m_gaps','gap_windows',v_gap_5m));
  end if;
  if v_gap_10m > coalesce((select max_gap_windows from ops.pipeline_slo_config where source='ohlcv_10m' and enabled), 0) then
    v_violations := v_violations || jsonb_build_array(jsonb_build_object('check','ohlcv_10m_gaps','gap_windows',v_gap_10m));
  end if;
  if v_gap_15m > coalesce((select max_gap_windows from ops.pipeline_slo_config where source='ohlcv_15m' and enabled), 0) then
    v_violations := v_violations || jsonb_build_array(jsonb_build_object('check','ohlcv_15m_gaps','gap_windows',v_gap_15m));
  end if;
  if v_gap_30m > coalesce((select max_gap_windows from ops.pipeline_slo_config where source='ohlcv_30m' and enabled), 0) then
    v_violations := v_violations || jsonb_build_array(jsonb_build_object('check','ohlcv_30m_gaps','gap_windows',v_gap_30m));
  end if;
  if v_gap_45m > coalesce((select max_gap_windows from ops.pipeline_slo_config where source='ohlcv_45m' and enabled), 0) then
    v_violations := v_violations || jsonb_build_array(jsonb_build_object('check','ohlcv_45m_gaps','gap_windows',v_gap_45m));
  end if;
  if v_gap_1h > coalesce((select max_gap_windows from ops.pipeline_slo_config where source='ohlcv_1h' and enabled), 0) then
    v_violations := v_violations || jsonb_build_array(jsonb_build_object('check','ohlcv_1h_gaps','gap_windows',v_gap_1h));
  end if;
  if v_gap_2h > coalesce((select max_gap_windows from ops.pipeline_slo_config where source='ohlcv_2h' and enabled), 0) then
    v_violations := v_violations || jsonb_build_array(jsonb_build_object('check','ohlcv_2h_gaps','gap_windows',v_gap_2h));
  end if;
  if v_gap_6h > coalesce((select max_gap_windows from ops.pipeline_slo_config where source='ohlcv_6h' and enabled), 0) then
    v_violations := v_violations || jsonb_build_array(jsonb_build_object('check','ohlcv_6h_gaps','gap_windows',v_gap_6h));
  end if;
  if v_gap_12h > coalesce((select max_gap_windows from ops.pipeline_slo_config where source='ohlcv_12h' and enabled), 0) then
    v_violations := v_violations || jsonb_build_array(jsonb_build_object('check','ohlcv_12h_gaps','gap_windows',v_gap_12h));
  end if;

  if v_stale_running::double precision > v_slo_queue_stale_running then
    v_violations := v_violations || jsonb_build_array(jsonb_build_object('check','job_queue_stale_running','value',v_stale_running,'max',v_slo_queue_stale_running));
  end if;

  if v_pending::double precision > v_slo_queue_pending then
    v_violations := v_violations || jsonb_build_array(jsonb_build_object('check','job_queue_pending','value',v_pending,'max',v_slo_queue_pending));
  end if;

  if (v_min_oi is null or v_now - v_min_oi > v_slo_oi_lag)
     and (v_min_oif is null or v_now - v_min_oif > v_slo_oif_lag) then
    v_violations := v_violations || jsonb_build_array(jsonb_build_object(
      'check','oi_dependency_stale',
      'open_interest_latest',v_min_oi,
      'oi_features_latest',v_min_oif,
      'message','oi_features staleness likely upstream open_interest dependency'
    ));
  end if;

  return jsonb_build_object(
    'captured_at_utc', v_now,
    'pairs', to_jsonb(p_pairs),
    'lookback_seconds', extract(epoch from p_lookback),
    'metrics', jsonb_build_object(
      'min_latest_raw_trades', v_min_raw_trades,
      'min_latest_market_context', v_min_market_context,
      'min_latest_order_book_snapshots', v_min_order_book_snapshots,
      'min_latest_order_book_indicators', v_min_order_book_indicators,
      'min_latest_ohlcv_1m', v_min_1m,
      'min_latest_ohlcv_5m', v_min_5m,
      'min_latest_ohlcv_10m', v_min_10m,
      'min_latest_ohlcv_15m', v_min_15m,
      'min_latest_ohlcv_30m', v_min_30m,
      'min_latest_ohlcv_45m', v_min_45m,
      'min_latest_ohlcv_1h', v_min_1h,
      'min_latest_ohlcv_2h', v_min_2h,
      'min_latest_ohlcv_6h', v_min_6h,
      'min_latest_ohlcv_12h', v_min_12h,
      'min_latest_indicator_values', v_min_iv,
      'min_latest_open_interest', v_min_oi,
      'min_latest_oi_features', v_min_oif,
      'job_queue_pending', v_pending,
      'job_queue_running', v_running,
      'job_queue_failed', v_failed,
      'job_queue_stale_running', v_stale_running,
      'ohlcv_1m_missing_total', v_missing_1m_total,
      'ohlcv_1m_missing_by_pair', v_missing_1m_by_pair,
      'gap_windows', jsonb_build_object(
        'ohlcv_5m', v_gap_5m,
        'ohlcv_10m', v_gap_10m,
        'ohlcv_15m', v_gap_15m,
        'ohlcv_30m', v_gap_30m,
        'ohlcv_45m', v_gap_45m,
        'ohlcv_1h', v_gap_1h,
        'ohlcv_2h', v_gap_2h,
        'ohlcv_6h', v_gap_6h,
        'ohlcv_12h', v_gap_12h
      )
    ),
    'violations', v_violations
  );
end;
$$;

create or replace function ops.fn_repair_ohlcv_chain(
  p_pairs text[] default array['BTC-USD','ETH-USD','SOL-USD'],
  p_start timestamptz default null,
  p_end timestamptz default null,
  p_backfill interval default interval '48 hours'
)
returns jsonb
language plpgsql
as $$
declare
  v_inserted integer := 0;
  v_rerun record;
  v_rows jsonb := '[]'::jsonb;
begin
  perform public.aggregate_ohlcv_1m();

  for v_rerun in select * from indicators.fn_backfill_ohlcv(p_backfill) loop
    v_rows := v_rows || jsonb_build_array(jsonb_build_object('timeframe', v_rerun.timeframe, 'rows_inserted', v_rerun.rows_inserted));
  end loop;

  v_inserted := ops.fn_repair_ohlcv_1m_continuity(p_pairs, p_start, p_end);

  if v_inserted > 0 then
    for v_rerun in select * from indicators.fn_backfill_ohlcv(p_backfill) loop
      v_rows := v_rows || jsonb_build_array(jsonb_build_object('timeframe', v_rerun.timeframe, 'rows_inserted', v_rerun.rows_inserted));
    end loop;
  end if;

  return jsonb_build_object(
    'aggregate_ohlcv_1m', true,
    'continuity_rows_inserted', v_inserted,
    'backfill_rows', v_rows
  );
end;
$$;

create or replace function ops.fn_run_recovery_window(
  p_start timestamptz,
  p_end timestamptz,
  p_reason text default 'manual_recovery'
)
returns jsonb
language plpgsql
as $$
declare
  v_pairs text[] := ops.fn_pairs();
  v_start timestamptz := date_trunc('minute', least(p_start, p_end));
  v_end timestamptz := date_trunc('minute', greatest(p_start, p_end));
  v_before jsonb;
  v_after jsonb;
  v_action_id bigint;
  v_reclaimed integer := 0;
  v_worker_request bigint;
  v_oi_ingest_request bigint;
  v_oi_backfill_request bigint;
  v_ohlcv_result jsonb := '{}'::jsonb;
  v_indicator_count integer := 0;
  v_orderbook_count bigint := 0;
  v_oi_backfill_count integer := 0;
  v_oi_recent_count integer := 0;
  v_backfill_interval interval;
begin
  if p_start is null or p_end is null then
    raise exception 'start/end are required';
  end if;

  v_backfill_interval := make_interval(hours => greatest(2, ops.fn_cfg_int('recovery_ohlcv_backfill_hours', 48)));

  v_before := ops.fn_pipeline_health_snapshot(v_pairs, interval '24 hours');
  perform ops.fn_log_health_snapshot('recovery_before', v_before);

  v_action_id := ops.fn_begin_action('run_recovery_window', 'manual', jsonb_build_object('reason', p_reason, 'start', v_start, 'end', v_end));

  begin
    v_reclaimed := indicators.fn_reclaim_stale_indicator_jobs(interval '10 minutes');

    v_ohlcv_result := ops.fn_repair_ohlcv_chain(v_pairs, v_start, v_end, v_backfill_interval);

    v_indicator_count := ops.fn_recompute_indicators_range(v_pairs, v_start, v_end);

    select indicators.fn_backfill_order_book_indicators(make_interval(hours => greatest(2, ops.fn_cfg_int('recovery_orderbook_backfill_hours', 48))))
      into v_orderbook_count;

    v_worker_request := ops.fn_invoke_edge(ops.fn_cfg_text('indicator_worker_url', ''), jsonb_build_object('reason', p_reason, 'window_start', v_start, 'window_end', v_end));
    v_oi_ingest_request := ops.fn_invoke_edge(ops.fn_cfg_text('oi_ingestor_url', ''), jsonb_build_object('reason', p_reason));
    v_oi_backfill_request := ops.fn_invoke_edge(ops.fn_cfg_text('oi_backfill_url', ''), jsonb_build_object('start', v_start, 'end', v_end, 'reason', p_reason));

    select indicators.fn_backfill_oi_features(v_start, v_end) into v_oi_backfill_count;
    select indicators.fn_compute_oi_features_recent(make_interval(hours => greatest(1, ops.fn_cfg_int('recovery_oi_reconcile_hours', 48)))) into v_oi_recent_count;

    if v_action_id is not null then
      perform ops.fn_end_action(
        v_action_id,
        'success',
        jsonb_build_object(
          'reclaimed_jobs', v_reclaimed,
          'ohlcv', v_ohlcv_result,
          'recomputed_indicator_calls', v_indicator_count,
          'orderbook_backfill_count', v_orderbook_count,
          'worker_request_id', v_worker_request,
          'oi_ingest_request_id', v_oi_ingest_request,
          'oi_backfill_request_id', v_oi_backfill_request,
          'oi_backfill_rows', v_oi_backfill_count,
          'oi_recent_rows', v_oi_recent_count
        ),
        null
      );
    end if;
  exception when others then
    if v_action_id is not null then
      perform ops.fn_end_action(
        v_action_id,
        'error',
        jsonb_build_object('reason', p_reason, 'start', v_start, 'end', v_end),
        SQLERRM
      );
    end if;
    raise;
  end;

  v_after := ops.fn_pipeline_health_snapshot(v_pairs, interval '24 hours');
  perform ops.fn_log_health_snapshot('recovery_after', v_after);

  return jsonb_build_object(
    'reason', p_reason,
    'window_start', v_start,
    'window_end', v_end,
    'before', v_before,
    'after', v_after
  );
end;
$$;

create or replace function ops.fn_pipeline_supervisor_tick()
returns jsonb
language plpgsql
as $$
declare
  v_lock boolean;
  v_pairs text[] := ops.fn_pairs();
  v_lookback interval := ops.fn_cfg_interval_hours('supervisor_lookback_hours', 24);
  v_snapshot_before jsonb;
  v_snapshot_after jsonb;
  v_viol_before int := 0;
  v_viol_after int := 0;
  v_pending int := 0;
  v_stale_running int := 0;
  v_action_id bigint;
  v_incident_id bigint;
  v_alert_url text := coalesce(ops.fn_cfg_text('incident_webhook_url', ''), '');
  v_request_id bigint;
begin
  v_lock := pg_try_advisory_lock(hashtext('ops.pipeline_supervisor_tick'));
  if not v_lock then
    return jsonb_build_object('ok', true, 'skipped', 'lock_not_acquired');
  end if;

  begin
    v_snapshot_before := ops.fn_pipeline_health_snapshot(v_pairs, v_lookback);
    v_viol_before := coalesce(jsonb_array_length(v_snapshot_before->'violations'), 0);
    perform ops.fn_log_health_snapshot('supervisor_before', v_snapshot_before);

    v_pending := coalesce((v_snapshot_before->'metrics'->>'job_queue_pending')::int, 0);
    v_stale_running := coalesce((v_snapshot_before->'metrics'->>'job_queue_stale_running')::int, 0);

    if v_stale_running > 0 then
      v_action_id := ops.fn_begin_action('reclaim_stale_jobs', 'supervisor', jsonb_build_object('stale_running', v_stale_running));
      if v_action_id is not null then
        begin
          perform indicators.fn_reclaim_stale_indicator_jobs(interval '10 minutes');
          perform ops.fn_end_action(v_action_id, 'success', jsonb_build_object('stale_running_before', v_stale_running), null);
        exception when others then
          perform ops.fn_end_action(v_action_id, 'error', '{}'::jsonb, SQLERRM);
        end;
      end if;
    end if;

    if v_pending > 0 then
      v_action_id := ops.fn_begin_action('trigger_indicator_worker', 'supervisor', jsonb_build_object('pending', v_pending));
      if v_action_id is not null then
        begin
          v_request_id := ops.fn_invoke_edge(ops.fn_cfg_text('indicator_worker_url', ''), jsonb_build_object('reason', 'supervisor_pending_backlog'));
          perform ops.fn_end_action(v_action_id, 'success', jsonb_build_object('request_id', v_request_id, 'pending_before', v_pending), null);
        exception when others then
          perform ops.fn_end_action(v_action_id, 'error', '{}'::jsonb, SQLERRM);
        end;
      end if;
    end if;

    if exists (
      select 1
      from jsonb_array_elements(v_snapshot_before->'violations') v
      where (v->>'check') like 'ohlcv_%'
    ) then
      v_action_id := ops.fn_begin_action('repair_ohlcv_chain', 'supervisor', jsonb_build_object('reason', 'ohlcv_violation'));
      if v_action_id is not null then
        begin
          perform ops.fn_repair_ohlcv_chain(
            v_pairs,
            now() at time zone 'utc' - v_lookback,
            now() at time zone 'utc',
            ops.fn_cfg_interval_hours('recovery_ohlcv_backfill_hours', 48)
          );
          perform ops.fn_end_action(v_action_id, 'success', jsonb_build_object('lookback_seconds', extract(epoch from v_lookback)), null);
        exception when others then
          perform ops.fn_end_action(v_action_id, 'error', '{}'::jsonb, SQLERRM);
        end;
      end if;
    end if;

    if exists (
      select 1
      from jsonb_array_elements(v_snapshot_before->'violations') v
      where (v->>'check') = 'indicator_values_freshness'
    ) then
      v_action_id := ops.fn_begin_action('recompute_indicators', 'supervisor', jsonb_build_object('reason', 'indicator_values_stale'));
      if v_action_id is not null then
        begin
          perform ops.fn_recompute_indicators_range(
            v_pairs,
            now() at time zone 'utc' - make_interval(mins => greatest(60, ops.fn_cfg_int('recovery_indicator_recompute_minutes', 360))),
            now() at time zone 'utc' - interval '1 minute'
          );
          perform ops.fn_end_action(v_action_id, 'success', '{}'::jsonb, null);
        exception when others then
          perform ops.fn_end_action(v_action_id, 'error', '{}'::jsonb, SQLERRM);
        end;
      end if;
    end if;

    if exists (
      select 1
      from jsonb_array_elements(v_snapshot_before->'violations') v
      where (v->>'check') in ('order_book_indicators_freshness','order_book_snapshots_freshness')
    ) then
      v_action_id := ops.fn_begin_action('backfill_orderbook_indicators', 'supervisor', jsonb_build_object('reason', 'orderbook_stale'));
      if v_action_id is not null then
        begin
          perform indicators.fn_backfill_order_book_indicators(ops.fn_cfg_interval_hours('recovery_orderbook_backfill_hours', 48));
          perform ops.fn_end_action(v_action_id, 'success', '{}'::jsonb, null);
        exception when others then
          perform ops.fn_end_action(v_action_id, 'error', '{}'::jsonb, SQLERRM);
        end;
      end if;
    end if;

    if exists (
      select 1
      from jsonb_array_elements(v_snapshot_before->'violations') v
      where (v->>'check') in ('open_interest_freshness','oi_features_freshness','oi_dependency_stale')
    ) then
      v_action_id := ops.fn_begin_action('ingest_open_interest', 'supervisor', jsonb_build_object('reason', 'oi_stale'));
      if v_action_id is not null then
        begin
          v_request_id := ops.fn_invoke_edge(ops.fn_cfg_text('oi_ingestor_url', ''), jsonb_build_object('reason', 'supervisor_oi_stale'));
          perform ops.fn_end_action(v_action_id, 'success', jsonb_build_object('request_id', v_request_id), null);
        exception when others then
          perform ops.fn_end_action(v_action_id, 'error', '{}'::jsonb, SQLERRM);
        end;
      end if;

      v_action_id := ops.fn_begin_action('recompute_oi_features', 'supervisor', jsonb_build_object('reason', 'oi_features_stale'));
      if v_action_id is not null then
        begin
          perform indicators.fn_compute_oi_features_recent(ops.fn_cfg_interval_hours('recovery_oi_reconcile_hours', 48));
          perform ops.fn_end_action(v_action_id, 'success', '{}'::jsonb, null);
        exception when others then
          perform ops.fn_end_action(v_action_id, 'error', '{}'::jsonb, SQLERRM);
        end;
      end if;
    end if;

    v_snapshot_after := ops.fn_pipeline_health_snapshot(v_pairs, v_lookback);
    v_viol_after := coalesce(jsonb_array_length(v_snapshot_after->'violations'), 0);
    perform ops.fn_log_health_snapshot('supervisor_after', v_snapshot_after);

    if v_viol_after > 0 then
      select id
        into v_incident_id
      from ops.pipeline_incident_log
      where status = 'open'
      order by opened_at_utc desc
      limit 1;

      if v_incident_id is null then
        insert into ops.pipeline_incident_log (summary, latest_snapshot, actions_summary, notes)
        values (
          format('Unresolved pipeline violations (%s checks)', v_viol_after),
          v_snapshot_after,
          jsonb_build_object('supervisor_tick_before', v_viol_before, 'supervisor_tick_after', v_viol_after),
          'Opened by ops.fn_pipeline_supervisor_tick'
        )
        returning id into v_incident_id;
      else
        update ops.pipeline_incident_log
           set latest_snapshot = v_snapshot_after,
               actions_summary = jsonb_build_object('supervisor_tick_before', v_viol_before, 'supervisor_tick_after', v_viol_after),
               notes = 'Updated by ops.fn_pipeline_supervisor_tick'
         where id = v_incident_id;
      end if;

      if btrim(v_alert_url) <> '' then
        v_action_id := ops.fn_begin_action('send_alert', 'supervisor', jsonb_build_object('incident_id', v_incident_id));
        if v_action_id is not null then
          begin
            v_request_id := ops.fn_invoke_edge(
              v_alert_url,
              jsonb_build_object(
                'incident_id', v_incident_id,
                'violations', v_snapshot_after->'violations',
                'actions_attempted', (
                  select coalesce(jsonb_agg(jsonb_build_object('action_name', action_name, 'status', status, 'finished_at_utc', finished_at_utc)), '[]'::jsonb)
                  from ops.pipeline_action_log
                  where started_at_utc >= now() at time zone 'utc' - interval '15 minutes'
                ),
                'next_retry_at_utc', now() at time zone 'utc' + interval '1 minute'
              )
            );

            update ops.pipeline_incident_log
               set webhook_sent = true,
                   last_alert_at_utc = now() at time zone 'utc'
             where id = v_incident_id;

            perform ops.fn_end_action(v_action_id, 'success', jsonb_build_object('request_id', v_request_id), null);
          exception when others then
            perform ops.fn_end_action(v_action_id, 'error', '{}'::jsonb, SQLERRM);
          end;
        end if;
      end if;
    else
      update ops.pipeline_incident_log
         set status = 'closed',
             closed_at_utc = now() at time zone 'utc',
             latest_snapshot = v_snapshot_after,
             notes = 'Closed by ops.fn_pipeline_supervisor_tick'
       where status = 'open';
    end if;

    perform pg_advisory_unlock(hashtext('ops.pipeline_supervisor_tick'));
    return jsonb_build_object(
      'ok', true,
      'violations_before', v_viol_before,
      'violations_after', v_viol_after,
      'snapshot_after', v_snapshot_after
    );
  exception when others then
    perform pg_advisory_unlock(hashtext('ops.pipeline_supervisor_tick'));
    raise;
  end;
end;
$$;

create or replace function ops.fn_pipeline_health_watchdog()
returns jsonb
language plpgsql
as $$
declare
  v_snapshot jsonb;
  v_count int;
begin
  v_snapshot := ops.fn_pipeline_health_snapshot(ops.fn_pairs(), ops.fn_cfg_interval_hours('supervisor_lookback_hours', 24));
  v_count := coalesce(jsonb_array_length(v_snapshot->'violations'), 0);
  perform ops.fn_log_health_snapshot('watchdog', v_snapshot);

  if v_count > 0 then
    raise exception 'ops_pipeline_health_violation count=% snapshot=%', v_count, v_snapshot::text;
  end if;

  return v_snapshot;
end;
$$;

do $$
declare
  v_jobid bigint;
begin
  select jobid into v_jobid from cron.job where jobname = 'pipeline-supervisor-tick';
  if v_jobid is not null then
    perform cron.unschedule(v_jobid);
  end if;
  perform cron.schedule(
    'pipeline-supervisor-tick',
    '* * * * *',
    $cron$select ops.fn_pipeline_supervisor_tick();$cron$
  );
end $$;

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
    $cron$select ops.fn_pipeline_health_watchdog();$cron$
  );
end $$;

do $$
declare
  v_jobid bigint;
begin
  select jobid into v_jobid from cron.job where jobname = 'run-indicator-worker-backstop';
  if v_jobid is not null then
    perform cron.unschedule(v_jobid);
  end if;
  perform cron.schedule(
    'run-indicator-worker-backstop',
    '* * * * *',
    $cron$
    select case
      when (select count(*) from indicators.job_queue where status='pending') > 0
      then ops.fn_invoke_edge(ops.fn_cfg_text('indicator_worker_url', ''), jsonb_build_object('reason','cron_backstop'))
      else null
    end;
    $cron$
  );
end $$;

do $$
declare
  v_jobid bigint;
begin
  select jobid into v_jobid from cron.job where jobname = 'oi-ingest-main';
  if v_jobid is not null then
    perform cron.unschedule(v_jobid);
  end if;
  perform cron.schedule(
    'oi-ingest-main',
    '1,16,31,46 * * * *',
    $cron$select ops.fn_invoke_edge(ops.fn_cfg_text('oi_ingestor_url', ''), jsonb_build_object('reason','cron_main'));$cron$
  );
end $$;

do $$
declare
  v_jobid bigint;
begin
  select jobid into v_jobid from cron.job where jobname = 'oi-ingest-retry';
  if v_jobid is not null then
    perform cron.unschedule(v_jobid);
  end if;
  perform cron.schedule(
    'oi-ingest-retry',
    '4,19,34,49 * * * *',
    $cron$select ops.fn_invoke_edge(ops.fn_cfg_text('oi_ingestor_url', ''), jsonb_build_object('reason','cron_retry'));$cron$
  );
end $$;

do $$
declare
  v_jobid bigint;
begin
  select jobid into v_jobid from cron.job where jobname = 'oi-reconcile';
  if v_jobid is not null then
    perform cron.unschedule(v_jobid);
  end if;
  perform cron.schedule(
    'oi-reconcile',
    '7 * * * *',
    $cron$
    select ops.fn_invoke_edge(
      ops.fn_cfg_text('oi_backfill_url', ''),
      jsonb_build_object(
        'start', (now() at time zone 'utc') - ops.fn_cfg_interval_hours('recovery_oi_reconcile_hours', 48),
        'end', now() at time zone 'utc',
        'reason', 'cron_reconcile'
      )
    );
    select indicators.fn_compute_oi_features_recent(ops.fn_cfg_interval_hours('recovery_oi_reconcile_hours', 48));
    $cron$
  );
end $$;
