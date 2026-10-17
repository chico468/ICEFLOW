"""Unit tests for IMO POLARIS engine."""
from src.core.polaris_risk import IceClass, IceType, IceRegimeComponent, calculate_rio

def test_open_water_rio():
    comp = [IceRegimeComponent(ice_type=IceType.OPEN_WATER, concentration_tenths=10)]
    res = calculate_rio(IceClass.PC5, comp)
    assert res.rio == 30
    assert res.status == "NORMAL_OPERATION"
    assert res.is_operation_permitted is True

def test_heavy_ice_prohibited_rio():
    """
    PC7 in 10/10 heavy multi-year ice.

    The v0.1 prototype asserted RIO == -50, which came from an approximate risk-value table it
    invented. The official MSC.1/Circ.1519 value for PC7 against heavy multi-year ice is -3 per
    tenth, so the correct outcome is -30. Both figures prohibit the operation; only one of them
    is the standard. The legacy spelling "Multi_Year" still deserialises to HEAVY_MULTI_YEAR.
    """
    comp = [IceRegimeComponent(ice_type=IceType.HEAVY_MULTI_YEAR, concentration_tenths=10)]
    res = calculate_rio(IceClass.PC7, comp)
    assert res.rio == -30
    assert res.status == "OPERATION_PROHIBITED"
    assert res.is_operation_permitted is False
    assert res.max_recommended_speed_knots == 0.0

def test_mixed_regime():
    comp = [
        IceRegimeComponent(ice_type=IceType.THIN_FIRST_YEAR_1, concentration_tenths=4),
        IceRegimeComponent(ice_type=IceType.OPEN_WATER, concentration_tenths=6)
    ]
    res = calculate_rio(IceClass.PC5, comp)
    assert res.rio > 0
    assert res.is_operation_permitted is True
