"""Fire gas: NASA AIRS carbon monoxide (CO) per 12-day step over the same region as the smoke layer.

CO is made by incomplete burning, smouldering peat above all, and lasts weeks in the air, so it traces the fires'
plume where haze retrievals give up. Source: AIRS L3 daily CO volume mixing ratio at 500 hPa (about 5.5 km up),
day and night passes, via GIBS, decoded with the GIBS colormap (ppbv; the colormap tops out at 350).
Each step averages every valid pass, then fills holes as smoke.py does. Writes web/data/co_SS.png and adds "co"
to steps.json: the June baseline and per-step value at the same cities as the smoke layer. Run after smoke.py.
"""
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import numpy as np
from PIL import Image

import mosaic
import smoke

LAYERS = ("AIRS_L3_Carbon_Monoxide_500hPa_Volume_Mixing_Ratio_Daily_Day",
          "AIRS_L3_Carbon_Monoxide_500hPa_Volume_Mixing_Ratio_Daily_Night")
COLORMAP = "https://gibs.earthdata.nasa.gov/colormaps/v1.3/AIRS_Carbon_Monoxide_Volume_Mixing_Ratio.xml"
LOW, HIGH = 100.0, 350.0  # ppbv: transparent at June-like levels, full colour at the colormap ceiling


def main() -> None:
    smoke.CACHE.mkdir(parents=True, exist_ok=True)
    lut = smoke.colormap(COLORMAP)
    meta_path = mosaic.WEB / "steps.json"
    meta = json.loads(meta_path.read_text())
    n = len(meta["steps"])
    jobs = [(st["step"], layer, (mosaic.STEP0 + timedelta(days=mosaic.STEP_DAYS * st["step"] + k)).isoformat())
            for st in meta["steps"] for k in range(mosaic.STEP_DAYS) for layer in LAYERS]
    with ThreadPoolExecutor(8) as pool:
        imgs = list(pool.map(lambda j: smoke.fetch(j[1], j[2]), jobs))
    sums = np.zeros((n, smoke.H, smoke.W), np.float32)
    counts = np.zeros_like(sums)
    for (s, _, _), img in zip(jobs, imgs):
        if img is None:
            continue
        v = smoke.decode(img, lut)
        ok = np.isfinite(v)
        sums[s][ok] += v[ok]
        counts[s][ok] += 1
    with np.errstate(all="ignore"):
        raw = sums / counts
    cities = {name: [] for name in smoke.CITIES}
    for s in range(n):
        with np.errstate(all="ignore"):
            nb = np.nanmean(raw[max(0, s - 1):min(n, s + 2)], axis=0)
        # AIRS L3 cells are 1 degree (40 of our pixels): a wide fill and smooth turns the blocks into a plume.
        mean = smoke.fill(np.where(np.isfinite(raw[s]), raw[s], nb), sigma=14, reach=30)
        t = np.nan_to_num(np.clip((mean - LOW) / (HIGH - LOW), 0, 1), nan=0)
        light, dark = np.array([196, 150, 255], np.float32), np.array([118, 20, 150], np.float32)  # violet: not smoke, fire or loss
        rgba = np.zeros((smoke.H, smoke.W, 4), np.uint8)
        rgba[..., :3] = (light + (dark - light) * t[..., None]).astype(np.uint8)
        a = np.where(np.isfinite(mean), t * 175, 0)  # linear and capped, so plume structure and land still show
        rgba[..., 3] = ((a // 12) * 12).astype(np.uint8)  # rounded alpha keeps the PNG small
        Image.fromarray(rgba).save(mosaic.WEB / f"co_{s:02d}.png", optimize=True)
        for name, (lat, lon) in smoke.CITIES.items():
            r, c = int((smoke.NORTH - lat) / 0.025), int((lon - smoke.WEST) / 0.025)
            win = mean[max(0, r - 4):r + 5, max(0, c - 4):c + 5]
            cities[name].append(round(float(np.nanmean(win))) if np.isfinite(win).any() else None)
        print(s, {k: v[-1] for k, v in cities.items()})
    meta["co"] = {"units": "ppbv", "level": "500 hPa", "low": LOW, "high": HIGH,
                  "cities": {k: {"latlon": smoke.CITIES[k], "ppbv": v} for k, v in cities.items()}}
    meta_path.write_text(json.dumps(meta, indent=1))


if __name__ == "__main__":
    main()
