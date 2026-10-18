"""The observed USNIC-format snapshot: validation, staleness and honest failure modes."""
from datetime import date

from src.data.observed_icebergs import (
    OBSERVED_STALE_AFTER_DAYS,
    find_snapshot,
    load_snapshot,
)

HEADER = "Iceberg,Length (NM),Width (NM),Latitude,Longitude,Area (sqNM),Area (sqKM),Last Update\n"


def _write(tmp_path, rows, name="AntarcticIcebergs_20260820.csv", bom=True):
    path = tmp_path / name
    path.write_bytes((("\ufeff" if bom else "") + HEADER + "".join(rows)).encode("utf-8"))
    return path


def test_repository_snapshot_loads_and_is_marked_observed():
    snap = load_snapshot(today=date(2026, 10, 17))
    assert snap["available"] is True
    assert snap["kind"] == "observed"
    assert snap["count"] == 33 and snap["rejected"] == []
    assert snap["observed_date"] == "2026-08-20"
    assert snap["used_for_routing"] is False
    assert snap["position_uncertainty"] == "not provided by the source"
    assert "not recorded" in snap["source"]  # the label must not over-claim the file's origin
    ids = [b["id"] for b in snap["icebergs"]]
    assert len(ids) == len(set(ids))
    for b in snap["icebergs"]:
        assert -90 <= b["latitude"] <= 90 and -180 <= b["longitude"] <= 180


def test_age_and_stale_flag_follow_the_clock():
    stale = load_snapshot(today=date(2026, 10, 17))
    assert stale["age_days"] == 58 and stale["stale"] is True
    assert "STALE" in stale["stale_note"]

    fresh = load_snapshot(today=date(2026, 8, 22))
    assert fresh["age_days"] == 2 and fresh["stale"] is False

    edge = load_snapshot(today=date(2026, 8, 20 + OBSERVED_STALE_AFTER_DAYS))
    assert edge["age_days"] == OBSERVED_STALE_AFTER_DAYS and edge["stale"] is False


def test_future_dated_snapshot_is_flagged_not_trusted():
    snap = load_snapshot(today=date(2026, 8, 1))
    assert snap["age_days"] == 0
    assert snap["warnings"], "a future-dated file must warn"


def test_bad_rows_are_reported_not_dropped_silently(tmp_path):
    path = _write(
        tmp_path,
        [
            "D1,10,5,-66.0,70.0,50,171,08/20/2026\n",
            "D2,10,5,-166.0,70.0,50,171,08/20/2026\n",   # latitude out of range
            "D3,10,5,-66.0,70.0,50,171,not-a-date\n",     # unreadable date
            "D4,0,5,-66.0,70.0,50,171,08/20/2026\n",      # non-positive size
            "D5,10,5,abc,70.0,50,171,08/20/2026\n",       # not a number
        ],
    )
    snap = load_snapshot(path, today=date(2026, 8, 21))
    assert snap["available"] and snap["count"] == 1
    assert {r["id"] for r in snap["rejected"]} == {"D2", "D3", "D4", "D5"}
    assert all(r["reason"] for r in snap["rejected"])


def test_missing_file_and_missing_columns_are_explicit(tmp_path):
    missing = load_snapshot(tmp_path / "nope.csv")
    assert missing["available"] is False and missing["icebergs"] == []
    assert "setup" in missing

    bad = tmp_path / "AntarcticIcebergs_20260101.csv"
    bad.write_text("Iceberg,Latitude\nD1,-66\n", encoding="utf-8")
    result = load_snapshot(bad)
    assert result["available"] is False and "missing required columns" in result["reason"]


def test_all_rows_invalid_is_unavailable_not_empty_success(tmp_path):
    path = _write(tmp_path, ["D1,10,5,-166.0,70.0,50,171,08/20/2026\n"])
    assert load_snapshot(path)["available"] is False


def test_find_snapshot_picks_the_newest_by_filename_date(tmp_path):
    _write(tmp_path, ["D1,10,5,-66,70,50,171,08/20/2026\n"], name="AntarcticIcebergs_20260820.csv")
    newer = _write(tmp_path, ["D1,10,5,-66,70,50,171,09/10/2026\n"], name="AntarcticIcebergs_20260910.csv")
    assert find_snapshot(tmp_path) == newer
    assert find_snapshot(tmp_path / "does_not_exist") is None


def test_utf8_bom_does_not_corrupt_first_column(tmp_path):
    path = _write(tmp_path, ["D1,10,5,-66,70,50,171,08/20/2026\n"], bom=True)
    assert load_snapshot(path, today=date(2026, 8, 21))["available"] is True
