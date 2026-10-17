"""
Synthetic Southern Ocean atmospheric and oceanographic forcing.

HONEST LABELLING (build spec principle P2): the *fields* produced here are simulated. They
stand in for ECMWF ERA5/HRES winds and Copernicus Marine CMEMS currents, which the production
system would ingest over the same interface. The models that consume these fields - iceberg
drift, ice growth, ship resistance, POLARIS - are the real thing. Swapping this module for a
NetCDF reader is the only change needed to run on live data.

What is modelled, and why each term is here:

  * Circumpolar westerlies      the Roaring Forties / Furious Fifties jet, peaking near 52 S
  * Synoptic lows               eastward-propagating depressions on a 3-5 day period
  * Katabatic outflow           dense air draining off the ice sheet, offshore, diurnally pulsed
  * Antarctic Circumpolar Cur.  eastward core near the Polar Front
  * Antarctic Coastal Current   westward, hugging the continental margin
  * Mesoscale eddies            from a noise streamfunction, so the flow is non-divergent
  * Sea state                   fetch-limited wave growth, damped by sea ice

Everything is seeded and vectorised over NumPy.
"""
from __future__ import annotations

import math
from typing import Dict, Optional, Tuple

import numpy as np
from pydantic import BaseModel, Field

from src.core.constants import ENV_SEED, SEAWATER_FREEZING_POINT_C
from src.core.noise import FractalNoise3D, smoothstep
from src.data.landmask import get_coast_field

# Structural parameters of the synthetic climate.
LAT_WESTERLY_JET = -52.0
SIGMA_WESTERLY = 9.0
U_WESTERLY_PEAK = 15.5           # m/s
LAT_ACC_CORE = -56.0
SIGMA_ACC = 7.0
U_ACC_PEAK = 0.42                # m/s
KATABATIC_PEAK_MS = 15.0
KATABATIC_DECAY_NM = 95.0
COASTAL_CURRENT_PEAK = 0.26      # m/s, westward
COASTAL_CURRENT_DECAY_NM = 75.0
CIRCUMPOLAR_TROUGH_LAT = -65.0

# Katabatic drainage is strongest where the ice sheet funnels air seaward. These are the two
# sectors that matter for Indian expeditions.
KATABATIC_HOTSPOTS = (
    (11.7, 1.45),    # Queen Maud Land / Schirmacher, serving Maitri
    (76.2, 1.55),    # Prydz Bay / Amery outflow, serving Bharati
    (140.0, 1.35),   # Terre Adelie, the classic katabatic maximum
)


class EnvSample(BaseModel):
    """Point sample of the atmosphere and upper ocean."""

    lat: float
    lon: float
    valid_time_hours: float

    u10: float = Field(description="10 m eastward wind component, m/s")
    v10: float = Field(description="10 m northward wind component, m/s")
    wind_speed_ms: float
    wind_dir_from_deg: float = Field(description="Meteorological convention: direction wind blows FROM")
    wind_gust_ms: float

    uo: float = Field(description="Surface eastward current, m/s")
    vo: float = Field(description="Surface northward current, m/s")
    current_speed_ms: float
    current_dir_to_deg: float = Field(description="Direction the current sets TOWARD")

    sst_c: float
    t2m_c: float
    msl_hpa: float
    sig_wave_height_m: float
    visibility_km: float
    katabatic_component_ms: float

    is_synthetic: bool = True
    source: str = "synthetic; stands in for ECMWF ERA5/HRES + Copernicus Marine CMEMS"


class EnvironmentModel:
    """Seeded, deterministic forcing fields over the Southern Ocean."""

    def __init__(self, seed: int = ENV_SEED, reference_day_of_year: int = 330) -> None:
        """reference_day_of_year defaults to late November, the start of the expedition season."""
        self.seed = seed
        self.reference_doy = reference_day_of_year
        self._n_synoptic = FractalNoise3D(seed)
        self._n_eddy = FractalNoise3D(seed + 17)
        self._n_thermo = FractalNoise3D(seed + 41)
        # Coast geometry is static, but the ice and routing layers re-request it for the same
        # grid dozens of times per field evaluation (divergence alone samples the drift field
        # four times, and each drift evaluation needs it twice). Caching by grid content turned
        # route planning from 24 seconds into a few.
        self._coast_cache: Dict[bytes, Tuple[np.ndarray, np.ndarray, np.ndarray]] = {}

    # ------------------------------------------------------------------ helpers
    def day_of_year(self, t_hours: float) -> float:
        return (self.reference_doy + t_hours / 24.0) % 365.25

    def _austral_summer_factor(self, t_hours: float) -> float:
        """1.0 at midsummer (late December), 0.0 at midwinter. Drives temperature and ice."""
        doy = self.day_of_year(t_hours)
        return 0.5 * (1.0 + math.cos(2.0 * math.pi * (doy - 356.0) / 365.25))

    def _coast_geometry(self, lat, lon) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        Distance to coast in nautical miles, plus a unit vector pointing offshore.

        The offshore direction is the gradient of the distance-to-coast field, which is exactly
        the direction katabatic winds drain and the direction the coastal current runs across.
        """
        cf = get_coast_field()
        lat = np.asarray(lat, dtype=np.float64)
        lon = np.asarray(lon, dtype=np.float64)

        key = b""
        if lat.size > 16:
            key = lat.tobytes() + b"|" + lon.tobytes()
            hit = self._coast_cache.get(key)
            if hit is not None:
                return hit

        d = cf.sample(lat, lon)

        h_lat, h_lon = 0.2, 0.5
        dd_dlat = (cf.sample(lat + h_lat, lon) - cf.sample(lat - h_lat, lon)) / (2.0 * h_lat)
        dd_dlon = (cf.sample(lat, lon + h_lon) - cf.sample(lat, lon - h_lon)) / (2.0 * h_lon)

        cos_lat = np.maximum(0.05, np.cos(np.radians(lat)))
        gx = dd_dlon / cos_lat          # eastward component of the gradient
        gy = dd_dlat                    # northward component
        mag = np.sqrt(gx * gx + gy * gy) + 1e-9
        result = (d, gx / mag, gy / mag)
        if key:
            if len(self._coast_cache) > 64:
                self._coast_cache.clear()
            self._coast_cache[key] = result
        return result

    def _katabatic_strength(self, lon) -> np.ndarray:
        """Longitudinal weighting of drainage intensity around the continent."""
        lon = np.asarray(lon, dtype=np.float64)
        total = np.full(np.shape(lon), 0.55, dtype=np.float64)
        for centre, amp in KATABATIC_HOTSPOTS:
            delta = np.abs(((lon - centre + 180.0) % 360.0) - 180.0)
            total = total + amp * np.exp(-(delta ** 2) / (2.0 * 22.0 ** 2))
        return total

    def _streamfunction_uv(
        self, noise: FractalNoise3D, lat, lon, t_hours: float, sx: float, sy: float, st: float, amp: float
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Wind or current perturbation derived from a noise streamfunction.

        Taking the curl of a scalar field guarantees the perturbation is non-divergent, which is
        what makes the eddies look like real eddies instead of sources and sinks.
        """
        lat = np.asarray(lat, dtype=np.float64)
        lon = np.asarray(lon, dtype=np.float64)
        h = 0.35

        def psi(la, lo):
            return noise.fbm(lo / sx - t_hours / st, la / sy, t_hours / (st * 3.0), octaves=4)

        dpsi_dlat = (psi(lat + h, lon) - psi(lat - h, lon)) / (2.0 * h)
        dpsi_dlon = (psi(lat, lon + h) - psi(lat, lon - h)) / (2.0 * h)
        cos_lat = np.maximum(0.05, np.cos(np.radians(lat)))
        u = -amp * dpsi_dlat
        v = amp * dpsi_dlon / cos_lat
        return u, v

    # ------------------------------------------------------------------- fields
    def wind_uv(self, lat, lon, t_hours: float) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Returns (u10, v10, katabatic_magnitude). All arrays, all m/s."""
        lat = np.asarray(lat, dtype=np.float64)
        lon = np.asarray(lon, dtype=np.float64)

        # 1. The circumpolar westerly jet.
        jet = U_WESTERLY_PEAK * np.exp(-((lat - LAT_WESTERLY_JET) ** 2) / (2.0 * SIGMA_WESTERLY ** 2))
        # Easterlies hug the continent inside the circumpolar trough.
        polar_easterly = -6.0 * np.exp(-((lat + 68.0) ** 2) / (2.0 * 5.0 ** 2))
        u = jet + polar_easterly
        v = np.zeros_like(u)

        # 2. Synoptic depressions, moving east on a 3-5 day period.
        du, dv = self._streamfunction_uv(self._n_synoptic, lat, lon, t_hours, sx=13.0, sy=7.0, st=42.0, amp=13.0)
        u = u + du
        v = v + dv

        # 3. Katabatic drainage: offshore-directed, decaying seaward, pulsing diurnally.
        d_coast, off_x, off_y = self._coast_geometry(lat, lon)
        offshore_mask = np.clip(d_coast, 0.0, None)
        diurnal = 0.72 + 0.28 * math.cos(2.0 * math.pi * ((t_hours % 24.0) - 3.0) / 24.0)
        kata_mag = (
            KATABATIC_PEAK_MS
            * self._katabatic_strength(lon)
            * np.exp(-offshore_mask / KATABATIC_DECAY_NM)
            * diurnal
            * (d_coast > 0.0)
        )
        # Gustiness in the drainage flow.
        kata_mag = kata_mag * (0.75 + 0.45 * np.abs(self._n_thermo.fbm(lon / 6.0, lat / 4.0, t_hours / 9.0, octaves=3)))
        u = u + kata_mag * off_x
        v = v + kata_mag * off_y

        return u, v, kata_mag

    def current_uv(self, lat, lon, t_hours: float) -> Tuple[np.ndarray, np.ndarray]:
        """Surface current components in m/s."""
        lat = np.asarray(lat, dtype=np.float64)
        lon = np.asarray(lon, dtype=np.float64)

        # 1. Antarctic Circumpolar Current, eastward near the Polar Front.
        u = U_ACC_PEAK * np.exp(-((lat - LAT_ACC_CORE) ** 2) / (2.0 * SIGMA_ACC ** 2))
        v = np.zeros_like(u)

        # 2. Antarctic Coastal Current: westward, running along the continental margin.
        d_coast, off_x, off_y = self._coast_geometry(lat, lon)
        along_x, along_y = off_y, -off_x  # rotate the offshore normal to get the alongshore axis
        coastal = COASTAL_CURRENT_PEAK * np.exp(-np.clip(d_coast, 0.0, None) / COASTAL_CURRENT_DECAY_NM)
        coastal = coastal * (d_coast > 0.0)
        # The coastal current sets westward, so pick the alongshore sense with a negative u.
        sign = np.where(along_x > 0.0, -1.0, 1.0)
        u = u + coastal * along_x * sign
        v = v + coastal * along_y * sign

        # 3. Mesoscale eddy field, non-divergent by construction.
        du, dv = self._streamfunction_uv(self._n_eddy, lat, lon, t_hours, sx=4.5, sy=2.6, st=240.0, amp=0.30)
        return u + du, v + dv

    def scalars(self, lat, lon, t_hours: float, wind_speed, ice_concentration=0.0) -> Dict[str, np.ndarray]:
        """Temperature, pressure, sea state and visibility."""
        lat = np.asarray(lat, dtype=np.float64)
        lon = np.asarray(lon, dtype=np.float64)
        summer = self._austral_summer_factor(t_hours)
        d_coast, _, _ = self._coast_geometry(lat, lon)
        noise = self._n_thermo.fbm(lon / 9.0, lat / 6.0, t_hours / 50.0, octaves=3)

        # 2 m air temperature: strong meridional gradient, seasonal swing, diurnal ripple.
        t2m = (
            -26.0
            + 28.0 * smoothstep(-72.0, -46.0, lat)
            + 9.0 * summer
            + 1.4 * math.cos(2.0 * math.pi * ((t_hours % 24.0) - 14.0) / 24.0)
            + 3.2 * noise
        )
        t2m = np.where(d_coast < 0.0, t2m - 11.0, t2m)  # the ice sheet interior is far colder

        # Sea surface temperature, floored at the freezing point of seawater.
        sst = -1.85 + 10.5 * smoothstep(-66.0, -44.0, lat) + 2.5 * summer + 0.7 * noise
        ice_c = np.asarray(ice_concentration, dtype=np.float64)
        sst = np.where(ice_c > 0.15, SEAWATER_FREEZING_POINT_C + 0.15 * (1.0 - ice_c), sst)
        sst = np.maximum(sst, SEAWATER_FREEZING_POINT_C)

        # Mean sea level pressure: the circumpolar trough plus synoptic anomalies.
        synoptic = self._n_synoptic.fbm(lon / 13.0 - t_hours / 42.0, lat / 7.0, t_hours / 126.0, octaves=4)
        msl = 1011.0 - 27.0 * np.exp(-((lat - CIRCUMPOLAR_TROUGH_LAT) ** 2) / (2.0 * 8.5 ** 2)) + 19.0 * synoptic

        # Fetch-limited fully-developed sea, then damped by ice cover.
        ws = np.asarray(wind_speed, dtype=np.float64)
        hs_open = np.clip(0.0246 * ws ** 2, 0.2, 13.0)
        hs = hs_open * np.power(np.clip(1.0 - ice_c, 0.0, 1.0), 1.6)
        hs = np.where(d_coast < 0.0, 0.0, hs)

        # Visibility collapses in blowing snow, which needs wind and cold together.
        blowing_snow = smoothstep(11.0, 25.0, ws) * smoothstep(0.0, -12.0, t2m)
        visibility = np.clip(28.0 - 26.0 * blowing_snow - 6.0 * np.clip(noise, 0.0, None), 0.15, 30.0)

        return {"t2m_c": t2m, "sst_c": sst, "msl_hpa": msl, "sig_wave_height_m": hs, "visibility_km": visibility}

    # ------------------------------------------------------------------ public
    def sample(self, lat: float, lon: float, t_hours: float = 0.0, ice_concentration: float = 0.0) -> EnvSample:
        """Single-point sample. Wraps the vector path, so it always agrees with gridded output."""
        u, v, kata = self.wind_uv(np.array([lat]), np.array([lon]), t_hours)
        uo, vo = self.current_uv(np.array([lat]), np.array([lon]), t_hours)
        ws = float(np.hypot(u, v)[0])
        sc = self.scalars(np.array([lat]), np.array([lon]), t_hours, np.array([ws]), np.array([ice_concentration]))

        u0, v0 = float(u[0]), float(v[0])
        uo0, vo0 = float(uo[0]), float(vo[0])
        wind_toward = (math.degrees(math.atan2(u0, v0)) + 360.0) % 360.0

        return EnvSample(
            lat=lat,
            lon=lon,
            valid_time_hours=t_hours,
            u10=round(u0, 3),
            v10=round(v0, 3),
            wind_speed_ms=round(ws, 2),
            wind_dir_from_deg=round((wind_toward + 180.0) % 360.0, 1),
            wind_gust_ms=round(ws * 1.38, 2),
            uo=round(uo0, 4),
            vo=round(vo0, 4),
            current_speed_ms=round(math.hypot(uo0, vo0), 3),
            current_dir_to_deg=round((math.degrees(math.atan2(uo0, vo0)) + 360.0) % 360.0, 1),
            sst_c=round(float(sc["sst_c"][0]), 2),
            t2m_c=round(float(sc["t2m_c"][0]), 2),
            msl_hpa=round(float(sc["msl_hpa"][0]), 1),
            sig_wave_height_m=round(float(sc["sig_wave_height_m"][0]), 2),
            visibility_km=round(float(sc["visibility_km"][0]), 1),
            katabatic_component_ms=round(float(kata[0]), 2),
        )

    def field(
        self,
        lat_min: float,
        lat_max: float,
        lon_min: float,
        lon_max: float,
        resolution_deg: float = 1.0,
        t_hours: float = 0.0,
        ice_concentration: Optional[np.ndarray] = None,
    ) -> Dict[str, object]:
        """Gridded sample for the map layers."""
        lats = np.arange(lat_min, lat_max + 1e-9, resolution_deg)
        lons = np.arange(lon_min, lon_max + 1e-9, resolution_deg * 2.0)
        lon_g, lat_g = np.meshgrid(lons, lats)

        u, v, kata = self.wind_uv(lat_g, lon_g, t_hours)
        uo, vo = self.current_uv(lat_g, lon_g, t_hours)
        ws = np.hypot(u, v)
        ic = np.zeros_like(lat_g) if ice_concentration is None else ice_concentration
        sc = self.scalars(lat_g, lon_g, t_hours, ws, ic)

        return {
            "lats": lats.round(4).tolist(),
            "lons": lons.round(4).tolist(),
            "valid_time_hours": t_hours,
            "u10": np.round(u, 2).tolist(),
            "v10": np.round(v, 2).tolist(),
            "wind_speed_ms": np.round(ws, 2).tolist(),
            "current_u": np.round(uo, 3).tolist(),
            "current_v": np.round(vo, 3).tolist(),
            "current_speed_ms": np.round(np.hypot(uo, vo), 3).tolist(),
            "t2m_c": np.round(sc["t2m_c"], 1).tolist(),
            "sst_c": np.round(sc["sst_c"], 2).tolist(),
            "msl_hpa": np.round(sc["msl_hpa"], 1).tolist(),
            "sig_wave_height_m": np.round(sc["sig_wave_height_m"], 2).tolist(),
            "katabatic_ms": np.round(kata, 2).tolist(),
            "is_synthetic": True,
            "source": "synthetic; stands in for ECMWF ERA5/HRES + Copernicus Marine CMEMS",
        }


_ENV: EnvironmentModel | None = None


def get_environment() -> EnvironmentModel:
    global _ENV
    if _ENV is None:
        _ENV = EnvironmentModel()
    return _ENV
