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
NEAR_KM = 2.0
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


def pick_product(key: str, sensor: str) -> str:
    """Use standard processing (SP) where it covers the whole window, otherwise near real time (NRT)."""
    rows = list(csv.DictReader(io.StringIO(get(f"{API}/data_availability/csv/{key}/all"))))
    for suffix in ("SP", "NRT"):
        for r in rows:
            if r["data_id"] == f"{sensor}_{suffix}" and r["min_date"] <= START.isoformat() and r["max_date"] >= END.isoformat():
                return r["data_id"]
    raise SystemExit(f"no {sensor} product covers {START} to {END}: {[r['data_id'] for r in rows]}")


def fetch(key: str) -> list[list]:
    """All detections in the Borneo box between START and END, cached after the first run."""
    if CACHE.exists():
        return json.loads(CACHE.read_text())
    area = f"{mosaic.WEST},{mosaic.SOUTH},{mosaic.EAST},{mosaic.NORTH}"
    points = []
    for sensor in SOURCES:
        product = pick_product(key, sensor)
        day = START
        while day <= END:
            text = get(f"{API}/area/csv/{key}/{product}/{area}/{DAYS_PER_CALL}/{day.isoformat()}")
            for r in csv.DictReader(io.StringIO(text)):
                if r.get("confidence", "n") != "l":  # drop low-confidence VIIRS detections
                    points.append([round(float(r["latitude"]), 4), round(float(r["longitude"]), 4), r["acq_date"]])
            day += timedelta(days=DAYS_PER_CALL)
        print(sensor, product, len(points))
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


def main() -> None:
    """Fetch, score, write firms.json."""
    points = fetch(map_key())
    in_loss, in_forest = agreement(points)
    out = {
        "points": points,
        "near_km": NEAR_KM,
        "loss_near": round(in_loss, 3),
        "forest_near": round(in_forest, 3),
        "agreement": (f"{in_loss:.0%} of radar-loss area lies within {NEAR_KM:g} km of a fire detection, "
                      f"against {in_forest:.0%} of all forest."),
    }
    (mosaic.WEB / "firms.json").write_text(json.dumps(out, separators=(",", ":")))
    print(out["agreement"], f"{len(points)} detections")


if __name__ == "__main__":
    main()
