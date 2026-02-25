-- Trade-flow snapshot watchdog and auto-heal
-- Detects stale snapshots / cron degradation, logs incidents, and triggers bounded catch-up tick.

begin;

insert into ops.pipeline_slo_config (source, enabled, max_lag, max_missing, max_gap_windows, max_numeric, notes)
values ('trade_flow_snapshots', true, interval '120 seconds', null, null, null, 'Per-pair freshness SLO for public.trade_flow_snapshots')
on conflict (source) do update
set enabled = excluded.enabled,
    max_lag = excluded.max_lag,
    notes = excluded.notes,
    updated_at = now() at time zone 'utc';


create or replace function ops.fn_trade_flow_snapshot_watchdog()
returns jsonb
language plpgsql
as $$
declare
  v_now timestamptz := now() at time zone 'utc';
  v_slo_lag interval := coalesce((select max_lag from ops.pipeline_slo_config where source='trade_flow_snapshots' and enabled), interval '120 seconds');
  v_slo_seconds numeric := extract(epoch from v_slo_lag);
  v_snapshot jsonb;
  v_max_age numeric := 1e9;
  v_success_15m integer := 0;
  v_fail_15m integer := 0;
  v_violation boolean := false;
  v_violation_reasons text[] := array[]::text[];
  v_incident_id bigint;
  v_action_id bigint;
  v_tick_result jsonb;
  v_summary text := 'trade_flow_snapshots stale_or_cron_degraded';
begin
  with pairs as (
    select unnest(array['BTC-USD','ETH-USD','SOL-USD'])::text as pair
  ),
  latest as (
    select p.pair, max(s.snapshot_time) as max_ts
    from pairs p
    left join public.trade_flow_snapshots s on s.pair = p.pair
    group by p.pair
  ),
  ages as (
    select
      pair,
      max_ts,
      extract(epoch from (v_now - max_ts))::numeric as age_seconds
    from latest
  ),
  cron_stats as (
    select
      count(*) filter (
        where d.status = 'succeeded'
          and coalesce(d.end_time, d.start_time) > v_now - interval '15 minutes'
      )::int as successes_15m,
      count(*) filter (
        where d.status in ('failed','error')
          and coalesce(d.end_time, d.start_time) > v_now - interval '15 minutes'
      )::int as failures_15m
    from cron.job_run_details d
    join cron.job j on j.jobid = d.jobid
    where j.jobname = 'trade_flow_snapshots_every_minute'
      and coalesce(d.end_time, d.start_time) > v_now - interval '60 minutes'
  )
  select jsonb_build_object(
      'captured_at_utc', v_now,
      'slo_seconds', v_slo_seconds,
      'pairs', (
        select jsonb_object_agg(pair, jsonb_build_object('max_ts', max_ts, 'age_seconds', age_seconds))
        from ages
      ),
      'max_age_seconds', (select coalesce(max(age_seconds), 1e9) from ages),
      'cron_successes_15m', (select coalesce(successes_15m, 0) from cron_stats),
      'cron_failures_15m', (select coalesce(failures_15m, 0) from cron_stats)
    )
    into v_snapshot;

  v_max_age := coalesce((v_snapshot->>'max_age_seconds')::numeric, 1e9);
  v_success_15m := coalesce((v_snapshot->>'cron_successes_15m')::int, 0);
  v_fail_15m := coalesce((v_snapshot->>'cron_failures_15m')::int, 0);

  if v_max_age > v_slo_seconds then
    v_violation := true;
    v_violation_reasons := array_append(v_violation_reasons, 'stale_trade_flow_snapshots');
  end if;

  if v_success_15m = 0 then
    v_violation := true;
    v_violation_reasons := array_append(v_violation_reasons, 'no_success_15m');
  end if;

  if v_fail_15m >= 3 then
    v_violation := true;
    v_violation_reasons := array_append(v_violation_reasons, 'cron_failures_15m>=3');
  end if;

  perform ops.fn_log_health_snapshot(
    'trade_flow_snapshot_watchdog',
    jsonb_build_object(
      'captured_at_utc', v_now,
      'violations', case when v_violation then to_jsonb(v_violation_reasons) else '[]'::jsonb end,
      'details', v_snapshot
    )
  );

  if v_violation then
    select id
      into v_incident_id
    from ops.pipeline_incident_log
    where status = 'open'
      and summary = v_summary
    order by opened_at_utc desc
    limit 1;

    if v_incident_id is null then
      insert into ops.pipeline_incident_log (status, severity, summary, latest_snapshot, actions_summary, notes)
      values (
        'open',
        'SEV-2',
        v_summary,
        v_snapshot,
        jsonb_build_object('reasons', to_jsonb(v_violation_reasons)),
        'Auto-opened by fn_trade_flow_snapshot_watchdog'
      )
      returning id into v_incident_id;
    else
      update ops.pipeline_incident_log
         set latest_snapshot = v_snapshot,
             actions_summary = jsonb_build_object('reasons', to_jsonb(v_violation_reasons)),
             notes = 'Updated by fn_trade_flow_snapshot_watchdog',
             last_alert_at_utc = v_now
       where id = v_incident_id;
    end if;

    v_action_id := ops.fn_begin_action(
      'trade_flow_snapshot_autoheal',
      'trade_flow_watchdog',
      jsonb_build_object('incident_id', v_incident_id, 'snapshot', v_snapshot)
    );

    if v_action_id is not null then
      begin
        select public.capture_trade_flow_snapshots_tick(v_now, 60) into v_tick_result;
        perform ops.fn_end_action(
          v_action_id,
          'success',
          jsonb_build_object('tick_result', v_tick_result),
          null
        );
      exception when others then
        perform ops.fn_end_action(
          v_action_id,
          'error',
          jsonb_build_object('snapshot', v_snapshot),
          sqlerrm
        );
      end;
    end if;
  else
    update ops.pipeline_incident_log
       set status = 'closed',
           closed_at_utc = v_now,
           latest_snapshot = v_snapshot,
           notes = 'Closed by fn_trade_flow_snapshot_watchdog'
     where status = 'open'
       and summary = v_summary;
  end if;

  return jsonb_build_object(
    'ok', true,
    'captured_at_utc', v_now,
    'violation', v_violation,
    'reasons', to_jsonb(v_violation_reasons),
    'snapshot', v_snapshot
  );
end;
$$;


do $$
declare
  v_jobid bigint;
begin
  select jobid into v_jobid from cron.job where jobname = 'trade-flow-snapshot-watchdog';
  if v_jobid is not null then
    perform cron.unschedule(v_jobid);
  end if;

  perform cron.schedule(
    'trade-flow-snapshot-watchdog',
    '*/2 * * * *',
    'select ops.fn_trade_flow_snapshot_watchdog();'
  );
end;
$$;

commit;
