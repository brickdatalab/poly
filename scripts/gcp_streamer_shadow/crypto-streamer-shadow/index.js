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
const FLUSH_INTERVAL_MS = Number(process.env.FLUSH_INTERVAL_MS || 3000);
const MAX_BATCH_SIZE = Number(process.env.MAX_BATCH_SIZE || 1000);
const MAX_BUFFER_SIZE = Number(process.env.MAX_BUFFER_SIZE || 100000);
const WATCHDOG_TIMEOUT_MS = Number(process.env.WATCHDOG_TIMEOUT_MS || 60000);
const HEARTBEAT_INTERVAL_MS = Number(process.env.HEARTBEAT_INTERVAL_MS || 30000);
const HEARTBEAT_ID = Number(process.env.HEARTBEAT_ID || 11);
const HEARTBEAT_SERVICE_NAME = process.env.HEARTBEAT_SERVICE_NAME || 'crypto-streamer-shadow';

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

let tradeBuffer = [];
let lastMessageTime = Date.now();
let tradesReceived = 0;
let tradesFlushed = 0;
let tradesBackedUp = 0;
let lastTradeTime = null;
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
    tradesReceived,
    tradesFlushed,
    tradesBackedUp,
    bufferSize: tradeBuffer.length,
    lastMessageAgoMs: msSinceLastMessage,
    lastTradeTime,
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
      tradesReceived,
      lastTradeTime,
      currentStatus,
      lastError,
      nowIso,
    ]);
  } catch (_err) {
    // Non-blocking heartbeat.
  }
}
setInterval(updateHeartbeat, HEARTBEAT_INTERVAL_MS);

function backupToDisk(trades) {
  try {
    const filename = `${BACKUP_DIR}/trades_${Date.now()}.json`;
    writeFileSync(filename, JSON.stringify(trades));
    tradesBackedUp += trades.length;
    console.log(`BACKUP: Saved ${trades.length} trades to ${filename}`);
    return true;
  } catch (err) {
    console.error('BACKUP FAILED:', err.message);
    return false;
  }
}

const insertTradesSqlPrefix = `
  INSERT INTO public.raw_trades (trade_id, pair, price, size, side, executed_at)
  VALUES
`;

function buildInsertTradesQuery(rows) {
  const values = [];
  const placeholders = rows.map((row, i) => {
    const base = i * 6;
    values.push(row.trade_id, row.pair, row.price, row.size, row.side, row.executed_at);
    return `($${base + 1},$${base + 2},$${base + 3},$${base + 4},$${base + 5},$${base + 6})`;
  });
  const sql = `${insertTradesSqlPrefix}\n${placeholders.join(',\n')}\nON CONFLICT (trade_id, executed_at) DO NOTHING`;
  return { sql, values };
}

async function restoreFromDisk() {
  let files = [];
  try {
    files = readdirSync(BACKUP_DIR).filter((f) => f.startsWith('trades_') && f.endsWith('.json'));
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
      const { sql, values } = buildInsertTradesQuery(rows);
      await pool.query(sql, values);
      unlinkSync(filepath);
      tradesFlushed += rows.length;
      console.log(`RESTORE: Recovered ${rows.length} trades from ${file}`);
    } catch (err) {
      console.error(`RESTORE failed for ${file}:`, err.message);
    }
  }
}

async function flushTrades() {
  if (tradeBuffer.length === 0 || flushInProgress) {
    return;
  }

  flushInProgress = true;
  const batchSize = tradeBuffer.length > 5000 ? 2000 : MAX_BATCH_SIZE;
  const batch = tradeBuffer.splice(0, batchSize);

  try {
    const { sql, values } = buildInsertTradesQuery(batch);
    await pool.query(sql, values);

    consecutiveFailures = 0;
    tradesFlushed += batch.length;
    if (tradesFlushed % 5000 < batch.length) {
      console.log(`Flushed total=${tradesFlushed}, buffer=${tradeBuffer.length}`);
    }

    if (tradesBackedUp > 0) {
      setImmediate(restoreFromDisk);
    }
  } catch (err) {
    consecutiveFailures += 1;
    lastError = err.message;
    console.error(`Flush failed (attempt ${consecutiveFailures}):`, err.message);

    if (consecutiveFailures >= 3) {
      backupToDisk(batch);
    } else {
      tradeBuffer = batch.concat(tradeBuffer);
    }
  } finally {
    flushInProgress = false;
  }

  if (tradeBuffer.length > 2000) {
    setImmediate(flushTrades);
  }
}
setInterval(flushTrades, FLUSH_INTERVAL_MS);

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
    if (data.type !== 'match' && data.type !== 'last_match') {
      return;
    }

    if (tradeBuffer.length >= MAX_BUFFER_SIZE) {
      const overflow = tradeBuffer.splice(0, 10000);
      backupToDisk(overflow);
    }

    tradeBuffer.push({
      trade_id: Number.parseInt(String(data.trade_id), 10),
      pair: data.product_id,
      price: data.price,
      size: data.size,
      side: data.side?.toUpperCase() || 'UNKNOWN',
      executed_at: data.time,
    });

    tradesReceived += 1;
    lastTradeTime = data.time;
    if (tradesReceived % 5000 === 0) {
      const mem = Math.round(process.memoryUsage().heapUsed / 1024 / 1024);
      console.log(`Trades=${tradesReceived}, buffer=${tradeBuffer.length}, memMB=${mem}`);
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

  wsClient.subscribe({ topic: 'matches', payload: { product_ids: SYMBOLS } }, 'exchangeMarketData');
}

async function shutdown(signal) {
  console.log(`${signal} received, draining...`);
  currentStatus = 'shutting_down';
  if (watchdogTimer) {
    clearTimeout(watchdogTimer);
  }

  let attempts = 0;
  while (tradeBuffer.length > 0 && attempts < 10) {
    await flushTrades();
    await new Promise((resolve) => setTimeout(resolve, 500));
    attempts += 1;
  }

  if (tradeBuffer.length > 0) {
    backupToDisk(tradeBuffer);
    tradeBuffer = [];
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

console.log('=== Crypto Streamer Shadow (Direct Postgres) ===');
console.log(`Symbols: ${SYMBOLS.join(',')}`);
restoreFromDisk();
startWebSocket();
updateHeartbeat();
