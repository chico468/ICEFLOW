#!/usr/bin/env python
"""Discover and download real NSIDC SIC data."""
from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path
from urllib.request import Request, urlopen

from src.data.nsidc_sea_ice import NSIDCSeaIceReader, BASE_URL_V6, DATASET_NAME, default_cache_dir


def discover_range():
    """Discover available range by probing V6."""
    available_years = []
    for year in range(2026, 1977, -1):
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
            html = resp.read().decode('utf-8', errors='ignore')
            import re
            matches = re.findall(r'sic_pss25_(\d{8})_([A-Za-z0-9]+)_v06r00\.nc', html)
            if matches:
                dates = sorted([m[0] for m in matches])
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
    html = resp.read().decode('utf-8', errors='ignore')
    import re
    matches = re.findall(r'sic_pss25_(\d{8})_([A-Za-z0-9]+)_v06r00\.nc', html)
    month_matches = [m for m in matches if int(m[0][4:6]) == month]
    if not month_matches:
        raise RuntimeError("No files in pilot month")
    d = date(int(month_matches[0][0][:4]), int(month_matches[0][0][4:6]), int(month_matches[0][0][6:8]))
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
        for y in range(args.start, args.end + 1):
            try:
                req = Request(f"{BASE_URL}/{y}/", headers={"User-Agent": "ICEFLOW"})
                resp = urlopen(req, timeout=10)
                html = resp.read().decode('utf-8', errors='ignore')
                import re
                matches = re.findall(r'sic_pss25_(\d{8})_am2_icdr_v04r00\.nc', html)
                total_files += len(matches)
            except Exception:
                pass
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

    # Full download with politeness
    manifest = {
        "product": DATASET_NAME,
        "version": "v06r00",
        "url_pattern": f"{BASE_URL_V6}/YYYY/sic_pss25_YYYYMMDD_<sensor>_v06r00.nc",
        "date_range": [str(first_date), str(last_date)],
        "requested_range": [f"{args.start}-01-01", f"{args.end}-12-31"],
        "gaps": [],
        "files": []
    }

    # Build date->filename map from listings
    date_to_filename = {}
    for y in range(args.start, args.end + 1):
        try:
            req = Request(f"{BASE_URL_V6}/{y}/", headers={"User-Agent": "ICEFLOW"})
            resp = urlopen(req, timeout=10)
            html = resp.read().decode('utf-8', errors='ignore')
            import re
            matches = re.findall(r'href="(sic_pss25_(\d{8})_[A-Za-z0-9]+_v06r00\.nc)"', html)
            for m in matches:
                fname = m[0]
                dstr = m[1]
                d = date(int(dstr[:4]), int(dstr[4:6]), int(dstr[6:8]))
                date_to_filename[d] = fname
        except Exception:
            continue

    all_dates = sorted(date_to_filename.keys())

    def download_file(d):
        reader = NSIDCSeaIceReader(cache_dir=cache_dir)
        filename = date_to_filename.get(d) or reader._filename(d)
        target = cache_dir / filename
        if target.exists():
            return d, target.stat().st_size, "cached"
        url = f"{BASE_URL_V6}/{d:%Y}/{filename}"
        for attempt in range(3):
            try:
                req = Request(url, headers={"User-Agent": "ICEFLOW"})
                resp = urlopen(req, timeout=60)
                data = resp.read()
                target.write_bytes(data)
                return d, len(data), "downloaded"
            except Exception as e:
                if attempt < 2:
                    time.sleep(2 ** attempt)
                else:
                    return d, 0, f"error:{e}"

    print(f"\nDownloading {len(all_dates)} files with max 4 concurrent...")
    manifest["per_year"] = {}
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = [ex.submit(download_file, d) for d in all_dates]
        done = 0
        for f in as_completed(futs):
            d, size, status = f.result()
            done += 1
            if done % 10 == 0:
                print(f"  {done}/{len(all_dates)}...")
            manifest["files"].append({"date": str(d), "filename": date_to_filename.get(d), "size": size, "status": status})
            y = d.year
            if y not in manifest["per_year"]:
                manifest["per_year"][y] = {"downloaded": 0, "cached": 0, "error": 0}
            if status == "downloaded":
                manifest["per_year"][y]["downloaded"] += 1
            elif status == "cached":
                manifest["per_year"][y]["cached"] += 1
            elif status.startswith("error"):
                manifest["per_year"][y]["error"] += 1

    # Write manifest next to cached files
    manifest_path = cache_dir / "manifest.json"
    with open(manifest_path, 'w') as f:
        json.dump(manifest, f, indent=2)
    print(f"Manifest written to {manifest_path}")


if __name__ == "__main__":
    main()
