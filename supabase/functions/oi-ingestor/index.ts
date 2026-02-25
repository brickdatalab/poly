import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

type PairConfig = {
  symbol: "BTC" | "ETH" | "SOL";
  pair: "BTC-USD" | "ETH-USD" | "SOL-USD";
  sourceInstrument: "BTC-USDT-SWAP" | "ETH-USDT-SWAP" | "SOL-USDT-SWAP";
};

type CandleRow = {
  bucket_time: string;
  close: number;
  volume: number;
};

type OkxEnvelope<T> = {
  code: string;
  msg: string;
  data: T[];
};

type OkxOpenInterestTick = {
  instId: string;
  oi: string;
  oiCcy: string;
  oiUsd: string;
  ts: string;
};

type OkxFundingTick = {
  instId: string;
  fundingRate: string;
  nextFundingTime: string;
  ts: string;
};

type OkxMarkPriceTick = {
  instId: string;
  markPx: string;
  ts: string;
};

const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const SUPABASE_SERVICE_ROLE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
const OKX_BASE = "https://www.okx.com";

const PAIRS: PairConfig[] = [
  { symbol: "BTC", pair: "BTC-USD", sourceInstrument: "BTC-USDT-SWAP" },
  { symbol: "ETH", pair: "ETH-USD", sourceInstrument: "ETH-USDT-SWAP" },
  { symbol: "SOL", pair: "SOL-USD", sourceInstrument: "SOL-USDT-SWAP" },
];

function floorTo15m(value: Date): Date {
  const out = new Date(value.getTime());
  out.setUTCSeconds(0, 0);
  out.setUTCMinutes(Math.floor(out.getUTCMinutes() / 15) * 15);
  return out;
}

function jsonResponse(status: number, body: Record<string, unknown>): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function parseNumber(value: unknown): number | null {
  if (value === null || value === undefined) {
    return null;
  }
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

async function fetchJson<T>(url: string): Promise<T> {
  const response = await fetch(url, { method: "GET" });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`Binance request failed (${response.status}): ${body}`);
  }
  return await response.json() as T;
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

async function fetchCandleRows(
  supabase: ReturnType<typeof createClient>,
  pair: string,
  targetBucketIso: string,
): Promise<{ current: CandleRow | null; previous: CandleRow | null }> {
  const { data: currentRows, error: currentErr } = await supabase
    .from("ohlcv_15m")
    .select("bucket_time,close,volume")
    .eq("pair", pair)
    .lte("bucket_time", targetBucketIso)
    .order("bucket_time", { ascending: false })
    .limit(1);
  if (currentErr) {
    throw new Error(`ohlcv_15m lookup failed for ${pair}: ${currentErr.message}`);
  }
  const current = (currentRows?.[0] as CandleRow | undefined) ?? null;
  if (!current) {
    return { current: null, previous: null };
  }
  const currentBucketIso = new Date(String(current.bucket_time)).toISOString();

  const { data: prevRows, error: prevErr } = await supabase
    .from("ohlcv_15m")
    .select("bucket_time,close,volume")
    .eq("pair", pair)
    .lt("bucket_time", currentBucketIso)
    .order("bucket_time", { ascending: false })
    .limit(1);
  if (prevErr) {
    throw new Error(`ohlcv_15m prev lookup failed for ${pair}: ${prevErr.message}`);
  }

  return {
    current,
    previous: (prevRows?.[0] as CandleRow | undefined) ?? null,
  };
}

async function fetchPreviousOi(
  supabase: ReturnType<typeof createClient>,
  symbol: string,
  bucketIso: string,
): Promise<number | null> {
  const { data, error } = await supabase
    .from("open_interest")
    .select("open_interest")
    .eq("symbol", symbol)
    .lt("bucket_time", bucketIso)
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

function requireOkxData<T>(
  envelope: OkxEnvelope<T>,
  endpointLabel: string,
): T {
  if (envelope.code !== "0" || !Array.isArray(envelope.data) || envelope.data.length === 0) {
    throw new Error(`OKX ${endpointLabel} request failed: ${JSON.stringify(envelope)}`);
  }
  return envelope.data[0];
}

async function upsertOpenInterestTick(
  supabase: ReturnType<typeof createClient>,
  pair: PairConfig,
): Promise<{ bucketTime: string; status: "inserted" | "skipped"; reason?: string }> {
  const oiEnvelope = await fetchJson<OkxEnvelope<OkxOpenInterestTick>>(
    `${OKX_BASE}/api/v5/public/open-interest?instType=SWAP&instId=${pair.sourceInstrument}`,
  );
  const fundingEnvelope = await fetchJson<OkxEnvelope<OkxFundingTick>>(
    `${OKX_BASE}/api/v5/public/funding-rate?instId=${pair.sourceInstrument}`,
  );
  const markEnvelope = await fetchJson<OkxEnvelope<OkxMarkPriceTick>>(
    `${OKX_BASE}/api/v5/public/mark-price?instType=SWAP&instId=${pair.sourceInstrument}`,
  );

  const oi = requireOkxData(oiEnvelope, "open-interest");
  const funding = requireOkxData(fundingEnvelope, "funding-rate");
  const mark = requireOkxData(markEnvelope, "mark-price");

  const sourceTimeMs = Number(oi.ts);
  if (!Number.isFinite(sourceTimeMs)) {
    return { bucketTime: "", status: "skipped", reason: "invalid_source_timestamp" };
  }
  const sourceTime = new Date(sourceTimeMs);
  const targetBucketIso = floorTo15m(sourceTime).toISOString();
  const sourceTimeIso = sourceTime.toISOString();

  const candles = await fetchCandleRows(supabase, pair.pair, targetBucketIso);
  if (!candles.current) {
    return {
      bucketTime: targetBucketIso,
      status: "skipped",
      reason: "missing_ohlcv_15m_bucket",
    };
  }
  const bucketIso = new Date(String(candles.current.bucket_time)).toISOString();

  const oiValue = parseNumber(oi.oi);
  if (oiValue === null) {
    return {
      bucketTime: bucketIso,
      status: "skipped",
      reason: "invalid_open_interest",
    };
  }

  const prevOi = await fetchPreviousOi(supabase, pair.symbol, bucketIso);
  const prevOiSafe = prevOi ?? oiValue;
  const oiChange = oiValue - prevOiSafe;
  const oiChangePct = prevOiSafe !== 0 ? (oiChange / prevOiSafe) : 0;

  const closePrice = parseNumber(candles.current.close) ?? 0;
  const prevClose = candles.previous ? (parseNumber(candles.previous.close) ?? closePrice) : closePrice;
  const volume = parseNumber(candles.current.volume) ?? 0;
  const priceChangePct = prevClose !== 0 ? (closePrice - prevClose) / prevClose : 0;
  const oiVolumeRatio = volume > 0 ? oiValue / volume : 0;
  const weakRally = priceChangePct > 0 && oiChange < 0 ? 1 : 0;
  const weakSelloff = priceChangePct < 0 && oiChange > 0 ? 1 : 0;
  const oiDivergence = weakRally === 1 || weakSelloff === 1 ? 1 : 0;

  const markPrice = parseNumber(mark.markPx);
  const fundingRate = parseNumber(funding.fundingRate);
  const fundingNextTimeMs = parseNumber(funding.nextFundingTime);
  const fundingNextTime = fundingNextTimeMs !== null
    ? new Date(fundingNextTimeMs).toISOString()
    : null;
  const fundingSourceMs = parseNumber(funding.ts);
  const fundingSourceTime = fundingSourceMs !== null ? new Date(fundingSourceMs).toISOString() : null;
  const openInterestNotional = parseNumber(oi.oiUsd) ??
    (markPrice !== null ? markPrice * oiValue : null);

  const row = {
    symbol: pair.symbol,
    pair: pair.pair,
    binance_symbol: pair.sourceInstrument,
    bucket_time: bucketIso,
    open_interest: oiValue,
    oi_change: oiChange,
    oi_change_pct: oiChangePct,
    close_price: closePrice,
    volume,
    price_change_pct: priceChangePct,
    oi_volume_ratio: oiVolumeRatio,
    oi_divergence: oiDivergence,
    weak_rally: weakRally,
    weak_selloff: weakSelloff,
    source_time: sourceTimeIso,
    ingested_at: new Date().toISOString(),
    mark_price: markPrice,
    open_interest_notional: openInterestNotional,
    funding_rate: fundingRate,
    funding_rate_8h_avg: fundingRate,
    funding_next_time: fundingNextTime,
    funding_source_time: fundingSourceTime,
  };

  const { error: upsertError } = await supabase
    .from("open_interest")
    .upsert(row, { onConflict: "symbol,bucket_time" });
  if (upsertError) {
    throw new Error(`open_interest upsert failed for ${pair.pair}: ${upsertError.message}`);
  }

  const { error: featureError } = await supabase.rpc("fn_compute_oi_features_for_bucket", {
    p_bucket_time: bucketIso,
  });
  if (featureError) {
    throw new Error(
      `oi_features compute failed for ${pair.pair} @ ${bucketIso}: ${featureError.message}`,
    );
  }

  return { bucketTime: bucketIso, status: "inserted" };
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

  const pairs = requestedPairs(payload.symbols);
  const results: Array<Record<string, unknown>> = [];
  let inserted = 0;
  let skipped = 0;

  for (const pair of pairs) {
    try {
      const outcome = await upsertOpenInterestTick(supabase, pair);
      if (outcome.status === "inserted") {
        inserted += 1;
      } else {
        skipped += 1;
      }
      results.push({
        pair: pair.pair,
        symbol: pair.symbol,
        status: outcome.status,
        bucket_time: outcome.bucketTime,
        reason: outcome.reason ?? null,
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

  const errorCount = results.filter((r) => r.status === "error").length;
  const status = errorCount > 0 ? 500 : 200;
  return jsonResponse(status, {
    ok: errorCount === 0,
    inserted,
    skipped,
    errors: errorCount,
    results,
  });
});
