"""Regional smoke: VIIRS Deep Blue aerosol optical depth (AOD) per 12-day step, Borneo to Singapore and Kuala Lumpur.

Fetches the daily GIBS images for Suomi-NPP and NOAA-20 over SMOKE_BOX, turns each colour back into its AOD value
with the GIBS colormap (MODIS_VIIRS_AOD), and averages every valid day in a step, then fills holes from the steps either side and from readings up to about 40 km away. AOD is how much sunlight the haze
blocks: under 0.3 is clear, above 1 is thick smoke. Writes web/data/smoke_SS.png and adds "smoke" to steps.json
(bounds, and the AOD at a few cities per step). Run after mosaic.py.
"""
import json
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import numpy as np
from PIL import Image

import mosaic

WEST, EAST, SOUTH, NORTH = 98.0, 120.0, -6.0, 8.0
W, H = 880, 560  # 0.025 degree pixels
LAYERS = ("VIIRS_SNPP_AOD_Deep_Blue_Land_Ocean", "VIIRS_NOAA20_AOD_Deep_Blue_Land_Ocean")
COLORMAP = "https://gibs.earthdata.nasa.gov/colormaps/v1.3/MODIS_VIIRS_AOD.xml"
WMS = ("https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi?SERVICE=WMS&REQUEST=GetMap&VERSION=1.1.1"
       f"&SRS=EPSG:4326&BBOX={WEST},{SOUTH},{EAST},{NORTH}&WIDTH={W}&HEIGHT={H}&FORMAT=image/png&TRANSPARENT=true")
CACHE = mosaic.RAW / "smoke"
CITIES = {  # name: (lat, lon)
    "Singapore": (1.35, 103.82),
    "Kuala Lumpur": (3.14, 101.69),
    "Kuching": (1.55, 110.34),
    "Pontianak": (-0.03, 109.33),
    "Palangka Raya": (-2.21, 113.92),
    "Banjarmasin": (-3.32, 114.59),
}


def colormap(url: str = COLORMAP) -> dict[tuple[int, int, int], float]:
    """RGB -> value (bin midpoint) from a GIBS colormap; no-data entries are left out."""
    xml = urllib.request.urlopen(url, timeout=60).read().decode()
    lut = {}
    for rgb, value in re.findall(r'<ColorMapEntry rgb="(\d+,\d+,\d+)" transparent="false"[^>]*?value="\[([^\])]*)', xml):
        lo, *hi = [float(v) for v in value.split(",")]
        ends = [v for v in [lo, *hi] if np.isfinite(v)]  # open-ended bins (-INF or +INF) take their finite end
        lut[tuple(int(c) for c in rgb.split(","))] = sum(ends) / len(ends) if ends else 0.0
    return lut


def fetch(layer: str, day: str) -> np.ndarray | None:
    """One day's RGBA image, cached."""
    path = CACHE / f"{layer}_{day}.png"
    if not path.exists():
        try:
            data = urllib.request.urlopen(f"{WMS}&LAYERS={layer}&TIME={day}", timeout=120).read()
        except OSError:
            return None
        if not data.startswith(b"\x89PNG"):
            return None
        path.write_bytes(data)
    return np.asarray(Image.open(path).convert("RGBA"))


def decode(img: np.ndarray, lut: dict) -> np.ndarray:
    """AOD per pixel; NaN where transparent or the colour is not in the colormap."""
    key = (img[..., 0].astype(np.int32) << 16) | (img[..., 1].astype(np.int32) << 8) | img[..., 2]
    keys = np.array(sorted((r << 16) | (g << 8) | b for r, g, b in lut), np.int32)
    vals = np.array([lut[((k >> 16) & 255, (k >> 8) & 255, k & 255)] for k in keys], np.float32)
    i = np.clip(np.searchsorted(keys, key), 0, len(keys) - 1)
    out = np.where(keys[i] == key, vals[i], np.nan).astype(np.float32)
    out[img[..., 3] == 0] = np.nan
    return out


def fill(a: np.ndarray, sigma: float = 3.0, reach: float = 16.0) -> np.ndarray:
    """Smooth the step mean and fill cloud holes from nearby readings (NaN-aware Gaussian).

    sigma (pixels of 0.025 degrees) evens out the per-swath blockiness; reach fills holes up to about 40 km
    from the nearest reading. Pixels farther from any reading stay NaN: no value is made up there.
    """
    from scipy.ndimage import gaussian_filter
    ok = np.isfinite(a)
    num, den = gaussian_filter(np.where(ok, a, 0), sigma), gaussian_filter(ok.astype(np.float32), sigma)
    wide_num, wide_den = gaussian_filter(np.where(ok, a, 0), reach), gaussian_filter(ok.astype(np.float32), reach)
    with np.errstate(all="ignore"):
        near = np.where(den > 0.2, num / den, np.nan)
        far = np.where(wide_den > 0.15, wide_num / wide_den, np.nan)
    return np.where(np.isfinite(near), near, far).astype(np.float32)


def main() -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    lut = colormap()
    meta_path = mosaic.WEB / "steps.json"
    meta = json.loads(meta_path.read_text())
    jobs = []
    for st in meta["steps"]:
        start = mosaic.STEP0 + timedelta(days=mosaic.STEP_DAYS * st["step"])
        for k in range(mosaic.STEP_DAYS):
            for layer in LAYERS:
                jobs.append((st["step"], layer, (start + timedelta(days=k)).isoformat()))
    with ThreadPoolExecutor(8) as pool:
        imgs = list(pool.map(lambda j: fetch(j[1], j[2]), jobs))
    sums = np.zeros((len(meta["steps"]), H, W), np.float32)
    counts = np.zeros_like(sums)
    for (s, _, _), img in zip(jobs, imgs):
        if img is None:
            continue
        aod = decode(img, lut)
        ok = np.isfinite(aod)
        sums[s][ok] += aod[ok]
        counts[s][ok] += 1
    cities = {name: [] for name in CITIES}
    with np.errstate(all="ignore"):
        raw = sums / counts
    n = len(meta["steps"])
    for s in range(n):
        # Holes (cloud, or smoke too thick to retrieve) take the mean of the steps either side before the spatial fill.
        with np.errstate(all="ignore"):
            nb = np.nanmean(raw[max(0, s - 1):min(n, s + 2)], axis=0)
        mean = fill(np.where(np.isfinite(raw[s]), raw[s], nb))
        # Smoke palette: clear below AOD 0.3; pale tan haze at 1; dark brown-grey smoke at 3 and above.
        t = np.nan_to_num(np.clip((mean - 0.3) / 2.7, 0, 1), nan=0)
        light, dark = np.array([226, 205, 160], np.float32), np.array([96, 74, 56], np.float32)
        rgba = np.zeros((H, W, 4), np.uint8)
        rgba[..., :3] = (light + (dark - light) * t[..., None] ** 0.8).astype(np.uint8)
        rgba[..., 3] = np.where(np.isfinite(mean), (np.clip((mean - 0.3) / 1.2, 0, 1) ** 0.8 * 225), 0).astype(np.uint8)
        # No reading even after the fill: grey veil with diagonal stripes, never drawn as clear air.
        # Deep Blue skips cloud and also smoke too thick to retrieve, so these holes are often the worst smoke.
        yy, xx = np.mgrid[0:H, 0:W]
        stripe = ((xx + yy) % 8) < 2
        hole = ~np.isfinite(mean)
        rgba[hole & stripe] = (190, 180, 168, 200)
        rgba[hole & ~stripe] = (140, 132, 122, 120)
        Image.fromarray(rgba).save(mosaic.WEB / f"smoke_{s:02d}.png", optimize=True)
        for name, (lat, lon) in CITIES.items():
            r, c = int((NORTH - lat) / 0.025), int((lon - WEST) / 0.025)
            win = mean[max(0, r - 4):r + 5, max(0, c - 4):c + 5]  # about 25 km around the city, on the filled field
            v = float(np.nanmean(win)) if np.isfinite(win).any() else None
            cities[name].append(round(v, 2) if v is not None else None)
        print(s, {n: v[-1] for n, v in cities.items()}, f"coverage {(counts[s] > 0).mean():.0%}")
    meta["smoke"] = {"bounds": [[SOUTH, WEST], [NORTH, EAST]], "cities": {n: {"latlon": CITIES[n], "aod": v} for n, v in cities.items()}}
    meta_path.write_text(json.dumps(meta, indent=1))


if __name__ == "__main__":
    main()
