# Development-Runs Protocol

This document records the "frozen" configuration for each real-data model so
that development runs (exploratory tuning, quick re-trains) can be distinguished
from the single definitive run whose artefacts and metrics are committed.

## Why

Per AGENTS.md rule 6 ("No metric, skill or accuracy claim in code, docs or UI
unless produced by a script run on real data"), every committed report JSON
must be regenerable from a documented, deterministic pipeline.  This protocol
ensures that:

1. The frozen configuration is unambiguous.
2. Any development run that deviates from the frozen config is clearly labelled.
3. Committed artefacts and metrics are always the output of the frozen run,
   never an ad-hoc or dev run.

## General procedure

1. **Read the frozen config below** before starting any training run.
2. **Run training** with `python -m scripts.train_real_sic` (SIC) or
   `python -m scripts.train_iceberg` (iceberg).  If you need to deviate
   (e.g. `--quick` for a smoke test, or different hyperparameters), run in a
   **temporary directory** — never in `models/` — and **do not commit** the
   output.
3. **Verify** the output matches the contract (valid JSON, no NaN, correct
   field names) before committing.
4. **Commit** only the frozen config's output.

---

## BE-2: Real SIC Forecaster

### Frozen configuration

| Parameter              | Value                                      |
|------------------------|--------------------------------------------|
| Training data          | NOAA/NSIDC CDR G02202 Version 6 (SSMIS)    |
| Train years            | 2005–2019                                  |
| Val years              | 2020–2021                                  |
| Test years             | 2022–2024                                  |
| Embargo between blocks | 14 days                                    |
| Leads                  | 3, 7, 14 days                              |
| Baseline               | Damped-anomaly persistence, tau tuned per lead |
| Model                  | HistGradientBoostingRegressor              |
| Hyperparameter candidates | 3 (defined in `CANDIDATE_HYPERPARAMETERS`) |
| Hyperparameters selected on | Val RMSE of full forecast (baseline + residual) |
| Uncertainty            | Split-conformal, 90%, stratified by lead and concentration bin |
| CI alpha (gate)        | 0.05 (95% CI of RMSE difference must exclude zero) |
| Promotion gate         | Both all-season AND Nov-Mar must exclude zero on VIZ cells |
| VIZ definition         | Climatology 5–95%                          |
| Coverage target        | 90%                                        |
| IIEE threshold         | 15% (Goessling et al. 2016)                |
| Seed                   | 26059                                      |
| n_bootstrap            | 200                                        |

### Development-run deviations

| Flag / Change            | Allowed in dev? | Commit? |
|--------------------------|-----------------|---------|
| `--quick` smoke test     | Yes             | No      |
| Different `--seed`       | Yes             | No      |
| Different hyperparams    | Yes             | No      |
| `--cache-dir` override   | Yes             | No      |
| `--evaluate-only`        | Yes             | No      |
| Modifying training logic | Only on frozen  | Yes     |

### Committed artefacts

| File                              | Tracked? | Notes                         |
|-----------------------------------|----------|-------------------------------|
| `models/real_sic_forecaster.joblib` | No     | Gitignored (`.gitignore`)     |
| `models/eval/real_sic_ml_report.json` | Yes  | This is the committed report  |
| `models/metrics.json`             | Yes      | **Must remain synthetic**     |

---

## BE-3: Iceberg Drift Forecaster

### Frozen configuration

| Parameter              | Value                                      |
|------------------------|--------------------------------------------|
| Training data          | BYU/NIC consolidated Antarctic iceberg DB v6 |
| Train period           | 2005-01-01 to 2017-12-31                   |
| Val period             | 2018-01-01 to 2018-12-31                   |
| Test period            | 2019-01-01 to 2022-12-31                   |
| Leads                  | 1, 3, 7 days                              |
| Baseline (b)           | Constant velocity from last 3 days         |
| Baseline (c)           | Constant velocity from last 7 days, damped (0.5x) |
| Model                  | HistGradientBoostingRegressor              |
| Hyperparameter candidates | 3 (in `ICEBERG_CANDIDATE_HYPERPARAMETERS`) |
| Hyperparameters selected on | Val RMSE of full position forecast      |
| Uncertainty            | Split-conformal, p50/p90 radii             |
| CI alpha (gate)        | 0.05 (bootstrap-CI-by-iceberg excludes zero) |
| Grounded threshold     | Speed < 0.1 kt (justified: below this, berg is grounded or untrackable) |
| Train/test split        | By iceberg track time (no iceberg in both train and test) |
| Seed                   | 26059                                      |
| n_bootstrap            | 200                                        |

### Development-run deviations

| Flag / Change            | Allowed in dev? | Commit? |
|--------------------------|-----------------|---------|
| `--quick` smoke test     | Yes             | No      |
| Different `--seed`       | Yes             | No      |
| Different hyperparams    | Yes             | No      |
| `--evaluate-only`        | Yes             | No      |
| Modifying grounding threshold | Only on frozen | Yes   |

### Committed artefacts

| File                              | Tracked? | Notes                         |
|-----------------------------------|----------|-------------------------------|
| `models/iceberg_forecaster.joblib` | No      | Gitignored                    |
| `models/eval/iceberg_ml_report.json` | Yes   | Committed scorecard report    |
| `data/raw/iceberg/consolidated_database_v6.zip` | Yes | Source data (3.6 MB) |
