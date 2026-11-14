"""Hand-check sheet: a random sample of radar burns with before and after optical images, for people to label.

For each sampled burn (8-connected loss cluster of at least 10 pixels at the last step, about 0.8 km2), builds two
cloud-masked median composites from NASA HLS (Landsat 30 m and Sentinel-2 30 m true colour, via GIBS):
before Jun 1 to Jul 20, after Oct 1 to Nov 6. Bright, low-saturation pixels count as cloud and are dropped.
Writes web/review/NN_before.jpg, NN_after.jpg, NN_mask.png and web/review/review.json with each burn's place,
size, and the fire and optical results, which the page keeps hidden until the reviewer reveals them.
Run after firms.py and optical.py.
"""
import json
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from io import BytesIO

import numpy as np
from PIL import Image
from scipy.ndimage import binary_dilation, label

import mosaic
import optical

N = 24
SEED = 1
PX = 320  # image size; the box is the burn's extent plus a margin, made square
LAYERS = ("HLS_S30_Nadir_BRDF_Adjusted_Reflectance", "HLS_L30_Nadir_BRDF_Adjusted_Reflectance")
BEFORE = (date(2026, 6, 1), date(2026, 7, 20))
AFTER = (date(2026, 10, 1), date(2026, 11, 6))
OUT = mosaic.WEB.parent / "review"
CACHE = mosaic.RAW / "hls"


def get(layer: str, day: date, box: tuple[float, float, float, float]) -> np.ndarray | None:
    """One HLS image as RGBA, or None when there is no pass that day."""
    w, s, e, n = box
    path = CACHE / f"{layer[4:7]}_{day.isoformat()}_{w:.3f}_{s:.3f}.png"
    if not path.exists():
        url = ("https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi?SERVICE=WMS&REQUEST=GetMap&VERSION=1.1.1"
               f"&LAYERS={layer}&SRS=EPSG:4326&BBOX={w},{s},{e},{n}&WIDTH={PX}&HEIGHT={PX}&FORMAT=image/png"
               f"&TRANSPARENT=true&TIME={day.isoformat()}")
        try:
            path.write_bytes(urllib.request.urlopen(url, timeout=120).read())
        except OSError:
            return None
    img = np.asarray(Image.open(path).convert("RGBA"))
    return img if (img[..., 3] > 0).mean() > 0.05 else None


def composite(period: tuple[date, date], box: tuple) -> np.ndarray | None:
    """Cloud-masked per-pixel median of every pass in the period."""
    days = [period[0] + timedelta(days=k) for k in range((period[1] - period[0]).days + 1)]
    jobs = [(layer, d) for d in days for layer in LAYERS]
    with ThreadPoolExecutor(12) as pool:
        imgs = [im for im in pool.map(lambda j: get(j[0], j[1], box), jobs) if im is not None]
    if not imgs:
        return None
    stack = np.stack(imgs).astype(np.float32)
    rgb, alpha = stack[..., :3], stack[..., 3]
    bright = rgb.mean(-1)
    sat = rgb.max(-1) - rgb.min(-1)
    clear = (alpha > 0) & ~((bright > 150) & (sat < 60)) & (bright > 8)  # drop cloud and empty pixels
    rgb[~clear] = np.nan
    with np.errstate(all="ignore"):
        med = np.nanmedian(rgb, axis=0)
    seen = np.isfinite(med).all(-1)
    out = np.nan_to_num(med, nan=0)
    # Gentle stretch so dark forest is readable; unseen pixels stay black.
    lo, hi = np.percentile(out[seen], [2, 98]) if seen.any() else (0, 255)
    out = ((out - lo) / max(hi - lo, 1) * 255).clip(0, 255)
    out = (out * 0.75 + out.mean(-1, keepdims=True) * 0.25).astype(np.uint8)  # tame the HLS rendering's neon greens
    out[~seen] = 0
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    CACHE.mkdir(parents=True, exist_ok=True)
    cached = np.load(mosaic.WORK / "mosaic.npz")
    land = mosaic.borneo_mask(cached["score"].shape[1:])
    lost = land & (np.nan_to_num(cached["score"][-1].astype(np.float32), nan=-99) > mosaic.LOSS_MIN)
    fire = np.load(mosaic.WORK / "fire_match.npz")["hit"]
    glon, glat = mosaic.grid()
    labels, n = label(lost, structure=np.ones((3, 3)))
    sizes = np.bincount(labels.ravel())
    big = np.nonzero(sizes[1:] >= 10)[0] + 1
    picks = np.random.default_rng(SEED).choice(big, size=min(N, len(big)), replace=False)

    # The optical check per pixel, to report alongside (hidden until reveal).
    before, after = optical.composite(optical.BEFORE), optical.composite(optical.AFTER)
    new = (before == 0) & np.isin(after, list(optical.DISTURBED))

    km2_px = (mosaic.RES * 111.32) ** 2 * np.cos(np.radians(glat))
    items = []
    for k, lab in enumerate(picks):
        rr, cc = np.nonzero(labels == lab)
        lat, lon = float(glat[rr, cc].mean()), float(glon[rr, cc].mean())
        half = max((rr.max() - rr.min()), (cc.max() - cc.min()), 12) * mosaic.RES * 0.8
        box = (lon - half, lat - half, lon + half, lat + half)
        b, a = composite(BEFORE, box), composite(AFTER, box)
        if b is None or a is None:
            print(k, "no optical images")
            continue
        Image.fromarray(b).save(OUT / f"{k:02d}_before.jpg", quality=82)
        Image.fromarray(a).save(OUT / f"{k:02d}_after.jpg", quality=82)
        # Radar outline on the same box.
        r0, r1 = int((mosaic.NORTH - box[3]) / mosaic.RES), int((mosaic.NORTH - box[1]) / mosaic.RES) + 1
        c0, c1 = int((box[0] - mosaic.WEST) / mosaic.RES), int((box[2] - mosaic.WEST) / mosaic.RES) + 1
        m = labels[r0:r1, c0:c1] == lab
        # Outline drawn at image resolution, 2 px wide, so it does not cover the inside of small burns.
        big_m = np.asarray(Image.fromarray(m.astype(np.uint8) * 255).resize((PX, PX), Image.NEAREST)) > 0
        edge = binary_dilation(big_m, iterations=2) & ~big_m
        rgba = np.zeros((PX, PX, 4), np.uint8)
        rgba[edge] = (255, 70, 40, 255)
        Image.fromarray(rgba).save(OUT / f"{k:02d}_mask.png")
        items.append({"id": k, "lat": round(lat, 4), "lon": round(lon, 4), "km2": round(float(km2_px[rr, cc].sum()), 1),
                      "fire": round(float(fire[rr, cc].mean()), 2), "optical": round(float(new[rr, cc].mean()), 2)})
        print(items[-1])
    (OUT / "review.json").write_text(json.dumps({"before": [d.isoformat() for d in BEFORE],
                                                 "after": [d.isoformat() for d in AFTER], "items": items}, indent=1))


if __name__ == "__main__":
    main()
