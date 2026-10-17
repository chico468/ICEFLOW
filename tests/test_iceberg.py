"""Unit tests for iceberg Lagrangian drift physics."""
from src.core.iceberg_tracker import IcebergProfile, predict_iceberg_drift

def test_iceberg_drift_prediction():
    berg = IcebergProfile(berg_id="TEST-01", latitude=-68.0, longitude=75.0)
    res = predict_iceberg_drift(
        berg=berg,
        wind_speed_ms=10.0,
        wind_direction_from_deg=90.0,
        current_speed_ms=0.3,
        current_direction_to_deg=270.0,
        forecast_hours=24,
        time_step_hours=6
    )
    assert len(res.trajectory) == 5
    assert res.net_displacement_km > 0.0
