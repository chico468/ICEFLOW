# RUN LOG PHASE 4 — iceberg physics hindcast (branch: demo-integration)

## 2026-11-01: Part A — demo-integration branch created from origin/main
- Created local-only branch demo-integration from origin/main
- Merged origin/real-voyage (fast-forward), then origin/be2-sic-ml (conflict in docs/RUN_LOG.md resolved by keeping both sides)
- Committed as 25f1f8d
- Full pytest: 367 passed, 3 warnings in 241.87s (0:04:01), clean tree

## 2026-11-01: Part A demo server — uvicorn on port 8000
- ICEFLOW_REPLAY_PACK=~/iceflow-data/replay-pack-2022-01 (existing pack, not copied from /tmp)
- No old uvicorn on port 8000 (old one on 8199, left untouched)
- Started: ICEFLOW_REPLAY_PACK=~/iceflow-data/replay-pack-2022-01 python3 -m uvicorn src.api.main:app --host 127.0.0.1 --port 8000
- curl /api/v1/health: status ok, warmup warming, data_provenance has iceberg_catalogue=real-seed, sea_ice_field=synthetic, atmosphere_ocean=synthetic
- curl POST /api/v1/voyage (cape_town->bharati, replay 2022-01-15): voyage_id d19a9270c9cd, arrival_iso 2022-01-24T04:36:00+00:00, status PLANNED
- curl POST /api/v1/voyage/d19a9270c9cd/step (24h, 6h ticks): status UNDER_WAY, 4 ticks, sim_hours 24.0, distance 336.0 nm, fuel 24.572 t, no open alerts
- curl GET /api/v1/voyage/d19a9270c9cd/timeline?step_min=60: 4 steps, provenance_by_variable per variable (ice_conc kind=observed)
- curl GET /api/v1/evidence/scorecard: data_source=real, 146 rows, promoted sic {3:False,7:False,14:True}, iceberg {1:False,3:False,7:False}
