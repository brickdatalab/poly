create or replace function indicators.fn_backfill_synthetic_indicators(
  p_from timestamptz,
  p_to timestamptz,
  p_pairs text[] default array['BTC-USD','ETH-USD','SOL-USD']
)
returns bigint
language plpgsql
as $$
declare
  v_bucket timestamptz;
  v_pair text;
  v_count bigint := 0;
begin
  if p_from is null then
    p_from := '2026-01-22 07:15:00+00'::timestamptz;
  end if;
  if p_to is null then
    p_to := date_trunc('minute', now()) - interval '15 minutes';
  end if;

  v_bucket := p_from;
  while v_bucket <= p_to loop
    if extract(second from v_bucket) = 0 and extract(minute from v_bucket) in (0,15,30,45) then
      foreach v_pair in array p_pairs loop
        perform indicators.fn_compute_all_synthetic_for_bucket(v_pair, v_bucket);
        v_count := v_count + 1;
      end loop;
    end if;
    v_bucket := v_bucket + interval '15 minutes';
  end loop;

  return v_count;
end;
$$;

comment on function indicators.fn_backfill_synthetic_indicators(timestamptz,timestamptz,text[]) is
  'Backfills synthetic indicators over a 15m boundary range for provided pairs.';

create or replace function indicators.fn_enqueue_synthetic_jobs(
  p_lookback interval default interval '4 hours'
)
returns bigint
language plpgsql
as $$
declare
  v_inserted bigint := 0;
begin
  with candidates as (
    select o.pair, o.bucket_time
    from indicators.ohlcv_15m o
    where o.bucket_time > date_trunc('minute', now()) - p_lookback
      and o.bucket_time <= date_trunc('minute', now()) - interval '15 minutes'
      and extract(second from o.bucket_time) = 0
      and extract(minute from o.bucket_time) in (0,15,30,45)
  ), phases as (
    select c.pair, c.bucket_time, p.decision_phase
    from candidates c
    cross join (values ('t_plus_1m'::text), ('t_plus_2m'::text)) p(decision_phase)
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
  'Enqueues synthetic jobs for recent 15m buckets and both decision phases.';

create or replace function indicators.fn_process_synthetic_jobs(
  p_batch_size integer default 100
)
returns integer
language plpgsql
as $$
declare
  r record;
  v_done integer := 0;
  v_ready_time timestamptz;
begin
  for r in
    select id, pair, bucket_time, decision_phase
    from indicators.synthetic_job_queue
    where status = 'pending'
    order by created_at
    limit p_batch_size
    for update skip locked
  loop
    begin
      update indicators.synthetic_job_queue
      set status = 'running', started_at = now(), attempts = attempts + 1, error_message = null
      where id = r.id;

      v_ready_time := case
        when r.decision_phase = 't_plus_1m' then r.bucket_time + interval '1 minute'
        else r.bucket_time + interval '2 minutes'
      end;

      -- Ensure required early candle is closed before compute.
      if date_trunc('minute', now()) >= v_ready_time then
        perform indicators.fn_compute_all_synthetic_for_bucket(r.pair, r.bucket_time);

        update indicators.synthetic_job_queue
        set status = 'done', completed_at = now()
        where id = r.id;

        v_done := v_done + 1;
      else
        update indicators.synthetic_job_queue
        set status = 'pending', started_at = null
        where id = r.id;
      end if;
    exception when others then
      update indicators.synthetic_job_queue
      set status = 'failed', completed_at = now(), error_message = sqlerrm
      where id = r.id;
    end;
  end loop;

  return v_done;
end;
$$;

comment on function indicators.fn_process_synthetic_jobs(integer) is
  'Processes pending synthetic jobs in batches without touching indicators.job_queue.';
