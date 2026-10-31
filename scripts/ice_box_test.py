"""Ice-box test: GLORYS siconc vs NSIDC G02202 V6 SIC.

Compares CMEMS GLORYS12V1 sea-ice concentration (siconc, 1/12 deg regular
lat/lon) against NOAA/NSIDC CDR G02202 V6 (polar stereographic 25 km) on three
boxes.  Output per case: n cells, correlation, mean difference, RMSE, plus 3
sample cells side by side to verify orientation.

NaN rule (documented in code):
  GLORYS siconc attrs contain no _FillValue / missing_value / comment.  The only
  metadata is cell_methods='area: mean where sea_ice', standard_name
  'sea_ice_area_fraction', units '1', valid_min=1 / valid_max=28670.  The
  dataset does NOT explicitly state that NaN means "no ice".  We adopt the rule
  that NaN siconc = 0 (open ocean, no ice) ONLY on cells where the co-located
  CMEMS current uo is valid (i.e. ocean, not land).  Cells where uo is also NaN
  (land / no current) are excluded.  This is what turns the previous "no
  overlap" failure into a usable comparison: in summer most open-ocean cells
  have valid uo but NaN siconc.
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

import httpx
import numpy as np
import xarray as xr
import pyproj

PACK = Path("/tmp/iceflow-full-pack")
GLORYS_NC = PACK / "glorys_siconc_20220115_33d.nc"
CURR_NC = PACK / "cmems_current_20220115_33d.nc"
NSIDC_CACHE = PACK / "nsidc_raw_cache"
CACHE_DIR = Path("/tmp/icebox-cache")
NSIDC_CACHE_EXTRA = Path("/tmp/icebox-nsidc-cache")
WORK = Path(tempfile.mkdtemp(prefix="icebox-"))

NSIDC_V6_BASE = "https://noaadata.apps.nsidc.org/NOAA/G02202_V6/south/daily"
CMEMS_DATASET = "cmems_mod_glo_phy_my_0.083deg_P1D-m"
W, S, E, N = -180.0, -90.0, 180.0, -60.0  # native subset box (Southern Ocean)

DOWNLOAD_LOG: list[str] = []
PROJ = pyproj.Proj("EPSG:3412")  # NSIDC southern polar stereographic, 25 km


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _download_size_first(url: str, local: Path) -> int:
    if local.is_file():
        size = local.stat().st_size
        DOWNLOAD_LOG.append(f"{url} -> {local.name} (cached, {size} bytes)")
        return size
    head = httpx.head(url, timeout=30, follow_redirects=True)
    size = int(head.headers.get("content-length", "0") or 0)
    print(f"    [size] {url} content-length={size} bytes")
    r = httpx.get(url, timeout=120)
    r.raise_for_status()
    local.write_bytes(r.content)
    size = local.stat().st_size
    DOWNLOAD_LOG.append(f"{url} -> {local.name} ({size} bytes, sha256={_sha256(local)[:12]}...)")
    print(f"    [download] {size} bytes")
    return size


def _coperm_subset(day: date, variables: list[str], out_name: str) -> Path:
    """Download one day of CMEMS variables. Returns local path (cached if present)."""
    local = CACHE_DIR / out_name
    if local.is_file():
        size = local.stat().st_size
        DOWNLOAD_LOG.append(f"CMEMS {CMEMS_DATASET} {day} vars={variables} (cached, {size} bytes)")
        print(f"    [cache] {out_name} {size} bytes")
        return local
    out = WORK / f"coperm_{day:%Y%m%d}_{'_'.join(variables)}"
    out.mkdir(exist_ok=True)
    cmd = [
        "copernicusmarine", "subset",
        "-i", CMEMS_DATASET,
    ]
    for v in variables:
        cmd += ["-v", v]
    cmd += [
        "--minimum-longitude", str(W), "--maximum-longitude", str(E),
        "--minimum-latitude", str(S), "--maximum-latitude", str(N),
        "--start-datetime", f"{day.isoformat()}T00:00:00",
        "--end-datetime", f"{day.isoformat()}T23:00:00",
        "-o", str(out), "--file-format", "netcdf", "--overwrite",
    ]
    t0 = time.perf_counter()
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    elapsed = time.perf_counter() - t0
    if res.returncode != 0:
        raise RuntimeError(f"CMEMS subset failed for {day} {variables}: {res.stderr[-1500:]}")
    produced = sorted(out.glob("*.nc"))
    if not produced:
        raise RuntimeError(f"CMEMS produced no file for {day} {variables} in {out}")
    src = produced[-1]
    size = src.stat().st_size
    DOWNLOAD_LOG.append(f"CMEMS {CMEMS_DATASET} {day} vars={variables} ({size} bytes, {elapsed:.1f}s)")
    print(f"    [download] CMEMS {day} {vars} {size} bytes in {elapsed:.1f}s")
    # Cache under a stable name for reuse.
    import shutil
    shutil.copy2(src, local)
    return local


def _to_2d(arr: np.ndarray) -> np.ndarray:
    arr = np.asarray(arr, dtype=np.float64)
    while arr.ndim > 2:
        arr = arr[0]
    return arr


def load_glorys(day: date):
    """(siconc 2D, uo_valid 2D bool, lats, lons) for ``day``."""
    in_pack = GLORYS_NC.is_file() and date(2022, 1, 15) <= day <= date(2022, 2, 16)
    if in_pack:
        g = xr.open_dataset(GLORYS_NC)
        c = xr.open_dataset(CURR_NC)
        times = np.asarray(g["time"].values)
        idx = int(np.argmin(np.abs(times - np.datetime64(day.isoformat()))))
        siconc = np.asarray(g["siconc"][idx].values, dtype=np.float64)
        ctimes = np.asarray(c["time"].values)
        cidx = int(np.argmin(np.abs(ctimes - np.datetime64(day.isoformat()))))
        uo = np.asarray(c["uo"][cidx].values, dtype=np.float64)
        lats = np.asarray(g["latitude"].values)
        lons = np.asarray(g["longitude"].values)
        g.close(); c.close()
    else:
        siconc_path = _coperm_subset(day, ["siconc"], f"glorys_siconc_{day:%Y%m%d}.nc")
        curr_path = _coperm_subset(day, ["uo", "vo"], f"cmems_current_{day:%Y%m%d}.nc")
        gs = xr.open_dataset(siconc_path)
        siconc = _to_2d(np.asarray(gs["siconc"].values))
        lats = np.asarray(gs["latitude"].values)
        lons = np.asarray(gs["longitude"].values)
        gs.close()
        gc = xr.open_dataset(curr_path)
        uo = _to_2d(np.asarray(gc["uo"].values))
        gc.close()
    return siconc, np.isfinite(uo), lats, lons


def nsidc_filename(day: date) -> str:
    if day.year >= 2025:
        sensor = "am2"
    elif day.year >= 2008:
        sensor = "F17"
    elif day.year >= 1995:
        sensor = "F13"
    elif day.year >= 1992:
        sensor = "F11"
    elif day.year >= 1987:
        sensor = "F08"
    else:
        sensor = "n07"
    return f"sic_pss25_{day:%Y%m%d}_{sensor}_v06r00.nc"


def _find_nsidc(day: date) -> Path:
    name = nsidc_filename(day)
    for cache in (NSIDC_CACHE, NSIDC_CACHE_EXTRA):
        p = cache / name
        if p.is_file():
            return p
    return NSIDC_CACHE / name


def load_nsidc(day: date):
    """(sic 2D, lat2d, lon2d, x, y, valid_mask) on the NSIDC 25 km grid."""
    local = _find_nsidc(day)
    if not local.is_file():
        url = f"{NSIDC_V6_BASE}/{day:%Y}/{nsidc_filename(day)}"
        _download_size_first(url, local)
    ds = xr.open_dataset(local)
    sic = np.asarray(ds["cdr_seaice_conc"].values, dtype=np.float64)
    if sic.ndim == 3:
        sic = sic[0]
    x = np.asarray(ds["x"].values); y = np.asarray(ds["y"].values)
    ds.close()
    xg, yg = np.meshgrid(x, y)
    lon2d, lat2d = PROJ(xg, yg, inverse=True)
    valid = np.isfinite(sic)
    return sic, lat2d, lon2d, x, y, valid


def to_pm180(lon: np.ndarray) -> np.ndarray:
    return (((lon + 180.0) % 360.0) + 360.0) % 360.0 - 180.0


def regrid_glorys_to_nsidc(siconc: np.ndarray, uo_valid: np.ndarray, g_lats: np.ndarray,
                           g_lons: np.ndarray, n_lat: np.ndarray, n_lon: np.ndarray,
                           x: np.ndarray, y: np.ndarray):
    """Area-average GLORYS (1/12 deg) onto NSIDC 25 km cells.

    Method: every GLORYS cell centre is projected into the NSIDC polar
    stereographic frame and assigned to the NSIDC cell containing it
    (nearest cell by x/y index).  Each NSIDC value is the mean of the GLORYS
    cells assigned to it -- an area average (each fine cell is fully assigned
    to one coarse cell).  Chosen over nearest-neighbour because GLORYS (~9 km)
    is finer than NSIDC (25 km).

    NaN rule: GLORYS NaN -> 0 only where uo_valid; where uo invalid the cell is
    skipped (land / no current).
    """
    siconc_filled = np.where(np.isnan(siconc) & uo_valid, 0.0, siconc)
    dx = float(np.diff(x).mean()); dy = float(np.diff(y).mean())
    g_lat_g, g_lon_g = np.meshgrid(g_lats, to_pm180(g_lons), indexing="ij")
    gx, gy = PROJ(g_lon_g.ravel(), g_lat_g.ravel())  # forward to EPSG:3412 metres
    i = np.clip(np.round((gx - x[0]) / dx).astype(int), 0, x.size - 1)
    j = np.clip(np.round((gy - y[0]) / dy).astype(int), 0, y.size - 1)
    n_y, n_x = n_lat.shape
    acc = np.zeros((n_y, n_x), dtype=np.float64)
    cnt = np.zeros((n_y, n_x), dtype=np.int64)
    gv = siconc_filled.ravel()
    finite = np.isfinite(gv)
    np.add.at(acc, (j[finite], i[finite]), gv[finite])
    np.add.at(cnt, (j[finite], i[finite]), 1)
    regridded = np.full((n_y, n_x), np.nan, dtype=np.float64)
    np.divide(acc, cnt, out=regridded, where=cnt > 0)
    return regridded, siconc_filled


def box_mask(n_lat, n_lon, west, south, east, north):
    return (n_lat >= south) & (n_lat <= north) & (n_lon >= west) & (n_lon <= east)


def compare_case(day: date, west: float, south: float, east: float, north: float,
                 label: str) -> dict:
    print(f"\n===== {label}  date={day.isoformat()}  box=({west},{south},{east},{north}) =====")
    siconc, uo_valid, g_lats, g_lons = load_glorys(day)
    sic, n_lat, n_lon, x, y, ns_valid = load_nsidc(day)
    regridded, siconc_filled = regrid_glorys_to_nsidc(siconc, uo_valid, g_lats, g_lons,
                                                      n_lat, n_lon, x, y)
    m = box_mask(n_lat, n_lon, west, south, east, north) & ns_valid & np.isfinite(regridded)
    n_cells = int(m.sum())
    g_vals = regridded[m]; s_vals = sic[m]
    out = {"label": label, "date": day.isoformat(),
           "box": [west, south, east, north], "n": n_cells}
    if n_cells == 0:
        print("  NO paired cells in box")
        return out
    corr = float(np.corrcoef(g_vals, s_vals)[0, 1]) if n_cells > 1 else float("nan")
    mean_diff = float(np.mean(g_vals - s_vals))
    rmse = float(np.sqrt(np.mean((g_vals - s_vals) ** 2)))
    out.update(correlation=corr, mean_diff=mean_diff, rmse=rmse,
               glorys_mean=float(np.mean(g_vals)), nsidc_mean=float(np.mean(s_vals)))
    print(f"  n_cells={n_cells}  correlation={corr:.6f}  mean_diff={mean_diff:.6f}  rmse={rmse:.6f}")
    print(f"  glorys_mean={out['glorys_mean']:.6f}  nsidc_mean={out['nsidc_mean']:.6f}")
    gross = (abs(mean_diff) > 0.3) or (rmse > 0.5) or (n_cells > 1 and abs(corr) < 0.3)
    out["gross_disagreement"] = bool(gross)
    print(f"  gross_disagreement={gross}")
    n_y, n_x = n_lat.shape
    idxs = np.flatnonzero(m)
    show = idxs[: min(3, len(idxs))]
    print("  sample cells (lat, lon, NSIDC_SIC, GLORYS_regridded):")
    for lin in show:
        j, i = divmod(int(lin), n_x)
        print(f"    ({n_lat[j, i]:+.2f}, {n_lon[j, i]:+.2f})  "
              f"NSIDC={sic[j, i]:.4f}  GLORYS={regridded[j, i]:.4f}")
    return out


def main():
    # Record GLORYS siconc metadata (task 2a).
    g = xr.open_dataset(GLORYS_NC)
    si = g["siconc"]
    print("GLORYS siconc attributes:", dict(si.attrs))
    print("GLORYS dataset attributes:", dict(g.attrs))
    print("GLORYS siconc: no _FillValue, no missing_value, no comment attribute; "
          "cell_methods implies ice-only computation (NaN = not-computed).")
    g.close()
    results = []
    results.append(compare_case(date(2022, 1, 15), -60.0, -75.0, -20.0, -60.0,
                                "Weddell Sea (20-60W, 60-75S) Jan 2022"))
    results.append(compare_case(date(2022, 1, 15), 60.0, -75.0, 80.0, -60.0,
                                "60-80E, 60-75S Jan 2022"))
    results.append(compare_case(date(2022, 8, 15), 60.0, -75.0, 80.0, -60.0,
                                "60-80E, 60-75S Aug 2022 (winter)"))
    print("\n===== DOWNLOAD LOG (sizes) =====")
    for line in DOWNLOAD_LOG:
        print(" ", line)
    print("\n===== SUMMARY =====")
    for r in results:
        print(f"  {r['label']:45s} n={r['n']:5d} corr={r.get('correlation', float('nan')): .6f} "
              f"mean_diff={r.get('mean_diff', float('nan')): .6f} rmse={r.get('rmse', float('nan')): .6f} "
              f"gross={r.get('gross_disagreement')}")
    any_gross = any(r.get("gross_disagreement") for r in results if r.get("n", 0) > 0)
    print(f"\nANY_GROSS_DISAGREEMENT: {any_gross}")
    if any_gross:
        print("STOP: gross disagreement detected in at least one case.")
        sys.exit(2)
    return results


if __name__ == "__main__":
    main()
