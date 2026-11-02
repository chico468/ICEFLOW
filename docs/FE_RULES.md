# FE_RULES — Stage 0–5 rules for the ICEFLOW-frontend worktree

Rules created 2026-11-02. Obey these for this and every later stage.

## 1. Environment

- pwd must end in `ICEFLOW-frontend`; branch must be `voyage-bridge`.
- Never run `git worktree remove`/`prune`, `rm -rf` on a folder, or `git clean`.
- Push only `voyage-bridge`; no force-push. Merge `origin/main` into `voyage-bridge` if needed.
- A demo backend runs at `http://127.0.0.1:8000` (main ICEFLOW folder). Use it as the dev
  proxy with `BACKEND_URL=http://127.0.0.1:8000`. Never start, stop or restart it.

## 2. Scope

Edit only `frontend/` and `docs/FE_*.md`, `docs/RUN_LOG_FE.md`,
`docs/BACKEND_ISSUES.md`, `docs/PROVENANCE_AUDIT.md`. Never touch `src/`, `tests/`,
`models/`, `scripts/` or the main `ICEFLOW` folder.

Backend problems go into `docs/BACKEND_ISSUES.md` (endpoint, request, response, what is
wrong). Never work around them by inventing data.

## 3. Integrity

- No invented data. Every number carries a ProvenanceBadge from the API payload.
- A badge says `Observed` / `Reanalysis` / `Forecast` / `Derived` / `Simulated` ONLY when
  that data arrived with that provenance.
- Loading, error and no-data states have their own labels.
- Never claim live GPS. "Real-time" only where literally true.
- Never weaken or delete a test. Use existing `--c-*` tokens; no raw hex outside tokens.

## 4. Failure

Diagnose, up to 3 different fixes, log each, then mark BLOCKED with evidence, skip only
dependents, continue.

## 5. Hard stops

Wrong folder; working directory removed; free disk below 5 GB; work that would break
these rules.

## 6. Memory (8 GB Mac)

Playwright `--workers=1`, headless. Targeted specs while developing; the whole suite only
in the last stage. Dev server port 5199 (`strictPort`). Stop dev servers you start.

## 7. Write-tool safety

Write any file in pieces of at most 120 lines (create, then append with bash heredoc
`cat >> file <<'EOF'`). Never put a whole large document in one call. After one failed
write switch to bash heredoc. Never retry the same failed call more than once.

## 8. Commits, logs, PRs

After each stage: commit, push, append to `docs/RUN_LOG_FE.md` (stage, SHA,
typecheck/unit/build summary lines, Playwright summary, screenshot paths, BLOCKED items,
decisions). If you must stop for context, commit and write `RESUME HERE: <step>`.
Open no PRs; log `https://github.com/chico468/ICEFLOW/compare/main...voyage-bridge`.

## 9. Backend / Playwright

- Playwright functional specs never start a backend: they use `page.route()` fixtures from
  real recorded responses in `frontend/e2e/fixtures/recorded/` (dated file names).
- One spec tagged `@live` runs against port 8000 only when `LIVE_BACKEND=1`.