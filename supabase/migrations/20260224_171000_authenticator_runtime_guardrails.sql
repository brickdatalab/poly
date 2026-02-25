-- Authenticator runtime guardrails for PostgREST-backed edge workers.
-- Keeps required schemas exposed and raises statement timeout high enough for bounded rollups.

do $$
declare
  v_current text;
  v_parts text[];
  v_trimmed text[];
  v_ordered text[];
  v_item text;
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
  v_ordered := array['public', 'indicators', 'profile_tracker'];

  foreach v_item in array v_parts loop
    v_item := btrim(v_item);
    if v_item <> '' and not (v_item = any(v_ordered)) then
      v_trimmed := array_append(v_trimmed, v_item);
    end if;
  end loop;

  if exists (select 1 from pg_namespace where nspname = 'copy_pros')
     and not ('copy_pros' = any(v_ordered)) then
    v_ordered := array_append(v_ordered, 'copy_pros');
  end if;

  if cardinality(v_trimmed) > 0 then
    foreach v_item in array v_trimmed loop
      if not (v_item = any(v_ordered)) then
        v_ordered := array_append(v_ordered, v_item);
      end if;
    end loop;
  end if;

  select string_agg(x, ', ') into v_new
  from unnest(v_ordered) as x;

  execute format('alter role authenticator set pgrst.db_schemas = %L', v_new);
  execute 'alter role authenticator set statement_timeout = ''60s''';
  execute 'alter role authenticator set lock_timeout = ''8s''';

  perform pg_notify('pgrst', 'reload config');
  perform pg_notify('pgrst', 'reload schema');
end $$;
