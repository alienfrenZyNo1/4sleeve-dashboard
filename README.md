# 4-Sleeve Ensemble Dashboard

READ-ONLY dashboard for the 4-sleeve tangency portfolio paper strategy.

## Safety
- **PAPER ONLY — NO LIVE CAPITAL**
- **RESEARCH CANARY — SD-009**
- This dashboard is display-only. No trading, no orders, no config mutations.

## Data Sources
1. **Primary (live):** `/data/paper-runner/daily_pnl.json` — when the paper runner is active
2. **Fallback (backtest):** `data/SD007-4sleeve-dd-optimization-data.json` — static backtest results

## Deployment (Coolify / Docker)

The app listens on port **5566**.

### Coolify Setup
1. Create new app from this Git repo
2. Set domain: `4sleeve.adrianmarikar.com`
3. Port: `5566`
4. (Optional) Mount paper runner data volume at `/data/paper-runner/`

## Local Development
```bash
pip install -r requirements.txt
python app.py
# Open http://localhost:5566
```

## API
- `GET /` — Dashboard HTML
- `GET /api/data` — JSON data payload

## Status Indicator
- Green: drawdown < 10%
- Yellow: drawdown 10-20%
- Red: drawdown > 20% (pulsing)
