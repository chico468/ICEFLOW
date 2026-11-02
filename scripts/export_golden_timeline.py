"""Export the Cape Town -> Bharati golden voyage timeline fixture.

Runs the replay on 2022-01-15 via the FastAPI test client (no network), steps the
voyage until arrival, and writes:

  frontend/e2e/fixtures/golden-voyage-timeline.json   the timeline payload
  frontend/e2e/fixtures/golden-voyage-timeline.manifest.json  inputs, product versions,
      sha256, generated_at, git sha

The only file added under frontend/ is the fixture JSON (per Phase 2 rule 2).
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import sys

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

# Point the replay at the built pack's NSIDC cache so 2022-01-15 is served from
# the local cache (no network).
os.environ["ICEFLOW_NSIDC_CACHE_DIR"] = "/tmp/iceflow-full-pack/nsidc_raw_cache"

from fastapi.testclient import TestClient
from src.api.main import app

FIX_DIR = REPO / "frontend" / "e2e" / "fixtures"
FIX_DIR.mkdir(parents=True, exist_ok=True)
FIXTURE = FIX_DIR / "golden-voyage-timeline.json"
MANIFEST = FIX_DIR / "golden-voyage-timeline.manifest.json"

client = TestClient(app)
ORIGIN = "cape_town"
DEST = "bharati"
REPLAY_DATE = "2022-01-15"


def _git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()
    except Exception:
        return "unknown"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    # 1. Create the voyage (replay, 2022-01-15).
    create = client.post(
        "/api/v1/voyage",
        json={
            "origin_id": ORIGIN,
            "destination_id": DEST,
            "vessel_key": "vasiliy_golovnin",
            "environment_mode": "replay",
            "replay_date": REPLAY_DATE,
            "grid_resolution_deg": 0.5,
            "departure_time_hours": 0.0,
            "departure_iso": f"{REPLAY_DATE}T12:00:00+00:00",
        },
    )
    assert create.status_code == 200, create.text
    voyage_id = create.json()["voyage_id"]

    # 2. Step until arrival (30-minute ticks).
    total_hours = 0.0
    while total_hours < 720:
        step = client.post(
            f"/api/v1/voyage/{voyage_id}/step",
            json={"hours": 24, "tick_hours": 0.5},
        )
        assert step.status_code == 200, step.text
        total_hours += 24.0
        state = step.json().get("status")
        if state in {"ARRIVED", "ABORTED", "BESET"}:
            break

    # 3. Fetch the timeline. Use a 30-minute step; if the payload exceeds 5 MB,
    #    coarsen to 60 minutes and say so.
    for step_min in (30.0, 60.0):
        tl = client.get(f"/api/v1/voyage/{voyage_id}/timeline?step_min={step_min}")
        assert tl.status_code == 200, tl.text
        payload = tl.json()
        size = len(tl.content)
        print(f"step_min={step_min} n_steps={payload['n_steps']} size={size/1024**2:.2f} MB")
        if size <= 5 * 1024 * 1024:
            break

    # 4. Write fixture.
    FIXTURE.write_text(json.dumps(payload, indent=2) + "\n")
    fix_size = FIXTURE.stat().st_size
    print(f"wrote {FIXTURE} ({fix_size/1024**2:.2f} MB)")

    # 5. Write manifest.
    pack_manifest_path = Path("/tmp/iceflow-full-pack/manifest.json")
    pack_manifest = json.loads(pack_manifest_path.read_text()) if pack_manifest_path.is_file() else {}
    manifest = {
        "voyage_id": voyage_id,
        "origin": ORIGIN,
        "destination": DEST,
        "replay_date": REPLAY_DATE,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_sha": _git_sha(),
        "fixture_file": str(FIXTURE.relative_to(REPO)),
        "fixture_size_bytes": fix_size,
        "step_min": step_min,
        "n_steps": payload["n_steps"],
        "not_available": payload.get("not_available", []),
        "replay_pack": "/tmp/iceflow-full-pack",
        "repack_products": [p["product"] for p in pack_manifest.get("products", [])],
        "nsidc_cache": os.environ["ICEFLOW_NSIDC_CACHE_DIR"],
        "sha256": _sha256(FIXTURE),
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"wrote {MANIFEST}")


if __name__ == "__main__":
    main()
