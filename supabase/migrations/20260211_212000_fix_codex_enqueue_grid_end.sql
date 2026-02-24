-- Fix codex enqueue grid end boundary.
-- Previous function used date_trunc('hour', v_now) as grid end, which skipped
-- :15/:30/:45 windows until the next hour.

create or replace function indicators.fn_enqueue_codex_signal_jobs(
  p_lookback interval default interval '45 minutes'
)
returns bigint
language plpgsql
as $$
declare
  v_inserted bigint := 0;
  v_now timestamptz := date_trunc('minute', now());
  v_grid_end timestamptz;
begin
  v_grid_end := date_trunc('hour', v_now)
    + (floor(extract(minute from v_now)::numeric / 15) * interval '15 minutes');

  with pairs as (
    select distinct pair
    from indicators.codex_signal_rules
    where is_active
  ), grid as (
    select
      p.pair,
      gs.bucket_time
    from pairs p
    cross join lateral (
      select generate_series(
        date_trunc('hour', v_now - p_lookback),
        v_grid_end,
        interval '15 minutes'
      ) as bucket_time
    ) gs
    where gs.bucket_time > v_now - p_lookback
      and gs.bucket_time + interval '2 minutes' <= v_now
  )
  insert into indicators.codex_signal_job_queue (pair, bucket_time, status)
  select pair, bucket_time, 'pending'
  from grid
  on conflict (pair, bucket_time) do nothing;

  get diagnostics v_inserted = row_count;
  return v_inserted;
end;
$$;

comment on function indicators.fn_enqueue_codex_signal_jobs(interval) is
  'Queues codex signal evaluations on 15m grid up to current quarter-hour boundary for active-rule pairs.';
