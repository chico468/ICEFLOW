"""Regional geography: the build pipeline's geometry and the loader's honest failure modes."""
import json
import ssl
import urllib.error
from unittest import mock

import pytest

from scripts.build_regional_context import (
    BuildError,
    build_context,
    clip_ring,
    fetch_json,
    main,
    process_polygon,
    read_json_file,
    simplify_ring,
    write_atomic,
)
from src.data.regional_context import REGION, load_regional

BOX = (0.0, 0.0, 10.0, 10.0)


def _square(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]


def _area(ring):
    return abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(ring, ring[1:] + ring[:1]))) / 2


def test_clip_keeps_a_polygon_that_is_already_inside():
    out = clip_ring(_square(2, 2, 4, 4), BOX)
    assert _area(out) == pytest.approx(4.0)


def test_clip_trims_a_polygon_that_straddles_the_edge():
    out = clip_ring(_square(5, 5, 15, 15), BOX)
    assert _area(out) == pytest.approx(25.0)
    assert all(0 <= x <= 10 and 0 <= y <= 10 for x, y in out)


def test_clip_removes_a_polygon_that_is_wholly_outside():
    assert clip_ring(_square(20, 20, 30, 30), BOX) == []


def test_clip_handles_a_polygon_that_covers_the_whole_box():
    assert _area(clip_ring(_square(-50, -50, 50, 50), BOX)) == pytest.approx(100.0)


def test_simplify_keeps_endpoints_and_drops_collinear_points():
    line = [(0, 0), (1, 0.001), (2, 0), (3, 0.002), (4, 0)]
    out = simplify_ring(line, 0.05)
    assert out[0] == (0, 0) and out[-1] == (4, 0) and len(out) < len(line)
    assert simplify_ring(line, 0) == line


def test_simplify_keeps_a_real_corner():
    out = simplify_ring([(0, 0), (5, 0), (5, 5)], 0.1)
    assert (5, 0) in out or len(out) == 3


def test_polygon_whose_exterior_is_clipped_away_drops_its_holes():
    polygon = [_square(20, 20, 30, 30), _square(22, 22, 24, 24)]
    assert process_polygon(polygon, BOX, 0.01) == []


def _fc(*features):
    return {"type": "FeatureCollection", "features": list(features)}


def _poly(name, ring):
    return {"type": "Feature", "properties": {"NAME": name}, "geometry": {"type": "Polygon", "coordinates": [ring]}}


def test_build_context_shape_attribution_and_labels():
    region = {"lon_min": 0.0, "lon_max": 10.0, "lat_min": 0.0, "lat_max": 10.0}
    land = _fc(_poly("x", _square(1, 1, 9, 9)), _poly("outside", _square(50, 50, 60, 60)))
    countries = _fc(_poly("Alpha", _square(1, 1, 5, 5)), _poly("Beta", _square(6, 6, 9, 9)), _poly("Far", _square(40, 40, 50, 50)))
    doc = build_context(land, countries, region=region, generated_utc="2026-01-01T00:00:00+00:00")
    assert doc["stats"]["land_polygons"] == 1
    assert [c["name"] for c in doc["countries"]] == ["Alpha", "Beta"]  # largest first; the far one is gone
    assert doc["countries"][0]["label"] == [3.0, 3.0]
    assert "Natural Earth" in doc["attribution"] and "not suitable for navigation" in doc["accuracy_note"]
    assert json.loads(json.dumps(doc)) == doc


def test_build_context_refuses_an_empty_result():
    region = {"lon_min": 0.0, "lon_max": 10.0, "lat_min": 0.0, "lat_max": 10.0}
    with pytest.raises(BuildError) as err:
        build_context(_fc(_poly("x", _square(50, 50, 60, 60))), _fc(), region=region)
    assert err.value.code == 3


def test_local_file_path_rejects_html_and_non_geojson(tmp_path):
    html = tmp_path / "land.geojson"
    html.write_text("<html>404</html>", encoding="utf-8")
    with pytest.raises(BuildError):
        read_json_file(str(html))
    notfc = tmp_path / "x.geojson"
    notfc.write_text('{"type": "Feature"}', encoding="utf-8")
    with pytest.raises(BuildError):
        read_json_file(str(notfc))


def test_cli_from_local_files_writes_a_loadable_file(tmp_path):
    land = tmp_path / "land.geojson"
    countries = tmp_path / "countries.geojson"
    land.write_text(json.dumps(_fc(_poly("l", _square(10, -40, 30, -20)))), encoding="utf-8")
    countries.write_text(json.dumps(_fc(_poly("Testland", _square(10, -40, 30, -20)))), encoding="utf-8")
    out = tmp_path / "regional.json"
    assert main(["--land-file", str(land), "--countries-file", str(countries), "--out", str(out)]) == 0
    doc = load_regional(out)
    assert doc["available"] is True and doc["countries"][0]["name"] == "Testland"
    assert doc["sources"][0]["sha256"] and doc["region"] == REGION


def test_cli_reports_failure_with_a_nonzero_exit(tmp_path):
    assert main(["--land-file", str(tmp_path / "missing.geojson"), "--countries-file", str(tmp_path / "m2.geojson"), "--out", str(tmp_path / "o.json")]) == 3
    assert not (tmp_path / "o.json").exists()


def test_write_atomic_leaves_no_temp_files(tmp_path):
    out = tmp_path / "sub" / "r.json"
    write_atomic(out, {"land": []})
    assert out.exists() and [p.name for p in out.parent.iterdir()] == ["r.json"]


def test_loader_says_not_built_and_how_to_build(tmp_path):
    doc = load_regional(tmp_path / "missing.json")
    assert doc["available"] is False and doc["land"] == []
    assert any("build_regional_context" in line for line in doc["setup"])
    assert doc["region"] == REGION


def test_loader_rejects_corrupt_or_foreign_files(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert load_regional(bad)["available"] is False
    foreign = tmp_path / "foreign.json"
    foreign.write_text('{"hello": 1}', encoding="utf-8")
    assert load_regional(foreign)["available"] is False


def test_region_covers_every_configured_port_and_station():
    from src.data.stations import get_ports, get_stations

    for p in list(get_ports()) + list(get_stations()):
        assert REGION["lat_min"] <= p["latitude"] <= REGION["lat_max"], p["name"]
        assert REGION["lon_min"] <= p["longitude"] <= REGION["lon_max"], p["name"]


def test_certificate_failure_is_reported_and_never_bypassed():
    err = urllib.error.URLError(ssl.SSLCertVerificationError("certificate verify failed"))
    with mock.patch("urllib.request.urlopen", side_effect=err) as opener:
        with pytest.raises(BuildError) as info:
            fetch_json("https://example.invalid/land.geojson")
    assert info.value.code == 2
    assert "left ON deliberately" in str(info.value) and "--land-file" in str(info.value)
    ctx = opener.call_args.kwargs["context"]
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname is True


def test_http_error_and_dead_network_exit_with_code_2():
    http = urllib.error.HTTPError("https://x", 404, "Not Found", {}, None)
    with mock.patch("urllib.request.urlopen", side_effect=http):
        with pytest.raises(BuildError) as info:
            fetch_json("https://x/land.geojson")
    assert info.value.code == 2 and "404" in str(info.value)
    with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Name or service not known")):
        with pytest.raises(BuildError) as info:
            fetch_json("https://x/land.geojson")
    assert info.value.code == 2 and "could not connect" in str(info.value)
