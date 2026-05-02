# Production Deployment Checklist — Polymarket Trading Bot

## Pre-requisites
- [ ] Server access (root@hermes-agent-hetzner) ✓
- [ ] GitHub repo cloned and updated ✓
- [ ] Python venv with dependencies installed
- [ ] Systemd service `polymarket-bot.service` configured (dry-run mode)

## Phase 0 — Acquire Credentials
- [ ] Create/use existing Polygon wallet (Metamask)
- [ ] Fund wallet with ~$50 MATIC/ETH for gas
- [ ] Generate Polymarket API key at https://polymarket.com/settings/api
- [ ] Copy API key, secret, wallet address to `~/.hermes/.env`:
  ```bash
  export POLYMARKET_API_KEY=...
  export POLYMARKET_API_SECRET=...
  export POLYMARKET_WALLET_ADDRESS=0x...
  ```
- [ ] (Optional) Generate Telegram bot token and note chat_id

## Phase 1 — Config Prep
- [ ] Copy `config/prod.yaml.template` → `config/prod.yaml`
- [ ] Fill in real Polymarket market contract IDs (from API or UI inspection)
- [ ] Set `dry_run: false` in prod.yaml
- [ ] Adjust `max_position_usd` and `max_total_exposure_usd` for $300 capital
- [ ] Commit prod.yaml to PRIVATE branch or gitignore it (DO NOT push secrets)

## Phase 2 — API Testing
- [ ] Run `scripts/test_polymarket_api.py`
- [ ] Verify:
  - [ ] Connection succeeds
  - [ ] Balance fetch works
  - [ ] Market IDs return valid prices
  - [ ] Can list open orders
- [ ] If any endpoint 404s, obtain correct market IDs from Polymarket expl

## Phase 3 — Paper Trading on Live API
- [ ] Ensure `dry_run: true` but with real API reads (prices from mainnet)
- [ ] Run bot for 48h via systemd
- [ ] Monitor logs: `journalctl -fu polymarket-bot.service`
- [ ] Check that matices build and no "Unknown market_id" errors appear
- [ ] Review daily report

## Phase 4 — Micro-Live Test ($10)
- [ ] Edit prod.yaml: max_position_usd=2, max_total_exposure_usd=10
- [ ] Allowed assets: only ETH and BTC on 1h window
- [ ] Run `scripts/deploy_live.sh`
- [ ] Let bot execute up to 5 trades MAX
- [ ] Manually verify each fill matches expected price+slippage
- [ ] After 5 trades or ±$2 P&L, run emergency stop

## Phase 5 — Full Live ($300)
- [ ] Restore full risk limits: max_position_usd=30, max_total=120
- [ ] Enable all 4 crypto assets (ETH, BTC, TAO, HL) on 1h/6h
- [ ] Disable 5m window (high noise)
- [ ] Deploy via `deploy_live.sh`
- [ ] Monitor first 24h hourly
- [ ] Review Telegram alerts for every entry/exit

## Phase 6 — Ongoing Monitoring
- [ ] Daily Telegram report at 08:00 Bratislava time
- [ ] Weekly review of matrix health (transition counts)
- [ ] Monthly performance audit (win rate, Sharpe ratio, max drawdown)
- [ ] Emergency stop drill (test `emergency_stop.sh` on a weekend)

## Rollback Plan
If anything goes wrong:
```bash
systemctl stop polymarket-bot.service
cp config/config.yaml.backup.* config.yaml   # latest dry-run config
systemctl start polymarket-bot.service
```

---

## Contacts
- Polymarket API docs: https://docs.polymarket.com/
- Community: https://discord.gg/polymarket
- Support: support@polymarket.com
