"""
Copernicus Marine & ECMWF Data Loader Interface.
Handles data transformation between WGS84 and Antarctic Polar Stereographic (EPSG:3031).
"""
import math
from typing import Tuple

def wgs84_to_polar_stereographic_epsg3031(lat: float, lon: float) -> Tuple[float, float]:
    """
    Mathematical projection from WGS84 (lat, lon) to Antarctic Polar Stereographic (EPSG:3031).
    Standard parallel: -71 deg S, Central Meridian: 0 deg.
    """
    a = 6378137.0          # WGS84 semi-major axis
    e = 0.0818191908426    # WGS84 eccentricity
    phi_c = math.radians(-71.0)
    phi = math.radians(lat)
    lam = math.radians(lon)
    
    # Calculate m and t
    m_c = math.cos(phi_c) / math.sqrt(1.0 - (e**2) * (math.sin(phi_c)**2))
    t_c = math.tan(math.pi/4.0 + phi_c/2.0) / (((1.0 - e*math.sin(phi_c))/(1.0 + e*math.sin(phi_c)))**(e/2.0))
    t = math.tan(math.pi/4.0 + phi/2.0) / (((1.0 - e*math.sin(phi))/(1.0 + e*math.sin(phi)))**(e/2.0))
    
    rho = a * m_c * (t / t_c)
    x = rho * math.sin(lam)
    y = -rho * math.cos(lam)
    return round(x, 2), round(y, 2)
