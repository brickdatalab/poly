-- Backstop cron trigger for indicator-worker.
-- Ensures pending jobs are periodically nudged even if trigger->pg_net path misses.

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
      when (select count(*) from indicators.job_queue where status = 'pending') > 0 then
        net.http_post(
          url := 'https://cxvntzszdkyggjjenefn.supabase.co/functions/v1/indicator-worker',
          headers := '{"Content-Type":"application/json"}'::jsonb,
          body := '{}'::jsonb
        )
      else
        null
    end;
    $cron$
  );
end $$;

