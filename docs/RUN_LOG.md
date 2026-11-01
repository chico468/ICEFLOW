
## 2026-11-01: PHASE 3 — BE-2 closeout on be2-sic-ml (reset to origin a4395d4)
- Regenerated models/eval/real_sic_ml_report.json via `python3 scripts/train_real_sic.py --evaluate-only` (model artefact real_sic_forecaster.joblib already present). Only generated_at/git_sha changed; all data values identical → report stable.
- IIEE per lead (15% threshold, VIZ mask from train climatology, Mkm²/day):
  * Lead 3: gbm 0.0302 / damped 0.0352 (all-season); gbm 0.0236 / damped 0.0276 (Nov-Mar)
  * Lead 7: gbm 0.0483 / damped 0.0793 (all-season); gbm 0.0369 / damped 0.0573 (Nov-Mar)
  * Lead 14: gbm 0.0744 / damped 0.1098 (all-season); gbm 0.0570 / damped 0.0906 (Nov-Mar)
- Lead-3 sanity check (computed on real test data, 1739352 rows):
  * passed=True; checks: cell_area_plausible=True, has_mismatches=True, mismatch_subset_of_viz=True, extent_plausible=True
  * mean_mismatched_cells=50.44/day; mean_cell_area=602.1 km² (nominal 625); mean_viz_area=0.9556 Mkm²
  * mean_mismatch_area=0.0302 Mkm²/day (= IIEE area); mean_iiee_pct=3.17%
  * IIEE at lead 3 = 0.0302 Mkm²/day, well below 1 Mkm²/day threshold → NO BUG, sanity passes
- Nov-Mar values: lower than all-season (0.0236 vs 0.0302 at lead 3 gbm) — physically expected (winter ice edge more compact/predictable). Earlier "fix" equalised them due to Nov-Mar mask not being applied (all-season mask used instead); current code applies correct Nov-Mar mask → values differ appropriately.
- Sensor check: NSIDC G02202 V6 daily directory — last 2025 V6 file = sic_pss25_20251229_am2_v06r00.nc (2025-12-29); NO 2026 V6 files (only sic_pss25_20260801_am2_icdr_v04r00.nc = v04r00 ICDR, not V6). 363 V6 days in 2025. Caveat: "V6 final available through 2025-12-29". No V6 days after 2025-12-29 to evaluate.
- Scorecard endpoint verification: loads models/eval/*.json with data_source=="real". 0.2223 AR(1) control does NOT appear in any scorecard row (only damped-baseline rows emitted; persistence 0.2223 used only as skill denominator). No fixture report in models/eval (iceberg_audit_report.json has data_source=None; others are real).
- Full pytest: 353 passed, 3 warnings, 0 failed (clean tree on be2-sic-ml a4395d4).
- Extras download (PID 38042): ~404 MB of ~6.6 GB, rate ~540 KB/s, ETA ~3+ hours. NOT killed per explicit instruction. Will check between steps; may need to build only snowfall + total_cloud_cover if ETA remains >90 min.
- Committing and pushing be2-sic-ml. Compare URL: https://github.com/chico468/ICEFLOW/compare/main...be2-sic-ml
- No items BLOCKED.
