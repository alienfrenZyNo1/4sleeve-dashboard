#!/usr/bin/env python3
"""Regression check for mirrored processed live API payloads."""
from __future__ import annotations

import importlib.util
import json
import os
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_PATH = ROOT / "app.py"

payload = {
    "source": "LIVE PAPER RUNNER",
    "is_live": True,
    "labels": ["t0", "t1"],
    "equity": [2000.0, 2002.09],
    "initial_capital": 2000.0,
    "current_equity": 2002.09,
    "net_pnl": 2.09,
    "net_pnl_pct": 0.0010440969963918523,
    "max_dd": 0,
    "sleeve_pnl": {
        "CrossSecMom": 0.5,
        "EMATrend": 0.135,
        "Grid": 0.136,
        "FundContrarian": 0.229,
    },
    "positions": [
        {"symbol": "4-SLEEVE", "sleeve": "Ensemble", "side": "PAPER", "size": 2000.0, "pnl": 2.09}
    ],
    "paper_status": "RUNNING",
    "last_updated": "2026-07-09T11:16:25Z",
}

with tempfile.TemporaryDirectory() as tmp:
    mirror_path = Path(tmp) / "live_api_data.json"
    mirror_path.write_text(json.dumps(payload))
    os.environ["PAPER_RUNNER_PATH"] = str(Path(tmp) / "missing-daily-pnl.json")
    os.environ["MIRRORED_API_PATH"] = str(mirror_path)

    spec = importlib.util.spec_from_file_location("dashboard_app_for_mirror_test", APP_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    data, source, is_live = module.get_data_source()
    assert is_live is True
    assert source == "LIVE PAPER RUNNER"
    processed = module.process_live_data(data)
    assert processed["current_equity"] == 2002.09
    assert processed["positions"][0]["symbol"] == "4-SLEEVE"

    client = module.app.test_client()
    response = client.get("/api/data")
    assert response.status_code == 200
    body = response.get_json()
    assert body["is_live"] is True
    assert body["source"] == "LIVE PAPER RUNNER"
    assert body["current_equity"] == 2002.09

print("mirrored live payload check passed")
