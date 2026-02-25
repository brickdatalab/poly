-- Issues #2 + #4
-- Master indicator registry and unified health/latency control-plane.
-- NOTE: no active column is intentionally included in ops.master_indicator_registry.

create table if not exists ops.master_indicator_registry (
  indicator_key text primary key,
  domain text not null check (domain in ('ohlcv_derived','order_book','open_interest','oi_features')),
  storage_table text not null,
  storage_column text not null,
  pair_column text not null default 'pair',
  time_column text not null,
  timeframe_seconds integer not null check (timeframe_seconds > 0),
  freshness_slo_seconds integer not null check (freshness_slo_seconds > 0),
  availability_mode text not null check (availability_mode in ('exact_bucket_required','latest_required')),
  expected_granularity_seconds integer not null check (expected_granularity_seconds > 0),
  reasoning_metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create or replace function ops.fn_timeframe_to_seconds(p_timeframe text)
returns integer
language plpgsql
as $$
begin
  return case p_timeframe
    when '1m' then 60
    when '5m' then 300
    when '10m' then 600
    when '15m' then 900
    when '30m' then 1800
    when '45m' then 2700
    when '1h' then 3600
    when '2h' then 7200
    when '6h' then 21600
    when '12h' then 43200
    else 900
  end;
end;
$$;

create or replace function ops.fn_sync_master_indicator_registry()
returns jsonb
language plpgsql
as $$
declare
  v_count integer := 0;
begin
  delete from ops.master_indicator_registry;

  insert into ops.master_indicator_registry (
    indicator_key,
    domain,
    storage_table,
    storage_column,
    pair_column,
    time_column,
    timeframe_seconds,
    freshness_slo_seconds,
    availability_mode,
    expected_granularity_seconds,
    reasoning_metadata
  )
  select
    format('ohlcv:%s:%s', ic.config_id, kv.key) as indicator_key,
    'ohlcv_derived'::text as domain,
    'indicators.indicator_values'::text as storage_table,
    kv.key::text as storage_column,
    'pair'::text as pair_column,
    'bucket_time'::text as time_column,
    ops.fn_timeframe_to_seconds(ic.timeframe) as timeframe_seconds,
    greatest(ops.fn_timeframe_to_seconds(ic.timeframe), 60) as freshness_slo_seconds,
    'exact_bucket_required'::text as availability_mode,
    ops.fn_timeframe_to_seconds(ic.timeframe) as expected_granularity_seconds,
    jsonb_build_object(
      'config_id', ic.config_id,
      'indicator_name', ic.indicator_name,
      'timeframe', ic.timeframe,
      'output_key', kv.key,
      'output_name', kv.value,
      'is_active', ic.is_active
    ) as reasoning_metadata
  from indicators.indicator_configs ic
  cross join lateral jsonb_each_text(ic.output_columns) kv
  where kv.key in ('v1','v2','v3','v4','v5')
    and ic.is_active;

  insert into ops.master_indicator_registry (
    indicator_key, domain, storage_table, storage_column, pair_column, time_column,
    timeframe_seconds, freshness_slo_seconds, availability_mode, expected_granularity_seconds, reasoning_metadata
  )
  select *
  from (
    values
      ('order_book:mid_price','order_book','indicators.order_book_indicators','mid_price','pair','captured_at',60,120,'latest_required',60,'{}'::jsonb),
      ('order_book:spread_pct','order_book','indicators.order_book_indicators','spread_pct','pair','captured_at',60,120,'latest_required',60,'{}'::jsonb),
      ('order_book:depth_ratio','order_book','indicators.order_book_indicators','depth_ratio','pair','captured_at',60,120,'latest_required',60,'{}'::jsonb),
      ('order_book:imbalance','order_book','indicators.order_book_indicators','imbalance','pair','captured_at',60,120,'latest_required',60,'{}'::jsonb),
      ('order_book:bid_depth_10bps','order_book','indicators.order_book_indicators','bid_depth_10bps','pair','captured_at',60,120,'latest_required',60,'{}'::jsonb),
      ('order_book:ask_depth_10bps','order_book','indicators.order_book_indicators','ask_depth_10bps','pair','captured_at',60,120,'latest_required',60,'{}'::jsonb),
      ('order_book:bid_depth_25bps','order_book','indicators.order_book_indicators','bid_depth_25bps','pair','captured_at',60,120,'latest_required',60,'{}'::jsonb),
      ('order_book:ask_depth_25bps','order_book','indicators.order_book_indicators','ask_depth_25bps','pair','captured_at',60,120,'latest_required',60,'{}'::jsonb),
      ('order_book:bid_depth_50bps','order_book','indicators.order_book_indicators','bid_depth_50bps','pair','captured_at',60,120,'latest_required',60,'{}'::jsonb),
      ('order_book:ask_depth_50bps','order_book','indicators.order_book_indicators','ask_depth_50bps','pair','captured_at',60,120,'latest_required',60,'{}'::jsonb),
      ('order_book:bid_slope','order_book','indicators.order_book_indicators','bid_slope','pair','captured_at',60,120,'latest_required',60,'{}'::jsonb),
      ('order_book:ask_slope','order_book','indicators.order_book_indicators','ask_slope','pair','captured_at',60,120,'latest_required',60,'{}'::jsonb),
      ('order_book:slippage_buy_100','order_book','indicators.order_book_indicators','slippage_buy_100','pair','captured_at',60,120,'latest_required',60,'{}'::jsonb),
      ('order_book:slippage_sell_100','order_book','indicators.order_book_indicators','slippage_sell_100','pair','captured_at',60,120,'latest_required',60,'{}'::jsonb),
      ('order_book:slippage_buy_1000','order_book','indicators.order_book_indicators','slippage_buy_1000','pair','captured_at',60,120,'latest_required',60,'{}'::jsonb),
      ('order_book:slippage_sell_1000','order_book','indicators.order_book_indicators','slippage_sell_1000','pair','captured_at',60,120,'latest_required',60,'{}'::jsonb),

      ('open_interest:open_interest','open_interest','indicators.open_interest','open_interest','pair','bucket_time',900,900,'latest_required',900,'{}'::jsonb),
      ('open_interest:oi_change','open_interest','indicators.open_interest','oi_change','pair','bucket_time',900,900,'latest_required',900,'{}'::jsonb),
      ('open_interest:oi_change_pct','open_interest','indicators.open_interest','oi_change_pct','pair','bucket_time',900,900,'latest_required',900,'{}'::jsonb),
      ('open_interest:price_change_pct','open_interest','indicators.open_interest','price_change_pct','pair','bucket_time',900,900,'latest_required',900,'{}'::jsonb),
      ('open_interest:oi_volume_ratio','open_interest','indicators.open_interest','oi_volume_ratio','pair','bucket_time',900,900,'latest_required',900,'{}'::jsonb),
      ('open_interest:oi_divergence','open_interest','indicators.open_interest','oi_divergence','pair','bucket_time',900,900,'latest_required',900,'{}'::jsonb),
      ('open_interest:weak_rally','open_interest','indicators.open_interest','weak_rally','pair','bucket_time',900,900,'latest_required',900,'{}'::jsonb),
      ('open_interest:weak_selloff','open_interest','indicators.open_interest','weak_selloff','pair','bucket_time',900,900,'latest_required',900,'{}'::jsonb),
      ('open_interest:mark_price','open_interest','indicators.open_interest','mark_price','pair','bucket_time',900,900,'latest_required',900,'{}'::jsonb),
      ('open_interest:open_interest_notional','open_interest','indicators.open_interest','open_interest_notional','pair','bucket_time',900,900,'latest_required',900,'{}'::jsonb),
      ('open_interest:funding_rate','open_interest','indicators.open_interest','funding_rate','pair','bucket_time',900,900,'latest_required',900,'{}'::jsonb),
      ('open_interest:funding_rate_8h_avg','open_interest','indicators.open_interest','funding_rate_8h_avg','pair','bucket_time',900,900,'latest_required',900,'{}'::jsonb),

      ('oi_features:divergence_1h','oi_features','indicators.oi_features','divergence_1h','pair','bucket_time',900,900,'latest_required',900,'{}'::jsonb),
      ('oi_features:divergence_4h','oi_features','indicators.oi_features','divergence_4h','pair','bucket_time',900,900,'latest_required',900,'{}'::jsonb),
      ('oi_features:funding_oi_pressure','oi_features','indicators.oi_features','funding_oi_pressure','pair','bucket_time',900,900,'latest_required',900,'{}'::jsonb),
      ('oi_features:funding_oi_pressure_1h','oi_features','indicators.oi_features','funding_oi_pressure_1h','pair','bucket_time',900,900,'latest_required',900,'{}'::jsonb),
      ('oi_features:basis_pct','oi_features','indicators.oi_features','basis_pct','pair','bucket_time',900,900,'latest_required',900,'{}'::jsonb),
      ('oi_features:oi_roc_1h','oi_features','indicators.oi_features','oi_roc_1h','pair','bucket_time',900,900,'latest_required',900,'{}'::jsonb),
      ('oi_features:oi_roc_4h','oi_features','indicators.oi_features','oi_roc_4h','pair','bucket_time',900,900,'latest_required',900,'{}'::jsonb),
      ('oi_features:oi_roc_24h','oi_features','indicators.oi_features','oi_roc_24h','pair','bucket_time',900,900,'latest_required',900,'{}'::jsonb),
      ('oi_features:oi_acceleration','oi_features','indicators.oi_features','oi_acceleration','pair','bucket_time',900,900,'latest_required',900,'{}'::jsonb),
      ('oi_features:weak_rally_streak','oi_features','indicators.oi_features','weak_rally_streak','pair','bucket_time',900,900,'latest_required',900,'{}'::jsonb),
      ('oi_features:weak_selloff_streak','oi_features','indicators.oi_features','weak_selloff_streak','pair','bucket_time',900,900,'latest_required',900,'{}'::jsonb),
      ('oi_features:oi_ema_8','oi_features','indicators.oi_features','oi_ema_8','pair','bucket_time',900,900,'latest_required',900,'{}'::jsonb),
      ('oi_features:oi_ema_24','oi_features','indicators.oi_features','oi_ema_24','pair','bucket_time',900,900,'latest_required',900,'{}'::jsonb),
      ('oi_features:oi_ema_dev_8','oi_features','indicators.oi_features','oi_ema_dev_8','pair','bucket_time',900,900,'latest_required',900,'{}'::jsonb),
      ('oi_features:oi_ema_dev_24','oi_features','indicators.oi_features','oi_ema_dev_24','pair','bucket_time',900,900,'latest_required',900,'{}'::jsonb),
      ('oi_features:price_oi_corr_16','oi_features','indicators.oi_features','price_oi_corr_16','pair','bucket_time',900,900,'latest_required',900,'{}'::jsonb),
      ('oi_features:price_oi_corr_24','oi_features','indicators.oi_features','price_oi_corr_24','pair','bucket_time',900,900,'latest_required',900,'{}'::jsonb),
      ('oi_features:oi_change_vol_pctile_24h','oi_features','indicators.oi_features','oi_change_vol_pctile_24h','pair','bucket_time',900,900,'latest_required',900,'{}'::jsonb),
      ('oi_features:turnover_1h','oi_features','indicators.oi_features','turnover_1h','pair','bucket_time',900,900,'latest_required',900,'{}'::jsonb),
      ('oi_features:turnover_4h','oi_features','indicators.oi_features','turnover_4h','pair','bucket_time',900,900,'latest_required',900,'{}'::jsonb)
  ) as static_rows(
    indicator_key, domain, storage_table, storage_column, pair_column, time_column,
    timeframe_seconds, freshness_slo_seconds, availability_mode, expected_granularity_seconds, reasoning_metadata
  );

  select count(*) into v_count from ops.master_indicator_registry;

  return jsonb_build_object('registry_rows', v_count);
end;
$$;

create or replace function ops.fn_indicator_master_health_snapshot(
  p_pairs text[] default array['BTC-USD','ETH-USD','SOL-USD'],
  p_lookback interval default interval '24 hours'
)
returns jsonb
language plpgsql
as $$
declare
  v_now timestamptz := now() at time zone 'utc';
  v_window_start timestamptz := (now() at time zone 'utc') - p_lookback;
  v_rows jsonb := '[]'::jsonb;
  v_row jsonb;
  v_pair text;
  r record;
  v_sql text;
  v_latest_ts timestamptz;
  v_lag_seconds bigint;
  v_expected_bucket_time timestamptz;
  v_observed_bucket_time timestamptz;
  v_missing_count integer;
  v_gap_count integer;
  v_duplicate_count integer;
  v_misaligned_count integer;
  v_status text;
  v_reason_code text;
  v_reason_detail text;
  v_dep_latest timestamptz;
  v_dep_lag_seconds bigint;
  v_dep_table text;
  v_summary jsonb;
  v_registry_rows integer;
  v_expected_ohlcv_rows integer;
  v_actual_ohlcv_rows integer;
begin
  select count(*) into v_registry_rows from ops.master_indicator_registry;
  if v_registry_rows = 0 then
    perform ops.fn_sync_master_indicator_registry();
    select count(*) into v_registry_rows from ops.master_indicator_registry;
  end if;

  if v_registry_rows = 0 then
    return jsonb_build_object(
      'generated_at_utc', to_char(v_now, 'YYYY-MM-DD"T"HH24:MI:SS"Z"'),
      'summary', jsonb_build_object(
        'total_checks', 1,
        'passed_checks', 0,
        'warn_checks', 0,
        'failed_checks', 1,
        'overall_status', 'FAIL',
        'traffic_light', 'RED'
      ),
      'rows', jsonb_build_array(jsonb_build_object(
        'indicator_key', 'registry:empty',
        'domain', 'registry',
        'pair', 'ALL',
        'status', 'FAIL',
        'traffic_light', 'RED',
        'reason_code', 'REGISTRY_DRIFT',
        'reason_detail', 'ops.master_indicator_registry is empty',
        'latest_ts', null,
        'lag_seconds', null,
        'slo_seconds', null,
        'expected_bucket_time', null,
        'observed_bucket_time', null,
        'missing_count', 0,
        'gap_count', 0,
        'duplicate_count', 0,
        'misaligned_count', 0,
        'dependency_snapshot', jsonb_build_object(),
        'remediation_class', 'reclaim_stale_jobs'
      ))
    );
  end if;

  select count(*) into v_expected_ohlcv_rows
  from indicators.indicator_configs ic
  cross join lateral jsonb_each_text(ic.output_columns) kv
  where kv.key in ('v1','v2','v3','v4','v5')
    and ic.is_active;

  select count(*) into v_actual_ohlcv_rows
  from ops.master_indicator_registry
  where domain = 'ohlcv_derived';

  if v_expected_ohlcv_rows <> v_actual_ohlcv_rows then
    v_rows := v_rows || jsonb_build_array(jsonb_build_object(
      'indicator_key', 'registry:ohlcv_config_count',
      'domain', 'ohlcv_derived',
      'pair', 'ALL',
      'status', 'FAIL',
      'traffic_light', 'RED',
      'reason_code', 'CONFIG_COUNT_MISMATCH',
      'reason_detail', format('expected=%s actual=%s', v_expected_ohlcv_rows, v_actual_ohlcv_rows),
      'latest_ts', null,
      'lag_seconds', null,
      'slo_seconds', null,
      'expected_bucket_time', null,
      'observed_bucket_time', null,
      'missing_count', 0,
      'gap_count', 0,
      'duplicate_count', 0,
      'misaligned_count', 0,
      'dependency_snapshot', jsonb_build_object(),
      'remediation_class', 'reclaim_stale_jobs'
    ));
  end if;

  for r in
    select *
    from ops.master_indicator_registry
    order by domain, indicator_key
  loop
    foreach v_pair in array p_pairs loop
      begin
        v_sql := format($fmt$
          with latest as (
            select
              max(%2$I) as latest_ts
            from %5$s
            where %1$I = %6$L
              and %2$I >= %7$L::timestamptz
              and %2$I < %8$L::timestamptz
              and %3$I is not null
          ),
          expected as (
            select
              case
                when %9$L = 'exact_bucket_required'
                then (to_timestamp(floor(extract(epoch from %8$L::timestamptz) / %4$s) * %4$s)::timestamptz - interval '1 second' * %4$s)
                else null::timestamptz
              end as expected_bucket_time
          ),
          expected_missing as (
            select
              case
                when %9$L <> 'exact_bucket_required' then 0
                when exists (
                  select 1
                  from %5$s t
                  join expected e on t.%2$I = e.expected_bucket_time
                  where t.%1$I = %6$L
                    and t.%3$I is not null
                ) then 0
                else 1
              end::int as missing_count
          )
          select
            (select latest_ts from latest) as latest_ts,
            (select expected_bucket_time from expected) as expected_bucket_time,
            (select latest_ts from latest) as observed_bucket_time,
            (select missing_count from expected_missing) as missing_count,
            0::int as gap_count,
            0::int as duplicate_count,
            0::int as misaligned_count
        $fmt$,
          r.pair_column,
          r.time_column,
          r.storage_column,
          r.expected_granularity_seconds,
          r.storage_table,
          v_pair,
          v_window_start,
          v_now,
          r.availability_mode
        );

        execute v_sql
          into v_latest_ts, v_expected_bucket_time, v_observed_bucket_time,
               v_missing_count, v_gap_count, v_duplicate_count, v_misaligned_count;

        v_lag_seconds := case when v_latest_ts is null then null else greatest(0, extract(epoch from (v_now - v_latest_ts))::bigint) end;

        v_dep_table := null;
        if r.domain = 'ohlcv_derived' then
          v_dep_table := case r.reasoning_metadata->>'timeframe'
            when '1m' then 'indicators.ohlcv_1m'
            when '5m' then 'indicators.ohlcv_5m'
            when '10m' then 'indicators.ohlcv_10m'
            when '15m' then 'indicators.ohlcv_15m'
            when '30m' then 'indicators.ohlcv_30m'
            when '45m' then 'indicators.ohlcv_45m'
            when '1h' then 'indicators.ohlcv_1h'
            when '2h' then 'indicators.ohlcv_2h'
            when '6h' then 'indicators.ohlcv_6h'
            when '12h' then 'indicators.ohlcv_12h'
            else null
          end;
        end if;

        v_dep_latest := null;
        v_dep_lag_seconds := null;
        if v_dep_table is not null then
          execute format('select max(bucket_time) from %s where pair = %L', v_dep_table, v_pair) into v_dep_latest;
          if v_dep_latest is not null then
            v_dep_lag_seconds := greatest(0, extract(epoch from (v_now - v_dep_latest))::bigint);
          end if;
        end if;

        v_status := 'PASS';
        v_reason_code := null;
        v_reason_detail := null;

        if v_latest_ts is null then
          v_status := 'FAIL';
          v_reason_code := 'NO_DATA_IN_WINDOW';
          v_reason_detail := 'No non-null rows in lookback window';
        elsif r.availability_mode = 'exact_bucket_required' and coalesce(v_missing_count, 0) > 0 then
          v_status := 'FAIL';
          v_reason_code := 'MISSING_EXPECTED_BUCKET';
          v_reason_detail := 'Latest expected bucket missing';
        elsif coalesce(v_lag_seconds, 0) > r.freshness_slo_seconds then
          v_status := 'FAIL';
          if v_dep_lag_seconds is not null and v_dep_lag_seconds > r.freshness_slo_seconds then
            v_reason_code := 'DEPENDENCY_STALE';
            v_reason_detail := 'Dependency source is stale';
          else
            v_reason_code := 'LAG_EXCEEDED';
            v_reason_detail := 'Latest row exceeds freshness SLO';
          end if;
        elsif coalesce(v_duplicate_count, 0) > 0 then
          v_status := 'WARN';
          v_reason_code := 'DUPLICATE_BUCKETS';
          v_reason_detail := 'Duplicate aligned buckets present';
        elsif coalesce(v_misaligned_count, 0) > 0 then
          v_status := 'WARN';
          v_reason_code := 'MISALIGNED_BUCKETS';
          v_reason_detail := 'Misaligned buckets present';
        elsif coalesce(v_gap_count, 0) > 0 then
          v_status := 'WARN';
          v_reason_code := 'GAP_VIOLATION';
          v_reason_detail := 'Gap violations detected';
        end if;

        v_row := jsonb_build_object(
          'indicator_key', r.indicator_key,
          'domain', r.domain,
          'pair', v_pair,
          'status', v_status,
          'traffic_light', case when v_status='PASS' then 'GREEN' when v_status='WARN' then 'YELLOW' else 'RED' end,
          'reason_code', coalesce(v_reason_code, 'NONE'),
          'reason_detail', coalesce(v_reason_detail, 'OK'),
          'latest_ts', v_latest_ts,
          'lag_seconds', v_lag_seconds,
          'slo_seconds', r.freshness_slo_seconds,
          'expected_bucket_time', v_expected_bucket_time,
          'observed_bucket_time', v_observed_bucket_time,
          'missing_count', coalesce(v_missing_count, 0),
          'gap_count', coalesce(v_gap_count, 0),
          'duplicate_count', coalesce(v_duplicate_count, 0),
          'misaligned_count', coalesce(v_misaligned_count, 0),
          'dependency_snapshot', jsonb_build_object(
            'dependency_latest_ts', v_dep_latest,
            'dependency_lag_seconds', v_dep_lag_seconds
          ),
          'remediation_class', case
            when coalesce(v_reason_code, '') in ('MISSING_EXPECTED_BUCKET','GAP_VIOLATION') then 'run_backfill_window'
            when coalesce(v_reason_code, '') in ('LAG_EXCEEDED','NO_DATA_IN_WINDOW') then 'trigger_recompute'
            when coalesce(v_reason_code, '') in ('DEPENDENCY_STALE') then 'escalate_source_ingestion'
            when coalesce(v_reason_code, '') in ('DUPLICATE_BUCKETS','MISALIGNED_BUCKETS') then 'reclaim_stale_jobs'
            else 'trigger_recompute'
          end
        );

        v_rows := v_rows || jsonb_build_array(v_row);
      exception
        when others then
          v_rows := v_rows || jsonb_build_array(jsonb_build_object(
            'indicator_key', r.indicator_key,
            'domain', r.domain,
            'pair', v_pair,
            'status', 'FAIL',
            'traffic_light', 'RED',
            'reason_code', 'QUERY_ERROR',
            'reason_detail', sqlerrm,
            'latest_ts', null,
            'lag_seconds', null,
            'slo_seconds', r.freshness_slo_seconds,
            'expected_bucket_time', null,
            'observed_bucket_time', null,
            'missing_count', 0,
            'gap_count', 0,
            'duplicate_count', 0,
            'misaligned_count', 0,
            'dependency_snapshot', jsonb_build_object(),
            'remediation_class', 'reclaim_stale_jobs'
          ));
      end;
    end loop;
  end loop;

  select jsonb_build_object(
    'total_checks', count(*),
    'passed_checks', count(*) filter (where (x->>'status') = 'PASS'),
    'warn_checks', count(*) filter (where (x->>'status') = 'WARN'),
    'failed_checks', count(*) filter (where (x->>'status') = 'FAIL'),
    'overall_status', case
      when count(*) filter (where (x->>'status') = 'FAIL') > 0 then 'FAIL'
      when count(*) filter (where (x->>'status') = 'WARN') > 0 then 'WARN'
      else 'PASS'
    end,
    'traffic_light', case
      when count(*) filter (where (x->>'status') = 'FAIL') > 0 then 'RED'
      when count(*) filter (where (x->>'status') = 'WARN') > 0 then 'YELLOW'
      else 'GREEN'
    end
  )
  into v_summary
  from jsonb_array_elements(v_rows) x;

  return jsonb_build_object(
    'generated_at_utc', to_char(v_now, 'YYYY-MM-DD"T"HH24:MI:SS"Z"'),
    'summary', v_summary,
    'rows', v_rows
  );
end;
$$;

create or replace function ops.fn_indicator_master_health_failures(
  p_pairs text[] default array['BTC-USD','ETH-USD','SOL-USD'],
  p_lookback interval default interval '24 hours'
)
returns jsonb
language sql
as $$
  select coalesce(
    (
      select jsonb_agg(x)
      from jsonb_array_elements((ops.fn_indicator_master_health_snapshot(p_pairs, p_lookback)->'rows')) x
      where (x->>'status') <> 'PASS'
    ),
    '[]'::jsonb
  );
$$;

create table if not exists ops.indicator_latency_slo_config (
  timeframe text primary key,
  p95_target_seconds integer not null,
  p99_target_seconds integer not null,
  hard_fail_seconds integer not null,
  enabled boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

insert into ops.indicator_latency_slo_config (timeframe, p95_target_seconds, p99_target_seconds, hard_fail_seconds, enabled)
values
  ('1m', 15, 30, 300, true),
  ('5m', 30, 60, 300, true),
  ('10m', 45, 90, 300, true),
  ('15m', 45, 90, 300, true),
  ('30m', 90, 180, 300, true),
  ('45m', 90, 180, 300, true),
  ('1h', 90, 180, 300, true),
  ('2h', 90, 180, 300, true),
  ('6h', 90, 180, 300, true),
  ('12h', 90, 180, 300, true)
on conflict (timeframe) do update
set
  p95_target_seconds = excluded.p95_target_seconds,
  p99_target_seconds = excluded.p99_target_seconds,
  hard_fail_seconds = excluded.hard_fail_seconds,
  enabled = excluded.enabled,
  updated_at = now();

create table if not exists ops.indicator_latency_log (
  id bigserial primary key,
  snapshot_at timestamptz not null default now(),
  pair text not null,
  timeframe text not null,
  config_id text not null,
  samples integer not null,
  p50_latency_seconds double precision not null,
  p95_latency_seconds double precision not null,
  p99_latency_seconds double precision not null,
  max_latency_seconds double precision not null,
  target_p95_seconds integer not null,
  target_p99_seconds integer not null,
  hard_fail_seconds integer not null,
  status text not null,
  reason_code text not null,
  reason_detail text not null,
  meta jsonb not null default '{}'::jsonb
);

create index if not exists idx_indicator_latency_log_snapshot
  on ops.indicator_latency_log (snapshot_at desc, timeframe, pair, config_id);

create or replace function ops.fn_indicator_compute_latency_snapshot(
  p_pairs text[] default array['BTC-USD','ETH-USD','SOL-USD'],
  p_lookback interval default interval '24 hours'
)
returns jsonb
language plpgsql
as $$
declare
  v_now timestamptz := now() at time zone 'utc';
  v_rows jsonb := '[]'::jsonb;
  v_summary jsonb;
begin
  with cfg as (
    select timeframe, p95_target_seconds, p99_target_seconds, hard_fail_seconds
    from ops.indicator_latency_slo_config
    where enabled
  ),
  queue_state as (
    select
      count(*) filter (where status='pending')::int as pending_count,
      count(*) filter (where status='running' and started_at < (now() at time zone 'utc') - interval '10 minutes')::int as stale_running
    from indicators.job_queue
  ),
  base as (
    select
      iv.pair,
      ic.timeframe,
      iv.config_id,
      greatest(
        0,
        extract(
          epoch from (
            iv.created_at - (
              iv.bucket_time + interval '1 second' * ops.fn_timeframe_to_seconds(ic.timeframe)
            )
          )
        )
      )::double precision as latency_seconds
    from indicators.indicator_values iv
    join indicators.indicator_configs ic
      on ic.config_id = iv.config_id
    where iv.pair = any(p_pairs)
      and iv.bucket_time >= v_now - p_lookback
  ),
  agg as (
    select
      b.pair,
      b.timeframe,
      b.config_id,
      count(*)::int as samples,
      percentile_cont(0.5) within group (order by b.latency_seconds)::double precision as p50_latency_seconds,
      percentile_cont(0.95) within group (order by b.latency_seconds)::double precision as p95_latency_seconds,
      percentile_cont(0.99) within group (order by b.latency_seconds)::double precision as p99_latency_seconds,
      max(b.latency_seconds)::double precision as max_latency_seconds
    from base b
    group by b.pair, b.timeframe, b.config_id
  ),
  scored as (
    select
      a.pair,
      a.timeframe,
      a.config_id,
      a.samples,
      a.p50_latency_seconds,
      a.p95_latency_seconds,
      a.p99_latency_seconds,
      a.max_latency_seconds,
      c.p95_target_seconds as target_p95_seconds,
      c.p99_target_seconds as target_p99_seconds,
      c.hard_fail_seconds,
      q.pending_count,
      q.stale_running,
      case a.timeframe
        when '1m' then extract(epoch from (v_now - (select max(bucket_time) from indicators.ohlcv_1m o where o.pair = a.pair)))::int
        when '5m' then extract(epoch from (v_now - (select max(bucket_time) from indicators.ohlcv_5m o where o.pair = a.pair)))::int
        when '10m' then extract(epoch from (v_now - (select max(bucket_time) from indicators.ohlcv_10m o where o.pair = a.pair)))::int
        when '15m' then extract(epoch from (v_now - (select max(bucket_time) from indicators.ohlcv_15m o where o.pair = a.pair)))::int
        when '30m' then extract(epoch from (v_now - (select max(bucket_time) from indicators.ohlcv_30m o where o.pair = a.pair)))::int
        when '45m' then extract(epoch from (v_now - (select max(bucket_time) from indicators.ohlcv_45m o where o.pair = a.pair)))::int
        when '1h' then extract(epoch from (v_now - (select max(bucket_time) from indicators.ohlcv_1h o where o.pair = a.pair)))::int
        when '2h' then extract(epoch from (v_now - (select max(bucket_time) from indicators.ohlcv_2h o where o.pair = a.pair)))::int
        when '6h' then extract(epoch from (v_now - (select max(bucket_time) from indicators.ohlcv_6h o where o.pair = a.pair)))::int
        when '12h' then extract(epoch from (v_now - (select max(bucket_time) from indicators.ohlcv_12h o where o.pair = a.pair)))::int
        else null
      end as upstream_lag_seconds
    from agg a
    join cfg c on c.timeframe = a.timeframe
    cross join queue_state q
  ),
  classified as (
    select
      s.*,
      case
        when s.samples < 20 then 'WARN'
        when s.p99_latency_seconds > s.hard_fail_seconds then 'FAIL'
        when s.p99_latency_seconds > s.target_p99_seconds then 'WARN'
        when s.p95_latency_seconds > s.target_p95_seconds then 'WARN'
        else 'PASS'
      end as status,
      case
        when s.samples < 20 then 'INSUFFICIENT_SAMPLES'
        when s.p99_latency_seconds > s.hard_fail_seconds and s.stale_running > 0 then 'WORKER_STALL'
        when s.p99_latency_seconds > s.hard_fail_seconds and s.pending_count > 0 then 'QUEUE_BACKLOG_PRESSURE'
        when s.p99_latency_seconds > s.hard_fail_seconds and coalesce(s.upstream_lag_seconds,0) > ops.fn_timeframe_to_seconds(s.timeframe) * 2 then 'UPSTREAM_CLOSE_DELAY'
        when s.p99_latency_seconds > s.hard_fail_seconds then 'LATENCY_HARD_FAIL'
        when s.p99_latency_seconds > s.target_p99_seconds then 'LATENCY_P99_BREACH'
        when s.p95_latency_seconds > s.target_p95_seconds then 'LATENCY_P95_BREACH'
        else 'NONE'
      end as reason_code,
      case
        when s.samples < 20 then 'insufficient samples in lookback window'
        when s.p99_latency_seconds > s.hard_fail_seconds and s.stale_running > 0 then 'stale running jobs observed in queue'
        when s.p99_latency_seconds > s.hard_fail_seconds and s.pending_count > 0 then 'pending queue backlog observed'
        when s.p99_latency_seconds > s.hard_fail_seconds and coalesce(s.upstream_lag_seconds,0) > ops.fn_timeframe_to_seconds(s.timeframe) * 2 then 'upstream close delay detected'
        when s.p99_latency_seconds > s.hard_fail_seconds then 'p99 latency above hard fail threshold'
        when s.p99_latency_seconds > s.target_p99_seconds then 'p99 latency above target'
        when s.p95_latency_seconds > s.target_p95_seconds then 'p95 latency above target'
        else 'within latency targets'
      end as reason_detail
    from scored s
  )
  select coalesce(jsonb_agg(jsonb_build_object(
    'pair', c.pair,
    'timeframe', c.timeframe,
    'config_id', c.config_id,
    'samples', c.samples,
    'p50_latency_seconds', c.p50_latency_seconds,
    'p95_latency_seconds', c.p95_latency_seconds,
    'p99_latency_seconds', c.p99_latency_seconds,
    'max_latency_seconds', c.max_latency_seconds,
    'target_p95_seconds', c.target_p95_seconds,
    'target_p99_seconds', c.target_p99_seconds,
    'hard_fail_seconds', c.hard_fail_seconds,
    'status', c.status,
    'reason_code', c.reason_code,
    'reason_detail', c.reason_detail,
    'queue_pending', c.pending_count,
    'queue_stale_running', c.stale_running,
    'upstream_lag_seconds', c.upstream_lag_seconds,
    'traffic_light', case when c.status='PASS' then 'GREEN' when c.status='WARN' then 'YELLOW' else 'RED' end
  )), '[]'::jsonb)
  into v_rows
  from classified c;

  select jsonb_build_object(
    'total_checks', count(*),
    'passed_checks', count(*) filter (where (x->>'status')='PASS'),
    'warn_checks', count(*) filter (where (x->>'status')='WARN'),
    'failed_checks', count(*) filter (where (x->>'status')='FAIL'),
    'overall_status', case
      when count(*) filter (where (x->>'status')='FAIL') > 0 then 'FAIL'
      when count(*) filter (where (x->>'status')='WARN') > 0 then 'WARN'
      else 'PASS'
    end,
    'traffic_light', case
      when count(*) filter (where (x->>'status')='FAIL') > 0 then 'RED'
      when count(*) filter (where (x->>'status')='WARN') > 0 then 'YELLOW'
      else 'GREEN'
    end
  )
  into v_summary
  from jsonb_array_elements(v_rows) x;

  return jsonb_build_object(
    'generated_at_utc', to_char(v_now, 'YYYY-MM-DD"T"HH24:MI:SS"Z"'),
    'window', jsonb_build_object('type', 'interval', 'value', p_lookback::text),
    'summary', v_summary,
    'rows', v_rows
  );
exception
  when others then
    return jsonb_build_object(
      'generated_at_utc', to_char(v_now, 'YYYY-MM-DD"T"HH24:MI:SS"Z"'),
      'window', jsonb_build_object('type', 'interval', 'value', p_lookback::text),
      'summary', jsonb_build_object(
        'total_checks', 1,
        'passed_checks', 0,
        'warn_checks', 0,
        'failed_checks', 1,
        'overall_status', 'FAIL',
        'traffic_light', 'RED'
      ),
      'rows', jsonb_build_array(jsonb_build_object(
        'pair', 'ALL',
        'timeframe', 'ALL',
        'config_id', 'ALL',
        'samples', 0,
        'p50_latency_seconds', 0,
        'p95_latency_seconds', 0,
        'p99_latency_seconds', 0,
        'max_latency_seconds', 0,
        'target_p95_seconds', 0,
        'target_p99_seconds', 0,
        'hard_fail_seconds', 0,
        'status', 'FAIL',
        'reason_code', 'QUERY_ERROR',
        'reason_detail', sqlerrm,
        'traffic_light', 'RED'
      ))
    );
end;
$$;

create or replace function ops.fn_indicator_latency_watchdog(
  p_pairs text[] default array['BTC-USD','ETH-USD','SOL-USD'],
  p_lookback interval default interval '24 hours'
)
returns jsonb
language plpgsql
as $$
declare
  v_report jsonb;
  v_inserted integer := 0;
begin
  v_report := ops.fn_indicator_compute_latency_snapshot(p_pairs, p_lookback);

  insert into ops.indicator_latency_log (
    pair, timeframe, config_id, samples,
    p50_latency_seconds, p95_latency_seconds, p99_latency_seconds, max_latency_seconds,
    target_p95_seconds, target_p99_seconds, hard_fail_seconds,
    status, reason_code, reason_detail, meta
  )
  select
    x->>'pair',
    x->>'timeframe',
    x->>'config_id',
    coalesce((x->>'samples')::int, 0),
    coalesce((x->>'p50_latency_seconds')::double precision, 0),
    coalesce((x->>'p95_latency_seconds')::double precision, 0),
    coalesce((x->>'p99_latency_seconds')::double precision, 0),
    coalesce((x->>'max_latency_seconds')::double precision, 0),
    coalesce((x->>'target_p95_seconds')::int, 0),
    coalesce((x->>'target_p99_seconds')::int, 0),
    coalesce((x->>'hard_fail_seconds')::int, 0),
    coalesce(x->>'status', 'FAIL'),
    coalesce(x->>'reason_code', 'QUERY_ERROR'),
    coalesce(x->>'reason_detail', 'unknown'),
    jsonb_build_object(
      'queue_pending', x->>'queue_pending',
      'queue_stale_running', x->>'queue_stale_running',
      'upstream_lag_seconds', x->>'upstream_lag_seconds'
    )
  from jsonb_array_elements(v_report->'rows') x;

  get diagnostics v_inserted = row_count;

  return jsonb_build_object(
    'inserted_rows', v_inserted,
    'summary', v_report->'summary',
    'report', v_report
  );
end;
$$;

select ops.fn_sync_master_indicator_registry();
