"""Explicitly subset one day of Copernicus surface current into ICEFLOW's local cache."""
from __future__ import annotations

import argparse
import subprocess
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

from src.data.real_flow import CMEMS_DATASET, import_copernicus_current_file


def fetch(day: str, cache_dir: str | None = None) -> Path:
    date.fromisoformat(day)
    with tempfile.TemporaryDirectory(prefix="iceflow-cmems-") as temp:
        command = [
            "copernicusmarine", "subset",
            "--dataset-id", CMEMS_DATASET,
            "--variable", "uo", "--variable", "vo",
            "--start-datetime", day, "--end-datetime", day,
            "--minimum-longitude", "-180", "--maximum-longitude", "180",
            "--minimum-latitude", "-90", "--maximum-latitude", "-25",
            "--minimum-depth", "0", "--maximum-depth", "1",
            "--output-directory", temp,
            "--output-filename", f"cmems_current_{day}.nc",
        ]
        # Credentials are read by the official CLI from its user-level login config, never passed here.
        subprocess.run(command, check=True)
        source = Path(temp) / f"cmems_current_{day}.nc"
        if not source.is_file():
            candidates = list(Path(temp).glob("*.nc"))
            if len(candidates) != 1:
                raise RuntimeError("Copernicus subset did not produce exactly one NetCDF file.")
            source = candidates[0]
        return import_copernicus_current_file(
            source,
            cache_dir=cache_dir,
            retrieved_at=datetime.now(timezone.utc),
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True, help="Daily valid date, UTC, YYYY-MM-DD")
    parser.add_argument("--cache-dir", help="Override ICEFLOW_FLOW_CACHE_DIR")
    args = parser.parse_args()
    print(fetch(args.date, args.cache_dir))


if __name__ == "__main__":
    main()
