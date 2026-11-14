"""Independent optical check of the radar loss: NASA OPERA DIST-ALERT (vegetation disturbance from Landsat and
Sentinel-2, HLS), read from GIBS on the same 0.0025 degree grid.

DIST-ALERT is published per satellite pass, so each period keeps the latest valid status per pixel:
- before: Jun 5 to Jul 10 (around the radar baseline)
- after:  Oct 1 to Nov 6 (the last radar step and the passes just after it)
A pixel shows new optical disturbance when its after-status is provisional or confirmed loss and its before-status
was "no disturbance". This drops land already disturbed before the fire season.

Reports, for radar-loss pixels (final step) that optical saw clearly in both periods: the share with new optical
disturbance, against the same share for unburned tree cover in the same 0.5 degree cells (chance). Also the share
of radar loss optical never saw clearly in the after period (cloud and smoke). With firms.py's per-pixel fire match, also the share confirmed by either source. Writes web/data/optical.json.
Run after firms.py.
"""
import json
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import numpy as np
from PIL import Image

import mosaic

LAYER = "OPERA_L3_DIST-ALERT-HLS_Color_Index"
WMS = ("https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi?SERVICE=WMS&REQUEST=GetMap&VERSION=1.1.1"
       f"&LAYERS={LAYER}&SRS=EPSG:4326&BBOX={mosaic.WEST},{mosaic.SOUTH},{mosaic.EAST},{mosaic.NORTH}"
       f"&WIDTH={round((mosaic.EAST - mosaic.WEST) / mosaic.RES)}&HEIGHT={round((mosaic.NORTH - mosaic.SOUTH) / mosaic.RES)}"
       "&FORMAT=image/png&TRANSPARENT=true")
CACHE = mosaic.RAW / "dist"
BEFORE = (date(2026, 6, 5), date(2026, 7, 10))
AFTER = (date(2026, 10, 1), date(2026, 11, 6))
CELL_DEG = 0.5
# GIBS colormap OPERA_Vegetation_Disturbance_Status: RGB -> status code.
STATUS = {(18, 18, 18): 0, (0, 85, 85): 1, (137, 127, 78): 2, (222, 224, 67): 3, (0, 136, 136): 4,
          (228, 135, 39): 5, (224, 27, 7): 6, (119, 119, 119): 7, (221, 221, 221): 8}
DISTURBED = {2, 3, 5, 6, 7, 8}  # provisional or confirmed, any size; 1 and 4 are first detections only


def fetch(day: date) -> np.ndarray | None:
    """Status codes for one day; -1 where that day has no pass."""
    path = CACHE / f"{day.isoformat()}.png"
    if not path.exists():
        try:
            data = urllib.request.urlopen(f"{WMS}&TIME={day.isoformat()}", timeout=180).read()
        except OSError:
            return None
        if not data.startswith(b"\x89PNG"):
            return None
        path.write_bytes(data)
    img = np.asarray(Image.open(path).convert("RGBA"))
    key = (img[..., 0].astype(np.int32) << 16) | (img[..., 1].astype(np.int32) << 8) | img[..., 2]
    out = np.full(key.shape, -1, np.int8)
    for (r, g, b), code in STATUS.items():
        out[key == ((r << 16) | (g << 8) | b)] = code
    out[img[..., 3] == 0] = -1
    return out


def composite(period: tuple[date, date]) -> np.ndarray:
    """Latest valid status per pixel over the period; -1 where never seen."""
    days = [period[0] + timedelta(days=k) for k in range((period[1] - period[0]).days + 1)]
    with ThreadPoolExecutor(6) as pool:
        imgs = list(pool.map(fetch, days))
    out = None
    for img in imgs:  # oldest first, so later passes overwrite
        if img is None:
            continue
        out = img.copy() if out is None else np.where(img >= 0, img, out)
    return out


def main() -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    before, after = composite(BEFORE), composite(AFTER)
    cached = np.load(mosaic.WORK / "mosaic.npz")
    score = cached["score"]
    land = mosaic.borneo_mask(score.shape[1:])
    forest = cached["forest"] & land
    lost = land & (np.nan_to_num(score[-1].astype(np.float32), nan=-99) > mosaic.LOSS_MIN)
    ever = np.zeros(lost.shape, bool)
    for s in range(score.shape[0]):
        ever |= np.nan_to_num(score[s].astype(np.float32), nan=-99) > mosaic.LOSS_MIN
    seen = (before == 0) & (after >= 0)  # clear view in both periods, and not already disturbed in June
    new = seen & np.isin(after, list(DISTURBED))

    size = round(CELL_DEG / mosaic.RES)
    rows, cols = np.indices(lost.shape)
    cell = (rows // size) * 10000 + cols // size
    burn_cells = np.unique(cell[lost])
    control = forest & ~ever & np.isin(cell, burn_cells)

    loss_seen = lost & seen
    out = {
        "before": [d.isoformat() for d in BEFORE], "after": [d.isoformat() for d in AFTER],
        "loss_confirmed": round(float(new[loss_seen].mean()), 3),
        "chance_confirmed": round(float(new[control & seen].mean()), 3),
        "loss_seen": round(float(loss_seen.sum() / lost.sum()), 3),
        "loss_unseen_after": round(float((lost & (after < 0)).sum() / lost.sum()), 3),
        "loss_disturbed_in_june": round(float((lost & (before > 0)).sum() / lost.sum()), 3),
    }
    fire_path = mosaic.WORK / "fire_match.npz"
    if fire_path.exists():  # written by firms.py: the timed fire match per pixel
        fire = np.load(fire_path)
        both = fire["lost"] & seen
        out["loss_fire_or_optical"] = round(float((fire["hit"] | new)[both].mean()), 3)
        out["loss_fire_and_optical"] = round(float((fire["hit"] & new)[both].mean()), 3)
        # A conservative CO2 floor: only peat loss that fire or optical confirms (co2.py's factors).
        import co2
        glon, glat = mosaic.grid()
        frac = co2.peat_fraction(glon, glat)
        km2_px = (mosaic.RES * 111.32) ** 2 * np.cos(np.radians(glat))
        ok = fire["lost"] & (fire["hit"] | new)
        peat_km2 = float((km2_px * frac)[ok].sum())
        out["confirmed_peat_km2"] = round(peat_km2, 1)
        out["confirmed_co2_mt"] = [round(peat_km2 * 100 * f * co2.CO2_PER_KG / 1e6, 1) for f in co2.FUEL_T_HA]
    print(out)
    (mosaic.WEB / "optical.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
