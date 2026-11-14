"""Fetch NASA FIRMS VIIRS fire detections over Borneo and score how well they agree with the radar loss.

Needs FIRMS_MAP_KEY in the repo's .env (free: https://firms.modaps.eosdis.nasa.gov/api/map_key/).
Writes web/data/firms.json: the detections (lat, lon, date) and one agreement sentence comparing the
share of radar-loss pixels near a detection with the share of all baseline forest pixels near one.
"""
import csv
import io
import json
import os
import urllib.request
from datetime import date, timedelta
from pathlib import Path

import numpy as np
from scipy.ndimage import distance_transform_edt

import mosaic

API = "https://firms.modaps.eosdis.nasa.gov/api"
SOURCES = ("VIIRS_SNPP", "VIIRS_NOAA20")
START, END = date(2026, 6, 17), date(2026, 10, 26)
DAYS_PER_CALL = 5
NEAR_KM = 2.0      # the first, loose test: any detection all season within 2 km
MATCH_KM = 1.0     # timed test: about three VIIRS pixels (375 m)
LAG_STEPS = 2      # timed test: a fire counts from two 12-day steps before the loss first shows, to that step
CELL_DEG = 0.5     # timed test: chance is measured on unburned tree cover in the same 0.5 degree cell
CACHE = mosaic.ROOT / "data" / "work" / "firms_raw.json"


def map_key() -> str:
    """Read FIRMS_MAP_KEY from the environment or the repo's .env."""
    if os.environ.get("FIRMS_MAP_KEY"):
        return os.environ["FIRMS_MAP_KEY"]
    env = mosaic.ROOT.parent / ".env"
    for line in env.read_text().splitlines() if env.exists() else []:
        if line.startswith("FIRMS_MAP_KEY="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("FIRMS_MAP_KEY missing: put it in .env")


def get(url: str) -> str:
    """GET a URL as text."""
    with urllib.request.urlopen(url, timeout=120) as resp:
        return resp.read().decode()


def availability(key: str) -> dict[str, tuple[str, str]]:
    """FIRMS product id -> (first date, last date) it covers."""
    rows = csv.DictReader(io.StringIO(get(f"{API}/data_availability/csv/{key}/all")))
    return {r["data_id"]: (r["min_date"], r["max_date"]) for r in rows}


def product_for(avail: dict, sensor: str, day: date) -> str:
    """Standard processing (SP) where it reaches, near real time (NRT) after it ends."""
    for suffix in ("SP", "NRT"):
        span = avail.get(f"{sensor}_{suffix}")
        if span and span[0] <= day.isoformat() <= span[1]:
            return f"{sensor}_{suffix}"
    raise SystemExit(f"no {sensor} product covers {day}")


def fetch(key: str) -> list[list]:
    """All detections in the Borneo box between START and END, cached after the first run."""
    if CACHE.exists():
        return json.loads(CACHE.read_text())
    area = f"{mosaic.WEST},{mosaic.SOUTH},{mosaic.EAST},{mosaic.NORTH}"
    points = []
    avail = availability(key)
    for sensor in SOURCES:
        day = START
        while day <= END:
            product = product_for(avail, sensor, day)
            last = min(day + timedelta(days=DAYS_PER_CALL - 1), date.fromisoformat(avail[product][1]))
            n = (last - day).days + 1  # never let one call run past the product's last day
            text = get(f"{API}/area/csv/{key}/{product}/{area}/{n}/{day.isoformat()}")
            for r in csv.DictReader(io.StringIO(text)):
                if r.get("confidence", "n") != "l":  # drop low-confidence VIIRS detections
                    points.append([round(float(r["latitude"]), 4), round(float(r["longitude"]), 4), r["acq_date"]])
            day = last + timedelta(days=1)
        print(sensor, len(points))
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(points))
    return points


def agreement(points: list[list]) -> tuple[float, float]:
    """Share of final radar-loss pixels within NEAR_KM of a detection, and the same share for all forest."""
    cached = np.load(mosaic.WORK / "mosaic.npz")
    score = cached["score"][-1].astype(np.float32)
    land = mosaic.borneo_mask(score.shape)
    forest = cached["forest"] & land
    lost = forest & np.isfinite(score) & (score > mosaic.LOSS_MIN)
    fire = np.zeros(score.shape, bool)
    for lat, lon, _ in points:
        r = int((mosaic.NORTH - lat) / mosaic.RES)
        c = int((lon - mosaic.WEST) / mosaic.RES)
        if 0 <= r < fire.shape[0] and 0 <= c < fire.shape[1]:
            fire[r, c] = True
    near = distance_transform_edt(~fire) * mosaic.RES * 111.32 <= NEAR_KM
    return float(near[lost].mean()), float(near[forest].mean())


def timed_agreement(points: list[list], match_km: float = MATCH_KM, lag_steps: int = LAG_STEPS, save: bool = True) -> dict:
    """Does a fire land where and when the canopy went? Compared with chance in the same place and season.

    For each lost pixel (the final loss map), its onset is the first 12-day step it crossed the loss threshold.
    It counts as matched when a detection lies within MATCH_KM during that step or the LAG_STEPS before it
    (the radar needs two looks, so the burn itself can sit a step or two earlier).
    Chance: unburned tree cover in the same CELL_DEG cells, each given an onset drawn from that cell's real
    burns, run through the identical test. Also reports the share of burns (8-connected clusters of at least
    10 pixels, about 0.8 km2) with at least one matched pixel.
    """
    from scipy.ndimage import label
    cached = np.load(mosaic.WORK / "mosaic.npz")
    score = cached["score"]
    n_steps, shape = score.shape[0], score.shape[1:]
    land = mosaic.borneo_mask(shape)
    forest = cached["forest"] & land
    onset = np.full(shape, -1, np.int8)
    for s in range(n_steps):
        over = np.nan_to_num(score[s].astype(np.float32), nan=-99) > mosaic.LOSS_MIN
        onset[(onset < 0) & over] = s
    final = np.nan_to_num(score[-1].astype(np.float32), nan=-99) > mosaic.LOSS_MIN
    lost = land & final & (onset >= 0)

    # Fire rasters per step, widened to MATCH_KM.
    near = np.zeros((n_steps, *shape), bool)
    fire = np.zeros((n_steps, *shape), bool)
    for lat, lon, d in points:
        s = mosaic.step_of(mosaic.parse_date(d.replace("-", "")))
        r, c = int((mosaic.NORTH - lat) / mosaic.RES), int((lon - mosaic.WEST) / mosaic.RES)
        if 0 <= s < n_steps and 0 <= r < shape[0] and 0 <= c < shape[1]:
            fire[s, r, c] = True
    for s in range(n_steps):
        if fire[s].any():
            near[s] = distance_transform_edt(~fire[s]) * mosaic.RES * 111.32 <= match_km
    window = near.copy()
    for k in range(1, lag_steps + 1):
        window[k:] |= near[:-k]

    def matched(rr: np.ndarray, cc: np.ndarray, on: np.ndarray) -> np.ndarray:
        return window[on, rr, cc]

    rr, cc = np.nonzero(lost)
    hit = matched(rr, cc, onset[rr, cc])
    hit_map = np.zeros(shape, bool)
    hit_map[rr, cc] = hit
    if save:
        np.savez_compressed(mosaic.WORK / "fire_match.npz", lost=lost, hit=hit_map)  # optical.py combines with this

    # Chance, place by place: control pixels borrow onsets from the real burns in their cell.
    rng = np.random.default_rng(0)
    size = round(CELL_DEG / mosaic.RES)
    cell = (rr // size) * 10000 + cc // size
    ctrl_r, ctrl_c = np.nonzero(forest & ~lost & (onset < 0))
    ctrl_cell = (ctrl_r // size) * 10000 + ctrl_c // size
    keep = np.isin(ctrl_cell, np.unique(cell))
    ctrl_r, ctrl_c, ctrl_cell = ctrl_r[keep], ctrl_c[keep], ctrl_cell[keep]
    ctrl_on = np.empty(len(ctrl_r), np.int8)
    order = np.argsort(cell)
    cells, starts = np.unique(cell[order], return_index=True)
    ends = np.append(starts[1:], len(order))
    on_sorted = onset[rr, cc][order]
    lookup = {c: on_sorted[a:b] for c, a, b in zip(cells, starts, ends)}
    for c in np.unique(ctrl_cell):
        idx = np.nonzero(ctrl_cell == c)[0]
        ctrl_on[idx] = rng.choice(lookup[c], size=len(idx))
    chance = matched(ctrl_r, ctrl_c, ctrl_on)

    # Per burn.
    labels, n = label(lost, structure=np.ones((3, 3)))
    sizes = np.bincount(labels.ravel())
    hit_by_label = np.bincount(labels[rr, cc], weights=hit, minlength=n + 1) > 0
    big = np.nonzero(sizes[1:] >= 10)[0] + 1
    burns = float(hit_by_label[big].mean()) if len(big) else float("nan")
    out = {"match_km": match_km, "window_days": (lag_steps + 1) * mosaic.STEP_DAYS,
           "loss_matched": round(float(hit.mean()), 3), "chance_matched": round(float(chance.mean()), 3),
           "burns_matched": round(burns, 3), "burns": int(len(big))}
    print(out)
    return out


def near_loss(points: list[list]) -> list[list]:
    """Append the onset step of the nearest radar burn within MATCH_KM (or -1), so the map can light a fire dot up
    only once the burn it matches has appeared."""
    cached = np.load(mosaic.WORK / "mosaic.npz")
    score = cached["score"]
    land = mosaic.borneo_mask(score.shape[1:])
    final = land & (np.nan_to_num(score[-1].astype(np.float32), nan=-99) > mosaic.LOSS_MIN)
    onset = np.full(final.shape, -1, np.int8)
    for s in range(score.shape[0]):
        onset[(onset < 0) & final & (np.nan_to_num(score[s].astype(np.float32), nan=-99) > mosaic.LOSS_MIN)] = s
    dist, (ir, ic) = distance_transform_edt(~final, return_indices=True)
    near = dist * mosaic.RES * 111.32 <= MATCH_KM
    out = []
    for lat, lon, d in points:
        r, c = int((mosaic.NORTH - lat) / mosaic.RES), int((lon - mosaic.WEST) / mosaic.RES)
        ok = 0 <= r < near.shape[0] and 0 <= c < near.shape[1] and near[r, c]
        out.append([lat, lon, d, int(onset[ir[r, c], ic[r, c]]) if ok else -1])
    return out


def thin(points: list[list], cell: float = 0.02) -> list[list]:
    """For the map: keep the first detection in each cell (about 2 km) and 12-day step, so the browser draws tens of
    thousands of dots, not 600k, and a time window of steps still shows every place that burned in it."""
    first: dict[tuple[int, int, int], list] = {}
    for lat, lon, d in points:
        k = (round(lat / cell), round(lon / cell), mosaic.step_of(mosaic.parse_date(d.replace("-", ""))))  # per step too
        if k not in first or d < first[k][2]:
            first[k] = [lat, lon, d]  # the detection's own position, so the dots do not line up on a grid
    return sorted(first.values(), key=lambda p: p[2])


def write_layers(points: list[list]) -> None:
    """One PNG per 12-day step with every detection from that step and the two before (36 days), at the radar grid.

    Bright yellow where the detection lies within MATCH_KM of a radar burn that has appeared by that step; faint
    elsewhere. No thinning: every nominal or high confidence detection is drawn.
    """
    from PIL import Image
    from scipy.ndimage import binary_dilation
    cached = np.load(mosaic.WORK / "mosaic.npz")
    score = cached["score"]
    n_steps, shape = score.shape[0], score.shape[1:]
    land = mosaic.borneo_mask(shape)
    final = land & (np.nan_to_num(score[-1].astype(np.float32), nan=-99) > mosaic.LOSS_MIN)
    onset = np.full(shape, 99, np.int8)
    for s in range(n_steps):
        onset[(onset == 99) & final & (np.nan_to_num(score[s].astype(np.float32), nan=-99) > mosaic.LOSS_MIN)] = s
    dist, (ir, ic) = distance_transform_edt(~final, return_indices=True)
    near_onset = np.where(dist * mosaic.RES * 111.32 <= MATCH_KM, onset[ir, ic], 99)  # onset of the nearby burn
    by_step = np.zeros((n_steps, *shape), bool)
    for lat, lon, d in points:
        s = mosaic.step_of(mosaic.parse_date(d.replace("-", "")))
        r, c = int((mosaic.NORTH - lat) / mosaic.RES), int((lon - mosaic.WEST) / mosaic.RES)
        if 0 <= s < n_steps and 0 <= r < shape[0] and 0 <= c < shape[1]:
            by_step[s, r, c] = True
    from scipy.ndimage import gaussian_filter
    for s in range(n_steps):
        seen = by_step[max(0, s - LAG_STEPS):s + 1].any(axis=0)
        hit = seen & (near_onset <= s)
        # Aggregate into soft clusters (density over about 1.5 km) so fire areas stay visible at island zoom,
        # where a single 280 m pixel is smaller than a screen pixel.
        dens = gaussian_filter(seen.astype(np.float32), 3)
        a_all = np.clip(dens * 6, 0, 1)
        dens_hit = gaussian_filter(binary_dilation(hit, iterations=2).astype(np.float32), 3)
        a_hit = np.clip(dens_hit * 3, 0, 1)
        rgba = np.zeros((*shape, 4), np.uint8)
        rgba[..., 0], rgba[..., 1], rgba[..., 2] = 255, 170, 50        # other fires: warm orange, see-through (reads as fire, not khaki)
        rgba[..., 3] = (a_all * 95).astype(np.uint8)
        top = a_hit > 0.05                                              # fires next to a radar burn: solid yellow on top
        rgba[top, 0], rgba[top, 1], rgba[top, 2] = 255, 226, 60
        rgba[top, 3] = np.maximum(rgba[top, 3], (a_hit[top] * 255).astype(np.uint8))
        # Drop the near-invisible tails and round alpha to 16 levels: same look, a fraction of the file size.
        a = rgba[..., 3]
        a[a < 12] = 0
        rgba[..., 3] = (a // 16) * 16
        rgba[rgba[..., 3] == 0] = 0
        # Half resolution (about 560 m): the layer is soft anyway.
        Image.fromarray(rgba).resize((shape[1] // 2, shape[0] // 2), Image.NEAREST).save(mosaic.WEB / f"fires_{s:02d}.png", optimize=True)


def main() -> None:
    """Fetch, score, write firms.json."""
    points = fetch(map_key())
    in_loss, in_forest = agreement(points)
    timed = timed_agreement(points)
    out = {
        "timed": timed,
        # The map draws every detection from the fires_SS.png layers; the json keeps only the numbers.
        "detections": len(points),
        "near_km": NEAR_KM,
        "loss_near": round(in_loss, 3),
        "forest_near": round(in_forest, 3),
        "agreement": (f"{in_loss:.0%} of radar-loss area lies within {NEAR_KM:g} km of a fire detection, "
                      f"against {in_forest:.0%} of all forest."),
    }
    (mosaic.WEB / "firms.json").write_text(json.dumps(out, separators=(",", ":")))
    write_layers(points)
    print(out["agreement"], f"{len(points)} detections")


def sweep() -> None:
    """Does the result depend on the chosen radius and window? Rerun the timed test over a grid of both."""
    points = json.loads(CACHE.read_text())
    rows = []
    for km in (0.5, 1.0, 2.0):
        for lag in (1, 2, 3):
            r = timed_agreement(points, km, lag, save=False)
            rows.append({k: r[k] for k in ("match_km", "window_days", "loss_matched", "chance_matched", "burns_matched")}
                        | {"ratio": round(r["loss_matched"] / r["chance_matched"], 1)})
    (mosaic.WEB / "fire_sweep.json").write_text(json.dumps(rows, indent=1))
    print("km  days  loss  chance  ratio  burns")
    for r in rows:
        print(f"{r['match_km']:<3} {r['window_days']:<5} {r['loss_matched']:.0%}  {r['chance_matched']:.0%}   "
              f"{r['ratio']:<5}  {r['burns_matched']:.0%}")


if __name__ == "__main__":
    import sys
    sweep() if sys.argv[1:] == ["--sweep"] else main()
