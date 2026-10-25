"""Southern Ocean sector definitions (longitude ranges)."""
from __future__ import annotations

# Standard Southern Ocean sectors as fixed documented constants
# Longitudes: west negative
SECTORS = {
    "Weddell Sea": (-60.0, 20.0),
    "Indian Ocean": (20.0, 90.0),
    "Western Pacific": (90.0, 160.0),
    "Ross Sea": (160.0, 180.0, -180.0, -130.0),  # crosses antimeridian
    "Bellingshausen-Amundsen": (-130.0, -60.0),
}
# Simple form for most sectors; handle cross-antimeridian separately
SECTORS_SIMPLE = {
    "Weddell Sea": (-60.0, 20.0),
    "Indian Ocean": (20.0, 90.0),
    "Western Pacific": (90.0, 160.0),
    "Ross Sea": (160.0, -130.0),  # (start, end) crossing 180
    "Bellingshausen-Amundsen": (-130.0, -60.0),
}
AUSTRAL_DEPARTURE_SEASON = (11, 12, 1, 2, 3)  # Nov-Mar
