-- Runtime recovery guards for indicator compute pipeline.
-- 1) Ensure PostgREST exposed schemas include indicators for edge-worker RPC calls.
-- 2) Add stale-running job reclaim function and cron backstop.

do $$
declare
  v_current text;
  v_parts text[];
  v_trimmed text[];
  v_item text;
  v_has_indicators boolean := false;
  v_new text;
begin
  select (
    select substring(conf from '^pgrst\.db_schemas=(.*)$')
    from unnest(coalesce(r.rolconfig, array[]::text[])) conf
    where conf like 'pgrst.db_schemas=%'
    limit 1
  )
  into v_current
  from pg_roles r
  where r.rolname = 'authenticator';

  v_current := coalesce(v_current, 'public');
  v_parts := string_to_array(v_current, ',');
  v_trimmed := array[]::text[];

  foreach v_item in array v_parts loop
    v_item := btrim(v_item);
    if v_item <> '' then
      v_trimmed := array_append(v_trimmed, v_item);
      if v_item = 'indicators' then
        v_has_indicators := true;
      end if;
    end if;
  end loop;

  if not v_has_indicators then
    v_trimmed := array_append(v_trimmed, 'indicators');
  end if;

  select string_agg(x, ', ') into v_new
  from (
    select distinct unnest(v_trimmed) as x
  ) s;

  execute format(
    'alter role authenticator set pgrst.db_schemas = %L',
    v_new
  );
  perform pg_notify('pgrst', 'reload config');
end $$;

create or replace function indicators.fn_reclaim_stale_indicator_jobs(
  p_max_age interval default interval '10 minutes'
)
returns integer
language plpgsql
security definer
set search_path = indicators, public
as $$
declare
  v_n integer := 0;
begin
  with moved as (
    update indicators.job_queue
       set status = 'pending',
           started_at = null
     where status = 'running'
       and started_at is not null
       and started_at < now() - p_max_age
    returning 1
  )
  select count(*) into v_n from moved;

  return coalesce(v_n, 0);
end;
$$;

comment on function indicators.fn_reclaim_stale_indicator_jobs(interval) is
  'Moves stale running indicator jobs back to pending for safe retry.';

do $$
declare
  v_jobid bigint;
begin
  select jobid into v_jobid from cron.job where jobname = 'reclaim-stale-indicator-jobs';
  if v_jobid is not null then
    perform cron.unschedule(v_jobid);
  end if;

  perform cron.schedule(
    'reclaim-stale-indicator-jobs',
    '*/5 * * * *',
    $cron$select indicators.fn_reclaim_stale_indicator_jobs(interval '10 minutes');$cron$
  );
end $$;

