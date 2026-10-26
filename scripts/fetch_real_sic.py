#!/usr/bin/env python
"""Discover and download real NSIDC SIC data."""
from __future__ import annotations

import argparse
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.request import Request, urlopen

from src.data.nsidc_sea_ice import NSIDCSeaIceReader, BASE_URL_V6, DATASET_NAME, default_cache_dir


_FILENAME_RE = re.compile(r'href="(sic_pss25_(\d{8})_[A-Za-z0-9]+_v06r00\.nc)"')


def collect_listing_filenames(listings: dict[int, str]) -> dict[date, str]:
    """Parse directory listings into a {date: filename} map.

    ``listings`` maps a year to the raw HTML text of that year's NSIDC index page.
    Dates absent from any listing are simply not added here (handled as gaps by
    the caller).
    """
    date_to_filename: dict[date, str] = {}
    for year, html in listings.items():
        for fname, dstr in _FILENAME_RE.findall(html or ""):
            try:
                d = date(int(dstr[:4]), int(dstr[4:6]), int(dstr[6:8]))
            except ValueError:
                continue
            date_to_filename[d] = fname
    return date_to_filename


def requested_date_range(start: date, end: date) -> list[date]:
    out = []
    cur = start
    while cur <= end:
        out.append(cur)
        cur += timedelta(days=1)
    return out


def find_gaps(date_to_filename: dict[date, str], requested: list[date]) -> list[date]:
    """Dates requested but absent from the listing map."""
    return [d for d in requested if d not in date_to_filename]


def _scrape_year(year: int, cache_dir: Path) -> dict[date, str]:
    """Scrape one year's NSIDC index listing; returns {date: filename}."""
    listing: dict[date, str] = {}
    try:
        req = Request(f"{BASE_URL_V6}/{year}/", headers={"User-Agent": "ICEFLOW"})
        with urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
        for fname, dstr in _FILENAME_RE.findall(html):
            try:
                d = date(int(dstr[:4]), int(dstr[4:6]), int(dstr[6:8]))
            except ValueError:
                continue
            listing[d] = fname
    except Exception:
        pass
    return listing


def discover_range():
    """Discover available range by probing V6."""
    available_years = []
    for year in range(2030, 1977, -1):
        try:
            req = Request(f"{BASE_URL_V6}/{year}/", headers={"User-Agent": "ICEFLOW"})
            resp = urlopen(req, timeout=10)
            if resp.status == 200:
                available_years.append(year)
        except Exception:
            continue
    available_years = sorted(available_years)
    if not available_years:
        raise RuntimeError("Could not discover available years")
    first_date = None
    last_date = None
    for year in available_years:
        try:
            req = Request(f"{BASE_URL_V6}/{year}/", headers={"User-Agent": "ICEFLOW"})
            resp = urlopen(req, timeout=10)
            html = resp.read().decode("utf-8", errors="ignore")
            matches = [m[1] for m in _FILENAME_RE.findall(html)]
            if matches:
                dates = sorted(matches)
                d0 = date(int(dates[0][:4]), int(dates[0][4:6]), int(dates[0][6:8]))
                d1 = date(int(dates[-1][:4]), int(dates[-1][4:6]), int(dates[-1][6:8]))
                if first_date is None or d0 < first_date:
                    first_date = d0
                if last_date is None or d1 > last_date:
                    last_date = d1
        except Exception:
            continue
    return first_date, last_date, available_years


def pilot_download(cache_dir: Path, year: int, month: int):
    reader = NSIDCSeaIceReader(cache_dir=cache_dir)
    req = Request(f"{BASE_URL_V6}/{year}/", headers={"User-Agent": "ICEFLOW"})
    resp = urlopen(req, timeout=10)
    html = resp.read().decode("utf-8", errors="ignore")
    matches = [m[1] for m in _FILENAME_RE.findall(html)]
    month_matches = [m for m in matches if int(m[4:6]) == month]
    if not month_matches:
        raise RuntimeError("No files in pilot month")
    d = date(int(month_matches[0][:4]), int(month_matches[0][4:6]), int(month_matches[0][6:8]))
    filename = reader._filename(d)
    url = reader._url(d)
    start = time.time()
    req2 = Request(url, headers={"User-Agent": "ICEFLOW"})
    resp2 = urlopen(req2, timeout=30)
    data = resp2.read()
    elapsed = time.time() - start
    size_kb = len(data) / 1024
    target = cache_dir / filename
    target.write_bytes(data)
    return size_kb, elapsed, len(month_matches)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=int, help="Start year")
    parser.add_argument("--end", type=int, help="End year")
    parser.add_argument("--pilot", action="store_true", help="Do pilot run only")
    args = parser.parse_args()

    cache_dir = default_cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)

    first_date, last_date, years = discover_range()
    print(f"Discovered range: {first_date} to {last_date} (years: {years})")
    print(f"Filename pattern: am2_icdr (AMSR2 ICDR era)")
    print(f"Product: {DATASET_NAME}")

    if args.start is None:
        args.start = first_date.year if first_date else min(years)
    if args.end is None:
        args.end = last_date.year if last_date else max(years)

    print(f"Using range: {args.start} to {args.end} (defaulting to discovered range, not 1990)")

    # Pilot
    pilot_year = args.start
    pilot_month = 8 if args.start >= 2026 else 7
    print(f"\nPILOT: downloading 1 month ({pilot_year}-{pilot_month:02d})...")
    try:
        size_kb, elapsed, files_in_month = pilot_download(cache_dir, pilot_year, pilot_month)
        print(f"Pilot: {files_in_month} files in month, first file {size_kb:.1f} KB in {elapsed:.2f}s")
        # extrapolate
        total_files = 0
        listings: dict[int, str] = {}
        for y in range(args.start, args.end + 1):
            try:
                req = Request(f"{BASE_URL_V6}/{y}/", headers={"User-Agent": "ICEFLOW"})
                with urlopen(req, timeout=10) as resp:
                    html = resp.read().decode("utf-8", errors="ignore")
                listings[y] = html
                total_files += len(_FILENAME_RE.findall(html))
            except Exception:
                continue
        total_mb = (total_files * size_kb) / 1024
        total_time_h = (total_files * elapsed) / 3600
        print(f"\nEXTRAPOLATION (before bulk download):")
        print(f"  Total files: {total_files}")
        print(f"  Estimated total size: {total_mb:.1f} MB")
        print(f"  Estimated time (sequential): {total_time_h:.1f} hours")
        print(f"  With max 4 concurrent + retries: ~{total_time_h/4:.1f} hours")
        if args.pilot:
            print("\nPilot complete. Use without --pilot to download full range.")
            return
    except Exception as e:
        print(f"Pilot failed: {e}")
        return

    # Build date->filename map from listings (no silent fallback to guessed filenames).
    date_to_filename: dict[date, str] = {}
    per_year: dict[int, dict] = {}
    for y in range(args.start, args.end + 1):
        listing = _scrape_year(y, cache_dir)
        per_year[y] = {"listed": len(listing)}
        date_to_filename.update(listing)

    requested = requested_date_range(date(args.start, 1, 1), date(args.end, 12, 31))
    gaps = find_gaps(date_to_filename, requested)
    # Record gaps per year.
    gaps_by_year: dict[int, int] = {}
    for g in gaps:
        gaps_by_year[g.year] = gaps_by_year.get(g.year, 0) + 1
    for y in range(args.start, args.end + 1):
        per_year.setdefault(y, {})["gaps"] = gaps_by_year.get(y, 0)

    print(f"\nRequested {len(requested)} days; found {len(date_to_filename)} files; "
          f"gaps: {len(gaps)} ({len(gaps_by_year)} years affected)")

    def download_file(d: date):
        # No silent fallback: the date MUST be present in the listing map.
        filename = date_to_filename[d]
        target = cache_dir / filename
        if target.exists():
            return d, target.stat().st_size, "cached"
        url = f"{BASE_URL_V6}/{d:%Y}/{filename}"
        for attempt in range(3):
            try:
                req = Request(url, headers={"User-Agent": "ICEFLOW"})
                with urlopen(req, timeout=60) as resp:
                    data = resp.read()
                target.write_bytes(data)
                return d, len(data), "downloaded"
            except Exception as e:
                if attempt < 2:
                    time.sleep(2 ** attempt)
                else:
                    return d, 0, f"error:{e}"

    to_download = sorted(date_to_filename.keys())
    print(f"Downloading {len(to_download)} files with max 4 concurrent...")
    manifest = {
        "product": DATASET_NAME,
        "version": "v06r00",
        "url_pattern": f"{BASE_URL_V6}/YYYY/sic_pss25_YYYYMMDD_<sensor>_v06r00.nc",
        "date_range": [str(first_date), str(last_date)],
        "requested_range": [f"{args.start}-01-01", f"{args.end}-12-31"],
        "gaps": [str(g) for g in gaps],
        "per_year": per_year,
        "files": [],
    }

    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = [ex.submit(download_file, d) for d in to_download]
        done = 0
        for f in as_completed(futs):
            d, size, status = f.result()
            done += 1
            if done % 10 == 0:
                print(f"  {done}/{len(to_download)}...")
            manifest["files"].append({"date": str(d), "filename": date_to_filename.get(d), "size": size, "status": status})
            y = d.year
            per_year.setdefault(y, {})
            if status == "downloaded":
                per_year[y]["downloaded"] = per_year[y].get("downloaded", 0) + 1
            elif status == "cached":
                per_year[y]["cached"] = per_year[y].get("cached", 0) + 1
            elif status.startswith("error"):
                per_year[y]["error"] = per_year[y].get("error", 0) + 1

    manifest_path = cache_dir / "manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"Manifest written to {manifest_path}")


if __name__ == "__main__":
    main()
