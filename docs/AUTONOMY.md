AUTONOMY RULES
1. Do not ask for permission or confirmation. Decide using these rules, record the decision in
   docs/RUN_LOG.md (what, why, evidence) and continue.
2. Standing approvals: run tests and scripts; create/edit files in this repo; install Python
   packages into the project's venv; git add/commit/push on the branch the phase names; create
   the branches the phases name; download from the sources already named (ARCO-ERA5, Copernicus
   Marine, NSIDC, BYU) up to 8 GB in total across the whole run, logging each download's size.
3. Never: push to main; force-push (only --force-with-lease on the phase's own branch, after a
   rebase); delete remote branches or tags; rm -rf outside cache/build dirs you created;
   git reset --hard on unpushed commits; edit anything under frontend/ (except adding the one
   fixture file Phase 2 names); print, log or commit credentials; use data from sources not
   named. Always commit before switching branches.
4. Integrity: never fabricate, hardcode or synthesise a result to make a test pass; never weaken
   or delete a test or loosen a threshold (the 60 s routing test stays 60 s); no synthetic data
   in any real mode; promotion flags are computed by code; no tuning on TEST. Every number you
   report comes from a command you ran.
5. If a step fails: diagnose, try up to 3 different fixes, log each. If it still fails, mark the
   item BLOCKED in RUN_LOG with evidence, skip only the items that depend on it, complete every
   independent item, and keep going. A blocked item is not a reason to end the run.
6. Hard stops, the only ones: free disk below 5 GB; a needed credential missing or rejected; the
   work would require breaking rule 3. Uncommitted changes you did not make: commit them to a
   branch wip/<date> and continue; never discard them. On a hard stop, write it in RUN_LOG and
   end with "HARD STOP: <reason>".
7. After each phase: commit, push, append to RUN_LOG: branch, SHA, what passed (raw pytest
   summary line from a literal clean clone of that SHA), what is BLOCKED, decisions made. If you
   must stop for context length, commit and write "RESUME HERE: <exact next step>".
