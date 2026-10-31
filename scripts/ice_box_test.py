"""Ice-box validation: compare GLORYS siconc vs NSIDC SIC for a single day.

Compares the CMEMS GLORYS12V1 daily sea-ice concentration against
NOAA/NSIDC CDR V6 observations within a small Antarctic box
(e.g. 60–80 °E, 60–75 °S) for the start date of a replay pack.

The GLORYS grid is regular lat/lon (0.083°); the NSIDC grid is 25 km
polar stereographic (EPSG:3412).  The GLORYS field is interpolated to the
NSIDC grid using scipy's ``RegularGridInterpolator`` after transforming
NSIDC x/y to lat/lon via pyproj.

Stop condition (fail-fast): the script exits with a non-zero status when
the Pearson correlation between the two fields (over non-NaN overlap) drops
below 0.3 **or** the mean absolute concentration difference exceeds 0.3.

Usage::

    python -m scripts.ice_box_test \
        --pack /tmp/iceflow-test-pack \
        --date 2022-01-15 \
        --bbox "60,-75,80,-60"
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr
from pyproj import Transformer
from scipy.interpolate import RegularGridInterpolator

CORR_STOP = 0.3
MEANDIFF_STOP = 0.3


def _find_product(manifest: dict, product_name: str) -> str | None:
    for p in manifest["products"]:
        if p["product"] == product_name:
            return p["local_path"]
    return None


def _load_product(pack_dir: Path, manifest: dict, product_name: str) -> xr.Dataset:
    rel_path = _find_product(manifest, product_name)
    if rel_path is None:
        raise FileNotFoundError(f"Product {product_name!r} not found in manifest")
    return xr.open_dataset(pack_dir / Path(rel_path).name)


def _non_nan_fraction(arr: np.ndarray) -> float:
    return float(np.isfinite(arr).mean()) if arr.size else 0.0


def _glorys_to_nsidc_grid(
    glorys_ds: xr.Dataset,
    nsidc_ds: xr.Dataset,
    date_str: str,
) -> np.ndarray:
    """Interpolate GLORYS siconc onto the NSIDC polar-stereographic grid."""
    siconc = glorys_ds["siconc"].sel(time=date_str)
    glorys_lat = np.asarray(siconc["latitude"].values, dtype=np.float64)
    glorys_lon = np.asarray(siconc["longitude"].values, dtype=np.float64)
    glorys_data = np.asarray(siconc.values, dtype=np.float64)

    nsidc_y = np.asarray(nsidc_ds["y"].values, dtype=np.float64)
    nsidc_x = np.asarray(nsidc_ds["x"].values, dtype=np.float64)

    transformer = Transformer.from_crs("EPSG:3412", "EPSG:4326", always_xy=True)
    xx, yy = np.meshgrid(nsidc_x, nsidc_y)
    lon_grid, lat_grid = transformer.transform(xx, yy)

    # RegularGridInterpolator requires ascending axes.
    lat_asc = np.sort(glorys_lat)
    lon_asc = np.sort(glorys_lon)
    lat_order = np.argsort(glorys_lat)
    lon_order = np.argsort(glorys_lon)
    data_ordered = glorys_data[np.ix_(lat_order, lon_order)]

    interp = RegularGridInterpolator(
        (lat_asc, lon_asc),
        data_ordered,
        bounds_error=False,
        fill_value=np.nan,
    )

    # GLORYS longitude may start at 0; wrap negative NSIDC lons to 0–360.
    lon_wrapped = lon_grid.copy()
    lon_wrapped[lon_wrapped < 0] += 360.0

    points = np.column_stack([lat_grid.ravel(), lon_wrapped.ravel()])
    return interp(points).reshape(lat_grid.shape)


def _bbox_mask(
    lat_grid: np.ndarray,
    lon_grid: np.ndarray,
    bbox: tuple[float, float, float, float],
) -> np.ndarray:
    west, south, east, north = bbox
    lon = lon_grid.copy()
    lon[lon < 0] += 360.0
    west_w = west if west >= 0 else west + 360.0
    east_w = east if east >= 0 else east + 360.0

    if west_w > east_w:
        mask = (lon >= west_w) | (lon <= east_w)
    else:
        mask = (lon >= west_w) & (lon <= east_w)
    mask &= (lat_grid >= south) & (lat_grid <= north)
    return mask


def run_ice_box_test(
    pack_dir: Path,
    test_date: date,
    bbox: tuple[float, float, float, float],
) -> dict[str, Any]:
    manifest = json.loads((pack_dir / "manifest.json").read_text())

    date_str = test_date.isoformat()
    print(f"Ice-box test for {date_str}")
    print(f"  Box: lon {bbox[0]}–{bbox[2]}°E, lat {bbox[1]}–{bbox[3]}°S")
    print()

    results: dict[str, Any] = {"date": date_str, "bbox": list(bbox)}

    # --- Load GLORYS siconc ---
    try:
        glorys = _load_product(pack_dir, manifest, "glorys_siconc")
        glorys_sic = glorys["siconc"].sel(time=date_str)
    except Exception as exc:
        print(f"  [error] Could not load GLORYS siconc: {exc}")
        results["glorys_siconc_available"] = False
        results["stop"] = False
        return results

    results["glorys_siconc_available"] = True
    glorys_arr = np.asarray(glorys_sic.values, dtype=np.float64)
    results["glorys_siconc_nonan_frac"] = _non_nan_fraction(glorys_arr)

    # --- Load NSIDC ice_conc ---
    try:
        nsidc = _load_product(pack_dir, manifest, "nrt_ice_concentration")
        nsidc_sic = nsidc["ice_conc"].sel(time=date_str)
    except Exception as exc:
        print(f"  [error] Could not load NSIDC ice_conc: {exc}")
        results["nsidc_sic_available"] = False
        results["stop"] = False
        return results

    results["nsidc_sic_available"] = True
    nsidc_arr = np.asarray(nsidc_sic.values, dtype=np.float64)
    results["nsidc_sic_nonan_frac"] = _non_nan_fraction(nsidc_arr)

    # --- Compute NSIDC lat/lon grid ---
    nsidc_y = np.asarray(nsidc["y"].values, dtype=np.float64)
    nsidc_x = np.asarray(nsidc["x"].values, dtype=np.float64)
    transformer = Transformer.from_crs("EPSG:3412", "EPSG:4326", always_xy=True)
    xx, yy = np.meshgrid(nsidc_x, nsidc_y)
    lon_grid, lat_grid = transformer.transform(xx, yy)
    lon_grid = np.asarray(lon_grid, dtype=np.float64)
    lat_grid = np.asarray(lat_grid, dtype=np.float64)

    # --- Interpolate GLORYS siconc to NSIDC grid ---
    print("  Interpolating GLORYS siconc to NSIDC grid...")
    try:
        glorys_on_nsidc = _glorys_to_nsidc_grid(glorys, nsidc, date_str)
    except Exception as exc:
        print(f"  [error] Interpolation failed: {exc}")
        results["interpolation"] = "failed"
        results["stop"] = False
        return results

    # --- Spatial mask: restrict to test bbox ---
    box_mask = _bbox_mask(lat_grid, lon_grid, bbox)

    valid = np.isfinite(glorys_on_nsidc) & np.isfinite(nsidc_arr) & box_mask
    if valid.sum() == 0:
        print("  [error] No overlap between GLORYS and NSIDC within box")
        print(f"  NSIDC non-NaN in box: {np.isfinite(nsidc_arr[box_mask]).sum()}")
        print(f"  GLORYS non-NaN in box (after interp): {np.isfinite(glorys_on_nsidc[box_mask]).sum()}")
        print("  [STOP] Ice-box test FAILS: no overlapping valid cells")
        results["overlap_count"] = 0
        results["nsidc_nonnan_in_box"] = int(np.isfinite(nsidc_arr[box_mask]).sum())
        results["glorys_nonnan_in_box"] = int(np.isfinite(glorys_on_nsidc[box_mask]).sum())
        results["stop"] = True
        results["stop_reason"] = "no_overlap_no_valid_cells"
        return results

    g_vals = glorys_on_nsidc[valid]
    n_vals = nsidc_arr[valid]

    # --- Correlation ---
    if g_vals.std() > 0 and n_vals.std() > 0:
        corr = float(np.corrcoef(g_vals, n_vals)[0, 1])
    else:
        corr = 0.0

    mean_abs_diff = float(np.mean(np.abs(g_vals - n_vals)))

    results["overlap_count"] = int(valid.sum())
    results["correlation"] = corr
    results["mean_abs_diff"] = mean_abs_diff
    results["glorys_mean"] = float(g_vals.mean())
    results["nsidc_mean"] = float(n_vals.mean())
    results["glorys_nonnan_after_interp"] = _non_nan_fraction(glorys_on_nsidc)

    print()
    print("=" * 60)
    print(f"  Overlap cells:        {valid.sum()}")
    print(f"  GLORYS siconc mean:     {results['glorys_mean']:.4f}")
    print(f"  NSIDC SIC mean:         {results['nsidc_mean']:.4f}")
    print(f"  Correlation:            {corr:.4f}")
    print(f"  Mean |diff|:            {mean_abs_diff:.4f}")
    print()

    # --- ERA5 swh under-ice flag ---
    era5_waves_path = _find_product(manifest, "era5_waves")
    swh_nonan_frac = None
    if era5_waves_path:
        try:
            era5 = xr.open_dataset(pack_dir / Path(era5_waves_path).name)
            times = np.asarray(era5["time"].values)
            noon = np.datetime64(f"{date_str}T12:00:00", "ns")
            t_idx = int(np.argmin(np.abs(times - noon)))
            swh = era5["swh"].isel(time=t_idx)

            lats = np.asarray(swh["latitude"].values, dtype=np.float64)
            lons = np.asarray(swh["longitude"].values, dtype=np.float64)
            swh_arr = np.asarray(swh.values, dtype=np.float64)

            lat_mask = (lats >= bbox[1]) & (lats <= bbox[3])

            lon_w = bbox[0] % 360
            lon_e = bbox[2] % 360
            lon_wrapped = lons.copy()
            lon_wrapped[lons < 0] += 360.0
            if lon_w <= lon_e:
                lon_mask = (lon_wrapped >= lon_w) & (lon_wrapped <= lon_e)
            else:
                lon_mask = (lon_wrapped >= lon_w) | (lon_wrapped <= lon_e)

            sub = swh_arr[np.ix_(lat_mask, lon_mask)]
            swh_nonan_frac = _non_nan_fraction(sub)
            era5.close()
        except Exception as exc:
            print(f"  [warn] ERA5 swh check: {exc}")

    results["era5_swh_nonan_frac"] = swh_nonan_frac

    # --- CMEMS extra variables (usi, vsi, sithick, siconc) ---
    extra_vars_report: dict[str, Any] = {}
    cmems_path = _find_product(manifest, "cmems_current")
    if cmems_path:
        try:
            cur_ds = xr.open_dataset(pack_dir / Path(cmems_path).name)
            for var in ("usi", "vsi", "sithick", "siconc"):
                if var in cur_ds.data_vars:
                    arr = np.asarray(cur_ds[var].isel(time=0).values)
                    if arr.ndim == 3 and "depth" in cur_ds[var].dims:
                        arr = arr[0]
                    extra_vars_report[var] = _non_nan_fraction(arr)
                else:
                    extra_vars_report[var] = "not present"
            cur_ds.close()
        except Exception as exc:
            extra_vars_report["error"] = str(exc)

    results["cmems_extra_vars"] = extra_vars_report

    stop = corr < CORR_STOP or mean_abs_diff > MEANDIFF_STOP
    results["stop"] = stop
    results["corr_stop"] = CORR_STOP
    results["meandiff_stop"] = MEANDIFF_STOP

    if stop:
        reasons = []
        if corr < CORR_STOP:
            reasons.append(f"correlation {corr:.4f} < {CORR_STOP}")
        if mean_abs_diff > MEANDIFF_STOP:
            reasons.append(f"mean |diff| {mean_abs_diff:.4f} > {MEANDIFF_STOP}")
        print(f"  [STOP] Ice-box test FAILS: {'; '.join(reasons)}")
    else:
        print(f"  [PASS] Correlation {corr:.4f} >= {CORR_STOP}; mean |diff| {mean_abs_diff:.4f} <= {MEANDIFF_STOP}")

    print()
    print("  Non-NaN fractions:")
    print(f"    GLORYS siconc:       {results['glorys_siconc_nonan_frac']:.4f}")
    print(f"    NSIDC SIC:           {results['nsidc_sic_nonan_frac']:.4f}")
    print(f"    GLORYS siconc interp:{results['glorys_nonnan_after_interp']:.4f}")
    if swh_nonan_frac is not None:
        print(f"    ERA5 swh in box:     {swh_nonan_frac:.4f}")
    for var, frac in extra_vars_report.items():
        print(f"    CMEMS {var}: {frac}")

    print("=" * 60)
    return results


def parse_bbox(value: str) -> tuple[float, float, float, float]:
    parts = [float(p) for p in value.split(",")]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("bbox must be lon_min,lat_min,lon_max,lat_max")
    west, south, east, north = parts
    return west, south, east, north


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", required=True, type=Path, help="Path to replay pack directory")
    parser.add_argument("--date", required=True, type=str, help="Date to test (YYYY-MM-DD)")
    parser.add_argument("--bbox", required=True, type=parse_bbox, help="lon_min,lat_min,lon_max,lat_max")
    args = parser.parse_args()

    try:
        test_date = datetime.strptime(args.date, "%Y-%m-%d").date()
    except ValueError:
        print(f"Error: --date must be YYYY-MM-DD, got {args.date}")
        raise SystemExit(2)

    results = run_ice_box_test(args.pack, test_date, args.bbox)

    results_path = args.pack / "ice_box_test_result.json"
    results_path.write_text(json.dumps(results, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"\nResults written: {results_path}")

    if results.get("stop", False):
        sys.exit(1)


if __name__ == "__main__":
    main()
