#!/usr/bin/env python3
"""Regression check that raw runner daily_pnl payload preserves execution_paper."""
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
    "source": "SD-009 4-sleeve paper runner",
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
        "target_weights": {"BTCUSDT": 0.1},
        "positions": [{"symbol": "BTCUSDT", "side": "LONG", "quantity": 0.003, "notional": 330.0}],
        "ledger": [{"symbol": "BTCUSDT", "side": "BUY", "quantity": 0.003, "fill_price": 110000.0}],
        "limitations": ["execution paper limitation"],
    },
    "daily_pnl": [
        {
            "ts": 1783602000000,
            "date": "2026-07-09T13:00:00+00:00",
            "equity": 2004.18,
            "normalized_equity": 1.00209,
            "pnl": 4.18,
            "total_pnl": 4.18,
            "return_pct": 0.00209,
            "drawdown_pct": 0.0,
            "regime": "bear",
            "cb_triggered": False,
            "cb_reason": "ok",
        }
    ],
}

with tempfile.TemporaryDirectory() as tmp:
    paper_path = Path(tmp) / "daily_pnl.json"
    paper_path.write_text(json.dumps(payload))
    os.environ["PAPER_RUNNER_PATH"] = str(paper_path)
    os.environ["MIRRORED_API_PATH"] = str(Path(tmp) / "missing-mirror.json")

    spec = importlib.util.spec_from_file_location("dashboard_app_for_raw_runner_test", APP_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    data, source, is_live = module.get_data_source()
    assert is_live is True
    assert source == "LIVE PAPER RUNNER"
    processed = module.process_live_data(data)
    assert processed["current_equity"] == 2004.18
    assert processed["execution_paper"]["enabled"] is True
    assert processed["execution_paper"]["positions"][0]["symbol"] == "BTCUSDT"

    client = module.app.test_client()
    response = client.get("/api/data")
    assert response.status_code == 200
    body = response.get_json()
    assert body["is_live"] is True
    assert body["execution_paper"]["enabled"] is True
    assert body["execution_paper"]["ledger"][-1]["side"] == "BUY"

print("raw runner execution payload check passed")
