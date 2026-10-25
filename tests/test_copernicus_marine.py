from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.data import copernicus_marine as cm

client = TestClient(app)
NOW = datetime.fromisoformat("2026-01-10T00:00:00+00:00")


def _layer(
    identifier: str,
    title: str,
    style: str,
    time_value: str,
    extra: str = "",
    metadata: str = "",
) -> str:
    return f"""
    <Layer>
      <ows:Title>{title}</ows:Title>
      <ows:Identifier>{identifier}</ows:Identifier>
      <ows:WGS84BoundingBox>
        <ows:LowerCorner>-180 -90</ows:LowerCorner>
        <ows:UpperCorner>180 90</ows:UpperCorner>
      </ows:WGS84BoundingBox>
      <Style isDefault="true"><ows:Identifier>{style}</ows:Identifier></Style>
      <Format>image/png</Format>
      <Dimension><ows:Identifier>time</ows:Identifier><Default>{time_value.split('/')[1] if '/' in time_value else time_value}</Default><Value>{time_value}</Value></Dimension>
      {extra}
      {metadata}
      <TileMatrixSetLink><TileMatrixSet>EPSG:3857</TileMatrixSet></TileMatrixSetLink>
    </Layer>"""


def _capabilities(
    *,
    edge_time: str = "2026-01-08T00:00:00Z/2026-01-10T00:00:00Z/P1D",
    concentration_time: str = "2026-01-07T00:00:00Z/2026-01-09T00:00:00Z/P1D",
    current_time: str = "2026-01-09T00:00:00Z/2026-01-10T00:00:00Z/PT6H",
    northward_current_time: str | None = None,
    forecast_time: str = "2026-01-01T00:00:00Z/2026-01-12T00:00:00Z/P1D",
) -> bytes:
    product_ice = "SEAICE_GLO_SEAICE_L4_NRT_OBSERVATIONS_011_001"
    product_ant = "SEAICE_ANT_PHY_AUTO_L3_NRT_011_012"
    product_ocean = "GLOBAL_ANALYSISFORECAST_PHY_001_024"
    layers = [
        _layer(
            f"{product_ice}/osisaf_obs-si_glo_phy-siedge_nrt_sh-P1D_202107/ice_edge",
            "Observed Antarctic ice edge",
            "cmap:viridis",
            edge_time,
        ),
        _layer(
            f"{product_ice}/osisaf_obs-si_glo_phy-siedge_nrt_sh-P1D_202107/status_flag",
            "Observed Antarctic ice-edge status flag",
            "cmap:rainbow",
            edge_time,
        ),
        _layer(
            f"{product_ice}/osisaf_obs-si_glo_phy-sic-south_nrt_amsr2_l4_P1D-m_202304/ice_conc",
            "Observed Antarctic ice concentration",
            "cmap:ice",
            concentration_time,
        ),
        _layer(
            f"{product_ice}/osisaf_obs-si_glo_phy-sic-south_nrt_amsr2_l4_P1D-m_202304/status_flag",
            "Observed Antarctic concentration status flag",
            "cmap:rainbow",
            concentration_time,
        ),
        _layer(
            f"{product_ant}/cmems_obs-si_ant_phy_nrt_l3-1km_P1D_202303/ice_concentration",
            "High-resolution Antarctic concentration",
            "cmap:ice",
            "2026-01-08T00:00:00Z/2026-01-10T00:00:00Z/P1D",
        ),
        _layer(
            f"{product_ocean}/cmems_mod_glo_phy_anfc_0.083deg_P1D-m_202406/siconc",
            "Global sea ice forecast concentration",
            "cmap:ice",
            forecast_time,
        ),
        _layer(
            f"{product_ocean}/cmems_mod_glo_phy-cur_anfc_0.083deg_PT6H-i_202406/uo",
            "Eastward current",
            "cmap:balance",
            current_time,
            "<Dimension><ows:Identifier>elevation</ows:Identifier><Default>-0.494</Default><Value>-0.494</Value></Dimension>",
            "<ows:Metadata><Unit>m s-1</Unit><StandardName>eastward_sea_water_velocity</StandardName><admp_updated_data>2026-01-10T00:00:00Z</admp_updated_data></ows:Metadata>",
        ),
        _layer(
            f"{product_ocean}/cmems_mod_glo_phy-cur_anfc_0.083deg_PT6H-i_202406/vo",
            "Northward current",
            "cmap:balance",
            northward_current_time or current_time,
            "<Dimension><ows:Identifier>elevation</ows:Identifier><Default>-0.494</Default><Value>-0.494</Value></Dimension>",
            "<ows:Metadata><Unit>m s-1</Unit><StandardName>northward_sea_water_velocity</StandardName><admp_updated_data>2026-01-10T00:00:00Z</admp_updated_data></ows:Metadata>",
        ),
        _layer(
            f"{product_ocean}/cmems_mod_glo_phy_anfc_0.083deg-sst-anomaly_P1D-m_202411/sea_surface_temperature_anomaly",
            "Sea surface temperature anomaly",
            "cmap:viridis",
            forecast_time,
            metadata="<ows:Metadata><Unit>degrees_C</Unit><StandardName>sea_surface_temperature_anomaly</StandardName><admp_updated_data>2026-01-10T00:00:00Z</admp_updated_data></ows:Metadata>",
        ),
    ]
    matrices = "".join(
        f"<TileMatrix><ows:Identifier>{zoom}</ows:Identifier>"
        f"<ScaleDenominator>{559082264.0287178 / (2**zoom)}</ScaleDenominator>"
        "<TopLeftCorner>-20037508.3428 20037508.3428</TopLeftCorner>"
        "<TileWidth>256</TileWidth><TileHeight>256</TileHeight>"
        f"<MatrixWidth>{2**zoom}</MatrixWidth><MatrixHeight>{2**zoom}</MatrixHeight>"
        "</TileMatrix>"
        for zoom in range(11)
    )
    return f"""<?xml version="1.0"?>
    <Capabilities xmlns="http://www.opengis.net/wmts/1.0"
      xmlns:ows="http://www.opengis.net/ows/1.1"
      xmlns:xlink="http://www.w3.org/1999/xlink">
      <ows:ServiceIdentification><ows:Title>Marine Data Store</ows:Title></ows:ServiceIdentification>
      <ows:OperationsMetadata><ows:Operation name="GetTile">
        <ows:DCP><ows:HTTP><ows:Get xlink:href="https://wmts.example/tiles"/>
        </ows:HTTP></ows:DCP>
        <ows:Constraint name="GetEncoding"><ows:AllowedValues><ows:Value>KVP</ows:Value></ows:AllowedValues></ows:Constraint>
      </ows:Operation></ows:OperationsMetadata>
      <Contents>{''.join(layers)}
        <TileMatrixSet><ows:Identifier>EPSG:3857</ows:Identifier>
          <ows:SupportedCRS>urn:ogc:def:crs:EPSG::3857</ows:SupportedCRS>
          {matrices}
        </TileMatrixSet>
      </Contents>
    </Capabilities>""".encode()


@pytest.fixture
def capabilities() -> cm.WmtsCapabilities:
    return cm.parse_capabilities(
        _capabilities(),
        retrieved_at_utc=datetime(2026, 1, 10, tzinfo=timezone.utc),
    )


def test_capabilities_discover_layers_styles_crs_time_and_kvp(capabilities):
    assert capabilities.service_title == "Marine Data Store"
    assert "KVP" in capabilities.get_tile_encodings
    edge = next(layer for layer in capabilities.layers.values() if layer.identifier.endswith("/ice_edge"))
    assert edge.styles == ("cmap:viridis",)
    assert edge.dimensions["time"] == (
        "2026-01-08T00:00:00Z/2026-01-10T00:00:00Z/P1D",
    )
    assert edge.tile_matrix_sets == ("EPSG:3857",)
    assert edge.wgs84_bounds == (-180.0, -90.0, 180.0, 90.0)
    assert capabilities.tile_matrix_sets["EPSG:3857"].supported_crs.endswith("3857")
    assert capabilities.tile_matrix_sets["EPSG:3857"].matrix_ids == tuple(
        str(value) for value in range(11)
    )
    assert capabilities.tile_matrix_sets["EPSG:3857"].scale_denominators["0"] == pytest.approx(
        559082264.0287178
    )
    current = next(
        layer for layer in capabilities.layers.values() if layer.identifier.endswith("/uo")
    )
    assert current.units == "m s-1"
    assert current.standard_name == "eastward_sea_water_velocity"
    assert current.data_updated_at_utc == NOW


def test_capabilities_normalize_latitude_longitude_axis_labels():
    capabilities = cm.parse_capabilities(
        """<Capabilities xmlns="http://www.opengis.net/wmts/1.0"
          xmlns:ows="http://www.opengis.net/ows/1.1">
          <Contents><Layer><ows:Identifier>test/ice_edge</ows:Identifier>
            <ows:WGS84BoundingBox axisLabels="Lat Long">
              <ows:LowerCorner>-85 -180</ows:LowerCorner>
              <ows:UpperCorner>-35 180</ows:UpperCorner>
            </ows:WGS84BoundingBox>
          </Layer></Contents>
        </Capabilities>"""
    )
    layer = capabilities.layers["test/ice_edge"]
    assert layer.wgs84_bounds == (-180.0, -85.0, 180.0, -35.0)


def test_live_discovery_names_match_current_products(capabilities):
    discovered = cm.discover_layers(capabilities)
    identifiers = {layer["identifier"] for layer in discovered}
    assert any("siedge_nrt_sh-P1D_202107/ice_edge" in value for value in identifiers)
    assert any("sic-south_nrt_amsr2_l4_P1D-m_202304/ice_conc" in value for value in identifiers)
    assert any("l3-1km_P1D_202303/ice_concentration" in value for value in identifiers)
    assert any(value.endswith("/uo") for value in identifiers)
    assert any(value.endswith("/vo") for value in identifiers)


def test_resolver_selects_concentration_and_pairs_surface_currents(capabilities):
    result = cm.resolve_environment_layers(
        NOW,
        now=NOW,
        capabilities=capabilities,
    )
    assert result["sea_ice_edge"]["source_valid_time_utc"] == datetime(
        2026, 1, 10, tzinfo=timezone.utc
    )
    assert result["sea_ice_edge"]["status"] == "ready"
    assert result["sea_ice_edge"]["classification"] == "observation"
    assert result["sea_ice_edge"]["render_quality_layer"].endswith("/status_flag")
    assert result["sea_ice_edge"]["render_quality_valid_time_utc"] == result["sea_ice_edge"]["source_valid_time_utc"]
    assert result["sea_ice_concentration"]["source_valid_time_utc"] == datetime(
        2026, 1, 9, tzinfo=timezone.utc
    )
    assert "sea_ice_type" not in result
    quality = result["sea_ice_concentration"]
    assert quality["render_quality_layer"].endswith("/status_flag")
    assert quality["render_quality_style"] == "cmap:rainbow"
    assert quality["render_quality_valid_time_utc"] == quality["source_valid_time_utc"]
    assert quality["render_quality_tile_dimensions"]["time"] == "2026-01-09T00:00:00Z"
    assert "time=2026-01-09T00%3A00%3A00.000Z" in quality["render_quality_tile_template"]
    assert (
        result["ocean_current_eastward"]["source_valid_time_utc"]
        == result["ocean_current_northward"]["source_valid_time_utc"]
    )
    assert result["ocean_current_eastward"]["status"] == "ready"


def test_resolver_can_skip_an_advertised_time_that_failed_tile_validation(capabilities):
    excluded_time = datetime(2026, 1, 10, tzinfo=timezone.utc)
    result = cm.resolve_environment_layers(
        NOW,
        now=NOW,
        capabilities=capabilities,
        excluded_source_times={"sea_ice_edge": {excluded_time}},
    )
    edge = result["sea_ice_edge"]
    assert edge["source_valid_time_utc"] == datetime(2026, 1, 9, tzinfo=timezone.utc)
    assert edge["tile_dimensions"]["time"] == "2026-01-09T00:00:00Z"
    assert edge["render_quality_valid_time_utc"] == edge["source_valid_time_utc"]
    assert edge["render_quality_tile_dimensions"]["time"] == "2026-01-09T00:00:00Z"


def test_historical_target_never_selects_a_later_observation(capabilities):
    result = cm.resolve_environment_layers(
        datetime(2026, 1, 9, 12, tzinfo=timezone.utc),
        now=NOW,
        capabilities=capabilities,
    )
    assert result["sea_ice_edge"]["source_valid_time_utc"] == datetime(
        2026, 1, 9, tzinfo=timezone.utc
    )
    assert result["sea_ice_edge"]["source_valid_time_utc"] < datetime(
        2026, 1, 9, 12, tzinfo=timezone.utc
    )


def test_future_target_rejects_satellite_observations_and_uses_forecast(capabilities):
    target = datetime(2026, 1, 11, tzinfo=timezone.utc)
    result = cm.resolve_environment_layers(target, now=NOW, capabilities=capabilities)
    assert result["sea_ice_edge"]["status"] == "unsupported_time"
    assert result["sea_ice_concentration"]["status"] == "unsupported_time"
    forecast = result["sea_ice_concentration_forecast"]
    assert forecast["status"] == "ready"
    assert forecast["classification"] == "forecast"
    assert forecast["source_valid_time_utc"] == target
    assert forecast["forecast_lead_hours"] is None
    assert "initialization time" in forecast["reason"]


def test_future_target_does_not_relabel_an_analysis_as_a_forecast(capabilities):
    target = datetime(2026, 1, 10, 1, tzinfo=timezone.utc)
    result = cm.resolve_environment_layers(target, now=NOW, capabilities=capabilities)
    forecast = result["sea_ice_concentration_forecast"]
    assert forecast["status"] == "unsupported_time"
    assert forecast["source_valid_time_utc"] is None
    assert forecast["tile_template"] is None
    assert "analysis, not a future forecast" in forecast["reason"]


def test_paired_currents_are_withheld_if_only_one_has_a_future_time():
    metadata = cm.parse_capabilities(
        _capabilities(
            current_time="2026-01-09T00:00:00Z/2026-01-10T06:00:00Z/PT6H",
            northward_current_time="2026-01-09T00:00:00Z/2026-01-10T00:00:00Z/PT6H",
        )
    )
    target = datetime(2026, 1, 10, 6, tzinfo=timezone.utc)
    result = cm.resolve_environment_layers(target, now=NOW, capabilities=metadata)
    assert result["ocean_current_eastward"]["status"] == "unsupported_time"
    assert result["ocean_current_northward"]["status"] == "unsupported_time"
    assert result["ocean_current_eastward"]["source_valid_time_utc"] is None
    assert result["ocean_current_northward"]["source_valid_time_utc"] is None


def test_forecast_horizon_beyond_advertised_time_coverage_is_outside_coverage(
    capabilities,
):
    target = datetime(2026, 1, 20, tzinfo=timezone.utc)
    result = cm.resolve_environment_layers(target, now=NOW, capabilities=capabilities)
    assert result["sea_ice_concentration_forecast"]["status"] == "outside_coverage"
    assert result["sea_surface_temperature_anomaly"]["status"] == "outside_coverage"


def test_stale_and_outside_coverage_are_explicit(capabilities):
    stale = cm.resolve_environment_layers(
        datetime(2026, 1, 10, tzinfo=timezone.utc),
        now=NOW,
        capabilities=cm.parse_capabilities(
            _capabilities(
                edge_time="2026-01-01T00:00:00Z/2026-01-02T00:00:00Z/P1D",
                concentration_time="2026-01-01T00:00:00Z/2026-01-02T00:00:00Z/P1D",
            )
        ),
    )
    assert stale["sea_ice_edge"]["status"] == "stale"
    assert stale["sea_ice_concentration"]["status"] == "stale"

    outside = cm.resolve_environment_layers(
        datetime(2025, 12, 1, tzinfo=timezone.utc),
        now=NOW,
        capabilities=capabilities,
    )
    assert outside["sea_ice_edge"]["status"] == "outside_coverage"


def test_concentration_is_not_blocked_by_a_different_edge_observation_time():
    split = cm.parse_capabilities(
        _capabilities(
            edge_time="2026-01-08T00:00:00Z/2026-01-08T00:00:00Z/P1D",
            concentration_time="2026-01-09T00:00:00Z/2026-01-09T00:00:00Z/P1D",
        )
    )
    result = cm.resolve_environment_layers(NOW, now=NOW, capabilities=split)
    assert result["sea_ice_edge"]["status"] == "ready"
    assert result["sea_ice_edge"]["source_valid_time_utc"] == datetime(
        2026, 1, 8, tzinfo=timezone.utc
    )
    assert result["sea_ice_concentration"]["status"] == "ready"
    assert result["sea_ice_concentration"]["source_valid_time_utc"] == datetime(
        2026, 1, 9, tzinfo=timezone.utc
    )
    assert (
        result["sea_ice_concentration"]["render_quality_valid_time_utc"]
        == result["sea_ice_concentration"]["source_valid_time_utc"]
    )


def test_layer_without_advertised_dataset_is_unavailable():
    empty = cm.parse_capabilities(
        b"""<Capabilities xmlns="http://www.opengis.net/wmts/1.0"
        xmlns:ows="http://www.opengis.net/ows/1.1"><Contents>
        <Layer><ows:Identifier>other</ows:Identifier></Layer>
        </Contents></Capabilities>"""
    )
    result = cm.resolve_environment_layers(NOW, now=NOW, capabilities=empty)
    assert result["sea_ice_edge"]["status"] == "unavailable"


def test_unsupported_calendar_interval_is_explicit(capabilities):
    monthly = cm.parse_capabilities(
        _capabilities(edge_time="2026-01-01T00:00:00Z/2026-03-01T00:00:00Z/P1M")
    )
    result = cm.resolve_environment_layers(NOW, now=NOW, capabilities=monthly)
    assert result["sea_ice_edge"]["status"] == "unsupported_time"


def test_tile_template_requires_advertised_kvp_png_style_and_matrix(capabilities):
    result = cm.resolve_environment_layers(NOW, now=NOW, capabilities=capabilities)
    edge = result["sea_ice_edge"]
    assert edge["tile_template"].startswith("https://wmts.example/tiles?")
    assert "tilematrix={z}" in edge["tile_template"]
    assert "tilerow={y}" in edge["tile_template"]
    assert "tilecol={x}" in edge["tile_template"]
    assert "time=2026-01-10T00%3A00%3A00.000Z" in edge["tile_template"]
    assert edge["source_crs"].endswith("3857")
    assert edge["tile_max_zoom"] == 10
    assert edge["units"] is None
    assert result["ocean_current_eastward"]["tile_dimensions"]["elevation"] == "-0.494"
    assert "elevation=-0.494" in result["ocean_current_eastward"]["tile_template"]
    no_kvp = cm.parse_capabilities(_capabilities().replace(b">KVP<", b">REST<"))
    assert cm.resolve_environment_layers(NOW, now=NOW, capabilities=no_kvp)[
        "sea_ice_edge"
    ]["tile_template"] is None


def test_tile_template_rejects_matrix_with_non_xyz_scale_denominators(capabilities):
    matrix_set = capabilities.tile_matrix_sets["EPSG:3857"]
    scales = dict(matrix_set.scale_denominators)
    scales["4"] *= 2
    capabilities.tile_matrix_sets["EPSG:3857"] = cm.TileMatrixSet(
        **{**matrix_set.__dict__, "scale_denominators": scales}
    )
    concentration = cm.resolve_environment_layers(
        NOW,
        now=NOW,
        capabilities=capabilities,
    )["sea_ice_concentration"]
    assert concentration["tile_template"] is None
    assert concentration["reason"] == (
        "Layer lacks a verified public KVP tile template in EPSG:3857 with PNG format."
    )


def test_tile_template_rejects_non_public_or_non_https_operation_url():
    for unsafe_url in (
        "http://wmts.example/tiles",
        "https://user:secret@wmts.example/tiles",
        "https://wmts.example/tiles?token=secret",
    ):
        xml = _capabilities().replace(
            b"https://wmts.example/tiles", unsafe_url.encode()
        )
        metadata = cm.parse_capabilities(xml)
        result = cm.resolve_environment_layers(NOW, now=NOW, capabilities=metadata)
        assert result["sea_ice_edge"]["tile_template"] is None
        assert "secret" not in str(result["sea_ice_edge"])


def test_capabilities_malformed_response_is_reported():
    with pytest.raises(cm.CopernicusMarineError, match="malformed XML"):
        cm.parse_capabilities(b"<Capabilities>")


def test_upstream_errors_are_safe_and_do_not_leak_credentials(monkeypatch):
    secret = "private-token-do-not-log"

    def fail(*args, **kwargs):
        raise httpx.ConnectError(f"failed for https://example.test/?token={secret}")

    monkeypatch.setattr(cm.httpx, "get", fail)
    cm.clear_metadata_cache()
    with pytest.raises(cm.CopernicusMarineError) as error:
        cm.get_capabilities("https://example.test/capabilities")
    assert secret not in str(error.value)


def test_metadata_cache_expires_and_has_a_bounded_entry_count(monkeypatch):
    cm.clear_metadata_cache()
    payload = _capabilities()
    calls = []

    class Response:
        content = payload

        def raise_for_status(self):
            return None

    def fetch(url, **kwargs):
        calls.append(url)
        return Response()

    monkeypatch.setattr(cm.httpx, "get", fetch)
    first = cm.get_capabilities("https://example.test/1", now_monotonic=10)
    second = cm.get_capabilities("https://example.test/1", now_monotonic=20)
    assert first is second
    assert len(calls) == 1
    cm.get_capabilities(
        "https://example.test/1",
        now_monotonic=10 + cm.METADATA_TTL_SECONDS + 1,
    )
    assert len(calls) == 2

    for index in range(cm.METADATA_CACHE_SIZE + 1):
        cm.get_capabilities(f"https://example.test/{index}", now_monotonic=50 + index)
    assert len(cm._metadata_cache) <= cm.METADATA_CACHE_SIZE


def test_api_is_registered_typed_and_uses_phase_one_time_resolution(monkeypatch):
    monkeypatch.setattr(
        "src.api.routers.copernicus_layers.resolve_environment_layers",
        lambda target: {
            "sea_ice_edge": {
                "key": "sea_ice_edge",
                "status": "unavailable",
                "target_time_utc": target,
                "product": "candidate",
                "variable": "ice_edge",
                "attribution": "Copernicus Marine Service",
                "provenance": "mock",
            }
        },
    )
    response = client.get(
        "/api/v1/environment/layers",
        params={
            "target_time_utc": "2026-01-10T00:00:00Z",
            "mode": "active_voyage",
            "departure_iso": "2026-01-09T00:00:00Z",
            "sim_hours": 24,
            "timestamp_iso": "2026-01-10T00:00:00Z",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["time_resolution"]["mode"] == "active_voyage"
    assert body["layers"]["sea_ice_edge"]["status"] == "unavailable"


def test_api_rejects_target_inconsistent_with_shared_clock():
    response = client.get(
        "/api/v1/environment/layers",
        params={
            "target_time_utc": "2026-01-11T00:00:00Z",
            "mode": "planning_forecast",
            "planning_reference_iso": "2026-01-09T00:00:00Z",
            "lead_hours": 24,
        },
    )
    assert response.status_code == 422
    assert "inconsistent" in response.json()["detail"]
