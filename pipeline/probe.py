"""Write the click-probe layers: HV and HH brightness per 12-day step on a 0.01 degree grid.

Each step holds the latest look up to that step, matched to the pre-season baseline (the same stretch
correction as the loss map), averaged over the track-frames that see the pixel. The web app reads one
pixel per step from these PNGs to draw the HV and HH history of a clicked spot. Alpha 0 means no data.
Also writes the Ketapang click-in point (the largest loss cluster in West Kalimantan) to steps.json.
"""
import json

import numpy as np
from PIL import Image
from scipy.ndimage import label

import mosaic

RES = 0.01  # degrees, about 1.1 km
KETAPANG_BOX = (109.6, 111.2, -3.2, -1.2)  # west, east, south, north: the Ketapang peatlands


def main() -> None:
    """Build per-step HV and HH composites at probe resolution and write them as PNGs."""
    inv = json.loads((mosaic.ROOT / "data" / "inventory.json").read_text())
    by_tf: dict[str, list[dict]] = {}
    for r in inv:
        by_tf.setdefault(r["tf"], []).append(r)
    glon, glat = mosaic.grid(RES)
    n_steps = max(mosaic.step_of(mosaic.parse_date(r["date"])) for r in inv) + 1
    sums = {k: np.zeros((n_steps, *glon.shape), np.float32) for k in ("HVHV", "HHHH")}
    counts = {k: np.zeros((n_steps, *glon.shape), np.uint16) for k in ("HVHV", "HHHH")}

    for tf, recs in sorted(by_tf.items()):
        rows, cols = mosaic.window(recs, RES)
        lon, lat = glon[rows, cols], glat[rows, cols]
        for layer in ("HVHV", "HHHH"):
            looks = mosaic.load_tf(recs, lon, lat, layer, smoothing=False)
            early = [a for d, a in looks if d < mosaic.BASELINE_END]
            if not early or len(looks) - len(early) < 2:
                continue
            with np.errstate(all="ignore"):
                base = np.nanmedian(early, axis=0)
            if np.isfinite(base).sum() < 500:
                continue
            ref = base > np.nanpercentile(base, mosaic.FOREST_PCT)
            carry = np.full(base.shape, np.nan, np.float32)
            by_step = {}
            for d, a in looks:
                a = mosaic.match(a, base, ref)  # baseline looks too, so the stretch never shows as change
                carry = np.where(np.isfinite(a), a, carry)
                by_step[mosaic.step_of(d)] = carry.copy()
            cur = np.full(base.shape, np.nan, np.float32)
            for s in range(n_steps):
                cur = by_step.get(s, cur)
                ok = np.isfinite(cur)
                sums[layer][s, rows, cols][ok] += cur[ok]
                counts[layer][s, rows, cols][ok] += 1
        print(tf)

    out = mosaic.WEB
    for layer, name in (("HVHV", "hv"), ("HHHH", "hh")):
        with np.errstate(all="ignore"):
            mean = sums[layer] / counts[layer]
        for s in range(n_steps):
            v = np.nan_to_num(mean[s], nan=0).clip(0, 255).astype(np.uint8)
            a = np.where(np.isfinite(mean[s]), 255, 0).astype(np.uint8)
            Image.fromarray(np.dstack([v, v, v, a])).save(out / f"probe_{name}_{s:02d}.png", optimize=True)
    write_ketapang()


def write_ketapang() -> None:
    """Find the largest loss cluster in the Ketapang box at the last step and store its centre."""
    cached = np.load(mosaic.WORK / "mosaic.npz")
    last = cached["score"][-1].astype(np.float32)
    glon, glat = mosaic.grid()
    w, e, s, n = KETAPANG_BOX
    box = (glon >= w) & (glon <= e) & (glat >= s) & (glat <= n)
    lost = box & np.isfinite(last) & (last > mosaic.LOSS_MIN)
    labels, count = label(lost)
    if not count:
        print("no loss cluster in the Ketapang box")
        return
    biggest = np.bincount(labels.ravel())[1:].argmax() + 1
    rr, cc = np.nonzero(labels == biggest)
    point = [round(float(glat[rr, cc].mean()), 4), round(float(glon[rr, cc].mean()), 4)]
    meta_path = mosaic.WEB / "steps.json"
    meta = json.loads(meta_path.read_text())
    meta["ketapang"] = point
    meta_path.write_text(json.dumps(meta, indent=1))
    print("Ketapang cluster", point, f"{len(rr)} px")


if __name__ == "__main__":
    main()
