from __future__ import annotations

import io
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from src.api.main import app
from src.api.routers import copernicus_layers
from src.data import copernicus_tiles

client = TestClient(app)
TARGET = datetime(2026, 10, 24, tzinfo=timezone.utc)
SOURCE_TIME = datetime(2026, 10, 19, tzinfo=timezone.utc)


def _layer(key: str) -> dict[str, object]:
    is_edge = key == "sea_ice_edge"
    variable = "ice_edge" if is_edge else "ice_conc"
    style = "cmap:viridis" if is_edge else "cmap:ice"
    return {
        "key": key,
        "status": "stale",
        "target_time_utc": TARGET,
        "source_valid_time_utc": SOURCE_TIME,
        "observation_time_utc": SOURCE_TIME,
        "classification": "observation",
        "product": "SEAICE_GLO_SEAICE_L4_NRT_OBSERVATIONS_011_001",
        "dataset": f"osisaf-{key}-dataset",
        "layer": f"osisaf-{key}-dataset/{variable}",
        "variable": variable,
        "units": None if is_edge else "%",
        "source_crs": "urn:ogc:def:crs:EPSG::3857",
        "tile_matrix_set": "EPSG:3857",
        "coverage_bounds_wgs84": {
            "west": -180.0,
            "south": -90.0,
            "east": 180.0,
            "north": 90.0,
        },
        "style": style,
        "tile_max_zoom": 8,
        "tile_template": (
            "https://wmts.marine.copernicus.eu/teroWmts?request=GetTile"
            f"&layer={key}&style={style.replace(':', '%3A')}"
            "&tilematrix={z}&tilerow={y}&tilecol={x}"
            "&time=2026-10-19T00%3A00%3A00Z"
        ),
        "render_quality_layer": f"osisaf-{key}-dataset/status_flag",
        "render_quality_style": "cmap:rainbow",
        "render_quality_valid_time_utc": SOURCE_TIME,
        "render_quality_tile_matrix_set": "EPSG:3857",
        "render_quality_tile_max_zoom": 8,
        "render_quality_tile_template": (
            "https://wmts.marine.copernicus.eu/teroWmts?request=GetTile"
            f"&layer=osisaf-{key}-dataset/status_flag&style=cmap%3Arainbow"
            "&tilematrix={z}&tilerow={y}&tilecol={x}&time=2026-10-19T00%3A00%3A00Z"
        ),
        "render_quality_tile_dimensions": {"time": "2026-10-19T00:00:00Z"},
        "render_quality_reason": None,
        "tile_dimensions": {"time": "2026-10-19T00:00:00Z"},
        "attribution": "Copernicus Marine Service (CMEMS)",
        "provenance": "Official Copernicus WMTS",
        "reason": "Observation is stale.",
    }


def _set_layer_time(layer: dict[str, object], source_time: datetime) -> None:
    previous = "2026-10-19T00%3A00%3A00Z"
    selected = source_time.strftime("%Y-%m-%dT00:00:00Z").replace(":", "%3A")
    layer["source_valid_time_utc"] = source_time
    layer["tile_dimensions"] = {"time": source_time.strftime("%Y-%m-%dT00:00:00Z")}
    layer["render_quality_valid_time_utc"] = source_time
    layer["render_quality_tile_dimensions"] = {
        "time": source_time.strftime("%Y-%m-%dT00:00:00Z"),
    }
    for key in ("tile_template", "render_quality_tile_template"):
        template = layer.get(key)
        if isinstance(template, str):
            layer[key] = template.replace(previous, selected)


def _png() -> bytes:
    image = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    image.putpixel((10, 20), (33, 145, 140, 255))
    image.putpixel((11, 20), (253, 231, 37, 255))
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _quality_png() -> bytes:
    image = Image.new("RGBA", (256, 256), (0, 53, 249, 255))
    image.putpixel((11, 20), (255, 42, 0, 255))
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def test_edge_tile_renders_categorical_classes_and_masks_flagged_pixels(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        copernicus_tiles,
        "_fetch_tile",
        lambda url: _quality_png() if "status_flag" in url else _png(),
    )
    monkeypatch.setattr(copernicus_tiles, "_valid_quality_flag_color", lambda _: (0, 53, 249))
    rendered = copernicus_tiles.render_sea_ice_tile(
        {
            **_layer("sea_ice_edge"),
            "style": "cmap:viridis",
        },
        "edge",
        3,
        1,
        6,
    )
    with Image.open(io.BytesIO(rendered)) as image:
        assert image.getpixel((10, 20)) == (45, 212, 191, 255)
        assert image.getpixel((11, 20)) == (0, 0, 0, 0)


def test_concentration_renderer_masks_flagged_pixels_and_keeps_valid_values(
    monkeypatch: pytest.MonkeyPatch,
):
    concentration = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    concentration.putpixel((10, 20), (40, 120, 190, 255))
    concentration.putpixel((11, 20), (234, 253, 253, 255))
    quality = Image.new("RGBA", (256, 256), (255, 42, 0, 255))
    quality.putpixel((10, 20), (0, 53, 249, 255))
    upstream_tiles = {
        "cmap%3Aice": concentration,
        "cmap%3Arainbow": quality,
    }
    requested_urls: list[str] = []

    def fetch(url: str) -> bytes:
        requested_urls.append(url)
        for style, image in upstream_tiles.items():
            if style in url:
                output = io.BytesIO()
                image.save(output, format="PNG")
                return output.getvalue()
        raise AssertionError(f"Unexpected WMTS tile URL: {url}")

    monkeypatch.setattr(copernicus_tiles, "_fetch_tile", fetch)
    monkeypatch.setattr(
        copernicus_tiles,
        "_valid_quality_flag_color",
        lambda _: (0, 53, 249),
    )
    rendered = copernicus_tiles.render_sea_ice_tile(
        _layer("sea_ice_concentration"),
        "concentration",
        3,
        1,
        6,
    )
    with Image.open(io.BytesIO(rendered)) as image:
        assert image.getpixel((10, 20)) == (40, 120, 190, 255)
        assert image.getpixel((11, 20)) == (0, 0, 0, 0)
        assert image.getpixel((12, 20)) == (0, 0, 0, 0)
    assert len(requested_urls) == 2
    assert all("time=2026-10-19T00%3A00%3A00Z" in url for url in requested_urls)


def test_status_flag_zero_color_comes_from_the_verified_public_legend(
    monkeypatch: pytest.MonkeyPatch,
):
    copernicus_tiles.clear_tile_cache()
    calls: list[dict[str, str]] = []
    content = (
        b'{"continuous":{"valueMin":0,"valueMax":64,'
        b'"cmap":{"colorMap":[[0,53,249],[255,42,0]]}}}'
    )
    monkeypatch.setattr(
        copernicus_tiles.httpx,
        "get",
        lambda url, *, params, **_: (
            calls.append(params)
            or SimpleNamespace(
                status_code=200,
                headers={"content-type": "application/json"},
                content=content,
                json=lambda: {
                    "continuous": {
                        "valueMin": 0,
                        "valueMax": 64,
                        "cmap": {"colorMap": [[0, 53, 249], [255, 42, 0]]},
                    }
                },
            )
        ),
    )
    template = _layer("sea_ice_concentration")["render_quality_tile_template"]
    assert isinstance(template, str)
    assert copernicus_tiles._valid_quality_flag_color(template) == (0, 53, 249)
    assert copernicus_tiles._valid_quality_flag_color(template) == (0, 53, 249)
    assert len(calls) == 1
    assert calls[0]["REQUEST"] == "GetLegend"
    assert calls[0]["LAYER"].endswith("/status_flag")
    copernicus_tiles.clear_tile_cache()


def test_concentration_renderer_refuses_missing_or_mismatched_quality_tile():
    layer = _layer("sea_ice_concentration")
    layer["render_quality_tile_template"] = None
    with pytest.raises(copernicus_tiles.CopernicusTileError, match="status_flag"):
        copernicus_tiles.render_sea_ice_tile(layer, "concentration", 3, 1, 6)


def test_edge_tile_enforces_advertised_zoom_and_matrix_bounds():
    layer = _layer("sea_ice_edge")
    with pytest.raises(copernicus_tiles.CopernicusTileError, match="advertised layer coverage"):
        copernicus_tiles.render_sea_ice_tile(layer, "edge", 9, 1, 6)
    with pytest.raises(copernicus_tiles.CopernicusTileError, match="outside the verified EPSG:3857 matrix"):
        copernicus_tiles.render_sea_ice_tile(layer, "edge", 3, 8, 6)


def test_edge_tiles_outside_advertised_geographic_coverage_are_transparent(
    monkeypatch: pytest.MonkeyPatch,
):
    layer = _layer("sea_ice_edge")
    layer["coverage_bounds_wgs84"] = {
        "west": -180.0,
        "south": -90.0,
        "east": 180.0,
        "north": -50.0,
    }
    monkeypatch.setattr(
        copernicus_tiles,
        "_fetch_tile",
        lambda _: pytest.fail("WMTS must not be queried outside the advertised bbox"),
    )
    rendered = copernicus_tiles.render_sea_ice_tile(layer, "edge", 2, 2, 1)
    with Image.open(io.BytesIO(rendered)) as image:
        assert image.size == (256, 256)
        assert image.getbbox() is None


def test_fetch_tile_requires_public_tls_service_without_embedded_credentials():
    for url in (
        "http://wmts.marine.copernicus.eu/teroWmts?request=GetTile",
        "https://user:password@wmts.marine.copernicus.eu/teroWmts?request=GetTile",
        "https://example.com/teroWmts?request=GetTile",
    ):
        with pytest.raises(copernicus_tiles.CopernicusTileError):
            copernicus_tiles._fetch_tile(url)


def test_fetch_tile_checks_response_type_and_uses_bounded_cache(monkeypatch: pytest.MonkeyPatch):
    copernicus_tiles.clear_tile_cache()
    now = [100.0]
    calls: list[str] = []
    monkeypatch.setattr(copernicus_tiles.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(
        copernicus_tiles.httpx,
        "get",
        lambda url, **_: (
            calls.append(url)
            or SimpleNamespace(
                status_code=200,
                headers={"content-type": "image/png"},
                content=_png(),
            )
        ),
    )
    url = "https://wmts.marine.copernicus.eu/teroWmts?request=GetTile&x=0"
    assert copernicus_tiles._fetch_tile(url) == _png()
    assert copernicus_tiles._fetch_tile(url) == _png()
    assert len(calls) == 1
    now[0] += copernicus_tiles.TILE_CACHE_TTL_SECONDS + 1
    assert copernicus_tiles._fetch_tile(url) == _png()
    assert len(calls) == 2
    copernicus_tiles.clear_tile_cache()

    monkeypatch.setattr(
        copernicus_tiles.httpx,
        "get",
        lambda *_args, **_kwargs: SimpleNamespace(
            status_code=200,
            headers={"content-type": "text/xml"},
            content=b"not a png",
        ),
    )
    with pytest.raises(copernicus_tiles.CopernicusTileError, match="did not return a PNG"):
        copernicus_tiles._fetch_tile(url)


def test_edge_renderer_probe_caches_upstream_failures(monkeypatch: pytest.MonkeyPatch):
    copernicus_tiles.clear_tile_cache()
    calls = []

    def fail(*_args, **_kwargs):
        calls.append(1)
        raise copernicus_tiles.CopernicusTileError("Copernicus WMTS GetTile returned HTTP 500.")

    monkeypatch.setattr(copernicus_tiles, "render_sea_ice_tile", fail)
    layer = _layer("sea_ice_edge")
    assert copernicus_tiles.probe_edge_tile_renderer(layer) == (
        "Copernicus WMTS GetTile returned HTTP 500."
    )
    assert copernicus_tiles.probe_edge_tile_renderer(layer) == (
        "Copernicus WMTS GetTile returned HTTP 500."
    )
    assert len(calls) == 1
    copernicus_tiles.clear_tile_cache()


def test_layers_api_advertises_edge_and_quality_masked_concentration_renderers(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        copernicus_layers,
        "resolve_environment_layers",
        lambda _: {
            "sea_ice_edge": _layer("sea_ice_edge"),
            "sea_ice_concentration": _layer("sea_ice_concentration"),
        },
    )
    monkeypatch.setattr(copernicus_tiles, "probe_edge_tile_renderer", lambda _: None)
    response = client.get(
        "/api/v1/environment/layers",
        params={
            "target_time_utc": "2026-10-24T00:00:00Z",
            "mode": "planning_forecast",
            "planning_reference_iso": "2026-10-24T00:00:00Z",
        },
    )
    assert response.status_code == 200, response.text
    layers = response.json()["layers"]
    assert layers["sea_ice_edge"]["render_status"] == "ready"
    assert "/tiles/edge/{z}/{x}/{y}.png" in layers["sea_ice_edge"]["render_tile_template"]
    assert layers["sea_ice_concentration"]["render_status"] == "ready"
    assert "/tiles/concentration/{z}/{x}/{y}.png" in (
        layers["sea_ice_concentration"]["render_tile_template"]
    )
    assert layers["sea_ice_concentration"]["render_quality_layer"].endswith("/status_flag")
    assert layers["sea_ice_concentration"]["render_quality_valid_time_utc"] == (
        "2026-10-19T00:00:00Z"
    )
    assert "sea_ice_type" not in layers
    assert "/api/v1/environment/layers/tiles/edge/{z}/{x}/{y}.png" in (
        layers["sea_ice_edge"]["render_tile_template"]
    )
    assert "target_time_utc=2026-10-24T00%3A00%3A00Z" in (
        layers["sea_ice_edge"]["render_tile_template"]
    )
    assert "source_valid_time_utc=2026-10-19T00%3A00%3A00Z" in (
        layers["sea_ice_concentration"]["render_tile_template"]
    )


def test_layers_api_keeps_concentration_available_when_edge_time_differs(
    monkeypatch: pytest.MonkeyPatch,
):
    concentration = _layer("sea_ice_concentration")
    edge = _layer("sea_ice_edge")
    edge["source_valid_time_utc"] = datetime(2026, 10, 18, tzinfo=timezone.utc)
    edge["tile_dimensions"] = {"time": "2026-10-18T00:00:00Z"}
    edge["tile_template"] = edge["tile_template"].replace(
        "2026-10-19T00%3A00%3A00Z",
        "2026-10-18T00%3A00%3A00Z",
    )
    edge["render_quality_valid_time_utc"] = edge["source_valid_time_utc"]
    edge["render_quality_tile_dimensions"] = {"time": "2026-10-18T00:00:00Z"}
    edge["render_quality_tile_template"] = edge["render_quality_tile_template"].replace(
        "2026-10-19T00%3A00%3A00Z",
        "2026-10-18T00%3A00%3A00Z",
    )
    monkeypatch.setattr(
        copernicus_layers,
        "resolve_environment_layers",
        lambda _: {
            "sea_ice_edge": edge,
            "sea_ice_concentration": concentration,
        },
    )
    monkeypatch.setattr(copernicus_tiles, "probe_edge_tile_renderer", lambda _: None)
    response = client.get(
        "/api/v1/environment/layers",
        params={
            "target_time_utc": "2026-10-24T00:00:00Z",
            "mode": "planning_forecast",
            "planning_reference_iso": "2026-10-24T00:00:00Z",
        },
    )
    assert response.status_code == 200, response.text
    layers = response.json()["layers"]
    assert layers["sea_ice_concentration"]["render_status"] == "ready"
    assert "/tiles/concentration/{z}/{x}/{y}.png" in (
        layers["sea_ice_concentration"]["render_tile_template"]
    )
    assert layers["sea_ice_edge"]["render_status"] == "ready"
    assert layers["sea_ice_edge"]["render_reason"] is None
    assert "sea_ice_type" not in layers


def test_layers_api_rejects_concentration_wmts_time_dimension_mismatch(
    monkeypatch: pytest.MonkeyPatch,
):
    concentration = _layer("sea_ice_concentration")
    concentration["tile_dimensions"] = {"time": "2026-10-18T00:00:00Z"}
    monkeypatch.setattr(
        copernicus_layers,
        "resolve_environment_layers",
        lambda _: {
            "sea_ice_edge": _layer("sea_ice_edge"),
            "sea_ice_concentration": concentration,
        },
    )
    monkeypatch.setattr(copernicus_tiles, "probe_edge_tile_renderer", lambda _: None)
    response = client.get(
        "/api/v1/environment/layers",
        params={
            "target_time_utc": "2026-10-24T00:00:00Z",
            "mode": "planning_forecast",
            "planning_reference_iso": "2026-10-24T00:00:00Z",
        },
    )
    assert response.status_code == 200, response.text
    layers = response.json()["layers"]
    assert layers["sea_ice_concentration"]["render_status"] == "unavailable"
    assert "WMTS time dimension does not match" in layers["sea_ice_concentration"]["render_reason"]


def test_tile_api_serves_edge_and_quality_masked_concentration(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        copernicus_layers,
        "resolve_environment_layers",
        lambda _: {
            "sea_ice_edge": _layer("sea_ice_edge"),
            "sea_ice_concentration": _layer("sea_ice_concentration"),
        },
    )
    monkeypatch.setattr(copernicus_tiles, "probe_edge_tile_renderer", lambda _: None)
    monkeypatch.setattr(
        copernicus_layers.copernicus_tiles,
        "render_sea_ice_tile",
        lambda layer, mode, z, x, y: _png(),
    )
    params = {
        "target_time_utc": "2026-10-24T00:00:00Z",
        "source_valid_time_utc": "2026-10-19T00:00:00Z",
    }
    edge = client.get("/api/v1/environment/layers/tiles/edge/3/1/6.png", params=params)
    concentration = client.get(
        "/api/v1/environment/layers/tiles/concentration/3/1/6.png",
        params=params,
    )
    assert edge.status_code == 200
    assert edge.headers["content-type"] == "image/png"
    assert concentration.status_code == 200
    assert concentration.headers["content-type"] == "image/png"


def test_layers_api_uses_newest_renderable_edge_observation_after_upstream_failure(
    monkeypatch: pytest.MonkeyPatch,
):
    target = datetime(2026, 10, 25, 6, tzinfo=timezone.utc)
    newest = _layer("sea_ice_edge")
    previous = _layer("sea_ice_edge")
    _set_layer_time(newest, datetime(2026, 10, 24, tzinfo=timezone.utc))
    _set_layer_time(previous, datetime(2026, 10, 23, tzinfo=timezone.utc))
    newest["target_time_utc"] = target
    previous["target_time_utc"] = target
    concentration = _layer("sea_ice_concentration")
    concentration["target_time_utc"] = target
    resolved_times: list[set[datetime]] = []

    def resolve(_target: datetime, *, excluded_source_times=None):
        excluded = (excluded_source_times or {}).get("sea_ice_edge", set())
        resolved_times.append(set(excluded))
        edge = previous if datetime(2026, 10, 24, tzinfo=timezone.utc) in excluded else newest
        return {
            "sea_ice_edge": edge.copy(),
            "sea_ice_concentration": concentration.copy(),
        }

    def probe(layer: dict[str, object]) -> str | None:
        if layer["source_valid_time_utc"] == datetime(2026, 10, 24, tzinfo=timezone.utc):
            return "Copernicus WMTS GetTile returned HTTP 500."
        return None

    monkeypatch.setattr(copernicus_layers, "resolve_environment_layers", resolve)
    monkeypatch.setattr(copernicus_tiles, "probe_edge_tile_renderer", probe)
    response = client.get(
        "/api/v1/environment/layers",
        params={
            "target_time_utc": target.isoformat(),
            "mode": "planning_forecast",
            "planning_reference_iso": target.isoformat(),
        },
    )
    assert response.status_code == 200, response.text
    edge = response.json()["layers"]["sea_ice_edge"]
    assert edge["source_valid_time_utc"] == "2026-10-23T00:00:00Z"
    assert edge["render_status"] == "ready"
    assert "2026-10-24T00:00:00Z" in edge["reason"]
    assert "HTTP 500" in edge["reason"]
    assert len(resolved_times) == 2
    assert resolved_times[1] == {datetime(2026, 10, 24, tzinfo=timezone.utc)}


def test_tile_api_rejects_concentration_with_mismatched_quality_time(
    monkeypatch: pytest.MonkeyPatch,
):
    concentration = _layer("sea_ice_concentration")
    concentration["render_quality_valid_time_utc"] = datetime(
        2026,
        10,
        18,
        tzinfo=timezone.utc,
    )
    monkeypatch.setattr(
        copernicus_layers,
        "resolve_environment_layers",
        lambda _: {
            "sea_ice_edge": _layer("sea_ice_edge"),
            "sea_ice_concentration": concentration,
        },
    )
    monkeypatch.setattr(copernicus_tiles, "probe_edge_tile_renderer", lambda _: None)
    response = client.get(
        "/api/v1/environment/layers/tiles/concentration/3/1/6.png",
        params={
            "target_time_utc": "2026-10-24T00:00:00Z",
            "source_valid_time_utc": "2026-10-19T00:00:00Z",
        },
    )
    assert response.status_code == 424
    assert "same-time status_flag" in response.json()["detail"]
