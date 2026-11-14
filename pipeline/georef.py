"""Place a NISAR GCOV NATIVE browse PNG on the map without the login-gated KML.

The NATIVE browse is a north-up UTM grid (about 180 m pixels) with a zero margin around the
swath. The four corners of the valid data are the four vertices of the CMR footprint polygon, so an
affine fit from footprint (UTM metres) to those corners (pixels) places the image. Measured on
023_053_A_176, 2026-06-17: 0.4 px residual, no rotation term.
"""
import numpy as np
from pyproj import Transformer

MAX_RESIDUAL_PX = 3.0


def utm_epsg(lon: list[float], lat: list[float]) -> int:
    """EPSG code of the UTM zone at the footprint centre."""
    zone = int((np.mean(lon) + 180) // 6) + 1
    return (32700 if np.mean(lat) < 0 else 32600) + zone


def fit(lon: list[float], lat: list[float], valid: np.ndarray) -> tuple[np.ndarray, int] | None:
    """Return (A, epsg) with pixel = [x, y, 1] @ A, or None when the corners do not fit."""
    rows, cols = np.nonzero(valid)
    if rows.size < 1000:
        return None
    corners = {
        "top": (cols[rows.argmin()], rows.min()),
        "bottom": (cols[rows.argmax()], rows.max()),
        "left": (cols.min(), rows[cols.argmin()]),
        "right": (cols.max(), rows[cols.argmax()]),
    }
    epsg = utm_epsg(lon, lat)
    x, y = Transformer.from_crs(4326, epsg, always_xy=True).transform(lon, lat)
    x, y = np.asarray(x), np.asarray(y)
    vertex = {"top": y.argmax(), "bottom": y.argmin(), "left": x.argmin(), "right": x.argmax()}
    if len(set(vertex.values())) < 4:
        return None
    src = np.array([[x[vertex[k]], y[vertex[k]], 1.0] for k in corners])
    dst = np.array([corners[k] for k in corners], float)
    a, *_ = np.linalg.lstsq(src, dst, rcond=None)
    if np.hypot(*(src @ a - dst).T).max() > MAX_RESIDUAL_PX:
        return None
    return a, epsg


def sample(img: np.ndarray, a: np.ndarray, epsg: int, lon: np.ndarray, lat: np.ndarray) -> np.ndarray:
    """Nearest-neighbour sample img at lon/lat arrays; NaN outside the image or where it is zero."""
    x, y = Transformer.from_crs(4326, epsg, always_xy=True).transform(lon, lat)
    px = x * a[0, 0] + y * a[1, 0] + a[2, 0]
    py = x * a[0, 1] + y * a[1, 1] + a[2, 1]
    c, r = np.rint(px).astype(np.int64), np.rint(py).astype(np.int64)
    inside = (c >= 0) & (c < img.shape[1]) & (r >= 0) & (r < img.shape[0])
    out = np.full(lon.shape, np.nan, np.float32)
    out[inside] = img[r[inside], c[inside]]
    out[out <= 1] = np.nan  # 0 is outside the swath; 1 pads partial products (and clips the darkest 5%)
    return out
