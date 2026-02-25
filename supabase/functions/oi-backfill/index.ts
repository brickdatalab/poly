import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

type PairConfig = {
  symbol: "BTC" | "ETH" | "SOL";
  pair: "BTC-USD" | "ETH-USD" | "SOL-USD";
  sourceInstrument: "BTC-USDT-SWAP" | "ETH-USDT-SWAP" | "SOL-USDT-SWAP";
};

type OkxEnvelope<T> = {
  code: string;
  msg: string;
  data: T[];
};

type OkxHistoryRow = [string, string, string, string];

type OIHistRow = {
  timestampMs: number;
  oi: number;
  oiUsd: number | null;
};

type CandlePoint = {
  bucketTime: string;
  close: number;
  volume: number;
  prevClose: number | null;
};

const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const SUPABASE_SERVICE_ROLE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
const OKX_BASE = "https://www.okx.com";

const PAIRS: PairConfig[] = [
  { symbol: "BTC", pair: "BTC-USD", sourceInstrument: "BTC-USDT-SWAP" },
  { symbol: "ETH", pair: "ETH-USD", sourceInstrument: "ETH-USDT-SWAP" },
  { symbol: "SOL", pair: "SOL-USD", sourceInstrument: "SOL-USDT-SWAP" },
];

function jsonResponse(status: number, body: Record<string, unknown>): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function floorTo15m(value: Date): Date {
  const out = new Date(value.getTime());
  out.setUTCSeconds(0, 0);
  out.setUTCMinutes(Math.floor(out.getUTCMinutes() / 15) * 15);
  return out;
}

function parseNumber(value: unknown): number | null {
  if (value === null || value === undefined) {
    return null;
  }
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

function requestedPairs(payloadSymbols: unknown): PairConfig[] {
  if (!Array.isArray(payloadSymbols) || payloadSymbols.length === 0) {
    return PAIRS;
  }
  const normalized = new Set(
    payloadSymbols.map((x) => String(x).trim().toUpperCase()),
  );
  const selected = PAIRS.filter((p) =>
    normalized.has(p.pair) || normalized.has(p.symbol) ||
    normalized.has(p.sourceInstrument)
  );
  return selected.length > 0 ? selected : PAIRS;
}

function parseRange(body: Record<string, unknown>): { start: Date; end: Date } {
  const now = new Date();
  const defaultEnd = floorTo15m(now);
  const defaultStart = new Date(defaultEnd.getTime() - (48 * 60 * 60 * 1000));

  const startRaw = body.start ? new Date(String(body.start)) : defaultStart;
  const endRaw = body.end ? new Date(String(body.end)) : defaultEnd;
  if (Number.isNaN(startRaw.getTime()) || Number.isNaN(endRaw.getTime())) {
    throw new Error("Invalid start/end timestamp");
  }
  const start = floorTo15m(startRaw);
  const end = floorTo15m(endRaw);
  if (end < start) {
    throw new Error("end must be >= start");
  }
  return { start, end };
}

async function fetchJson<T>(url: string): Promise<T> {
  const response = await fetch(url, { method: "GET" });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`OKX request failed (${response.status}): ${body}`);
  }
  return await response.json() as T;
}

function parseOkxHistoryRow(raw: OkxHistoryRow): OIHistRow | null {
  if (!Array.isArray(raw) || raw.length < 4) {
    return null;
  }
  const ts = parseNumber(raw[0]);
  const oi = parseNumber(raw[1]);
  const oiUsd = parseNumber(raw[3]);
  if (ts === null || oi === null) {
    return null;
  }
  return {
    timestampMs: ts,
    oi,
    oiUsd,
  };
}

async function fetchOpenInterestHistory(
  sourceInstrument: string,
  start: Date,
  end: Date,
): Promise<Map<string, OIHistRow>> {
  const startMs = start.getTime();
  const endMs = end.getTime();
  let cursorEnd = endMs;
  let page = 0;
  const byBucket = new Map<string, OIHistRow>();

  while (page < 200) {
    const url =
      `${OKX_BASE}/api/v5/rubik/stat/contracts/open-interest-history?instId=${sourceInstrument}&period=15m&end=${cursorEnd}`;
    const envelope = await fetchJson<OkxEnvelope<OkxHistoryRow>>(url);
    if (envelope.code !== "0" || !Array.isArray(envelope.data) || envelope.data.length === 0) {
      break;
    }

    let oldestTs = Number.MAX_SAFE_INTEGER;
    for (const raw of envelope.data) {
      const row = parseOkxHistoryRow(raw);
      if (!row) {
        continue;
      }
      const ts = row.timestampMs;
      if (ts < oldestTs) {
        oldestTs = ts;
      }
      if (ts < startMs || ts > endMs) {
        continue;
      }
      const bucketIso = floorTo15m(new Date(ts)).toISOString();
      byBucket.set(bucketIso, row);
    }

    if (oldestTs === Number.MAX_SAFE_INTEGER || oldestTs <= startMs || oldestTs >= cursorEnd) {
      break;
    }
    cursorEnd = oldestTs - 1;
    page += 1;
  }

  return byBucket;
}

async function loadCandles(
  supabase: ReturnType<typeof createClient>,
  pair: string,
  startIso: string,
  endIso: string,
): Promise<Map<string, CandlePoint>> {
  const { data: prevRows, error: prevErr } = await supabase
    .from("ohlcv_15m")
    .select("bucket_time,close")
    .eq("pair", pair)
    .lt("bucket_time", startIso)
    .order("bucket_time", { ascending: false })
    .limit(1);
  if (prevErr) {
    throw new Error(`ohlcv_15m previous candle lookup failed for ${pair}: ${prevErr.message}`);
  }

  const { data: rows, error } = await supabase
    .from("ohlcv_15m")
    .select("bucket_time,close,volume")
    .eq("pair", pair)
    .gte("bucket_time", startIso)
    .lte("bucket_time", endIso)
    .order("bucket_time", { ascending: true });
  if (error) {
    throw new Error(`ohlcv_15m range lookup failed for ${pair}: ${error.message}`);
  }

  const out = new Map<string, CandlePoint>();
  let prevClose = prevRows && prevRows.length > 0
    ? parseNumber(prevRows[0].close)
    : null;

  for (const raw of rows ?? []) {
    const bucketIso = new Date(String(raw.bucket_time)).toISOString();
    const close = parseNumber(raw.close) ?? 0;
    const volume = parseNumber(raw.volume) ?? 0;
    out.set(bucketIso, {
      bucketTime: bucketIso,
      close,
      volume,
      prevClose,
    });
    prevClose = close;
  }
  return out;
}

async function loadPreviousOi(
  supabase: ReturnType<typeof createClient>,
  symbol: string,
  startIso: string,
): Promise<number | null> {
  const { data, error } = await supabase
    .from("open_interest")
    .select("open_interest")
    .eq("symbol", symbol)
    .lt("bucket_time", startIso)
    .order("bucket_time", { ascending: false })
    .limit(1);
  if (error) {
    throw new Error(`open_interest previous lookup failed for ${symbol}: ${error.message}`);
  }
  if (!data || data.length === 0) {
    return null;
  }
  return parseNumber(data[0].open_interest);
}

async function upsertBackfillRows(
  supabase: ReturnType<typeof createClient>,
  pair: PairConfig,
  start: Date,
  end: Date,
): Promise<{ inserted: number; skippedNoCandle: number; skippedNoOi: number; buckets: number }> {
  const startIso = start.toISOString();
  const endIso = end.toISOString();

  const historyByBucket = await fetchOpenInterestHistory(pair.sourceInstrument, start, end);
  const candlesByBucket = await loadCandles(supabase, pair.pair, startIso, endIso);
  let previousOi = await loadPreviousOi(supabase, pair.symbol, startIso);

  const bucketKeys = [...historyByBucket.keys()].sort();
  const touchedBuckets = new Set<string>();
  let inserted = 0;
  let skippedNoCandle = 0;
  let skippedNoOi = 0;

  for (const bucketIso of bucketKeys) {
    const oiRow = historyByBucket.get(bucketIso);
    if (!oiRow) {
      continue;
    }

    const candle = candlesByBucket.get(bucketIso);
    if (!candle) {
      skippedNoCandle += 1;
      continue;
    }

    const oiValue = oiRow.oi;

    const prevOiSafe = previousOi ?? oiValue;
    const oiChange = oiValue - prevOiSafe;
    const oiChangePct = prevOiSafe !== 0 ? (oiChange / prevOiSafe) : 0;
    const prevClose = candle.prevClose ?? candle.close;
    const priceChangePct = prevClose !== 0 ? (candle.close - prevClose) / prevClose : 0;
    const oiVolumeRatio = candle.volume > 0 ? oiValue / candle.volume : 0;
    const weakRally = priceChangePct > 0 && oiChange < 0 ? 1 : 0;
    const weakSelloff = priceChangePct < 0 && oiChange > 0 ? 1 : 0;
    const oiDivergence = weakRally === 1 || weakSelloff === 1 ? 1 : 0;
    const sourceTimeIso = new Date(oiRow.timestampMs).toISOString();

    const row = {
      symbol: pair.symbol,
      pair: pair.pair,
      binance_symbol: pair.sourceInstrument,
      bucket_time: bucketIso,
      open_interest: oiValue,
      oi_change: oiChange,
      oi_change_pct: oiChangePct,
      close_price: candle.close,
      volume: candle.volume,
      price_change_pct: priceChangePct,
      oi_volume_ratio: oiVolumeRatio,
      oi_divergence: oiDivergence,
      weak_rally: weakRally,
      weak_selloff: weakSelloff,
      source_time: sourceTimeIso,
      ingested_at: new Date().toISOString(),
      mark_price: null,
      open_interest_notional: oiRow.oiUsd,
      funding_rate: null,
      funding_rate_8h_avg: null,
      funding_next_time: null,
      funding_source_time: null,
    };

    const { error: upsertError } = await supabase
      .from("open_interest")
      .upsert(row, { onConflict: "symbol,bucket_time" });
    if (upsertError) {
      throw new Error(
        `open_interest upsert failed for ${pair.pair} @ ${bucketIso}: ${upsertError.message}`,
      );
    }

    previousOi = oiValue;
    inserted += 1;
    touchedBuckets.add(bucketIso);
  }

  for (const bucketIso of [...touchedBuckets].sort()) {
    const { error: featureError } = await supabase.rpc("fn_compute_oi_features_for_bucket", {
      p_bucket_time: bucketIso,
    });
    if (featureError) {
      throw new Error(`oi_features compute failed for ${bucketIso}: ${featureError.message}`);
    }
  }

  return {
    inserted,
    skippedNoCandle,
    skippedNoOi,
    buckets: touchedBuckets.size,
  };
}

Deno.serve(async (req: Request) => {
  if (req.method !== "POST") {
    return jsonResponse(405, { error: "Method not allowed" });
  }

  const supabase = createClient(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, {
    db: { schema: "indicators" },
  });

  let payload: Record<string, unknown> = {};
  try {
    const text = await req.text();
    if (text.trim() !== "") {
      payload = JSON.parse(text) as Record<string, unknown>;
    }
  } catch {
    return jsonResponse(400, { error: "Invalid JSON body" });
  }

  let start: Date;
  let end: Date;
  try {
    ({ start, end } = parseRange(payload));
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return jsonResponse(400, { error: message });
  }

  const pairs = requestedPairs(payload.symbols);
  const results: Array<Record<string, unknown>> = [];
  let totalInserted = 0;
  let totalNoCandle = 0;
  let totalNoOi = 0;
  let totalBuckets = 0;

  for (const pair of pairs) {
    try {
      const out = await upsertBackfillRows(supabase, pair, start, end);
      totalInserted += out.inserted;
      totalNoCandle += out.skippedNoCandle;
      totalNoOi += out.skippedNoOi;
      totalBuckets += out.buckets;
      results.push({
        pair: pair.pair,
        symbol: pair.symbol,
        inserted_rows: out.inserted,
        buckets_touched: out.buckets,
        skipped_missing_candle: out.skippedNoCandle,
        skipped_invalid_oi: out.skippedNoOi,
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      results.push({
        pair: pair.pair,
        symbol: pair.symbol,
        status: "error",
        error: message,
      });
    }
  }

  const errors = results.filter((r) => r.status === "error").length;
  const status = errors > 0 ? 500 : 200;
  return jsonResponse(status, {
    ok: errors === 0,
    start: start.toISOString(),
    end: end.toISOString(),
    inserted_rows: totalInserted,
    buckets_touched: totalBuckets,
    skipped_missing_candle: totalNoCandle,
    skipped_invalid_oi: totalNoOi,
    errors,
    results,
  });
});
