"""Unit tests for Lindqvist ice resistance."""
from src.core.lindqvist_model import VesselParameters, calculate_ice_resistance

def test_open_water_resistance():
    vessel = VesselParameters()
    res = calculate_ice_resistance(vessel, velocity_knots=12.0, ice_thickness_m=0.0, ice_concentration=0.0)
    assert res.crushing_resistance_kn == 0.0
    assert res.total_resistance_kn > 0.0

def test_ice_resistance_increases_with_thickness():
    vessel = VesselParameters()
    r1 = calculate_ice_resistance(vessel, velocity_knots=6.0, ice_thickness_m=0.5, ice_concentration=0.8)
    r2 = calculate_ice_resistance(vessel, velocity_knots=6.0, ice_thickness_m=1.2, ice_concentration=0.8)
    assert r2.total_resistance_kn > r1.total_resistance_kn
    assert r2.required_power_kw > r1.required_power_kw
