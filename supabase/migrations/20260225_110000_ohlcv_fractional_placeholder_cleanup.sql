-- Issue #3: OHLCV missing values remediation
-- Root cause repair: remove fractional-second placeholder rows introduced by prior continuity patching,
-- then run the existing bounded repair chain.

create or replace function ops.fn_cleanup_ohlcv_1m_fractional_placeholders(
  p_pairs text[] default array['BTC-USD','ETH-USD','SOL-USD'],
  p_start timestamptz default null,
  p_end timestamptz default null
)
returns jsonb
language plpgsql
as $$
declare
  v_deleted integer := 0;
  v_deleted_by_pair jsonb := '{}'::jsonb;
begin
  select
    coalesce(sum(x.cnt), 0)::integer,
    coalesce(jsonb_object_agg(x.pair, x.cnt), '{}'::jsonb)
  into v_deleted, v_deleted_by_pair
  from (
    select
      pair,
      count(*)::integer as cnt
    from indicators.ohlcv_1m
    where pair = any(p_pairs)
      and (p_start is null or bucket_time >= p_start)
      and (p_end is null or bucket_time <= p_end)
      and bucket_time <> date_trunc('minute', bucket_time)
      and coalesce(volume, 0) = 0
      and coalesce(trade_count, 0) = 0
    group by pair
  ) x;

  if v_deleted > 0 then
    delete from indicators.ohlcv_1m
    where pair = any(p_pairs)
      and (p_start is null or bucket_time >= p_start)
      and (p_end is null or bucket_time <= p_end)
      and bucket_time <> date_trunc('minute', bucket_time)
      and coalesce(volume, 0) = 0
      and coalesce(trade_count, 0) = 0;
  end if;

  return jsonb_build_object(
    'deleted_rows', v_deleted,
    'deleted_by_pair', v_deleted_by_pair,
    'window_start', p_start,
    'window_end', p_end
  );
end;
$$;

create or replace function ops.fn_repair_ohlcv_issue3(
  p_pairs text[] default array['BTC-USD','ETH-USD','SOL-USD'],
  p_start timestamptz default null,
  p_end timestamptz default null,
  p_backfill interval default interval '7 days'
)
returns jsonb
language plpgsql
as $$
declare
  v_cleanup jsonb := '{}'::jsonb;
  v_chain jsonb := '{}'::jsonb;
begin
  v_cleanup := ops.fn_cleanup_ohlcv_1m_fractional_placeholders(p_pairs, p_start, p_end);
  v_chain := ops.fn_repair_ohlcv_chain(p_pairs, p_start, p_end, p_backfill);

  return jsonb_build_object(
    'cleanup', v_cleanup,
    'repair_chain', v_chain,
    'continuity_rows_inserted', coalesce((v_chain->>'continuity_rows_inserted')::integer, 0),
    'backfill_rows', coalesce(v_chain->'backfill_rows', '[]'::jsonb)
  );
end;
$$;
