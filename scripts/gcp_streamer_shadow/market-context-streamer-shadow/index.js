import { WebsocketClient } from 'coinbase-api';
import express from 'express';
import { mkdirSync, writeFileSync, readFileSync, readdirSync, unlinkSync } from 'fs';
import { Pool } from 'pg';

const SYMBOLS = (process.env.SYMBOLS || 'BTC-USD,ETH-USD,SOL-USD')
  .split(',')
  .map((s) => s.trim())
  .filter(Boolean);
const PORT = Number(process.env.PORT || 8080);
const BACKUP_DIR = process.env.BACKUP_DIR || '/data/backup';
const FLUSH_INTERVAL_MS = Number(process.env.FLUSH_INTERVAL_MS || 2000);
const MAX_BATCH_SIZE = Number(process.env.MAX_BATCH_SIZE || 1000);
const MAX_BUFFER_SIZE = Number(process.env.MAX_BUFFER_SIZE || 100000);
const WATCHDOG_TIMEOUT_MS = Number(process.env.WATCHDOG_TIMEOUT_MS || 60000);
const HEARTBEAT_INTERVAL_MS = Number(process.env.HEARTBEAT_INTERVAL_MS || 30000);
const HEARTBEAT_ID = Number(process.env.HEARTBEAT_ID || 12);
const HEARTBEAT_SERVICE_NAME = process.env.HEARTBEAT_SERVICE_NAME || 'market-context-streamer-shadow';

const requiredEnv = ['PGHOST', 'PGPORT', 'PGDATABASE', 'PGUSER', 'PGPASSWORD'];
for (const key of requiredEnv) {
  if (!process.env[key]) {
    console.error(`ERROR: missing required env var ${key}`);
    process.exit(1);
  }
}

mkdirSync(BACKUP_DIR, { recursive: true });

const pool = new Pool({
  host: process.env.PGHOST,
  port: Number(process.env.PGPORT),
  database: process.env.PGDATABASE,
  user: process.env.PGUSER,
  password: process.env.PGPASSWORD,
  ssl: { rejectUnauthorized: false },
  max: 8,
  idleTimeoutMillis: 30000,
  connectionTimeoutMillis: 10000,
});

let tickerBuffer = [];
let lastMessageTime = Date.now();
let tickersReceived = 0;
let tickersFlushed = 0;
let tickersBackedUp = 0;
let lastTickerTime = null;
let currentStatus = 'starting';
let lastError = null;
let wsClient = null;
let watchdogTimer = null;
let isConnected = false;
let flushInProgress = false;
let consecutiveFailures = 0;

const app = express();
app.get('/health', (_req, res) => {
  const now = Date.now();
  const msSinceLastMessage = now - lastMessageTime;
  const healthy = isConnected && msSinceLastMessage < WATCHDOG_TIMEOUT_MS;
  const memUsage = process.memoryUsage();
  res.status(healthy ? 200 : 503).json({
    status: currentStatus,
    healthy,
    isConnected,
    symbols: SYMBOLS,
    tickersReceived,
    tickersFlushed,
    tickersBackedUp,
    bufferSize: tickerBuffer.length,
    lastMessageAgoMs: msSinceLastMessage,
    lastTickerTime,
    lastError,
    consecutiveFailures,
    memoryMB: Math.round(memUsage.heapUsed / 1024 / 1024),
    uptime: process.uptime(),
  });
});
app.listen(PORT, () => console.log(`Health endpoint on port ${PORT}`));

const heartbeatSql = `
  INSERT INTO public.websocket_heartbeat (
    id, service_name, last_heartbeat, trades_received, last_trade_at, status, error_message, updated_at
  ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
  ON CONFLICT (id) DO UPDATE SET
    service_name = EXCLUDED.service_name,
    last_heartbeat = EXCLUDED.last_heartbeat,
    trades_received = EXCLUDED.trades_received,
    last_trade_at = EXCLUDED.last_trade_at,
    status = EXCLUDED.status,
    error_message = EXCLUDED.error_message,
    updated_at = EXCLUDED.updated_at
`;

async function updateHeartbeat() {
  const nowIso = new Date().toISOString();
  try {
    await pool.query(heartbeatSql, [
      HEARTBEAT_ID,
      HEARTBEAT_SERVICE_NAME,
      nowIso,
      tickersReceived,
      lastTickerTime,
      currentStatus,
      lastError,
      nowIso,
    ]);
  } catch (_err) {
    // Non-blocking heartbeat.
  }
}
setInterval(updateHeartbeat, HEARTBEAT_INTERVAL_MS);

function backupToDisk(rows) {
  try {
    const filename = `${BACKUP_DIR}/tickers_${Date.now()}.json`;
    writeFileSync(filename, JSON.stringify(rows));
    tickersBackedUp += rows.length;
    console.log(`BACKUP: Saved ${rows.length} tickers to ${filename}`);
    return true;
  } catch (err) {
    console.error('BACKUP FAILED:', err.message);
    return false;
  }
}

const insertTickerSqlPrefix = `
  INSERT INTO public.market_context (pair, timestamp, best_bid, best_ask)
  VALUES
`;

function buildInsertTickersQuery(rows) {
  const values = [];
  const placeholders = rows.map((row, i) => {
    const base = i * 4;
    values.push(row.pair, row.timestamp, row.best_bid, row.best_ask);
    return `($${base + 1},$${base + 2},$${base + 3},$${base + 4})`;
  });
  return {
    sql: `${insertTickerSqlPrefix}\n${placeholders.join(',\n')}`,
    values,
  };
}

async function restoreFromDisk() {
  let files = [];
  try {
    files = readdirSync(BACKUP_DIR).filter((f) => f.startsWith('tickers_') && f.endsWith('.json'));
  } catch (_err) {
    return;
  }
  if (files.length === 0) {
    return;
  }

  files.sort();
  console.log(`RESTORE: Found ${files.length} backup files`);
  for (const file of files) {
    try {
      const filepath = `${BACKUP_DIR}/${file}`;
      const rows = JSON.parse(readFileSync(filepath, 'utf8'));
      if (!Array.isArray(rows) || rows.length === 0) {
        unlinkSync(filepath);
        continue;
      }
      const { sql, values } = buildInsertTickersQuery(rows);
      await pool.query(sql, values);
      unlinkSync(filepath);
      tickersFlushed += rows.length;
      console.log(`RESTORE: Recovered ${rows.length} tickers from ${file}`);
    } catch (err) {
      console.error(`RESTORE failed for ${file}:`, err.message);
    }
  }
}

async function flushTickers() {
  if (tickerBuffer.length === 0 || flushInProgress) {
    return;
  }

  flushInProgress = true;
  const batchSize = tickerBuffer.length > 5000 ? 2000 : MAX_BATCH_SIZE;
  const batch = tickerBuffer.splice(0, batchSize);

  try {
    const { sql, values } = buildInsertTickersQuery(batch);
    await pool.query(sql, values);

    consecutiveFailures = 0;
    tickersFlushed += batch.length;
    if (tickersFlushed % 5000 < batch.length) {
      console.log(`Flushed total=${tickersFlushed}, buffer=${tickerBuffer.length}`);
    }

    if (tickersBackedUp > 0) {
      setImmediate(restoreFromDisk);
    }
  } catch (err) {
    consecutiveFailures += 1;
    lastError = err.message;
    console.error(`Flush failed (attempt ${consecutiveFailures}):`, err.message);

    if (consecutiveFailures >= 3) {
      backupToDisk(batch);
    } else {
      tickerBuffer = batch.concat(tickerBuffer);
    }
  } finally {
    flushInProgress = false;
  }

  if (tickerBuffer.length > 2000) {
    setImmediate(flushTickers);
  }
}
setInterval(flushTickers, FLUSH_INTERVAL_MS);

function resetWatchdog() {
  lastMessageTime = Date.now();
  if (watchdogTimer) {
    clearTimeout(watchdogTimer);
  }
  watchdogTimer = setTimeout(() => {
    currentStatus = 'watchdog_reconnect';
    lastError = 'Watchdog timeout';
    if (wsClient) {
      wsClient.closeAll(true);
    }
  }, WATCHDOG_TIMEOUT_MS);
}

function startWebSocket() {
  currentStatus = 'connecting';
  wsClient = new WebsocketClient();

  wsClient.on('open', () => {
    isConnected = true;
    currentStatus = 'connected';
    lastError = null;
    resetWatchdog();
  });

  wsClient.on('update', (data) => {
    resetWatchdog();
    if (data.type !== 'ticker') {
      return;
    }

    if (tickerBuffer.length >= MAX_BUFFER_SIZE) {
      const overflow = tickerBuffer.splice(0, 10000);
      backupToDisk(overflow);
    }

    tickerBuffer.push({
      pair: data.product_id,
      timestamp: data.time,
      best_bid: data.best_bid,
      best_ask: data.best_ask,
    });

    tickersReceived += 1;
    lastTickerTime = data.time;
    if (tickersReceived % 5000 === 0) {
      const mem = Math.round(process.memoryUsage().heapUsed / 1024 / 1024);
      console.log(`Tickers=${tickersReceived}, buffer=${tickerBuffer.length}, memMB=${mem}`);
    }
  });

  wsClient.on('reconnect', () => {
    currentStatus = 'reconnecting';
    isConnected = false;
  });

  wsClient.on('reconnected', () => {
    isConnected = true;
    currentStatus = 'connected';
    lastError = null;
    resetWatchdog();
  });

  wsClient.on('close', () => {
    currentStatus = 'disconnected';
    isConnected = false;
  });

  wsClient.on('exception', (data) => {
    lastError = JSON.stringify(data);
    currentStatus = 'error';
  });

  wsClient.subscribe({ topic: 'ticker', payload: { product_ids: SYMBOLS } }, 'exchangeMarketData');
}

async function shutdown(signal) {
  console.log(`${signal} received, draining...`);
  currentStatus = 'shutting_down';
  if (watchdogTimer) {
    clearTimeout(watchdogTimer);
  }

  let attempts = 0;
  while (tickerBuffer.length > 0 && attempts < 10) {
    await flushTickers();
    await new Promise((resolve) => setTimeout(resolve, 500));
    attempts += 1;
  }

  if (tickerBuffer.length > 0) {
    backupToDisk(tickerBuffer);
    tickerBuffer = [];
  }

  await updateHeartbeat();
  await pool.end();
  if (wsClient) {
    wsClient.closeAll(true);
  }
  process.exit(0);
}

process.on('SIGTERM', () => shutdown('SIGTERM'));
process.on('SIGINT', () => shutdown('SIGINT'));
process.on('uncaughtException', (err) => {
  lastError = err.message;
  console.error('UNCAUGHT:', err);
});
process.on('unhandledRejection', (err) => {
  lastError = String(err);
  console.error('UNHANDLED:', err);
});

console.log('=== Market Context Streamer Shadow (Direct Postgres) ===');
console.log(`Symbols: ${SYMBOLS.join(',')}`);
restoreFromDisk();
startWebSocket();
updateHeartbeat();
