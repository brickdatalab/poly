-- Fix realtime signal scheduling so synthetic/codex ticks do not depend on closed 15m candles.
-- This enables quarter-hour prediction windows to evaluate at :02/:17/:32/:47.

create or replace function indicators.fn_enqueue_synthetic_jobs(
  p_lookback interval default interval '4 hours'
)
returns bigint
language plpgsql
as $$
declare
  v_inserted bigint := 0;
  v_now timestamptz := date_trunc('minute', now());
  v_from timestamptz := v_now - p_lookback;
  v_floor_from timestamptz;
  v_floor_now timestamptz;
begin
  v_floor_from := date_trunc('hour', v_from)
    + make_interval(mins => (floor(extract(minute from v_from) / 15)::int * 15));
  v_floor_now := date_trunc('hour', v_now)
    + make_interval(mins => (floor(extract(minute from v_now) / 15)::int * 15));

  with pairs as (
    select distinct o.pair
    from indicators.ohlcv_1m o
    where o.bucket_time > v_from - interval '15 minutes'
      and o.bucket_time <= v_now
  ), buckets as (
    select gs as bucket_time
    from generate_series(v_floor_from, v_floor_now, interval '15 minutes') gs
    where gs > v_from
      and gs + interval '2 minutes' <= v_now
      and extract(second from gs) = 0
      and extract(minute from gs)::int in (0, 15, 30, 45)
  ), phases as (
    select p.pair, b.bucket_time, ph.decision_phase
    from pairs p
    cross join buckets b
    cross join (values ('t_plus_1m'::text), ('t_plus_2m'::text)) ph(decision_phase)
  )
  insert into indicators.synthetic_job_queue (pair, bucket_time, decision_phase, status)
  select pair, bucket_time, decision_phase, 'pending'
  from phases
  on conflict (pair, bucket_time, decision_phase) do nothing;

  get diagnostics v_inserted = row_count;
  return v_inserted;
end;
$$;

comment on function indicators.fn_enqueue_synthetic_jobs(interval) is
  'Enqueues synthetic jobs for quarter-hour buckets ready at t+1/t+2 using wall-clock bucket generation.';

create or replace function indicators.fn_enqueue_codex_signal_jobs(
  p_lookback interval default interval '45 minutes'
)
returns bigint
language plpgsql
as $$
declare
  v_inserted bigint := 0;
  v_now timestamptz := date_trunc('minute', now());
begin
  with pairs as (
    select distinct pair
    from indicators.codex_signal_rules
    where is_active
  ), candidates as (
    select distinct s.pair, s.bucket_time
    from indicators.synthetic_indicator_values s
    join pairs p
      on p.pair = s.pair
    where s.bucket_time > v_now - p_lookback
      and s.bucket_time + interval '2 minutes' <= v_now
      and extract(second from s.bucket_time) = 0
      and extract(minute from s.bucket_time)::int in (0, 15, 30, 45)
  )
  insert into indicators.codex_signal_job_queue (pair, bucket_time, status)
  select pair, bucket_time, 'pending'
  from candidates
  on conflict (pair, bucket_time) do nothing;

  get diagnostics v_inserted = row_count;
  return v_inserted;
end;
$$;

comment on function indicators.fn_enqueue_codex_signal_jobs(interval) is
  'Enqueues codex jobs from available synthetic buckets for active rule pairs.';

create or replace function indicators.fn_refresh_recent_synthetic(
  p_lookback interval default interval '45 minutes'
)
returns integer
language plpgsql
as $$
declare
  v_now timestamptz := date_trunc('minute', now());
  v_from timestamptz := v_now - p_lookback;
  v_floor_from timestamptz;
  v_floor_now timestamptz;
  r record;
  v_count integer := 0;
begin
  v_floor_from := date_trunc('hour', v_from)
    + make_interval(mins => (floor(extract(minute from v_from) / 15)::int * 15));
  v_floor_now := date_trunc('hour', v_now)
    + make_interval(mins => (floor(extract(minute from v_now) / 15)::int * 15));

  for r in
    with pairs as (
      select distinct o.pair
      from indicators.ohlcv_1m o
      where o.bucket_time > v_from - interval '15 minutes'
        and o.bucket_time <= v_now
    ), buckets as (
      select gs as bucket_time
      from generate_series(v_floor_from, v_floor_now, interval '15 minutes') gs
      where gs > v_from
        and gs + interval '2 minutes' <= v_now
        and extract(second from gs) = 0
        and extract(minute from gs)::int in (0, 15, 30, 45)
    )
    select p.pair, b.bucket_time
    from pairs p
    cross join buckets b
    order by b.bucket_time, p.pair
  loop
    perform indicators.fn_compute_all_synthetic_for_bucket(r.pair, r.bucket_time);
    v_count := v_count + 1;
  end loop;

  return v_count;
end;
$$;

comment on function indicators.fn_refresh_recent_synthetic(interval) is
  'Recomputes recent quarter-hour synthetic buckets to heal transient missing-input flags before codex evaluation.';

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
begin
  v_syn_refreshed := indicators.fn_refresh_recent_synthetic(greatest(p_lookback, interval '45 minutes'));
  v_syn_enq := indicators.fn_enqueue_synthetic_jobs(p_lookback);
  v_syn_done := indicators.fn_process_synthetic_jobs(p_syn_batch_size);
  v_codex_enq := indicators.fn_enqueue_codex_signal_jobs(p_lookback);
  v_codex_done := indicators.fn_process_codex_signal_jobs(p_codex_batch_size);

  return jsonb_build_object(
    'ran_at_utc', now(),
    'lookback', p_lookback::text,
    'synthetic_refreshed', v_syn_refreshed,
    'synthetic_enqueued', v_syn_enq,
    'synthetic_processed', v_syn_done,
    'codex_enqueued', v_codex_enq,
    'codex_processed', v_codex_done
  );
end;
$$;

comment on function indicators.fn_run_realtime_signal_tick(interval,integer,integer) is
  'Single realtime tick: enqueue/process synthetic jobs, then enqueue/process codex jobs.';

create or replace function indicators.fn_signal_pipeline_watchdog(
  p_max_lag interval default interval '20 minutes',
  p_reconcile_lookback interval default interval '6 hours'
)
returns jsonb
language plpgsql
as $$
declare
  v_now timestamptz := date_trunc('minute', now());
  v_latest_synth timestamptz;
  v_latest_queue timestamptz;
  v_did_reconcile boolean := false;
  v_tick jsonb := '{}'::jsonb;
begin
  select max(bucket_time)
  into v_latest_synth
  from indicators.synthetic_indicator_values
  where pair in (
    select distinct pair
    from indicators.codex_signal_rules
    where is_active
  );

  select max(bucket_time)
  into v_latest_queue
  from indicators.codex_signal_job_queue
  where pair in (
    select distinct pair
    from indicators.codex_signal_rules
    where is_active
  );

  if v_latest_synth is null
     or v_now - v_latest_synth > p_max_lag
     or v_latest_queue is null
     or v_now - v_latest_queue > p_max_lag then
    v_tick := indicators.fn_run_realtime_signal_tick(p_reconcile_lookback, 5000, 5000);
    v_did_reconcile := true;
  end if;

  return jsonb_build_object(
    'ran_at_utc', v_now,
    'max_lag', p_max_lag::text,
    'latest_synth_bucket', v_latest_synth,
    'latest_codex_queue_bucket', v_latest_queue,
    'did_reconcile', v_did_reconcile,
    'reconcile_tick', v_tick
  );
end;
$$;

comment on function indicators.fn_signal_pipeline_watchdog(interval,interval) is
  'Watchdog: if synthetic/codex freshness lags beyond threshold, run reconcile realtime tick automatically.';

do $$
declare
  v_jobid bigint;
begin
  -- Main realtime schedule aligned with decision windows.
  select jobid into v_jobid from cron.job where jobname = 'codex-signal-tick-main';
  if v_jobid is not null then
    perform cron.unschedule(v_jobid);
  end if;

  perform cron.schedule(
    'codex-signal-tick-main',
    '2,17,32,47 * * * *',
    $cron$select indicators.fn_run_realtime_signal_tick(interval '45 minutes', 5000, 5000);$cron$
  );

  -- Retry schedule for resilience if upstream timing drifts by a minute or two.
  select jobid into v_jobid from cron.job where jobname = 'codex-signal-tick-retry';
  if v_jobid is not null then
    perform cron.unschedule(v_jobid);
  end if;

  perform cron.schedule(
    'codex-signal-tick-retry',
    '4,19,34,49 * * * *',
    $cron$select indicators.fn_run_realtime_signal_tick(interval '90 minutes', 5000, 5000);$cron$
  );

  -- Watchdog reconciliation every 5 minutes.
  select jobid into v_jobid from cron.job where jobname = 'codex-signal-watchdog';
  if v_jobid is not null then
    perform cron.unschedule(v_jobid);
  end if;

  perform cron.schedule(
    'codex-signal-watchdog',
    '*/5 * * * *',
    $cron$select indicators.fn_signal_pipeline_watchdog(interval '20 minutes', interval '6 hours');$cron$
  );
end;
$$;
