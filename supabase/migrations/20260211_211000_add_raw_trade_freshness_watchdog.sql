-- Add raw-trades freshness watchdog to trigger upstream signal pipeline when feed stalls.

create or replace function indicators.fn_raw_trades_freshness_watchdog(
  p_max_lag interval default interval '3 minutes'
)
returns jsonb
language plpgsql
as $$
declare
  v_now timestamptz := now();
  v_latest timestamptz;
  v_lag interval;
  v_triggered boolean := false;
  v_request_id bigint;
  v_url text := 'https://signal-pipeline-277919876041.us-central1.run.app/run';
begin
  select min(max_executed_at)
    into v_latest
  from (
    select max(executed_at) as max_executed_at
    from public.raw_trades
    where pair in ('BTC-USD', 'ETH-USD', 'SOL-USD')
    group by pair
  ) x;

  if v_latest is null then
    v_lag := interval '100 years';
  else
    v_lag := v_now - v_latest;
  end if;

  if v_lag > p_max_lag then
    select net.http_post(
      url := v_url,
      headers := '{"Content-Type": "application/json"}'::jsonb,
      body := '{}'::jsonb
    )
    into v_request_id;

    v_triggered := true;
  end if;

  return jsonb_build_object(
    'ran_at_utc', v_now,
    'max_lag', p_max_lag::text,
    'latest_raw_trade', v_latest,
    'lag_seconds', extract(epoch from v_lag),
    'triggered_pipeline', v_triggered,
    'request_id', v_request_id
  );
end;
$$;

comment on function indicators.fn_raw_trades_freshness_watchdog(interval) is
  'Checks raw_trades freshness for BTC/ETH/SOL and triggers signal-pipeline HTTP run when lag exceeds threshold.';

do $$
declare
  v_jobid bigint;
begin
  select jobid into v_jobid from cron.job where jobname = 'raw-trades-freshness-watchdog';
  if v_jobid is not null then
    perform cron.unschedule(v_jobid);
  end if;

  perform cron.schedule(
    'raw-trades-freshness-watchdog',
    '* * * * *',
    $cron$select indicators.fn_raw_trades_freshness_watchdog(interval '3 minutes');$cron$
  );
end;
$$;
