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
      p_bucket_time + interval '2 minutes' as decision_minute
    from indicators.codex_signal_rules r
    join indicators.synthetic_indicator_values s
      on s.pair = r.pair
     and s.bucket_time = p_bucket_time
     and s.config_id = r.config_id
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
    decision_minute
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
    decision_minute
  from matched
  on conflict (pair, bucket_time, rule_id) do update
  set
    prediction = excluded.prediction,
    signals_passed = excluded.signals_passed,
    base_accuracy = excluded.base_accuracy,
    indicator_value = excluded.indicator_value,
    config_id = excluded.config_id,
    fired_at = excluded.fired_at,
    decision_minute = excluded.decision_minute;

  get diagnostics v_rows = row_count;
  return v_rows;
end;
$$;

comment on function indicators.fn_emit_codex_signals_for_bucket(text,timestamptz) is
  'Evaluates active codex rules for pair/bucket and upserts all fired signal rows with directional signals_passed count.';

create or replace function indicators.fn_enqueue_codex_signal_jobs(
  p_lookback interval default interval '45 minutes'
)
returns bigint
language plpgsql
as $$
declare
  v_inserted bigint := 0;
begin
  with pairs as (
    select distinct pair
    from indicators.codex_signal_rules
    where is_active
  ),
  candidates as (
    select p.pair, o.bucket_time
    from pairs p
    join indicators.ohlcv_15m o
      on o.pair = p.pair
    where o.bucket_time > date_trunc('minute', now()) - p_lookback
      and o.bucket_time <= date_trunc('minute', now())
      and o.bucket_time + interval '2 minutes' <= date_trunc('minute', now())
      and extract(second from o.bucket_time) = 0
      and extract(minute from o.bucket_time)::int in (0, 15, 30, 45)
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
  'Enqueues forward codex signal jobs for quarter-hour buckets whose decision minute (t0+2m) is available.';

create or replace function indicators.fn_process_codex_signal_jobs(
  p_batch_size integer default 200
)
returns integer
language plpgsql
as $$
declare
  r record;
  v_done integer := 0;
begin
  for r in
    select id, pair, bucket_time
    from indicators.codex_signal_job_queue
    where status = 'pending'
    order by created_at
    limit p_batch_size
    for update skip locked
  loop
    begin
      update indicators.codex_signal_job_queue
      set
        status = 'running',
        started_at = now(),
        attempts = attempts + 1,
        error_message = null
      where id = r.id;

      if date_trunc('minute', now()) >= r.bucket_time + interval '2 minutes' then
        perform indicators.fn_emit_codex_signals_for_bucket(r.pair, r.bucket_time);

        update indicators.codex_signal_job_queue
        set status = 'done', completed_at = now()
        where id = r.id;

        v_done := v_done + 1;
      else
        update indicators.codex_signal_job_queue
        set status = 'pending', started_at = null
        where id = r.id;
      end if;
    exception when others then
      update indicators.codex_signal_job_queue
      set status = 'failed', completed_at = now(), error_message = sqlerrm
      where id = r.id;
    end;
  end loop;

  return v_done;
end;
$$;

comment on function indicators.fn_process_codex_signal_jobs(integer) is
  'Processes pending codex signal jobs in batches and emits realtime threshold-based signals.';
