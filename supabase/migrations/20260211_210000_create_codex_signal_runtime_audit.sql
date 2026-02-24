-- Add per-window runtime audit for codex signal evaluation.
-- Goal: eliminate silent failures by recording why a bucket emitted zero signals.

create table if not exists indicators.codex_signal_runtime_audit (
  id bigserial primary key,
  pair text not null,
  bucket_time timestamptz not null,
  evaluation_status text not null,
  active_rules integer not null default 0,
  rules_with_inputs integer not null default 0,
  rules_passed integer not null default 0,
  missing_inputs jsonb not null default '{}'::jsonb,
  error_message text,
  evaluated_at timestamptz not null default now(),
  unique (pair, bucket_time),
  constraint codex_signal_runtime_audit_status_check
    check (evaluation_status in ('emitted', 'no_signal', 'stale_inputs', 'error'))
);

create index if not exists idx_codex_signal_runtime_audit_bucket
  on indicators.codex_signal_runtime_audit (bucket_time desc, pair);

comment on table indicators.codex_signal_runtime_audit is
  'Per pair/15m bucket evaluation audit for codex signals. Records why signals emitted or did not emit.';
comment on column indicators.codex_signal_runtime_audit.missing_inputs is
  'JSON object keyed by config_id with missing input counts when synthetic values are unavailable.';
comment on column indicators.codex_signal_runtime_audit.evaluation_status is
  'emitted: at least one rule fired; no_signal: inputs existed but no threshold pass; stale_inputs: insufficient inputs; error: function error.';

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
  ), grid as (
    select
      p.pair,
      gs.bucket_time
    from pairs p
    cross join lateral (
      select generate_series(
        date_trunc('hour', v_now - p_lookback),
        date_trunc('hour', v_now),
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
  'Queues codex signal evaluations on wall-clock 15m grid for active-rule pairs, independent of synthetic presence.';

create or replace function indicators.fn_emit_codex_signals_for_bucket(
  p_pair text,
  p_bucket_time timestamptz
)
returns integer
language plpgsql
as $$
declare
  v_rows integer := 0;
  v_active_rules integer := 0;
  v_rules_with_inputs integer := 0;
  v_rules_passed integer := 0;
  v_missing_inputs jsonb := '{}'::jsonb;
  v_status text := 'no_signal';
begin
  with rule_eval as (
    select
      r.rule_id,
      r.pair,
      r.config_id,
      r.operator,
      r.threshold,
      r.prediction,
      r.base_accuracy,
      s.v1 as indicator_value,
      (s.v1 is not null) as has_input,
      case
        when s.v1 is null then false
        when r.operator = '>=' and s.v1 >= r.threshold then true
        when r.operator = '<=' and s.v1 <= r.threshold then true
        else false
      end as passes
    from indicators.codex_signal_rules r
    left join indicators.synthetic_indicator_values s
      on s.pair = r.pair
     and s.bucket_time = p_bucket_time
     and s.config_id = r.config_id
    where r.is_active
      and r.pair = p_pair
  ), matched as (
    select
      r.rule_id,
      r.pair,
      p_bucket_time as bucket_time,
      r.prediction,
      count(*) over (
        partition by r.pair, p_bucket_time, r.prediction
      )::integer as signals_passed,
      r.base_accuracy,
      r.indicator_value,
      r.config_id,
      now() as fired_at,
      p_bucket_time + interval '2 minutes' as decision_minute,
      o.open::numeric as opening_price,
      o.close::numeric as closing_price,
      case
        when o.open is null or o.close is null then null
        when o.close > o.open then 'up'
        when o.close < o.open then 'down'
        else 'flat'
      end as actual_direction,
      case
        when o.open is null or o.close is null then null
        when o.close > o.open then (r.prediction = 'up')
        when o.close < o.open then (r.prediction = 'down')
        else null
      end as is_accurate,
      case
        when o.bucket_time is null then null
        else o.bucket_time + interval '15 minutes'
      end as resolved_at
    from rule_eval r
    left join indicators.ohlcv_15m o
      on o.pair = r.pair
     and o.bucket_time = p_bucket_time
    where r.passes
  ), metrics as (
    select
      count(*)::integer as active_rules,
      count(*) filter (where has_input)::integer as rules_with_inputs,
      count(*) filter (where passes)::integer as rules_passed
    from rule_eval
  ), missing as (
    select
      coalesce(
        jsonb_object_agg(config_id, jsonb_build_object('missing_count', missing_count)),
        '{}'::jsonb
      ) as missing_inputs
    from (
      select config_id, count(*)::integer as missing_count
      from rule_eval
      where not has_input
      group by config_id
    ) x
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
    decision_minute,
    opening_price,
    closing_price,
    actual_direction,
    is_accurate,
    resolved_at
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
    decision_minute,
    opening_price,
    closing_price,
    actual_direction,
    is_accurate,
    resolved_at
  from matched
  on conflict (pair, bucket_time, rule_id) do update
  set
    prediction = excluded.prediction,
    signals_passed = excluded.signals_passed,
    base_accuracy = excluded.base_accuracy,
    indicator_value = excluded.indicator_value,
    config_id = excluded.config_id,
    fired_at = excluded.fired_at,
    decision_minute = excluded.decision_minute,
    opening_price = excluded.opening_price,
    closing_price = excluded.closing_price,
    actual_direction = excluded.actual_direction,
    is_accurate = excluded.is_accurate,
    resolved_at = excluded.resolved_at;

  get diagnostics v_rows = row_count;

  select active_rules, rules_with_inputs, rules_passed
    into v_active_rules, v_rules_with_inputs, v_rules_passed
  from (
    with rule_eval as (
      select
        r.config_id,
        s.v1 as indicator_value,
        (s.v1 is not null) as has_input,
        case
          when s.v1 is null then false
          when r.operator = '>=' and s.v1 >= r.threshold then true
          when r.operator = '<=' and s.v1 <= r.threshold then true
          else false
        end as passes
      from indicators.codex_signal_rules r
      left join indicators.synthetic_indicator_values s
        on s.pair = r.pair
       and s.bucket_time = p_bucket_time
       and s.config_id = r.config_id
      where r.is_active
        and r.pair = p_pair
    )
    select
      count(*)::integer as active_rules,
      count(*) filter (where has_input)::integer as rules_with_inputs,
      count(*) filter (where passes)::integer as rules_passed
    from rule_eval
  ) m;

  select missing_inputs
    into v_missing_inputs
  from (
    with rule_eval as (
      select
        r.config_id,
        (s.v1 is not null) as has_input
      from indicators.codex_signal_rules r
      left join indicators.synthetic_indicator_values s
        on s.pair = r.pair
       and s.bucket_time = p_bucket_time
       and s.config_id = r.config_id
      where r.is_active
        and r.pair = p_pair
    )
    select coalesce(
      jsonb_object_agg(config_id, jsonb_build_object('missing_count', missing_count)),
      '{}'::jsonb
    ) as missing_inputs
    from (
      select config_id, count(*)::integer as missing_count
      from rule_eval
      where not has_input
      group by config_id
    ) x
  ) mm;

  if v_rules_passed > 0 then
    v_status := 'emitted';
  elsif v_active_rules > 0 and v_rules_with_inputs = 0 then
    v_status := 'stale_inputs';
  else
    v_status := 'no_signal';
  end if;

  insert into indicators.codex_signal_runtime_audit (
    pair,
    bucket_time,
    evaluation_status,
    active_rules,
    rules_with_inputs,
    rules_passed,
    missing_inputs,
    error_message,
    evaluated_at
  )
  values (
    p_pair,
    p_bucket_time,
    v_status,
    v_active_rules,
    v_rules_with_inputs,
    v_rules_passed,
    coalesce(v_missing_inputs, '{}'::jsonb),
    null,
    now()
  )
  on conflict (pair, bucket_time) do update
  set
    evaluation_status = excluded.evaluation_status,
    active_rules = excluded.active_rules,
    rules_with_inputs = excluded.rules_with_inputs,
    rules_passed = excluded.rules_passed,
    missing_inputs = excluded.missing_inputs,
    error_message = excluded.error_message,
    evaluated_at = excluded.evaluated_at;

  return v_rows;
exception
  when others then
    insert into indicators.codex_signal_runtime_audit (
      pair,
      bucket_time,
      evaluation_status,
      active_rules,
      rules_with_inputs,
      rules_passed,
      missing_inputs,
      error_message,
      evaluated_at
    )
    values (
      p_pair,
      p_bucket_time,
      'error',
      coalesce(v_active_rules, 0),
      coalesce(v_rules_with_inputs, 0),
      coalesce(v_rules_passed, 0),
      coalesce(v_missing_inputs, '{}'::jsonb),
      left(sqlerrm, 800),
      now()
    )
    on conflict (pair, bucket_time) do update
    set
      evaluation_status = excluded.evaluation_status,
      active_rules = excluded.active_rules,
      rules_with_inputs = excluded.rules_with_inputs,
      rules_passed = excluded.rules_passed,
      missing_inputs = excluded.missing_inputs,
      error_message = excluded.error_message,
      evaluated_at = excluded.evaluated_at;

    raise;
end;
$$;

comment on function indicators.fn_emit_codex_signals_for_bucket(text,timestamptz) is
  'Evaluates active codex rules for a pair/bucket, writes fired signals, and always upserts runtime audit status.';
