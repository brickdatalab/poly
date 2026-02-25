-- Issue #1: Open interest freshness upgrade to 5-minute cadence.

update ops.pipeline_slo_config
set
  max_lag = interval '20 minutes',
  notes = 'open interest + oi_features freshness for 5m ingest cadence',
  updated_at = now()
where source in ('open_interest', 'oi_features');

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
    '*/5 * * * *',
    $cron$select ops.fn_invoke_edge(ops.fn_cfg_text('oi_ingestor_url', ''), jsonb_build_object('reason','cron_main_5m'));$cron$
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
    '2-59/5 * * * *',
    $cron$select ops.fn_invoke_edge(ops.fn_cfg_text('oi_ingestor_url', ''), jsonb_build_object('reason','cron_retry_5m'));$cron$
  );
end $$;
