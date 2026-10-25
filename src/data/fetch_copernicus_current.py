"""Explicitly subset one day of Copernicus surface current into ICEFLOW's local cache."""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

from src.data.real_flow import CMEMS_DATASET, import_copernicus_current_file


def _find_copernicus_executable() -> str | None:
    executable = shutil.which("copernicusmarine")
    if executable is not None:
        return executable
    suffix = ".exe" if os.name == "nt" else ""
    candidate = Path(sys.executable).with_name(f"copernicusmarine{suffix}")
    if candidate.is_file():
        return str(candidate)
    return None


def fetch(day: str, cache_dir: str | None = None) -> Path:
    date.fromisoformat(day)
    executable = _find_copernicus_executable()
    if executable is None:
        raise RuntimeError(
            "Copernicus Marine Toolbox CLI is unavailable. Install the `copernicusmarine` "
            "package in this Python environment and run `copernicusmarine login`."
        )
    with tempfile.TemporaryDirectory(prefix="iceflow-cmems-") as temp:
        command = [
            executable, "subset",
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
        # Never block on interactive prompts in non-interactive environments.
        subprocess.run(command, check=True, stdin=subprocess.DEVNULL)
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
