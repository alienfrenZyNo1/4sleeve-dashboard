#!/usr/bin/env python3
"""
4-Sleeve Ensemble Dashboard — PAPER ONLY
READ-ONLY display for the 4-sleeve tangency portfolio research.
No trading, no orders, no mutations. Display only.
"""
import json
import os
from pathlib import Path
from datetime import datetime, timezone
from string import Template
from flask import Flask, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Data paths
# ---------------------------------------------------------------------------
PAPER_RUNNER_PATH = Path(os.environ.get("PAPER_RUNNER_PATH", "/data/paper-runner/daily_pnl.json"))
BACKTEST_FALLBACK = Path(__file__).parent / "data" / "SD007-4sleeve-dd-optimization-data.json"

DD_GREEN = 0.10
DD_YELLOW = 0.20

SLEEVE_NAMES = ["CrossSecMom", "EMATrend", "Grid", "FundContrarian"]
SLEEVE_COLORS = {
    "CrossSecMom":    "#4dc9f6",
    "EMATrend":       "#f67019",
    "Grid":           "#acc236",
    "FundContrarian": "#f53794",
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
    daily = paper.get("daily_pnl", [])
    labels = [d.get("date", f"Day {i}") for i, d in enumerate(daily)]
    equity_values = [d.get("equity", 0) for d in daily]
    initial = paper.get("initial_capital", 10000)
    current_equity = equity_values[-1] if equity_values else initial

    peak = initial
    max_dd = 0
    for eq in equity_values:
        if eq > peak:
            peak = eq
        dd = (eq - peak) / peak if peak > 0 else 0
        if dd < max_dd:
            max_dd = dd

    sleeve_pnl = {s: 0 for s in SLEEVE_NAMES}
    for d in daily:
        for s in SLEEVE_NAMES:
            sleeve_pnl[s] += d.get("pnl_by_sleeve", {}).get(s, 0)

    return {
        "labels": labels,
        "equity": equity_values,
        "initial_capital": initial,
        "current_equity": current_equity,
        "current_dd": max_dd,
        "max_dd": max_dd,
        "sleeve_pnl": sleeve_pnl,
        "positions": paper.get("positions", []),
        "ann_return": paper.get("ann_return"),
        "sharpe": paper.get("sharpe"),
        "walk_forward": [],
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
        wf_results.append({
            "config": name.replace("_", " "),
            "train_ann": split.get("train", {}).get("ann", 0),
            "train_sharpe": split.get("train", {}).get("sharpe", 0),
            "train_dd": split.get("train", {}).get("maxdd", 0),
            "test_ann": split.get("test", {}).get("ann", 0),
            "test_sharpe": split.get("test", {}).get("sharpe", 0),
            "test_dd": split.get("test", {}).get("maxdd", 0),
            "both_positive": split.get("both_positive", False),
        })

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
    elif ad < DD_YELLOW:
        return "yellow", "ELEVATED DD"
    else:
        return "red", "CRITICAL DD"


def fmt_pct(v):
    if v is None:
        return "—"
    return f"{v * 100:.1f}%"


def fmt_num(v, decimals=2):
    if v is None:
        return "—"
    return f"{v:.{decimals}f}"


# ---------------------------------------------------------------------------
# HTML Template
# ---------------------------------------------------------------------------
PAGE_TEMPLATE = Template('''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>4-Sleeve Ensemble Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
  :root {
    --bg: #0d1117; --card: #161b22; --border: #30363d;
    --text: #c9d1d9; --text-bright: #f0f6fc;
    --green: #3fb950; --yellow: #d29922; --red: #f85149;
    --blue: #58a6ff; --accent: #1f6feb;
  }
  * { margin:0; padding:0; box-sizing:border-box; }
  body { font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif; background:var(--bg); color:var(--text); min-height:100vh; padding:20px; }
  .header { text-align:center; margin-bottom:24px; }
  .header h1 { font-size:1.8rem; color:var(--text-bright); letter-spacing:-0.5px; }
  .header .subtitle { color:var(--text); font-size:0.9rem; margin-top:4px; }
  .banner { text-align:center; padding:8px 16px; font-weight:700; font-size:0.85rem; letter-spacing:1px; border-radius:6px; margin-bottom:8px; }
  .banner-paper { background:rgba(248,81,73,0.15); border:1px solid rgba(248,81,73,0.4); color:var(--red); }
  .banner-canary { background:rgba(210,153,34,0.15); border:1px solid rgba(210,153,34,0.4); color:var(--yellow); }
  .status-bar { display:flex; align-items:center; justify-content:center; gap:16px; margin-bottom:24px; flex-wrap:wrap; }
  .status-pill { display:inline-flex; align-items:center; gap:6px; padding:6px 14px; border-radius:20px; font-size:0.8rem; font-weight:600; border:1px solid var(--border); background:var(--card); }
  .status-dot { width:10px; height:10px; border-radius:50%; display:inline-block; }
  .dot-green { background:var(--green); box-shadow:0 0 8px rgba(63,185,80,0.5); }
  .dot-yellow { background:var(--yellow); box-shadow:0 0 8px rgba(210,153,34,0.5); }
  .dot-red { background:var(--red); box-shadow:0 0 8px rgba(248,81,73,0.5); animation:pulse 1.5s infinite; }
  @keyframes pulse { 0%,100%{opacity:1;} 50%{opacity:0.5;} }
  .grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:16px; margin-bottom:24px; }
  .metric-card { background:var(--card); border:1px solid var(--border); border-radius:10px; padding:20px; text-align:center; }
  .metric-label { font-size:0.75rem; text-transform:uppercase; letter-spacing:1px; color:var(--text); margin-bottom:8px; }
  .metric-value { font-size:2rem; font-weight:700; color:var(--text-bright); }
  .metric-sub { font-size:0.75rem; color:var(--text); margin-top:4px; }
  .chart-container { background:var(--card); border:1px solid var(--border); border-radius:10px; padding:20px; margin-bottom:24px; }
  .chart-title { font-size:1rem; font-weight:600; color:var(--text-bright); margin-bottom:16px; }
  .two-col { display:grid; grid-template-columns:1fr 1fr; gap:16px; margin-bottom:24px; }
  @media (max-width:768px) { .two-col { grid-template-columns:1fr; } }
  table { width:100%; border-collapse:collapse; font-size:0.85rem; }
  th { text-align:left; padding:10px 12px; border-bottom:1px solid var(--border); color:var(--text); font-weight:600; font-size:0.75rem; text-transform:uppercase; letter-spacing:0.5px; }
  td { padding:8px 12px; border-bottom:1px solid rgba(48,54,61,0.5); color:var(--text); }
  td.num { text-align:right; font-variant-numeric:tabular-nums; }
  .pos { color:var(--green); }
  .neg { color:var(--red); }
  .check { color:var(--green); }
  .sleeve-bar { display:flex; align-items:center; gap:8px; margin-bottom:8px; }
  .sleeve-bar-track { flex:1; height:8px; background:var(--bg); border-radius:4px; overflow:hidden; }
  .sleeve-bar-fill { height:100%; border-radius:4px; }
  .footer { text-align:center; padding:20px; color:var(--text); font-size:0.75rem; border-top:1px solid var(--border); margin-top:24px; }
  .no-data { text-align:center; padding:40px; color:var(--text); }
</style>
</head>
<body>

<div class="header">
  <h1>4-Sleeve Ensemble Dashboard</h1>
  <div class="subtitle">CrossSecMom &middot; EMATrend &middot; Grid &middot; FundContrarian &middot; Tangency Portfolio</div>
</div>

<div class="banner banner-paper">&#9888; PAPER ONLY — NO LIVE CAPITAL</div>
<div class="banner banner-canary">&#128300; RESEARCH CANARY — SD-009</div>

<div class="status-bar">
  <span class="status-pill">
    <span class="status-dot dot-$dd_color"></span>
    $dd_label
  </span>
  <span class="status-pill">
    <span class="status-dot dot-$source_color"></span>
    $source
  </span>
</div>

<div class="grid">
  <div class="metric-card">
    <div class="metric-label">Annualized Return</div>
    <div class="metric-value">$ann_return_str</div>
  </div>
  <div class="metric-card">
    <div class="metric-label">Sharpe Ratio</div>
    <div class="metric-value">$sharpe_str</div>
  </div>
  <div class="metric-card">
    <div class="metric-label">Max Drawdown</div>
    <div class="metric-value" style="color:var(--red)">$maxdd_str</div>
  </div>
  <div class="metric-card">
    <div class="metric-label">Current Equity</div>
    <div class="metric-value">$equity_str</div>
    <div class="metric-sub">from $initial_str</div>
  </div>
</div>

<div class="chart-container">
  <div class="chart-title">Equity Curve $equity_note</div>
  <canvas id="equityChart" height="80"></canvas>
</div>

<div class="two-col">
  <div class="chart-container">
    <div class="chart-title">Sleeve Allocation / P&amp;L</div>
    $sleeve_bars_html
  </div>
  <div class="chart-container">
    <div class="chart-title">Current Positions</div>
    $positions_html
  </div>
</div>

$walk_forward_html

<div class="footer">
  READ-ONLY DISPLAY &middot; NO TRADING &middot; NO ORDERS &middot; RESEARCH ONLY<br>
  Data: $source &middot; Generated $generated_at
</div>

<script>
const ctx = document.getElementById('equityChart').getContext('2d');
new Chart(ctx, {
  type: 'line',
  data: {
    labels: $chart_labels,
    datasets: [{
      label: 'Equity',
      data: $chart_data,
      borderColor: '#58a6ff',
      backgroundColor: 'rgba(88,166,255,0.1)',
      borderWidth: 2, fill: true, tension: 0.3,
      pointRadius: 0, pointHoverRadius: 4,
    }]
  },
  options: {
    responsive: true, maintainAspectRatio: false,
    plugins: {
      legend: { display: false },
      tooltip: { backgroundColor: '#161b22', borderColor: '#30363d', borderWidth: 1 }
    },
    scales: {
      x: { ticks: { color: '#8b949e', maxTicksLimit: 12 }, grid: { color: 'rgba(48,54,61,0.3)' } },
      y: { ticks: { color: '#8b949e' }, grid: { color: 'rgba(48,54,61,0.3)' } }
    }
  }
});
</script>

</body>
</html>''')


@app.route("/")
def dashboard():
    data, source, is_live = get_data_source()

    if is_live:
        processed = process_live_data(data)
    elif data:
        processed = process_backtest_data(data)
    else:
        processed = {
            "labels": [], "equity": [], "initial_capital": 0,
            "current_equity": 0, "current_dd": 0, "max_dd": 0,
            "sleeve_pnl": {s: 0 for s in SLEEVE_NAMES},
            "positions": [], "ann_return": None, "sharpe": None,
            "walk_forward": [],
        }

    dd_color, dd_label = dd_status(processed.get("current_dd", 0))
    source_color = "green" if is_live else "yellow"

    sp = processed.get("sleeve_pnl", {s: 0 for s in SLEEVE_NAMES})
    max_sleeve = max(sp.values(), default=1) or 1
    sleeve_bars = []
    for s in SLEEVE_NAMES:
        val = sp.get(s, 0)
        pct = (abs(val) / max_sleeve * 100) if max_sleeve > 0 else 0
        color = SLEEVE_COLORS.get(s, "#58a6ff")
        sleeve_bars.append(
            '<div class="sleeve-bar">'
            f'<span style="min-width:120px;font-size:0.85rem">{s}</span>'
            f'<div class="sleeve-bar-track"><div class="sleeve-bar-fill" style="width:{pct:.0f}%;background:{color}"></div></div>'
            f'<span style="min-width:60px;text-align:right;font-variant-numeric:tabular-nums;font-size:0.85rem">{val*100:.1f}%</span>'
            '</div>'
        )

    positions = processed.get("positions", [])
    if positions:
        pos_rows = []
        for p in positions:
            pnl = p.get("pnl", 0)
            cls = "pos" if pnl >= 0 else "neg"
            pos_rows.append(
                f"<tr><td>{p.get('symbol','')}</td><td>{p.get('sleeve','')}</td>"
                f"<td>{p.get('side','')}</td>"
                f"<td class='num'>{p.get('size','')}</td>"
                f"<td class='num {cls}'>{pnl:.2f}</td></tr>"
            )
        positions_html = (
            '<table><tr><th>Symbol</th><th>Sleeve</th><th>Side</th>'
            '<th class="num">Size</th><th class="num">PnL</th></tr>'
            + "".join(pos_rows) + '</table>'
        )
    else:
        positions_html = '<div class="no-data">No live positions.<br>Paper runner not connected.</div>'

    wf_results = processed.get("walk_forward", [])
    if wf_results:
        wf_rows = []
        for w in wf_results:
            wf_rows.append(
                "<tr>"
                f"<td>{w['config']}</td>"
                f"<td class='num pos'>{w['train_ann']*100:.1f}%</td>"
                f"<td class='num'>{w['train_sharpe']:.2f}</td>"
                f"<td class='num neg'>{w['train_dd']*100:.1f}%</td>"
                f"<td class='num pos'>{w['test_ann']*100:.1f}%</td>"
                f"<td class='num'>{w['test_sharpe']:.2f}</td>"
                f"<td class='num neg'>{w['test_dd']*100:.1f}%</td>"
                f"<td class='check'>{'YES' if w['both_positive'] else 'NO'}</td>"
                "</tr>"
            )
        walk_forward_html = (
            '<div class="chart-container">'
            '<div class="chart-title">Walk-Forward Split Results (60/40 Train/Test)</div>'
            '<table><tr>'
            '<th>Config</th><th class="num">Train Ann</th><th class="num">Train Sharpe</th>'
            '<th class="num">Train MaxDD</th><th class="num">Test Ann</th>'
            '<th class="num">Test Sharpe</th><th class="num">Test MaxDD</th><th>Both+</th>'
            '</tr>' + "".join(wf_rows) + '</table></div>'
        )
    else:
        walk_forward_html = ""

    equity_note = "(LIVE)" if is_live else "(ILLUSTRATIVE from backtest summary)"
    decimals = 2 if is_live else 4

    rendered = PAGE_TEMPLATE.substitute(
        source=source,
        source_color=source_color,
        dd_color=dd_color,
        dd_label=dd_label,
        ann_return_str=fmt_pct(processed.get("ann_return")),
        sharpe_str=fmt_num(processed.get("sharpe")),
        maxdd_str=fmt_pct(processed.get("max_dd")),
        equity_str=fmt_num(processed.get("current_equity"), decimals),
        initial_str=fmt_num(processed.get("initial_capital"), decimals),
        chart_labels=json.dumps(processed.get("labels", [])),
        chart_data=json.dumps(processed.get("equity", [])),
        equity_note=equity_note,
        sleeve_bars_html="".join(sleeve_bars),
        positions_html=positions_html,
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
