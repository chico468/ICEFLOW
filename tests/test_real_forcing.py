"""Tests for the real-forcing iceberg environment (Phase 4B).

Fast tests only: no 5 GB forcing download, no network.
"""
from __future__ import annotations

from src.core.real_forcing import RealForcingEnvironment


def test_real_forcing_environment_is_not_synthetic():
    """The real-forcing environment must label itself non-synthetic (honesty principle P2)."""
    assert RealForcingEnvironment.is_synthetic is False
    src = RealForcingEnvironment.source
    assert "ERA5" in src
    assert "GLORYS" in src
    assert "synthetic" not in src.lower()
