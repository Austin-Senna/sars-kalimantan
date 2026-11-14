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


def burn_series(mask: np.ndarray) -> dict | None:
    """HV and HH over one burn, from the single track-frame with the most looks over it.

    Averages the burned pixels only (mask, on the 0.0025 degree grid), every look matched to that frame's own
    pre-season baseline, so neither the stretch nor a change of viewing geometry shows up as change.
    """
    inv = json.loads((mosaic.ROOT / "data" / "inventory.json").read_text())
    by_tf: dict[str, list[dict]] = {}
    for r in inv:
        by_tf.setdefault(r["tf"], []).append(r)
    glon, glat = mosaic.grid()
    rr, cc = np.nonzero(mask)
    best = None
    for tf, recs in sorted(by_tf.items()):
        rows, cols = mosaic.window(recs)
        if not (rows.start <= rr.min() and rr.max() < rows.stop and cols.start <= cc.min() and cc.max() < cols.stop):
            continue
        lon, lat = glon[rows, cols], glat[rows, cols]
        burn = mask[rows, cols]
        out = {}
        for layer in ("HVHV", "HHHH"):
            looks = mosaic.load_tf(recs, lon, lat, layer)
            early = [a for d, a in looks if d < mosaic.BASELINE_END]
            if len(early) < 1:
                break
            with np.errstate(all="ignore"):
                base = np.nanmedian(early, axis=0)
            ref = base > np.nanpercentile(base, mosaic.FOREST_PCT)
            pts = []
            for d, a in looks:
                m = mosaic.match(a, base, ref)[burn]
                if np.isfinite(m).mean() > 0.8:
                    pts.append((d.isoformat(), round(float(np.nanmean(m)), 1)))
            out[layer] = pts
        if len(out) == 2 and len(out["HVHV"]) > (len(best["hv"]) if best else 0):
            best = {"tf": tf, "hv": out["HVHV"], "hh": out["HHHH"]}
        print(tf, {k: len(v) for k, v in out.items()})
    return best


def write_ketapang() -> None:
    """Find the largest loss cluster in the Ketapang box at the last step; store its centre, size and island rank."""
    cached = np.load(mosaic.WORK / "mosaic.npz")
    last = cached["score"][-1].astype(np.float32)
    glon, glat = mosaic.grid()
    land = mosaic.borneo_mask(last.shape)
    lost = land & np.isfinite(last) & (last > mosaic.LOSS_MIN)
    km2_px = (mosaic.RES * 111.32) ** 2 * np.cos(np.radians(glat))
    labels, count = label(lost, structure=np.ones((3, 3)))  # 8-connected: diagonal pixels belong to one burn
    if not count:
        print("no loss clusters")
        return
    sizes = np.bincount(labels.ravel(), weights=km2_px.ravel())[1:]
    w, e, s, n = KETAPANG_BOX
    box = (glon >= w) & (glon <= e) & (glat >= s) & (glat <= n)
    inside = np.unique(labels[box & lost])
    biggest = inside[np.argmax(sizes[inside - 1])]
    rr, cc = np.nonzero(labels == biggest)
    point = [round(float(glat[rr, cc].mean()), 4), round(float(glon[rr, cc].mean()), 4)]
    km2 = float(sizes[biggest - 1])
    rank = int((sizes > km2).sum()) + 1
    meta_path = mosaic.WEB / "steps.json"
    meta = json.loads(meta_path.read_text())
    meta["ketapang"] = point
    meta["ketapang_km2"] = round(km2, 1)
    meta["ketapang_rank"] = rank
    meta["ketapang_series"] = burn_series(labels == biggest)
    meta_path.write_text(json.dumps(meta, indent=1))
    print("Ketapang cluster", point, f"{km2:.1f} km2, rank {rank} of {count} on the island")

if __name__ == "__main__":
    import sys
    write_ketapang() if sys.argv[1:] == ["--ketapang"] else main()
