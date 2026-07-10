#!/usr/bin/env python3
"""
4-Sleeve Ensemble Dashboard — PAPER ONLY
READ-ONLY display for the 4-sleeve tangency portfolio research.
No trading, no orders, no mutations. Display only.
"""
import json
import os
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from string import Template

from flask import Flask, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Data paths
# ---------------------------------------------------------------------------
PAPER_RUNNER_PATH = Path(os.environ.get("PAPER_RUNNER_PATH", "/data/paper-runner/daily_pnl.json"))
MIRRORED_API_PATH = Path(os.environ.get("MIRRORED_API_PATH", "/data/paper-runner/live_api_data.json"))
BACKTEST_FALLBACK = Path(__file__).parent / "data" / "SD007-4sleeve-dd-optimization-data.json"

DD_GREEN = 0.10
DD_YELLOW = 0.20

SLEEVE_NAMES = ["CrossSecMom", "EMATrend", "Grid", "FundContrarian"]
SLEEVE_COLORS = {
    "CrossSecMom": "#50d5ff",
    "EMATrend": "#ff9b54",
    "Grid": "#c9f364",
    "FundContrarian": "#ff5db1",
}


def load_json_safe(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def get_data_source():
    paper = load_json_safe(PAPER_RUNNER_PATH)
    if paper and "daily_pnl" in paper:
        return paper, "LIVE PAPER RUNNER", True
    mirrored_api = load_json_safe(MIRRORED_API_PATH)
    if mirrored_api and mirrored_api.get("is_live") and "equity" in mirrored_api:
        return mirrored_api, mirrored_api.get("source") or "LIVE PAPER MIRROR", True
    backtest = load_json_safe(BACKTEST_FALLBACK)
    if backtest:
        return backtest, "BACKTEST FALLBACK", False
    return {}, "NO DATA", False


def generate_backtest_equity(total_ret, n_days):
    """Generate a representative equity curve from summary stats."""
    import random

    random.seed(42)
    equity = [1.0]
    daily_ret = (1 + total_ret) ** (1 / n_days) - 1
    dd_start = int(n_days * 0.55)
    dd_len = int(n_days * 0.15)
    for i in range(1, n_days + 1):
        noise = random.gauss(0, abs(daily_ret) * 2)
        base = daily_ret + noise
        if dd_start < i < dd_start + dd_len:
            base -= abs(daily_ret) * 3
        equity.append(equity[-1] * (1 + base))
    step = max(1, len(equity) // 200)
    return equity[::step]


def process_live_data(paper):
    if "daily_pnl" not in paper and "equity" in paper:
        mirrored = dict(paper)
        mirrored.setdefault("labels", [f"Point {i}" for i, _ in enumerate(mirrored.get("equity", []))])
        mirrored.setdefault("initial_capital", 2000.0)
        equity = mirrored.get("equity", [])
        mirrored.setdefault("current_equity", equity[-1] if equity else mirrored["initial_capital"])
        mirrored.setdefault("peak_equity", max([mirrored["initial_capital"], *equity]))
        mirrored.setdefault("net_pnl", mirrored["current_equity"] - mirrored["initial_capital"])
        mirrored.setdefault("net_pnl_pct", (mirrored["current_equity"] / mirrored["initial_capital"] - 1) if mirrored["initial_capital"] else 0)
        mirrored.setdefault("current_dd", 0)
        mirrored.setdefault("max_dd", 0)
        mirrored.setdefault("sleeve_pnl", {s: 0 for s in SLEEVE_NAMES})
        mirrored.setdefault("positions", [])
        execution = mirrored.get("execution_paper") or {}
        mirrored.setdefault("execution_labels", execution.get("labels") or mirrored.get("labels", []))
        mirrored.setdefault("execution_equity", execution.get("equity_curve") or ([mirrored["initial_capital"], execution.get("equity")] if execution.get("equity") is not None else [mirrored["initial_capital"]]))
        mirrored.setdefault("walk_forward", [])
        mirrored.setdefault("paper_status", "RUNNING")
        return mirrored

    daily = paper.get("daily_pnl", [])
    labels = [d.get("date", f"Point {i}") for i, d in enumerate(daily)]
    equity_values = [d.get("equity", 0) for d in daily]
    initial = paper.get("initial_capital", 2000.0)
    current_equity = paper.get("current_equity") or (equity_values[-1] if equity_values else initial)
    peak_equity = paper.get("peak_equity") or max([initial, *equity_values]) if equity_values else initial

    max_dd_frac = abs(paper.get("max_drawdown_pct", 0) or 0) / 100
    if not max_dd_frac:
        peak = initial
        max_dd = 0
        for eq in equity_values:
            if eq > peak:
                peak = eq
            dd = (eq - peak) / peak if peak > 0 else 0
            if dd < max_dd:
                max_dd = dd
        max_dd_frac = abs(max_dd)

    sleeve_pnl = paper.get("sleeve_allocation") or {s: 0 for s in SLEEVE_NAMES}

    net_pnl = paper.get("net_pnl")
    if net_pnl is None:
        net_pnl = current_equity - initial
    net_pnl_pct = paper.get("net_pnl_pct")
    if net_pnl_pct is None:
        net_pnl_pct = (current_equity / initial - 1) if initial else 0

    return {
        "labels": labels,
        "equity": equity_values or [initial],
        "initial_capital": initial,
        "current_equity": current_equity,
        "peak_equity": peak_equity,
        "net_pnl": net_pnl,
        "net_pnl_pct": net_pnl_pct,
        "current_dd": -max_dd_frac,
        "max_dd": max_dd_frac,
        "sleeve_pnl": sleeve_pnl,
        "positions": paper.get("positions", []),
        "execution_paper": paper.get("execution_paper", {"enabled": False}),
        "execution_labels": (paper.get("execution_paper") or {}).get("labels")
        or labels,
        "execution_equity": (paper.get("execution_paper") or {}).get("equity_curve")
        or [d.get("execution_equity") for d in daily if d.get("execution_equity") is not None]
        or ([initial, (paper.get("execution_paper") or {}).get("equity")] if (paper.get("execution_paper") or {}).get("equity") is not None else [initial]),
        "ann_return": paper.get("ann_return"),
        "sharpe": paper.get("sharpe"),
        "walk_forward": [],
        "last_updated": paper.get("updated_at"),
        "last_processed_at": paper.get("last_processed_at"),
        "paper_status": paper.get("status", "RUNNING"),
        "circuit_breaker": paper.get("circuit_breaker", {}),
    }


def process_backtest_data(bt):
    meta = bt.get("meta", {})
    baseline = bt.get("baseline", {})
    weights = bt.get("weights", {})
    wf = bt.get("walk_forward", {})

    n_days = min(meta.get("n_days", 1192), 1192)
    equity_curve = generate_backtest_equity(baseline.get("total_ret", 8.0), n_days)
    n = len(equity_curve)
    labels = [f"Day {int(i * n_days / n)}" for i in range(n)]

    maxdd = abs(baseline.get("maxdd", -0.38))

    wf_results = []
    for name, split in wf.items():
        wf_results.append(
            {
                "config": name.replace("_", " "),
                "train_ann": split.get("train", {}).get("ann", 0),
                "train_sharpe": split.get("train", {}).get("sharpe", 0),
                "train_dd": split.get("train", {}).get("maxdd", 0),
                "test_ann": split.get("test", {}).get("ann", 0),
                "test_sharpe": split.get("test", {}).get("sharpe", 0),
                "test_dd": split.get("test", {}).get("maxdd", 0),
                "both_positive": split.get("both_positive", False),
            }
        )

    return {
        "labels": labels,
        "equity": equity_curve,
        "initial_capital": 1.0,
        "current_equity": equity_curve[-1] if equity_curve else 1.0,
        "current_dd": 0,
        "max_dd": maxdd,
        "sleeve_pnl": {s: weights.get(s, 0) for s in SLEEVE_NAMES},
        "positions": [],
        "meta": meta,
        "baseline": baseline,
        "weights": weights,
        "walk_forward": wf_results,
        "ann_return": baseline.get("ann"),
        "sharpe": baseline.get("sharpe"),
    }


def dd_status(dd_frac):
    ad = abs(dd_frac)
    if ad < DD_GREEN:
        return "green", "NOMINAL"
    if ad < DD_YELLOW:
        return "yellow", "ELEVATED DD"
    return "red", "CRITICAL DD"


def fmt_pct(v):
    if v is None:
        return "—"
    return f"{v * 100:.1f}%"


def fmt_num(v, decimals=2):
    if v is None:
        return "—"
    return f"{v:.{decimals}f}"


def fmt_money(v):
    if v is None:
        return "—"
    sign = "-" if v < 0 else ""
    return f"{sign}${abs(v):,.2f}"


def fmt_signed_money(v):
    if v is None:
        return "—"
    sign = "+" if v >= 0 else "-"
    return f"{sign}${abs(v):,.2f}"


# ---------------------------------------------------------------------------
# HTML Template
# ---------------------------------------------------------------------------
PAGE_TEMPLATE = Template(
    r'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>4-Sleeve Ensemble Dashboard</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
  :root {
    color-scheme: dark;
    --bg: #070910;
    --bg-2: #0a0d15;
    --panel: rgba(19, 23, 35, 0.78);
    --panel-strong: rgba(24, 29, 43, 0.96);
    --panel-soft: rgba(255, 255, 255, 0.035);
    --border: rgba(255, 255, 255, 0.09);
    --border-strong: rgba(255, 255, 255, 0.16);
    --text: #e7ecf5;
    --muted: #94a0b8;
    --faint: #657089;
    --green: #39d98a;
    --yellow: #f5c451;
    --red: #ff5e70;
    --blue: #5ec8ff;
    --violet: #8f7aff;
    --shadow: 0 18px 60px rgba(0, 0, 0, 0.35);
    --radius-lg: 24px;
    --radius-md: 18px;
    --radius-sm: 12px;
  }

  * { box-sizing: border-box; }
  html { min-height: 100%; background: var(--bg); overflow-x: hidden; }
  body {
    min-height: 100vh;
    margin: 0;
    overflow-x: hidden;
    color: var(--text);
    font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
    background:
      radial-gradient(circle at top left, rgba(94, 200, 255, 0.16), transparent 34rem),
      radial-gradient(circle at 85% 10%, rgba(143, 122, 255, 0.18), transparent 30rem),
      linear-gradient(180deg, #090c14 0%, #070910 44%, #06080e 100%);
  }

  .page {
    width: min(1240px, 100%);
    margin: 0 auto;
    padding: max(16px, env(safe-area-inset-top)) clamp(14px, 3vw, 32px) 32px;
  }

  .hero {
    position: relative;
    display: grid;
    gap: 18px;
    padding: clamp(20px, 4vw, 38px);
    margin: 4px 0 18px;
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    background:
      linear-gradient(135deg, rgba(255, 255, 255, 0.085), rgba(255, 255, 255, 0.018)),
      linear-gradient(135deg, rgba(94, 200, 255, 0.08), rgba(143, 122, 255, 0.055));
    box-shadow: var(--shadow), inset 0 1px 0 rgba(255, 255, 255, 0.08);
    overflow: hidden;
  }
  .hero::after {
    content: "";
    position: absolute;
    right: 0;
    bottom: -42%;
    left: 42%;
    height: 210px;
    border-radius: 999px;
    background: rgba(94, 200, 255, 0.10);
    filter: blur(42px);
    pointer-events: none;
  }
  .hero-top {
    position: relative;
    z-index: 1;
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 18px;
  }
  .eyebrow {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    width: fit-content;
    padding: 7px 10px;
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 999px;
    background: rgba(0, 0, 0, 0.22);
    color: #cbd6ea;
    font-size: 0.72rem;
    font-weight: 800;
    letter-spacing: 0.11em;
    text-transform: uppercase;
  }
  h1 {
    margin: 12px 0 8px;
    max-width: 820px;
    color: #ffffff;
    font-size: clamp(2.05rem, 8vw, 4.6rem);
    line-height: 0.95;
    letter-spacing: -0.065em;
    text-wrap: balance;
  }
  .subtitle {
    max-width: 760px;
    margin: 0;
    color: var(--muted);
    font-size: clamp(0.95rem, 2.4vw, 1.15rem);
    line-height: 1.55;
  }
  .hero-side {
    display: grid;
    justify-items: end;
    gap: 10px;
    min-width: min(270px, 36vw);
  }

  .status-row, .banner-row {
    display: flex;
    align-items: center;
    justify-content: flex-start;
    flex-wrap: wrap;
    gap: 10px;
  }
  .status-pill, .banner {
    display: inline-flex;
    min-height: 38px;
    align-items: center;
    gap: 8px;
    border-radius: 999px;
    font-size: 0.76rem;
    font-weight: 800;
    letter-spacing: 0.03em;
    white-space: nowrap;
  }
  .status-pill {
    padding: 8px 12px;
    border: 1px solid var(--border);
    background: rgba(255, 255, 255, 0.05);
    color: #dfe8f8;
  }
  .status-dot { width: 10px; height: 10px; flex: 0 0 auto; border-radius: 50%; display: inline-block; }
  .dot-green { background: var(--green); box-shadow: 0 0 14px rgba(57, 217, 138, 0.55); }
  .dot-yellow { background: var(--yellow); box-shadow: 0 0 14px rgba(245, 196, 81, 0.50); }
  .dot-red { background: var(--red); box-shadow: 0 0 14px rgba(255, 94, 112, 0.55); animation: pulse 1.45s infinite; }
  @keyframes pulse { 0%, 100% { opacity: 1; transform: scale(1); } 50% { opacity: .56; transform: scale(.84); } }

  .banner {
    padding: 8px 12px;
    border: 1px solid rgba(255, 255, 255, 0.10);
    background: rgba(255, 255, 255, 0.045);
  }
  .banner-paper { color: #ffd7dd; border-color: rgba(255, 94, 112, 0.35); background: rgba(255, 94, 112, 0.11); }
  .banner-canary { color: #ffe9a8; border-color: rgba(245, 196, 81, 0.34); background: rgba(245, 196, 81, 0.10); }

  .view-switcher {
    position: sticky;
    top: max(10px, env(safe-area-inset-top));
    z-index: 20;
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 10px;
    margin: 0 0 16px;
    padding: 8px;
    border: 1px solid var(--border);
    border-radius: 999px;
    background: rgba(8, 11, 19, 0.82);
    box-shadow: var(--shadow), inset 0 1px 0 rgba(255,255,255,0.08);
    backdrop-filter: blur(18px);
  }
  .view-button {
    min-height: 48px;
    border: 0;
    border-radius: 999px;
    background: rgba(255,255,255,0.055);
    color: var(--muted);
    font: inherit;
    font-weight: 900;
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 9px;
    letter-spacing: 0.01em;
  }
  .view-button[aria-pressed="true"] {
    background: linear-gradient(135deg, rgba(94,200,255,0.28), rgba(143,122,255,0.24));
    color: #fff;
    box-shadow: inset 0 1px 0 rgba(255,255,255,0.16), 0 0 24px rgba(94,200,255,0.16);
  }
  .view-icon { font-size: 1.1rem; line-height: 1; }
  .paper-view { display: none; }
  .paper-view.active { display: block; }

  .metric-grid {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 14px;
    margin: 18px 0;
  }
  .metric-card, .panel {
    border: 1px solid var(--border);
    background: var(--panel);
    box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.055);
    backdrop-filter: blur(16px);
  }
  .metric-card {
    min-width: 0;
    border-radius: var(--radius-md);
    padding: clamp(15px, 2.2vw, 22px);
  }
  .metric-label {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    margin-bottom: 12px;
    color: var(--muted);
    font-size: 0.72rem;
    font-weight: 800;
    letter-spacing: 0.085em;
    text-transform: uppercase;
  }
  .metric-value {
    color: #ffffff;
    font-size: clamp(1.55rem, 5vw, 2.35rem);
    font-weight: 800;
    line-height: 1;
    letter-spacing: -0.055em;
    font-variant-numeric: tabular-nums;
  }
  .metric-value.danger { color: var(--red); }
  .metric-sub { margin-top: 8px; color: var(--faint); font-size: 0.78rem; }

  .panel {
    border-radius: var(--radius-lg);
    padding: clamp(16px, 2.6vw, 22px);
    margin-bottom: 16px;
  }
  .panel-header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 16px;
    margin-bottom: 16px;
  }
  .panel-title { margin: 0; color: #ffffff; font-size: clamp(1rem, 2vw, 1.15rem); letter-spacing: -0.02em; }
  .panel-note { margin: 4px 0 0; color: var(--faint); font-size: 0.82rem; line-height: 1.35; }
  .chart-shell { position: relative; height: clamp(280px, 44vh, 430px); width: 100%; }
  #modelEquityChart, #executionEquityChart { width: 100% !important; height: 100% !important; }

  .two-col {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
    gap: 16px;
  }
  .sleeve-stack { display: grid; gap: 13px; }
  .sleeve-bar {
    display: grid;
    grid-template-columns: minmax(108px, 0.8fr) minmax(120px, 1.6fr) minmax(56px, auto);
    align-items: center;
    gap: 10px;
  }
  .sleeve-name { color: #e8eef9; font-size: 0.88rem; font-weight: 700; min-width: 0; overflow: hidden; text-overflow: ellipsis; }
  .sleeve-bar-track {
    position: relative;
    height: 11px;
    overflow: hidden;
    border-radius: 999px;
    background: rgba(255, 255, 255, 0.055);
  }
  .sleeve-bar-fill { height: 100%; min-width: 4px; border-radius: 999px; box-shadow: 0 0 16px color-mix(in srgb, currentColor 35%, transparent); }
  .sleeve-value { color: #dfe8f8; text-align: right; font-size: 0.86rem; font-weight: 800; font-variant-numeric: tabular-nums; }

  .no-data {
    display: grid;
    place-items: center;
    min-height: 154px;
    padding: 22px;
    border: 1px dashed rgba(255, 255, 255, 0.12);
    border-radius: var(--radius-md);
    color: var(--muted);
    text-align: center;
    line-height: 1.5;
  }
  .no-data strong { color: #fff; }

  .table-wrap { width: 100%; overflow: visible; }
  table { width: 100%; border-collapse: collapse; font-size: 0.86rem; }
  th {
    text-align: left;
    padding: 11px 12px;
    border-bottom: 1px solid var(--border-strong);
    color: var(--muted);
    font-size: 0.70rem;
    font-weight: 900;
    letter-spacing: 0.08em;
    text-transform: uppercase;
  }
  td { padding: 12px; border-bottom: 1px solid rgba(255,255,255,0.055); color: #d9e2f2; }
  td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
  .pos { color: var(--green); }
  .neg { color: var(--red); }
  .check { color: var(--green); font-weight: 900; }
  .config-cell { color: #ffffff; font-weight: 700; }

  .footer {
    margin-top: 18px;
    padding: 18px 4px 4px;
    border-top: 1px solid var(--border);
    color: var(--faint);
    font-size: 0.78rem;
    line-height: 1.55;
    text-align: center;
  }
  .footer strong { color: var(--muted); }

  @media (max-width: 980px) {
    .hero-top { display: grid; }
    .hero-side { justify-items: start; min-width: 0; }
    .metric-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .two-col { grid-template-columns: 1fr; }
  }

  @media (max-width: 720px) {
    .page { padding-left: 12px; padding-right: 12px; }
    .hero { border-radius: 22px; padding: 18px; }
    h1 { margin-top: 10px; }
    .subtitle { font-size: 0.95rem; }
    .status-row, .banner-row { display: grid; grid-template-columns: 1fr; width: 100%; }
    .status-pill, .banner { width: 100%; justify-content: center; white-space: normal; text-align: center; }
    .metric-grid { gap: 10px; margin: 12px 0; }
    .metric-card { border-radius: 16px; padding: 14px; }
    .metric-label { min-height: 2.1em; align-items: flex-start; font-size: 0.66rem; }
    .metric-value { font-size: clamp(1.45rem, 10vw, 2.1rem); }
    .panel { border-radius: 18px; padding: 14px; }
    .panel-header { display: grid; gap: 4px; margin-bottom: 12px; }
    .chart-shell { height: 300px; }
    .sleeve-bar { grid-template-columns: 1fr auto; gap: 8px 10px; }
    .sleeve-bar-track { grid-column: 1 / -1; grid-row: 2; }
    .sleeve-value { grid-column: 2; grid-row: 1; }
    .table-wrap { overflow: visible; }
    table, thead, tbody, tr, th, td { display: block; }
    thead { display: none; }
    tr {
      margin: 0 0 12px;
      padding: 12px;
      border: 1px solid var(--border);
      border-radius: 16px;
      background: rgba(255, 255, 255, 0.032);
    }
    td {
      display: flex;
      justify-content: space-between;
      gap: 14px;
      padding: 8px 0;
      border-bottom: 1px solid rgba(255, 255, 255, 0.055);
      text-align: right !important;
    }
    td:last-child { border-bottom: 0; }
    td::before {
      content: attr(data-label);
      flex: 0 0 auto;
      color: var(--faint);
      text-align: left;
      font-size: 0.69rem;
      font-weight: 900;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }
    .config-cell { display: block; text-align: left !important; font-size: 1rem; }
    .config-cell::before { display: block; margin-bottom: 4px; }
  }

  @media (max-width: 340px) {
    .metric-grid { grid-template-columns: 1fr; }
    .chart-shell { height: 260px; }
    .eyebrow { font-size: 0.66rem; }
  }

  @media (prefers-reduced-motion: reduce) {
    *, *::before, *::after { animation-duration: 0.01ms !important; animation-iteration-count: 1 !important; scroll-behavior: auto !important; }
  }
</style>
</head>
<body>
<div class="page">
  <header class="hero">
    <div class="hero-top">
      <div>
        <div class="eyebrow">SD-009 · paper canary</div>
        <h1>4-Sleeve Ensemble</h1>
        <p class="subtitle">A read-only monitor for the tangency portfolio: CrossSecMom, EMATrend, Grid, and FundContrarian. Built for quick mobile checks without hiding the risk warnings.</p>
      </div>
      <div class="hero-side" aria-label="Current safety and data source">
        <div class="status-row">
          <span class="status-pill"><span id="dd-dot" class="status-dot dot-$dd_color"></span><span id="dd-label">$dd_label</span></span>
          <span class="status-pill"><span id="source-dot" class="status-dot dot-$source_color"></span><span id="source-label">$source</span></span>
        </div>
        <div class="banner-row">
          <span class="banner banner-paper">⚠ Paper only — no live capital</span>
          <span class="banner banner-canary">🔬 Research canary</span>
        </div>
      </div>
    </div>
  </header>

  <nav class="view-switcher" aria-label="Paper dashboard views">
    <button type="button" class="view-button" data-view="model" aria-controls="model-paper-view" aria-pressed="true"><span class="view-icon">📈</span><span>Model Paper</span></button>
    <button type="button" class="view-button" data-view="execution" aria-controls="execution-paper-view" aria-pressed="false"><span class="view-icon">⚙</span><span>Execution Paper</span></button>
  </nav>

  <main id="model-paper-view" class="paper-view active" aria-label="Model paper page">
    <section class="metric-grid" aria-label="Model paper metrics">
      <article class="metric-card">
        <div id="metric1-label" class="metric-label">$metric1_label</div>
        <div id="metric1-value" class="metric-value">$metric1_value</div>
        <div id="metric1-sub" class="metric-sub">$metric1_sub</div>
      </article>
      <article class="metric-card">
        <div id="metric2-label" class="metric-label">$metric2_label</div>
        <div id="metric2-value" class="metric-value $metric2_class">$metric2_value</div>
        <div id="metric2-sub" class="metric-sub">$metric2_sub</div>
      </article>
      <article class="metric-card">
        <div id="metric3-label" class="metric-label">$metric3_label</div>
        <div id="metric3-value" class="metric-value danger">$metric3_value</div>
        <div id="metric3-sub" class="metric-sub">$metric3_sub</div>
      </article>
      <article class="metric-card">
        <div id="metric4-label" class="metric-label">$metric4_label</div>
        <div id="metric4-value" class="metric-value">$metric4_value</div>
        <div id="metric4-sub" class="metric-sub">$metric4_sub</div>
      </article>
    </section>

    <section class="panel" aria-label="Model paper equity curve">
      <div class="panel-header">
        <div>
          <h2 class="panel-title">Model Paper Equity Curve</h2>
          <p id="equity-note" class="panel-note">$equity_note</p>
        </div>
      </div>
      <div class="chart-shell"><canvas id="modelEquityChart"></canvas></div>
    </section>

    <section class="two-col">
      <article class="panel">
        <div class="panel-header">
          <div>
            <h2 class="panel-title">Sleeve Allocation / P&amp;L</h2>
            <p class="panel-note">Frozen sleeve weights or accumulated paper P&amp;L, depending on data source.</p>
          </div>
        </div>
        <div id="sleeve-stack" class="sleeve-stack">$sleeve_bars_html</div>
      </article>
      <article class="panel">
        <div class="panel-header">
          <div>
            <h2 class="panel-title">Model paper trades</h2>
            <p class="panel-note">Model-paper trade/position state. Read-only; this page cannot place orders.</p>
          </div>
        </div>
        <div id="positions-panel">$positions_html</div>
      </article>
    </section>

    $walk_forward_html
  </main>

  <main id="execution-paper-view" class="paper-view" aria-label="Execution paper page">
    <section class="metric-grid" aria-label="Execution paper metrics">$execution_metric_cards_html</section>

    <section class="panel" aria-label="Execution paper equity curve">
      <div class="panel-header">
        <div>
          <h2 class="panel-title">Execution equity curve</h2>
          <p class="panel-note">Execution-paper account value after simulated fills, fees, slippage, and mark-to-market.</p>
        </div>
      </div>
      <div class="chart-shell"><canvas id="executionEquityChart"></canvas></div>
    </section>

    <section class="panel" aria-label="Execution paper account">
      <div class="panel-header">
        <div>
          <h2 class="panel-title">Execution Paper Account</h2>
          <p class="panel-note">Simulated exchange-style fills, fees, slippage, positions, and cash ledger. Still paper-only — no live orders.</p>
        </div>
      </div>
      <div id="execution-paper-panel">$execution_paper_html</div>
    </section>
  </main>

  <footer class="footer">
    <strong>READ-ONLY DISPLAY · NO TRADING · NO ORDERS · RESEARCH ONLY</strong><br>
    Data: <span id="footer-source">$source</span> · Generated <span id="footer-generated">$generated_at</span>
  </footer>
</div>

<script>
const modelLabels = $chart_labels;
const modelEquityData = $chart_data;
const executionLabels = $execution_chart_labels;
const executionEquityData = $execution_chart_data;
const isSmallScreen = window.matchMedia('(max-width: 720px)').matches;
const moneyFmt = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' });
const pctFmt = new Intl.NumberFormat('en-US', { style: 'percent', minimumFractionDigits: 1, maximumFractionDigits: 1 });

function fmtMoney(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '—';
  return moneyFmt.format(Number(value));
}
function fmtSignedMoney(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '—';
  const n = Number(value);
  return (n >= 0 ? '+' : '-') + moneyFmt.format(Math.abs(n));
}
function fmtPct(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '—';
  return pctFmt.format(Number(value));
}
function setText(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = value;
}
function setMetric(id, label, value, sub) {
  setText('metric' + id + '-label', label);
  setText('metric' + id + '-value', value);
  setText('metric' + id + '-sub', sub || '');
}
function setDot(id, color) {
  const el = document.getElementById(id);
  if (!el) return;
  el.className = 'status-dot dot-' + color;
}
function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>'"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]));
}
function fmtNum(value, digits = 6) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '—';
  return Number(value).toFixed(digits);
}
function tableHtml(headers, rows, emptyMessage) {
  if (!rows || rows.length === 0) {
    return '<div class="no-data"><div><strong>' + escapeHtml(emptyMessage) + '</strong></div></div>';
  }
  const head = headers.map(h => '<th' + (h.num ? ' class="num"' : '') + '>' + escapeHtml(h.label) + '</th>').join('');
  const body = rows.map(row => '<tr>' + headers.map(h => '<td data-label="' + escapeHtml(h.label) + '" class="' + (h.num ? 'num ' : '') + escapeHtml(row[h.key + '_class'] || '') + '">' + escapeHtml(row[h.key] ?? '') + '</td>').join('') + '</tr>').join('');
  return '<div class="table-wrap"><table><thead><tr>' + head + '</tr></thead><tbody>' + body + '</tbody></table></div>';
}
function renderModelTrades(data) {
  const rows = (data.positions || []).map(p => {
    const pnl = Number(p.pnl || 0);
    return {
      symbol: p.symbol || '',
      symbol_class: 'config-cell',
      sleeve: p.sleeve || '',
      side: p.side || '',
      size: typeof p.size === 'number' ? fmtMoney(p.size) : (p.size || ''),
      pnl: typeof p.pnl === 'number' ? fmtSignedMoney(p.pnl) : (p.pnl || ''),
      pnl_class: pnl >= 0 ? 'pos' : 'neg',
    };
  });
  document.getElementById('positions-panel').innerHTML = tableHtml([
    {key:'symbol', label:'Symbol'}, {key:'sleeve', label:'Sleeve'}, {key:'side', label:'Side'},
    {key:'size', label:'Size', num:true}, {key:'pnl', label:'PnL', num:true},
  ], rows, 'No live model-paper trades.');
}
function renderExecutionPositions(executionPaper) {
  const rows = (executionPaper.positions || []).map(p => {
    const upnl = Number(p.unrealized_pnl || 0);
    return {
      symbol: p.symbol || '',
      symbol_class: 'config-cell',
      side: p.side || '',
      quantity: fmtNum(p.quantity, 6),
      avg_entry_price: fmtNum(p.avg_entry_price, 6),
      mark_price: fmtNum(p.mark_price, 6),
      notional: fmtMoney(p.notional),
      unrealized_pnl: fmtSignedMoney(upnl),
      unrealized_pnl_class: upnl >= 0 ? 'pos' : 'neg',
    };
  });
  document.getElementById('execution-positions-panel').innerHTML = tableHtml([
    {key:'symbol', label:'Symbol'}, {key:'side', label:'Side'}, {key:'quantity', label:'Qty', num:true},
    {key:'avg_entry_price', label:'Entry', num:true}, {key:'mark_price', label:'Mark', num:true},
    {key:'notional', label:'Notional', num:true}, {key:'unrealized_pnl', label:'UPnL', num:true},
  ], rows, 'No simulated execution positions.');
}
function renderExecutionFills(executionPaper) {
  const rows = (executionPaper.ledger || []).slice(-20).map(f => ({
    symbol: f.symbol || '',
    symbol_class: 'config-cell',
    side: f.side || '',
    quantity: fmtNum(f.quantity, 6),
    fill_price: fmtNum(f.fill_price, 6),
    notional: fmtMoney(f.notional),
    fee: fmtMoney(f.fee),
    reason: f.reason || '',
  }));
  document.getElementById('execution-fills-panel').innerHTML = tableHtml([
    {key:'symbol', label:'Symbol'}, {key:'side', label:'Side'}, {key:'quantity', label:'Qty', num:true},
    {key:'fill_price', label:'Fill', num:true}, {key:'notional', label:'Notional', num:true},
    {key:'fee', label:'Fee', num:true}, {key:'reason', label:'Reason'},
  ], rows, 'No simulated fills yet.');
}
function updateExecutionMetrics(executionPaper) {
  const ep = executionPaper || {};
  const pnl = Number(ep.net_pnl || 0);
  setText('execution-metric-equity', fmtMoney(ep.equity));
  setText('execution-metric-equity-sub', 'simulated fill account');
  const pnlEl = document.getElementById('execution-metric-pnl');
  if (pnlEl) {
    pnlEl.textContent = fmtSignedMoney(pnl);
    pnlEl.classList.toggle('pos', pnl >= 0);
    pnlEl.classList.toggle('neg', pnl < 0);
  }
  setText('execution-metric-pnl-sub', fmtPct(ep.net_pnl_pct));
  setText('execution-metric-cash', fmtMoney(ep.available_cash ?? ep.cash));
  setText('execution-metric-cash-sub', fmtMoney(ep.short_collateral) + ' reserved for shorts');
  setText('execution-metric-positions', String((ep.positions || []).length));
  setText('execution-metric-positions-sub', String((ep.ledger || []).length) + ' ledger rows');
}

function makeEquityChart(canvasId, labels, data, color, fill) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return null;
  return new Chart(canvas.getContext('2d'), {
    type: 'line',
    data: {
      labels,
      datasets: [{
        label: 'Equity',
        data,
        borderColor: color,
        backgroundColor: fill,
        borderWidth: isSmallScreen ? 2.4 : 3.4,
        fill: true,
        tension: 0.32,
        pointRadius: 0,
        pointHoverRadius: 4,
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      interaction: { intersect: false, mode: 'index' },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: 'rgba(14, 18, 29, 0.98)',
          borderColor: 'rgba(255,255,255,0.14)',
          borderWidth: 1,
          titleColor: '#ffffff',
          bodyColor: '#dfe8f8',
          displayColors: false,
          padding: 12,
        }
      },
      scales: {
        x: {
          ticks: { color: '#657089', maxTicksLimit: isSmallScreen ? 5 : 9, maxRotation: 0 },
          grid: { color: 'rgba(255,255,255,0.045)' },
          border: { color: 'rgba(255,255,255,0.08)' }
        },
        y: {
          ticks: { color: '#657089', maxTicksLimit: isSmallScreen ? 5 : 7 },
          grid: { color: 'rgba(255,255,255,0.045)' },
          border: { color: 'rgba(255,255,255,0.08)' }
        }
      }
    }
  });
}

const modelEquityChart = makeEquityChart('modelEquityChart', modelLabels, modelEquityData, '#7ddcff', 'rgba(94, 200, 255, 0.22)');
const executionEquityChart = makeEquityChart('executionEquityChart', executionLabels, executionEquityData, '#39d98a', 'rgba(57, 217, 138, 0.18)');

function showPaperView(view) {
  const selected = view === 'execution' ? 'execution' : 'model';
  document.querySelectorAll('.paper-view').forEach(el => el.classList.toggle('active', el.id === selected + '-paper-view'));
  document.querySelectorAll('.view-button').forEach(btn => btn.setAttribute('aria-pressed', String(btn.dataset.view === selected)));
  localStorage.setItem('paperView', selected);
  setTimeout(() => {
    if (modelEquityChart) modelEquityChart.resize();
    if (executionEquityChart) executionEquityChart.resize();
  }, 0);
}
document.querySelectorAll('.view-button').forEach(btn => btn.addEventListener('click', () => showPaperView(btn.dataset.view)));
showPaperView(localStorage.getItem('paperView') || 'model');

function applyLiveData(data) {
  if (!data || !data.is_live) return;
  if (modelEquityChart) {
    modelEquityChart.data.labels = data.labels || [];
    modelEquityChart.data.datasets[0].data = data.equity || [];
    modelEquityChart.update('none');
  }
  if (executionEquityChart) {
    const ep = data.execution_paper || {};
    executionEquityChart.data.labels = data.execution_labels || ep.labels || data.labels || [];
    executionEquityChart.data.datasets[0].data = data.execution_equity || ep.equity_curve || [data.initial_capital, ep.equity].filter(v => v !== undefined && v !== null);
    executionEquityChart.update('none');
  }

  const ep = data.execution_paper || {};
  updateExecutionMetrics(ep);
  renderModelTrades(data);
  renderExecutionPositions(ep);
  renderExecutionFills(ep);

  setMetric(1, 'Paper equity', fmtMoney(data.current_equity), 'started from ' + fmtMoney(data.initial_capital));
  setMetric(2, 'Paper P&L', fmtSignedMoney(data.net_pnl), fmtPct(data.net_pnl_pct));
  setMetric(3, 'Max drawdown', fmtPct(data.max_dd), 'paper canary');
  setMetric(4, 'Status', data.paper_status || 'RUNNING', 'updated ' + (data.last_updated || '—'));
  setText('equity-note', 'Live $$2,000 paper equity. Auto-refreshes every 15 seconds; equity changes only when the paper runner processes a new candle.');
  setText('source-label', data.source || 'LIVE PAPER RUNNER');
  setText('footer-source', data.source || 'LIVE PAPER RUNNER');
  setText('footer-generated', data.last_updated || new Date().toISOString());
  setDot('source-dot', 'green');

  const dd = Math.abs(Number(data.max_dd || 0));
  const ddColor = dd < 0.10 ? 'green' : (dd < 0.20 ? 'yellow' : 'red');
  setDot('dd-dot', ddColor);
  setText('dd-label', dd < 0.10 ? 'NOMINAL' : (dd < 0.20 ? 'ELEVATED DD' : 'CRITICAL DD'));
}

async function refreshPaperData() {
  try {
    const response = await fetch('/api/data?ts=' + Date.now(), { cache: 'no-store' });
    if (!response.ok) return;
    const data = await response.json();
    applyLiveData(data);
  } catch (err) {
    console.warn('paper dashboard refresh failed', err);
  }
}

setInterval(refreshPaperData, 15000);
refreshPaperData();
</script>
</body>
</html>'''
)


@app.route("/")
def dashboard():
    data, source, is_live = get_data_source()

    if is_live:
        processed = process_live_data(data)
    elif data:
        processed = process_backtest_data(data)
    else:
        processed = {
            "labels": [],
            "equity": [],
            "initial_capital": 0,
            "current_equity": 0,
            "current_dd": 0,
            "max_dd": 0,
            "sleeve_pnl": {s: 0 for s in SLEEVE_NAMES},
            "positions": [],
            "ann_return": None,
            "sharpe": None,
            "walk_forward": [],
        }

    dd_color, dd_label = dd_status(processed.get("current_dd", 0))
    source_color = "green" if is_live else "yellow"

    sp = processed.get("sleeve_pnl", {s: 0 for s in SLEEVE_NAMES})
    max_sleeve = max((abs(v) for v in sp.values()), default=1) or 1
    sleeve_bars = []
    for s in SLEEVE_NAMES:
        val = sp.get(s, 0)
        pct = (abs(val) / max_sleeve * 100) if max_sleeve > 0 else 0
        color = SLEEVE_COLORS.get(s, "#5ec8ff")
        cls = "pos" if val >= 0 else "neg"
        sleeve_bars.append(
            '<div class="sleeve-bar">'
            f'<span class="sleeve-name">{escape(s)}</span>'
            f'<div class="sleeve-bar-track"><div class="sleeve-bar-fill" style="width:{pct:.0f}%;background:{color}"></div></div>'
            f'<span class="sleeve-value {cls}">{val * 100:.1f}%</span>'
            '</div>'
        )

    positions = processed.get("positions", [])
    if positions:
        pos_rows = []
        for p in positions:
            pnl = p.get("pnl", 0)
            cls = "pos" if pnl >= 0 else "neg"
            size = p.get("size", "")
            size_display = fmt_money(size) if isinstance(size, (int, float)) else str(size)
            pnl_display = fmt_signed_money(pnl) if isinstance(pnl, (int, float)) else str(pnl)
            pos_rows.append(
                "<tr>"
                f"<td data-label='Symbol' class='config-cell'>{escape(str(p.get('symbol', '')))}</td>"
                f"<td data-label='Sleeve'>{escape(str(p.get('sleeve', '')))}</td>"
                f"<td data-label='Side'>{escape(str(p.get('side', '')))}</td>"
                f"<td data-label='Size' class='num'>{escape(size_display)}</td>"
                f"<td data-label='PnL' class='num {cls}'>{escape(pnl_display)}</td>"
                "</tr>"
            )
        positions_html = (
            '<div class="table-wrap"><table><thead><tr>'
            '<th>Symbol</th><th>Sleeve</th><th>Side</th>'
            '<th class="num">Size</th><th class="num">PnL</th>'
            '</tr></thead><tbody>'
            + "".join(pos_rows)
            + "</tbody></table></div>"
        )
    else:
        empty_line = "No active paper positions right now." if is_live else "Paper runner not connected to this dashboard yet."
        positions_html = f'<div class="no-data"><div><strong>No live positions.</strong><br>{empty_line}</div></div>'

    execution_paper = processed.get("execution_paper") or {}
    if execution_paper.get("enabled"):
        exec_net = execution_paper.get("net_pnl", 0)
        exec_cls = "pos" if isinstance(exec_net, (int, float)) and exec_net >= 0 else "neg"
        exec_summary = (
            '<div class="metric-grid" style="margin-bottom:18px">'
            '<article class="metric-card">'
            '<div class="metric-label">Execution equity</div>'
            f'<div class="metric-value">{escape(fmt_money(execution_paper.get("equity")))}</div>'
            '<div class="metric-sub">simulated fill account</div>'
            '</article>'
            '<article class="metric-card">'
            '<div class="metric-label">Execution P&amp;L</div>'
            f'<div class="metric-value {exec_cls}">{escape(fmt_signed_money(exec_net))}</div>'
            f'<div class="metric-sub">{escape(fmt_pct(execution_paper.get("net_pnl_pct")))}</div>'
            '</article>'
            '<article class="metric-card">'
            '<div class="metric-label">Available cash</div>'
            f'<div class="metric-value">{escape(fmt_money(execution_paper.get("available_cash", execution_paper.get("cash"))))}</div>'
            f'<div class="metric-sub">{escape(fmt_money(execution_paper.get("short_collateral")))} reserved for shorts</div>'
            '</article>'
            '<article class="metric-card">'
            '<div class="metric-label">Ledger rows</div>'
            f'<div class="metric-value">{len(execution_paper.get("ledger") or [])}</div>'
            f'<div class="metric-sub">{len(execution_paper.get("positions") or [])} open paper positions</div>'
            '</article>'
            '</div>'
        )

        exec_pos_rows = []
        for p in (execution_paper.get("positions") or [])[:20]:
            upnl = p.get("unrealized_pnl", 0)
            cls = "pos" if isinstance(upnl, (int, float)) and upnl >= 0 else "neg"
            exec_pos_rows.append(
                "<tr>"
                f"<td data-label='Symbol' class='config-cell'>{escape(str(p.get('symbol', '')))}</td>"
                f"<td data-label='Side'>{escape(str(p.get('side', '')))}</td>"
                f"<td data-label='Qty' class='num'>{escape(fmt_num(p.get('quantity'), 6))}</td>"
                f"<td data-label='Entry' class='num'>{escape(fmt_num(p.get('avg_entry_price'), 6))}</td>"
                f"<td data-label='Mark' class='num'>{escape(fmt_num(p.get('mark_price'), 6))}</td>"
                f"<td data-label='Notional' class='num'>{escape(fmt_money(p.get('notional')))}</td>"
                f"<td data-label='UPnL' class='num {cls}'>{escape(fmt_signed_money(upnl))}</td>"
                "</tr>"
            )
        exec_positions_table = (
            '<div id="execution-positions-panel"><div class="table-wrap"><table><thead><tr>'
            '<th>Symbol</th><th>Side</th><th class="num">Qty</th><th class="num">Entry</th><th class="num">Mark</th><th class="num">Notional</th><th class="num">UPnL</th>'
            '</tr></thead><tbody>' + "".join(exec_pos_rows) + '</tbody></table></div></div>'
            if exec_pos_rows
            else '<div id="execution-positions-panel"><div class="no-data"><div><strong>No simulated execution positions.</strong></div></div></div>'
        )

        exec_fill_rows = []
        for f in (execution_paper.get("ledger") or [])[-20:]:
            exec_fill_rows.append(
                "<tr>"
                f"<td data-label='Symbol' class='config-cell'>{escape(str(f.get('symbol', '')))}</td>"
                f"<td data-label='Side'>{escape(str(f.get('side', '')))}</td>"
                f"<td data-label='Qty' class='num'>{escape(fmt_num(f.get('quantity'), 6))}</td>"
                f"<td data-label='Fill' class='num'>{escape(fmt_num(f.get('fill_price'), 6))}</td>"
                f"<td data-label='Notional' class='num'>{escape(fmt_money(f.get('notional')))}</td>"
                f"<td data-label='Fee' class='num'>{escape(fmt_money(f.get('fee')))}</td>"
                f"<td data-label='Reason'>{escape(str(f.get('reason', '')))}</td>"
                "</tr>"
            )
        exec_ledger_table = (
            '<h3 class="panel-title" style="font-size:1rem;margin-top:20px">Recent simulated fills</h3>'
            '<div id="execution-fills-panel"><div class="table-wrap"><table><thead><tr>'
            '<th>Symbol</th><th>Side</th><th class="num">Qty</th><th class="num">Fill</th><th class="num">Notional</th><th class="num">Fee</th><th>Reason</th>'
            '</tr></thead><tbody>' + "".join(exec_fill_rows) + '</tbody></table></div></div>'
            if exec_fill_rows
            else '<h3 class="panel-title" style="font-size:1rem;margin-top:20px">Recent simulated fills</h3><div id="execution-fills-panel"><div class="no-data"><div><strong>No simulated fills yet.</strong></div></div></div>'
        )
        limitations = execution_paper.get("limitations") or []
        limit_html = "".join(f"<li>{escape(str(item))}</li>" for item in limitations[:4])
        execution_paper_html = exec_summary + exec_positions_table + exec_ledger_table
        if limit_html:
            execution_paper_html += f'<div class="panel-note" style="margin-top:14px"><strong>Limitations:</strong><ul>{limit_html}</ul></div>'
    else:
        execution_paper_html = '<div class="no-data"><div><strong>Execution paper not enabled yet.</strong><br>The API is live, but no execution-paper account payload is available.</div></div>'

    exec_net = execution_paper.get("net_pnl", 0) if execution_paper.get("enabled") else 0
    exec_cls = "pos" if isinstance(exec_net, (int, float)) and exec_net >= 0 else "neg"
    execution_metric_cards_html = (
        '<article class="metric-card">'
        '<div class="metric-label">Execution equity</div>'
        f'<div id="execution-metric-equity" class="metric-value">{escape(fmt_money(execution_paper.get("equity") if execution_paper.get("enabled") else None))}</div>'
        '<div id="execution-metric-equity-sub" class="metric-sub">simulated fill account</div>'
        '</article>'
        '<article class="metric-card">'
        '<div class="metric-label">Execution P&amp;L</div>'
        f'<div id="execution-metric-pnl" class="metric-value {exec_cls}">{escape(fmt_signed_money(exec_net) if execution_paper.get("enabled") else "—")}</div>'
        f'<div id="execution-metric-pnl-sub" class="metric-sub">{escape(fmt_pct(execution_paper.get("net_pnl_pct")) if execution_paper.get("enabled") else "—")}</div>'
        '</article>'
        '<article class="metric-card">'
        '<div class="metric-label">Available cash</div>'
        f'<div id="execution-metric-cash" class="metric-value">{escape(fmt_money(execution_paper.get("available_cash", execution_paper.get("cash")) if execution_paper.get("enabled") else None))}</div>'
        f'<div id="execution-metric-cash-sub" class="metric-sub">{escape(fmt_money(execution_paper.get("short_collateral")))} reserved for shorts</div>'
        '</article>'
        '<article class="metric-card">'
        '<div class="metric-label">Open positions</div>'
        f'<div id="execution-metric-positions" class="metric-value">{len(execution_paper.get("positions") or []) if execution_paper.get("enabled") else 0}</div>'
        f'<div id="execution-metric-positions-sub" class="metric-sub">{len(execution_paper.get("ledger") or []) if execution_paper.get("enabled") else 0} ledger rows</div>'
        '</article>'
    )

    wf_results = processed.get("walk_forward", [])
    if wf_results:
        wf_rows = []
        for w in wf_results:
            wf_rows.append(
                "<tr>"
                f"<td data-label='Config' class='config-cell'>{escape(w['config'])}</td>"
                f"<td data-label='Train Ann' class='num pos'>{w['train_ann'] * 100:.1f}%</td>"
                f"<td data-label='Train Sharpe' class='num'>{w['train_sharpe']:.2f}</td>"
                f"<td data-label='Train MaxDD' class='num neg'>{w['train_dd'] * 100:.1f}%</td>"
                f"<td data-label='Test Ann' class='num pos'>{w['test_ann'] * 100:.1f}%</td>"
                f"<td data-label='Test Sharpe' class='num'>{w['test_sharpe']:.2f}</td>"
                f"<td data-label='Test MaxDD' class='num neg'>{w['test_dd'] * 100:.1f}%</td>"
                f"<td data-label='Both+' class='check'>{'YES' if w['both_positive'] else 'NO'}</td>"
                "</tr>"
            )
        walk_forward_html = (
            '<section class="panel">'
            '<div class="panel-header"><div>'
            '<h2 class="panel-title">Walk-Forward Split Results</h2>'
            '<p class="panel-note">60/40 train/test split. On phones, each split becomes a compact card.</p>'
            '</div></div>'
            '<div class="table-wrap"><table><thead><tr>'
            '<th>Config</th><th class="num">Train Ann</th><th class="num">Train Sharpe</th>'
            '<th class="num">Train MaxDD</th><th class="num">Test Ann</th>'
            '<th class="num">Test Sharpe</th><th class="num">Test MaxDD</th><th>Both+</th>'
            '</tr></thead><tbody>'
            + "".join(wf_rows)
            + "</tbody></table></div></section>"
        )
    else:
        walk_forward_html = ""

    if is_live:
        net_pnl = processed.get("net_pnl", 0)
        metric1_label = "Paper equity"
        metric1_value = fmt_money(processed.get("current_equity"))
        metric1_sub = f"started from {fmt_money(processed.get('initial_capital'))}"
        metric2_label = "Paper P&L"
        metric2_value = fmt_signed_money(net_pnl)
        metric2_sub = fmt_pct(processed.get("net_pnl_pct"))
        metric2_class = "pos" if net_pnl >= 0 else "neg"
        metric3_label = "Max drawdown"
        metric3_value = fmt_pct(processed.get("max_dd"))
        metric3_sub = "paper canary"
        metric4_label = "Status"
        metric4_value = processed.get("paper_status", "RUNNING")
        metric4_sub = f"updated {processed.get('last_updated') or '—'}"
        equity_note = "Live $2,000 paper equity. Auto-refreshes every 15 seconds; equity changes only when the paper runner processes a new candle."
        decimals = 2
    else:
        metric1_label = "Annualized return"
        metric1_value = fmt_pct(processed.get("ann_return"))
        metric1_sub = "backtest fallback"
        metric2_label = "Sharpe ratio"
        metric2_value = fmt_num(processed.get("sharpe"))
        metric2_sub = "backtest fallback"
        metric2_class = ""
        metric3_label = "Max drawdown"
        metric3_value = fmt_pct(processed.get("max_dd"))
        metric3_sub = "backtest fallback"
        metric4_label = "Current equity"
        metric4_value = fmt_num(processed.get("current_equity"), 4)
        metric4_sub = f"from {fmt_num(processed.get('initial_capital'), 4)}"
        equity_note = "Illustrative curve generated from the bundled backtest summary."
        decimals = 4

    rendered = PAGE_TEMPLATE.substitute(
        source=source,
        source_color=source_color,
        dd_color=dd_color,
        dd_label=dd_label,
        metric1_label=metric1_label,
        metric1_value=metric1_value,
        metric1_sub=metric1_sub,
        metric2_label=metric2_label,
        metric2_value=metric2_value,
        metric2_sub=metric2_sub,
        metric2_class=metric2_class,
        metric3_label=metric3_label,
        metric3_value=metric3_value,
        metric3_sub=metric3_sub,
        metric4_label=metric4_label,
        metric4_value=metric4_value,
        metric4_sub=metric4_sub,
        chart_labels=json.dumps(processed.get("labels", [])),
        chart_data=json.dumps(processed.get("equity", [])),
        execution_chart_labels=json.dumps(processed.get("execution_labels", processed.get("labels", []))),
        execution_chart_data=json.dumps(processed.get("execution_equity", [])),
        equity_note=equity_note,
        sleeve_bars_html="".join(sleeve_bars),
        positions_html=positions_html,
        execution_metric_cards_html=execution_metric_cards_html,
        execution_paper_html=execution_paper_html,
        walk_forward_html=walk_forward_html,
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    )
    return rendered


@app.route("/api/data")
def api_data():
    data, source, is_live = get_data_source()
    if is_live:
        processed = process_live_data(data)
    elif data:
        processed = process_backtest_data(data)
    else:
        processed = {}
    processed["source"] = source
    processed["is_live"] = is_live
    return jsonify(processed)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5566, debug=False)
