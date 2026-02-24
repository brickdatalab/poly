#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import signal
import subprocess
import threading
import time
import webbrowser
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
import sys

if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

try:
    from scripts.codex_signals_playground.dashboard_core import (
        bucket_for_decision,
        next_decision_after,
        summarize_pair_window,
        utcnow,
    )
except ModuleNotFoundError:  # direct script invocation fallback
    from dashboard_core import (  # type: ignore
        bucket_for_decision,
        next_decision_after,
        summarize_pair_window,
        utcnow,
    )


def _load_env() -> dict[str, str]:
    env = dict(os.environ)
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            s = line.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            k, v = s.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def _build_db_url(env: dict[str, str]) -> str:
    direct = (env.get("SUPABASE_DB_URL") or "").strip()
    if direct:
        return direct

    supabase_url = (env.get("SUPABASE_URL") or "").strip()
    password = (env.get("SUPABASE_DB_PASSWORD") or "").strip()
    if not supabase_url or not password:
        raise SystemExit("Missing DB config: set SUPABASE_DB_URL or SUPABASE_URL + SUPABASE_DB_PASSWORD in .env")

    host = supabase_url.replace("https://", "").replace("http://", "").strip().split("/")[0]
    project_ref = host.split(".")[0] if host else ""
    if not project_ref:
        raise SystemExit(f"Could not parse project ref from SUPABASE_URL={supabase_url!r}")

    return f"postgresql://postgres:{password}@db.{project_ref}.supabase.co:5432/postgres"


def _sql_lit(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _psql_scalar(db_url: str, sql: str) -> str:
    q = sql.strip().rstrip(";")
    out = subprocess.check_output(
        [
            "psql",
            db_url,
            "-v",
            "ON_ERROR_STOP=1",
            "-P",
            "pager=off",
            "-t",
            "-A",
            "-c",
            q,
        ],
        text=True,
    )
    return out.strip()


def _json_safe(value: Any) -> Any:
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    return value


@dataclass
class DashboardState:
    sigma_min: float
    pairs: list[str]
    started_at: str = field(default_factory=lambda: utcnow().isoformat())
    next_run_utc: str | None = None
    last_tick_utc: str | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    seq: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)

    def append_events(self, rows: list[dict[str, Any]]) -> None:
        with self.lock:
            now_iso = utcnow().isoformat()
            self.last_tick_utc = now_iso
            for r in rows:
                self.seq += 1
                r["id"] = self.seq
                r["created_at_utc"] = now_iso
                self.events.append(r)
            # Keep in-memory session bounded.
            self.events = self.events[-1200:]

    def set_next_run(self, next_run: datetime) -> None:
        with self.lock:
            self.next_run_utc = next_run.astimezone(timezone.utc).isoformat()
            self.last_tick_utc = utcnow().isoformat()

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            events = list(self.events)
            fired = sum(1 for e in events if e.get("signal_fired"))
            passed = sum(1 for e in events if e.get("filter_pass"))
            return {
                "started_at_utc": self.started_at,
                "server_time_utc": utcnow().isoformat(),
                "next_run_utc": self.next_run_utc,
                "last_tick_utc": self.last_tick_utc,
                "sigma_min": self.sigma_min,
                "pairs": self.pairs,
                "stats": {
                    "events": len(events),
                    "signal_fired": fired,
                    "filter_pass": passed,
                },
                "events": events,
            }


def _run_signal_pipeline_cycle(db_url: str) -> dict[str, int]:
    try:
        payload = _psql_scalar(
            db_url,
            "select indicators.fn_run_realtime_signal_tick(interval '45 minutes', 5000, 5000)::text",
        )
        data = json.loads(payload) if payload else {}
        return {
            "synthetic_enqueued": int(data.get("synthetic_enqueued", 0) or 0),
            "synthetic_processed": int(data.get("synthetic_processed", 0) or 0),
            "codex_enqueued": int(data.get("codex_enqueued", 0) or 0),
            "codex_processed": int(data.get("codex_processed", 0) or 0),
        }
    except Exception:
        # Backward-compatible fallback for environments not yet migrated.
        syn_enq = int(
            _psql_scalar(
                db_url,
                "select indicators.fn_enqueue_synthetic_jobs(interval '45 minutes')::text",
            )
            or "0"
        )
        syn_done = int(
            _psql_scalar(
                db_url,
                "select indicators.fn_process_synthetic_jobs(5000)::text",
            )
            or "0"
        )
        codex_enq = int(
            _psql_scalar(
                db_url,
                "select indicators.fn_enqueue_codex_signal_jobs(interval '45 minutes')::text",
            )
            or "0"
        )
        codex_done = int(
            _psql_scalar(
                db_url,
                "select indicators.fn_process_codex_signal_jobs(5000)::text",
            )
            or "0"
        )
        return {
            "synthetic_enqueued": syn_enq,
            "synthetic_processed": syn_done,
            "codex_enqueued": codex_enq,
            "codex_processed": codex_done,
        }


def _fetch_rows_for_pair_bucket(db_url: str, pair: str, bucket: datetime) -> list[dict[str, Any]]:
    pair_sql = _sql_lit(pair)
    bucket_sql = _sql_lit(bucket.isoformat())
    sql = f"""
    select coalesce(json_agg(x order by x.base_accuracy desc, x.rule_id), '[]'::json)::text
    from (
      select
        s.rule_id,
        s.prediction,
        s.base_accuracy::float8 as base_accuracy,
        s.indicator_value::float8 as indicator_value,
        s.config_id,
        r.operator,
        r.threshold::float8 as threshold,
        s.signals_passed
      from indicators.codex_signals s
      join indicators.codex_signal_rules r
        on r.rule_id = s.rule_id
      where s.pair = {pair_sql}
        and s.bucket_time = {bucket_sql}::timestamptz
    ) x
    """
    raw = _psql_scalar(db_url, sql)
    return json.loads(raw) if raw else []


def _fetch_sigma_std_map(
    db_url: str,
    pair: str,
    bucket: datetime,
    config_ids: list[str],
) -> dict[str, float]:
    if not config_ids:
        return {}
    cfg_arr = "array[" + ", ".join(_sql_lit(c) for c in sorted(set(config_ids))) + "]"
    pair_sql = _sql_lit(pair)
    bucket_sql = _sql_lit(bucket.isoformat())
    sql = f"""
    select coalesce(json_object_agg(config_id, sd), '{{}}'::json)::text
    from (
      select
        config_id,
        stddev_samp(v1)::float8 as sd
      from indicators.synthetic_indicator_values
      where pair = {pair_sql}
        and config_id = any({cfg_arr})
        and bucket_time > {bucket_sql}::timestamptz - interval '21 days'
        and bucket_time <= {bucket_sql}::timestamptz
        and v1 is not null
      group by config_id
    ) t
    """
    raw = _psql_scalar(db_url, sql)
    parsed = json.loads(raw) if raw else {}
    out: dict[str, float] = {}
    for k, v in parsed.items():
        if v is None:
            continue
        try:
            out[k] = float(v)
        except Exception:
            continue
    return out


def _scheduler_loop(state: DashboardState, db_url: str, stop_evt: threading.Event) -> None:
    due = next_decision_after(utcnow())
    while not stop_evt.is_set():
        now = utcnow()
        state.set_next_run(due)

        while now >= due and not stop_evt.is_set():
            current_due = due
            due = next_decision_after(current_due + timedelta(seconds=1))
            state.set_next_run(due)

            bucket = bucket_for_decision(current_due)
            cycle_meta: dict[str, Any] = {"enqueued": 0, "processed": 0, "ok": True}
            pipeline_error: str | None = None
            try:
                cycle_meta = _run_signal_pipeline_cycle(db_url)
            except Exception as exc:  # pragma: no cover
                pipeline_error = str(exc)
                cycle_meta = {"enqueued": 0, "processed": 0, "ok": False, "error": pipeline_error}

            batch: list[dict[str, Any]] = []
            for pair in state.pairs:
                try:
                    rows = _fetch_rows_for_pair_bucket(db_url, pair, bucket)
                    sigma_map = _fetch_sigma_std_map(
                        db_url,
                        pair,
                        bucket,
                        [str(r.get("config_id") or "") for r in rows if r.get("config_id")],
                    )
                    event = summarize_pair_window(
                        pair=pair,
                        bucket_time=bucket,
                        rows=rows,
                        sigma_std_by_config=sigma_map,
                        sigma_min=state.sigma_min,
                    )
                    event["decision_time_utc"] = current_due.isoformat()
                    event["interval_label"] = bucket.strftime("%Y-%m-%d %H:%M") + " → +15m"
                    event["enqueue_processed"] = cycle_meta
                    if pipeline_error:
                        event["pipeline_error"] = pipeline_error
                except Exception as exc:  # pragma: no cover
                    event = {
                        "pair": pair,
                        "bucket_time": bucket.isoformat(),
                        "decision_time_utc": current_due.isoformat(),
                        "interval_label": bucket.strftime("%Y-%m-%d %H:%M") + " → +15m",
                        "signal_fired": False,
                        "filter_pass": False,
                        "prediction": "error",
                        "rules_passed": 0,
                        "sigma_from_threshold": None,
                        "base_accuracy_ref": None,
                        "top_rule_id": None,
                        "detail": [],
                        "error": str(exc),
                        "enqueue_processed": cycle_meta,
                    }
                batch.append(event)
            state.append_events(batch)
            now = utcnow()

        time.sleep(0.5)


def _html() -> str:
    return """<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>Codex Signals Realtime Playground</title>
  <style>
    :root {
      --bg: #08090b;
      --panel: #efeff2;
      --ink: #0b0d12;
      --muted: #5f6675;
      --pass: #57d66f;
      --nopass: #ff6b6b;
      --warn: #f7c948;
      --edge: #1a1e27;
    }

    * { box-sizing: border-box; }

    body {
      margin: 0;
      min-height: 100vh;
      background: radial-gradient(circle at 12% 8%, #11161f 0%, var(--bg) 45%, #040507 100%);
      color: #f6f7fb;
      font-family: Inter, "Avenir Next", "Segoe UI", "SF Pro Text", system-ui, sans-serif;
      padding: 28px;
    }

    .stage {
      border: 1px solid #2b3342;
      border-radius: 12px;
      background: linear-gradient(135deg, #07090d 0%, #020305 100%);
      box-shadow: 0 30px 70px rgba(0,0,0,0.45);
      min-height: calc(100vh - 56px);
      padding: 28px;
      display: grid;
      grid-template-columns: 1.08fr 1fr;
      gap: 28px;
    }

    .timer-side {
      display: grid;
      grid-template-rows: auto 1fr auto;
      gap: 20px;
      align-items: center;
      padding: 6px 8px;
    }

    .meta {
      display: flex;
      align-items: center;
      justify-content: space-between;
      color: #9aa4b8;
      font-size: 13px;
      letter-spacing: 0.02em;
      text-transform: uppercase;
    }

    .timer {
      font-weight: 800;
      line-height: 0.9;
      font-size: clamp(120px, 22vw, 280px);
      letter-spacing: 0.05em;
      text-align: center;
      color: #f4f6fb;
      text-shadow: 0 10px 45px rgba(255,255,255,0.12);
      user-select: none;
    }

    .timer.warn { color: #ffe28a; }

    .timer-notes {
      display: flex;
      justify-content: space-between;
      align-items: center;
      color: #8f98ab;
      font-size: 13px;
    }

    .controls {
      display: flex;
      align-items: center;
      gap: 14px;
      background: rgba(255,255,255,0.04);
      border: 1px solid rgba(255,255,255,0.08);
      padding: 10px 12px;
      border-radius: 10px;
    }

    .controls label {
      font-size: 12px;
      color: #c8cfdd;
    }

    .controls input[type=\"range\"] { width: 140px; }

    .panel {
      background: var(--panel);
      color: var(--ink);
      border-radius: 10px;
      border: 1px solid #c8ccd7;
      padding: 18px 18px 14px;
      display: grid;
      grid-template-rows: auto auto 1fr;
      min-height: 0;
    }

    .legend {
      display: flex;
      align-items: center;
      gap: 14px;
      margin-bottom: 10px;
      flex-wrap: wrap;
    }

    .dot {
      width: 64px;
      height: 64px;
      border-radius: 999px;
      display: grid;
      place-items: center;
      font-size: 11px;
      font-weight: 700;
      text-align: center;
      line-height: 1.1;
      color: #111;
    }

    .dot.pass { background: var(--pass); }
    .dot.no { background: var(--nopass); }

    .legend-text {
      color: var(--muted);
      font-size: 12px;
      line-height: 1.35;
      max-width: 420px;
    }

    .table-wrap {
      margin-top: 10px;
      border: 1px solid #d7dbe5;
      border-radius: 8px;
      overflow: auto;
      background: white;
      min-height: 0;
    }

    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 12px;
    }

    thead th {
      position: sticky;
      top: 0;
      background: #f3f5fb;
      color: #31394a;
      text-align: left;
      padding: 10px 8px;
      border-bottom: 1px solid #dce1ed;
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }

    tbody td {
      padding: 9px 8px;
      border-bottom: 1px solid #eceff6;
      white-space: nowrap;
    }

    tbody tr:hover { background: #f7f9ff; }

    .pill {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 74px;
      padding: 4px 8px;
      border-radius: 999px;
      font-weight: 700;
      font-size: 11px;
      letter-spacing: 0.03em;
    }

    .pill.pass { background: rgba(87,214,111,0.22); color: #0f6f1f; }
    .pill.no { background: rgba(255,107,107,0.24); color: #9d1d1d; }
    .pill.fired { background: rgba(57,138,255,0.17); color: #225fbe; }
    .pill.none { background: #eef1f8; color: #58617a; }

    .muted { color: #8089a0; }

    @media (max-width: 1120px) {
      .stage { grid-template-columns: 1fr; }
      .timer { font-size: clamp(100px, 26vw, 220px); }
      .panel { min-height: 55vh; }
    }
  </style>
</head>
<body>
  <div class=\"stage\">
    <section class=\"timer-side\">
      <div class=\"meta\">
        <span>Codex Signal Realtime</span>
        <span id=\"serverTime\">--:--:--</span>
      </div>

      <div id=\"timer\" class=\"timer\">00:00</div>

      <div class=\"timer-notes\">
        <div class=\"controls\">
          <label>
            Sigma Min
            <input id=\"sigmaMin\" type=\"range\" min=\"0.25\" max=\"4\" step=\"0.25\" value=\"0.25\" />
          </label>
          <strong id=\"sigmaValue\">0.25σ</strong>
          <label><input id=\"soundToggle\" type=\"checkbox\" checked /> Sound</label>
        </div>
        <span class=\"muted\" id=\"nextRun\">next: --</span>
      </div>
    </section>

    <section class=\"panel\">
      <div class=\"legend\">
        <div class=\"dot pass\">pass\nfilter</div>
        <div class=\"dot no\">no pass\nfilter</div>
        <div class=\"legend-text\">
          Rolling BTC/ETH 15m window outputs at <strong>:02, :17, :32, :47</strong>.\n
          Session is in-memory and resets when this window/script closes.
        </div>
      </div>

      <div class=\"muted\" style=\"font-size:12px;\">
        Shows fired vs not-fired, direction, sigma distance from threshold, and base accuracy reference.
      </div>

      <div class=\"table-wrap\">
        <table>
          <thead>
            <tr>
              <th>UTC Time</th>
              <th>Pair</th>
              <th>Interval</th>
              <th>Fired</th>
              <th>Sigma</th>
              <th>Filter</th>
              <th>Prediction</th>
              <th>Base Acc</th>
              <th>Rule</th>
            </tr>
          </thead>
          <tbody id=\"rows\"></tbody>
        </table>
      </div>
    </section>
  </div>

  <script>
    const timerEl = document.getElementById('timer');
    const rowsEl = document.getElementById('rows');
    const serverTimeEl = document.getElementById('serverTime');
    const nextRunEl = document.getElementById('nextRun');
    const sigmaMinEl = document.getElementById('sigmaMin');
    const sigmaValueEl = document.getElementById('sigmaValue');
    const soundToggleEl = document.getElementById('soundToggle');

    let state = null;
    let seenIds = new Set();

    function fmtClockParts(ms) {
      const total = Math.max(0, Math.floor(ms / 1000));
      const mm = String(Math.floor(total / 60)).padStart(2, '0');
      const ss = String(total % 60).padStart(2, '0');
      return `${mm}:${ss}`;
    }

    function fmtUTC(iso) {
      if (!iso) return '--';
      const d = new Date(iso);
      return d.toISOString().replace('T', ' ').replace('.000Z', 'Z');
    }

    function beep() {
      if (!soundToggleEl.checked) return;
      const Ctx = window.AudioContext || window.webkitAudioContext;
      if (!Ctx) return;
      const ctx = new Ctx();
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = 'sine';
      osc.frequency.value = 880;
      gain.gain.value = 0.03;
      osc.connect(gain).connect(ctx.destination);
      osc.start();
      setTimeout(() => {
        osc.stop();
        ctx.close();
      }, 180);
    }

    function renderRows(events) {
      const sigmaMin = Number(sigmaMinEl.value);
      const sorted = [...events].sort((a, b) => (a.id || 0) - (b.id || 0));
      const rows = [];

      for (const e of sorted) {
        const sigma = (e.sigma_from_threshold === null || e.sigma_from_threshold === undefined)
          ? null
          : Number(e.sigma_from_threshold);
        const filterPass = Boolean(e.signal_fired && sigma !== null && Math.abs(sigma) >= sigmaMin && (e.prediction === 'up' || e.prediction === 'down'));

        if ((e.id && !seenIds.has(e.id) && filterPass)) {
          beep();
        }
        if (e.id) seenIds.add(e.id);

        rows.push(`
          <tr>
            <td>${fmtUTC(e.created_at_utc)}</td>
            <td><strong>${e.pair}</strong></td>
            <td>${e.interval_label || ''}</td>
            <td><span class=\"pill ${e.signal_fired ? 'fired' : 'none'}\">${e.signal_fired ? 'true' : 'false'}</span></td>
            <td>${sigma === null ? '<span class="muted">--</span>' : `${sigma.toFixed(2)}σ`}</td>
            <td><span class=\"pill ${filterPass ? 'pass' : 'no'}\">${filterPass ? 'pass' : 'no pass'}</span></td>
            <td>${e.prediction || 'none'}</td>
            <td>${e.base_accuracy_ref == null ? '<span class="muted">--</span>' : `${(Number(e.base_accuracy_ref) * 100).toFixed(2)}%`}</td>
            <td title=\"${e.top_rule_id || ''}\">${e.top_rule_id || '<span class="muted">none</span>'}</td>
          </tr>
        `);
      }

      rowsEl.innerHTML = rows.reverse().join('');
    }

    async function poll() {
      try {
        const res = await fetch('/api/state', { cache: 'no-store' });
        if (!res.ok) return;
        state = await res.json();
        renderRows(state.events || []);
        serverTimeEl.textContent = fmtUTC(state.server_time_utc);
        nextRunEl.textContent = `next: ${fmtUTC(state.next_run_utc)}`;
      } catch (_) {
        // silent retry
      }
    }

    function tickTimer() {
      if (!state || !state.next_run_utc) {
        timerEl.textContent = '00:00';
        timerEl.classList.remove('warn');
        return;
      }
      const now = new Date();
      const next = new Date(state.next_run_utc);
      const diff = next - now;
      timerEl.textContent = fmtClockParts(diff);
      if (diff <= 10000) timerEl.classList.add('warn');
      else timerEl.classList.remove('warn');
    }

    sigmaMinEl.addEventListener('input', () => {
      sigmaValueEl.textContent = `${Number(sigmaMinEl.value).toFixed(2)}σ`;
      if (state) renderRows(state.events || []);
    });

    sigmaValueEl.textContent = `${Number(sigmaMinEl.value).toFixed(2)}σ`;

    setInterval(tickTimer, 200);
    setInterval(poll, 1000);
    poll();
  </script>
</body>
</html>
"""


def _make_handler(state: DashboardState):
    html_doc = _html().encode("utf-8")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
            return

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/":
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(html_doc)
                return

            if parsed.path == "/api/state":
                payload = json.dumps(_json_safe(state.snapshot()), allow_nan=False).encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(payload)
                return

            if parsed.path == "/api/health":
                payload = json.dumps({"ok": True, "time_utc": utcnow().isoformat()}).encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(payload)
                return

            self.send_response(HTTPStatus.NOT_FOUND)
            self.end_headers()

    return Handler


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Run localhost realtime codex signals playground dashboard")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--sigma-min", type=float, default=0.25)
    ap.add_argument("--pairs", default="BTC-USD,ETH-USD")
    ap.add_argument("--no-open", action="store_true")
    return ap.parse_args()


def main() -> None:
    args = parse_args()
    env = _load_env()
    db_url = _build_db_url(env)

    pairs = [p.strip() for p in args.pairs.split(",") if p.strip()]
    if not pairs:
        raise SystemExit("No pairs supplied")

    state = DashboardState(sigma_min=float(args.sigma_min), pairs=pairs)

    stop_evt = threading.Event()

    scheduler = threading.Thread(
        target=_scheduler_loop,
        kwargs={"state": state, "db_url": db_url, "stop_evt": stop_evt},
        daemon=True,
    )
    scheduler.start()

    server = ThreadingHTTPServer((args.host, args.port), _make_handler(state))
    url = f"http://{args.host}:{args.port}"
    print(f"Dashboard running at {url}")
    print(f"Pairs: {', '.join(pairs)} | Sigma min: {args.sigma_min:.2f}")
    if not args.no_open:
        webbrowser.open(url)

    def _shutdown(*_: Any) -> None:
        stop_evt.set()
        try:
            server.shutdown()
        except Exception:
            pass

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        stop_evt.set()
        server.server_close()


if __name__ == "__main__":
    main()
