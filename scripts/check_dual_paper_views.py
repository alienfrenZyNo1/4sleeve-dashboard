#!/usr/bin/env python3
"""Regression check for dual Model/Execution paper dashboard views."""
from __future__ import annotations

import importlib.util
import json
import os
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_PATH = ROOT / "app.py"

payload = {
    "schema_version": 1,
    "mode": "paper",
    "paper_only": True,
    "status": "RUNNING",
    "initial_capital": 2000.0,
    "current_equity": 2004.18,
    "peak_equity": 2004.18,
    "net_pnl": 4.18,
    "net_pnl_pct": 0.00209,
    "max_drawdown_pct": 0.0,
    "last_processed_ts": 1783602000000,
    "last_processed_at": "2026-07-09T13:00:00+00:00",
    "updated_at": "2026-07-09T13:55:32+00:00",
    "sleeve_allocation": {"CrossSecMom": 0.5, "EMATrend": 0.135, "Grid": 0.136, "FundContrarian": 0.229},
    "positions": [{"symbol": "4-SLEEVE", "sleeve": "Ensemble", "side": "PAPER", "size": 2000.0, "pnl": 4.18}],
    "circuit_breaker": {"triggered": False, "block_new_risk": False, "reason": "ok"},
    "execution_paper": {
        "enabled": True,
        "cash": 1675.55,
        "equity": 1997.42,
        "net_pnl": -2.58,
        "net_pnl_pct": -0.00129,
        "equity_curve": [1999.0, 1998.0, 1997.42],
        "labels": ["t0", "t1", "t2"],
        "target_weights": {"BTCUSDT": 0.1},
        "positions": [{"symbol": "BTCUSDT", "side": "LONG", "quantity": 0.003, "notional": 330.0}],
        "ledger": [{"symbol": "BTCUSDT", "side": "BUY", "quantity": 0.003, "fill_price": 110000.0, "notional": 330.0, "fee": 0.13, "reason": "hourly-target-rebalance"}],
        "limitations": ["execution paper limitation"],
    },
    "daily_pnl": [
        {"ts": 1783598400000, "date": "2026-07-09T12:00:00+00:00", "equity": 2000.0, "execution_equity": 1999.0, "pnl": 0.0, "total_pnl": 0.0, "return_pct": 0.0, "drawdown_pct": 0.0},
        {"ts": 1783602000000, "date": "2026-07-09T13:00:00+00:00", "equity": 2004.18, "execution_equity": 1997.42, "pnl": 4.18, "total_pnl": 4.18, "return_pct": 0.00209, "drawdown_pct": 0.0},
    ],
}

with tempfile.TemporaryDirectory() as tmp:
    paper_path = Path(tmp) / "daily_pnl.json"
    paper_path.write_text(json.dumps(payload))
    os.environ["PAPER_RUNNER_PATH"] = str(paper_path)
    os.environ["MIRRORED_API_PATH"] = str(Path(tmp) / "missing-mirror.json")

    spec = importlib.util.spec_from_file_location("dashboard_app_for_dual_view_test", APP_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    client = module.app.test_client()
    response = client.get("/")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    # Sticky icon menu with two buttons.
    assert 'class="view-switcher"' in html
    assert 'data-view="model"' in html
    assert 'data-view="execution"' in html
    assert "📈" in html and "⚙" in html

    # Two page-like views.
    assert 'id="model-paper-view"' in html
    assert 'id="execution-paper-view"' in html
    assert 'canvas id="modelEquityChart"' in html
    assert 'canvas id="executionEquityChart"' in html

    # Model paper must show trades/positions just like execution paper.
    assert "Model Paper" in html
    assert "Model paper trades" in html
    assert "4-SLEEVE" in html

    # Execution paper must show chart + fills.
    assert "Execution Paper" in html
    assert "Execution equity curve" in html
    assert "Recent simulated fills" in html
    assert "BTCUSDT" in html

    # JS should switch visible pages without navigation.
    assert "function showPaperView" in html
    assert "localStorage.setItem('paperView'" in html

print("dual paper view check passed")
