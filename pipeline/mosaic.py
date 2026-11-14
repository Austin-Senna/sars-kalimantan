"""Build the 12-day canopy-loss mosaic of Indonesian Borneo from NISAR GCOV HV browse images.

Per track-frame: sample every date onto a common lat/lon grid, take June as the baseline, and score
loss as baseline HV minus current HV wherever June was forest-bright. A pixel counts as lost only when
its two most recent looks both show the drop (a persistence filter against speckle and wet days).
Track-frames are combined by averaging their latest scores. Writes the web layers to web/data/.
"""
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.ndimage import uniform_filter

import georef

ROOT = Path(__file__).parent
RAW = ROOT / "data" / "raw"
WEB = ROOT.parent / "web" / "data"

WEST, EAST, SOUTH, NORTH = 108.5, 119.3, -4.3, 4.4
RES = 0.0025  # degrees, about 280 m
PROBE_EVERY = 4  # click-probe grid is RES * 4, about 1.1 km
STEP0 = date(2026, 6, 17)  # first NISAR science-phase 12-day cycle
STEP_DAYS = 12
BASELINE_END = date(2026, 7, 1)  # June looks form the baseline
SMOOTH = 3  # grid pixels, boxcar
FOREST_PCT = 40  # June HV above this percentile of the track-frame counts as canopy
NOISE_K = 3.0  # a drop counts as loss above NOISE_K robust sigmas of the date-to-date noise
LOSS_MIN = 1.0  # loss score threshold, in sigmas above the NOISE_K floor (score = drop / sigma - NOISE_K)


def grid() -> tuple[np.ndarray, np.ndarray]:
    """Pixel-centre lon and lat arrays for the output grid, north row first."""
    lons = WEST + RES * (np.arange(round((EAST - WEST) / RES)) + 0.5)
    lats = NORTH - RES * (np.arange(round((NORTH - SOUTH) / RES)) + 0.5)
    return np.meshgrid(lons.astype(np.float64), lats.astype(np.float64))


def step_of(d: date) -> int:
    """Index of the 12-day step a date falls in."""
    return (d - STEP0).days // STEP_DAYS


def window(recs: list[dict]) -> tuple[slice, slice]:
    """Grid rows and columns covering every footprint of a track-frame."""
    lon = [v for r in recs for v in r["lon"]]
    lat = [v for r in recs for v in r["lat"]]
    c0 = max(0, int((min(lon) - WEST) / RES))
    c1 = min(round((EAST - WEST) / RES), int((max(lon) - WEST) / RES) + 1)
    r0 = max(0, int((NORTH - max(lat)) / RES))
    r1 = min(round((NORTH - SOUTH) / RES), int((NORTH - min(lat)) / RES) + 1)
    return slice(r0, r1), slice(c0, c1)


def smooth(a: np.ndarray) -> np.ndarray:
    """NaN-aware boxcar."""
    ok = np.isfinite(a)
    num = uniform_filter(np.where(ok, a, 0), SMOOTH)
    den = uniform_filter(ok.astype(np.float32), SMOOTH)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(den > 0.5, num / den, np.nan)


def load_tf(recs: list[dict], lon: np.ndarray, lat: np.ndarray, layer: str) -> list[tuple[date, np.ndarray]]:
    """Sampled, smoothed looks for one track-frame and layer, oldest first."""
    looks = []
    for r in recs:
        path = RAW / f"{r['key']}_{layer}.png"
        if not path.exists():
            continue
        img = np.asarray(Image.open(path).convert("L"))
        hv_path = RAW / f"{r['key']}_HVHV.png"
        valid = img > 0 if layer == "HVHV" else np.asarray(Image.open(hv_path).convert("L")) > 0
        fitted = georef.fit(r["lon"], r["lat"], valid)
        if fitted is None:
            print(f"  skip {r['key']} {layer}: corners do not fit")
            continue
        looks.append((date.fromisoformat(r["date"][:4] + "-" + r["date"][4:6] + "-" + r["date"][6:]),
                      smooth(georef.sample(img, *fitted, lon, lat))))
    return sorted(looks, key=lambda t: t[0])


def match(a: np.ndarray, base: np.ndarray, forest: np.ndarray) -> np.ndarray:
    """Undo the per-image stretch: map a's forest median and IQR onto the baseline's."""
    both = forest & np.isfinite(a)
    if both.sum() < 1000:
        return np.full_like(a, np.nan)
    qa = np.percentile(a[both], [25, 50, 75])
    qb = np.percentile(base[both], [25, 50, 75])
    scale = (qb[2] - qb[0]) / max(qa[2] - qa[0], 1e-3)
    return (a - qa[1]) * scale + qb[1]


def main() -> None:
    """Score every track-frame, composite per step, write layers and stats."""
    inv = json.loads((ROOT / "data" / "inventory.json").read_text())
    by_tf: dict[str, list[dict]] = {}
    for r in inv:
        by_tf.setdefault(r["tf"], []).append(r)
    glon, glat = grid()
    shape = glon.shape
    last = max(step_of(date.fromisoformat(f"{r['date'][:4]}-{r['date'][4:6]}-{r['date'][6:]}")) for r in inv)
    n_steps = last + 1

    score_sum = np.zeros((n_steps, *shape), np.float32)
    score_n = np.zeros((n_steps, *shape), np.uint8)
    base_sum = np.zeros(shape, np.float32)
    base_n = np.zeros(shape, np.uint8)

    only = set(sys.argv[1:])
    for tf, recs in sorted(by_tf.items()):
        if only and tf not in only:
            continue
        rows, cols = window(recs)
        lon, lat = glon[rows, cols], glat[rows, cols]
        hv = load_tf(recs, lon, lat, "HVHV")
        june = [a for d, a in hv if d < BASELINE_END]
        if not june or len(hv) - len(june) < 2:
            print(f"{tf}: {len(june)} June looks, {len(hv) - len(june)} later; skipped")
            continue
        with np.errstate(all="ignore"):
            base = np.nanmean(june, axis=0)
        if np.isfinite(base).sum() < 10000:
            print(f"{tf}: too little valid June data; skipped")
            continue
        forest = base > np.nanpercentile(base, FOREST_PCT)
        later = [(d, match(a, base, forest)) for d, a in hv if d >= BASELINE_END]
        diffs = np.concatenate([(base - a)[forest & np.isfinite(a)] for _, a in later])
        sigma = 1.4826 * np.median(np.abs(diffs - np.median(diffs)))
        prev = None
        latest = np.full(base.shape, np.nan, np.float32)
        by_step: dict[int, np.ndarray] = {}
        for d, a in later:
            drop = np.where(forest, (base - a) / sigma - NOISE_K, np.nan)
            persistent = drop if prev is None else np.fmin(drop, prev)
            latest = np.where(np.isfinite(persistent), persistent, latest)
            prev = drop
            by_step[step_of(d)] = latest.copy()
        carry = np.full(base.shape, np.nan, np.float32)
        for s in range(n_steps):
            if s in by_step:
                carry = by_step[s]
            ok = np.isfinite(carry)
            score_sum[s, rows, cols][ok] += carry[ok]
            score_n[s, rows, cols][ok] += 1
        ok = np.isfinite(base)
        base_sum[rows, cols][ok] += base[ok]
        base_n[rows, cols][ok] += 1
        print(f"{tf}: {len(june)} June looks, {len(later)} later, sigma {sigma:.1f}")
    write(score_sum, score_n, base_sum, base_n, glat, n_steps)


def write(score_sum, score_n, base_sum, base_n, glat, n_steps) -> None:
    """Write PNG layers and steps.json."""
    WEB.mkdir(parents=True, exist_ok=True)
    with np.errstate(all="ignore"):
        base = base_sum / base_n
        score = score_sum / score_n
    Image.fromarray(np.nan_to_num(base, nan=0).clip(0, 255).astype(np.uint8)).save(WEB / "base_hv.png", optimize=True)
    forest = np.isfinite(score[0]) | np.isfinite(score[-1])
    rgba = np.zeros((*forest.shape, 4), np.uint8)
    rgba[forest] = (126, 224, 190, 90)
    Image.fromarray(rgba).save(WEB / "forest.png", optimize=True)
    km2_px = (RES * 111.32) ** 2 * np.cos(np.radians(glat))
    steps = []
    for s in range(n_steps):
        lost = np.isfinite(score[s]) & (score[s] > LOSS_MIN)
        t = np.clip((score[s] - LOSS_MIN) / 4, 0, 1)
        img = np.zeros((*lost.shape, 4), np.uint8)
        img[..., 0] = 255
        img[..., 1] = (190 * (1 - t)).astype(np.uint8)
        img[..., 2] = 40
        img[..., 3] = np.where(lost, 220, 0)
        Image.fromarray(img).save(WEB / f"loss_{s:02d}.png", optimize=True)
        start = STEP0 + timedelta(days=STEP_DAYS * s)
        steps.append({"step": s, "start": start.isoformat(),
                      "end": (start + timedelta(days=STEP_DAYS - 1)).isoformat(),
                      "km2": round(float(km2_px[lost].sum()), 1)})
    (WEB / "steps.json").write_text(json.dumps({"bounds": [[SOUTH, WEST], [NORTH, EAST]], "steps": steps}, indent=1))
    for s in steps:
        print(s)


if __name__ == "__main__":
    main()
