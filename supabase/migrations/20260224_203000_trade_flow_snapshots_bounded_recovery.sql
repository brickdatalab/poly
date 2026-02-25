-- Trade flow snapshots: bounded recovery + runtime hardening
-- - Keeps ingestion path unchanged (raw_trades producer remains external/GCP)
-- - Replaces unbounded catch-up logic with chunked, idempotent upsert windows

begin;

create or replace function public.fn_upsert_trade_flow_snapshots_window(
    p_start timestamptz,
    p_end timestamptz
) returns bigint
language plpgsql
as $$
declare
    v_start timestamptz;
    v_end timestamptz;
    v_rows bigint := 0;
begin
    if p_start is null or p_end is null then
        raise exception 'p_start and p_end are required';
    end if;

    v_start := date_trunc('minute', p_start);
    v_end := date_trunc('minute', p_end);

    if v_start >= v_end then
        return 0;
    end if;

    with
    pairs as (
        select unnest(array['BTC-USD','ETH-USD','SOL-USD'])::text as pair
    ),
    minutes as (
        select generate_series(v_start, v_end - interval '1 minute', interval '1 minute') as snapshot_time
    ),
    grid as (
        select p.pair, m.snapshot_time
        from pairs p
        cross join minutes m
    ),
    anchor as (
        select
            p.pair,
            coalesce((
                select s.cvd_cumulative
                from public.trade_flow_snapshots s
                where s.pair = p.pair
                  and s.snapshot_time < v_start
                order by s.snapshot_time desc
                limit 1
            ), 0::numeric) as cvd_anchor
        from pairs p
    ),
    calc as (
        select
            g.pair,
            g.snapshot_time,
            lp.current_price,
            a5.buy_volume,
            a5.sell_volume,
            case
                when a5.sell_volume > 0 then round(a5.buy_volume / a5.sell_volume, 4)
                else 0::numeric
            end as trade_flow_ratio,
            a5.cvd_value,
            case
                when (a5.buy_volume + a5.sell_volume) > 0
                    then round((a5.buy_volume - a5.sell_volume) / nullif((a5.buy_volume + a5.sell_volume), 0), 6)
                else 0::numeric
            end as trade_flow_imbalance,
            a1.buy_volume_1m,
            a1.sell_volume_1m,
            a1.cvd_delta_1m
        from grid g
        left join lateral (
            select rt.price::numeric as current_price
            from public.raw_trades rt
            where rt.pair = g.pair
              and rt.executed_at < g.snapshot_time
            order by rt.executed_at desc
            limit 1
        ) lp on true
        left join lateral (
            select
                coalesce(sum(case when rt.side = 'BUY' then rt.size else 0::numeric end), 0::numeric)::numeric as buy_volume,
                coalesce(sum(case when rt.side = 'SELL' then rt.size else 0::numeric end), 0::numeric)::numeric as sell_volume,
                coalesce(sum(case when rt.side = 'BUY' then rt.size else -rt.size end), 0::numeric)::numeric as cvd_value
            from public.raw_trades rt
            where rt.pair = g.pair
              and rt.executed_at >= g.snapshot_time - interval '5 minutes'
              and rt.executed_at < g.snapshot_time
        ) a5 on true
        left join lateral (
            select
                coalesce(sum(case when rt.side = 'BUY' then rt.size else 0::numeric end), 0::numeric)::numeric as buy_volume_1m,
                coalesce(sum(case when rt.side = 'SELL' then rt.size else 0::numeric end), 0::numeric)::numeric as sell_volume_1m,
                coalesce(sum(case when rt.side = 'BUY' then rt.size else -rt.size end), 0::numeric)::numeric as cvd_delta_1m
            from public.raw_trades rt
            where rt.pair = g.pair
              and rt.executed_at >= g.snapshot_time - interval '1 minute'
              and rt.executed_at < g.snapshot_time
        ) a1 on true
    ),
    with_cumulative as (
        select
            c.pair,
            c.snapshot_time,
            c.current_price,
            c.buy_volume,
            c.sell_volume,
            c.trade_flow_ratio,
            c.cvd_value,
            c.trade_flow_imbalance,
            c.buy_volume_1m,
            c.sell_volume_1m,
            c.cvd_delta_1m,
            a.cvd_anchor
              + sum(c.cvd_delta_1m) over (
                    partition by c.pair
                    order by c.snapshot_time
                    rows between unbounded preceding and current row
                ) as cvd_cumulative
        from calc c
        join anchor a on a.pair = c.pair
    )
    insert into public.trade_flow_snapshots (
        pair,
        snapshot_time,
        current_price,
        buy_volume,
        sell_volume,
        trade_flow_ratio,
        cvd_value,
        trade_flow_imbalance,
        buy_volume_1m,
        sell_volume_1m,
        cvd_delta_1m,
        cvd_cumulative
    )
    select
        pair,
        snapshot_time,
        current_price,
        buy_volume,
        sell_volume,
        trade_flow_ratio,
        cvd_value,
        trade_flow_imbalance,
        buy_volume_1m,
        sell_volume_1m,
        cvd_delta_1m,
        cvd_cumulative
    from with_cumulative
    on conflict (pair, snapshot_time) do update set
        current_price = excluded.current_price,
        buy_volume = excluded.buy_volume,
        sell_volume = excluded.sell_volume,
        trade_flow_ratio = excluded.trade_flow_ratio,
        cvd_value = excluded.cvd_value,
        trade_flow_imbalance = excluded.trade_flow_imbalance,
        buy_volume_1m = excluded.buy_volume_1m,
        sell_volume_1m = excluded.sell_volume_1m,
        cvd_delta_1m = excluded.cvd_delta_1m,
        cvd_cumulative = excluded.cvd_cumulative;

    get diagnostics v_rows = row_count;
    return coalesce(v_rows, 0);
end;
$$;

comment on function public.fn_upsert_trade_flow_snapshots_window(timestamptz, timestamptz) is
'Upserts trade_flow_snapshots in [start,end) minute window from raw_trades with deterministic cumulative CVD.';


create or replace function public.fn_backfill_trade_flow_snapshots(
    p_start timestamptz,
    p_end timestamptz,
    p_chunk_minutes integer default 120
) returns jsonb
language plpgsql
as $$
declare
    v_cursor timestamptz;
    v_end timestamptz;
    v_next timestamptz;
    v_rows bigint;
    v_total_rows bigint := 0;
    v_windows integer := 0;
    v_chunk integer := greatest(coalesce(p_chunk_minutes, 120), 1);
begin
    if p_start is null or p_end is null then
        raise exception 'p_start and p_end are required';
    end if;

    v_cursor := date_trunc('minute', p_start);
    v_end := date_trunc('minute', p_end);

    if v_cursor >= v_end then
        return jsonb_build_object(
            'ok', true,
            'windows', 0,
            'rows_upserted', 0,
            'start', v_cursor,
            'end', v_end
        );
    end if;

    while v_cursor < v_end loop
        v_next := least(v_cursor + make_interval(mins => v_chunk), v_end);
        v_rows := public.fn_upsert_trade_flow_snapshots_window(v_cursor, v_next);
        v_total_rows := v_total_rows + coalesce(v_rows, 0);
        v_windows := v_windows + 1;
        v_cursor := v_next;
    end loop;

    return jsonb_build_object(
        'ok', true,
        'windows', v_windows,
        'rows_upserted', v_total_rows,
        'start', date_trunc('minute', p_start),
        'end', date_trunc('minute', p_end),
        'chunk_minutes', v_chunk
    );
end;
$$;

comment on function public.fn_backfill_trade_flow_snapshots(timestamptz, timestamptz, integer) is
'Chunked backfill wrapper for trade_flow_snapshots; runs deterministic window upserts.';


create or replace function public.capture_trade_flow_snapshots_tick(
    p_as_of timestamptz default date_trunc('minute', now()),
    p_max_catchup_minutes integer default 15
) returns jsonb
language plpgsql
as $$
declare
    v_as_of timestamptz := date_trunc('minute', coalesce(p_as_of, now()));
    v_max integer := greatest(coalesce(p_max_catchup_minutes, 15), 1);
    v_start timestamptz;
    v_end_exclusive timestamptz;
    v_rows bigint := 0;
begin
    with pairs as (
        select unnest(array['BTC-USD','ETH-USD','SOL-USD'])::text as pair
    ),
    latest as (
        select p.pair, max(s.snapshot_time) as last_snapshot
        from pairs p
        left join public.trade_flow_snapshots s
          on s.pair = p.pair
         and s.snapshot_time <= v_as_of
        group by p.pair
    )
    select min(
        coalesce(
            last_snapshot + interval '1 minute',
            v_as_of - make_interval(mins => v_max)
        )
    )
    into v_start
    from latest;

    if v_start is null then
        v_start := v_as_of - make_interval(mins => v_max);
    end if;

    v_start := date_trunc('minute', v_start);
    v_end_exclusive := least(v_start + make_interval(mins => v_max), v_as_of + interval '1 minute');

    if v_start >= v_end_exclusive then
        return jsonb_build_object(
            'ok', true,
            'rows_upserted', 0,
            'start', v_start,
            'end_exclusive', v_end_exclusive,
            'as_of', v_as_of
        );
    end if;

    v_rows := public.fn_upsert_trade_flow_snapshots_window(v_start, v_end_exclusive);

    return jsonb_build_object(
        'ok', true,
        'rows_upserted', coalesce(v_rows, 0),
        'start', v_start,
        'end_exclusive', v_end_exclusive,
        'as_of', v_as_of,
        'max_catchup_minutes', v_max
    );
end;
$$;

comment on function public.capture_trade_flow_snapshots_tick(timestamptz, integer) is
'Bounded minute tick for trade_flow_snapshots; catches up in fixed-size windows to prevent timeout loops.';


create or replace function public.capture_trade_flow_snapshots()
returns void
language plpgsql
as $$
begin
    perform public.capture_trade_flow_snapshots_tick();
end;
$$;


do $$
declare
    v_job_id bigint;
begin
    select jobid
      into v_job_id
      from cron.job
     where jobname = 'trade_flow_snapshots_every_minute'
     order by jobid
     limit 1;

    if v_job_id is not null then
        perform cron.unschedule(v_job_id);
    end if;

    perform cron.schedule(
        'trade_flow_snapshots_every_minute',
        '* * * * *',
        'select public.capture_trade_flow_snapshots_tick();'
    );
end;
$$;

commit;
