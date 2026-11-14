"""Estimate CO2 from the radar-loss area that sits on peat, and add it to web/data/steps.json.

CO2 per step = sum over lost pixels of (pixel area x peat fraction) x peat fuel burnt x emission factor.
- Peat fraction: Peat-ML global peatland extent (Melton et al. 2022, CC-BY 4.0), percent per 1/12 degree cell.
  Download: https://zenodo.org/records/7352284 (unzip the .tif into data/raw/peat/).
- Fuel burnt: 353 t dry matter per ha, 95% CI 170 to 536 (IPCC 2013 Wetlands Supplement, Table 2.6,
  tropical wildfire on drained peat).
- Emission factor: 464 g CO2-C per kg dry matter (Table 2.7, tropical), times 44/12 = 1,701 g CO2 per kg.
Also writes web/data/peat.png and peatburn_SS.png (burned peat per step). Car comparison: 4.6 t CO2 per typical passenger car per year (US EPA).
Counts peat only, not the trees above it, and assumes every lost pixel on peat burned.
Run after mosaic.py and probe.py (mosaic.py rewrites steps.json).
"""
import json

import numpy as np
import tifffile

import mosaic

PEAT_TIF = mosaic.RAW / "peat" / "Peat-ML_global_peatland_extent.tif"
FUEL_T_HA = (353, 170, 536)  # mean, low, high
CO2_PER_KG = 464 * 44 / 12 / 1000  # kg CO2 per kg dry matter
CAR_T_YEAR = 4.6  # t CO2 a typical US passenger car emits in a year (EPA)


def peat_fraction(glon: np.ndarray, glat: np.ndarray) -> np.ndarray:
    """Peat-ML fraction (0 to 1) at each grid pixel, nearest cell."""
    with tifffile.TiffFile(PEAT_TIF) as t:
        page = t.pages[0]
        sx, sy, _ = page.tags["ModelPixelScaleTag"].value
        _, _, _, lon0, lat0, _ = page.tags["ModelTiepointTag"].value
        peat = page.asarray()
    r = ((lat0 - glat) / sy).astype(int)
    c = ((glon - lon0) / sx).astype(int)
    return np.nan_to_num(peat[r, c], nan=0) / 100


def write_peat(frac: np.ndarray, land: np.ndarray) -> None:
    """Peat layer for the map: brown, more opaque where more of the cell is peat."""
    from PIL import Image
    rgba = np.zeros((*frac.shape, 4), np.uint8)
    rgba[..., :3] = (120, 72, 40)
    rgba[..., 3] = np.where(land, (frac * 170).clip(0, 170), 0).astype(np.uint8)
    Image.fromarray(rgba).save(mosaic.WEB / "peat.png", optimize=True)


def write_burned_peat(s: int, lost: np.ndarray, frac: np.ndarray) -> None:
    """Per-step layer: lost pixels on peat as dark char, darker where more of the cell is peat."""
    from PIL import Image
    from scipy.ndimage import binary_dilation
    on_peat = lost & (frac > 0.05)
    shown = binary_dilation(on_peat)  # the same one-pixel halo as the loss layer, so they line up
    rgba = np.zeros((*lost.shape, 4), np.uint8)
    rgba[..., :3] = (38, 22, 14)
    rgba[..., 3] = np.where(shown, (90 + frac * 165).clip(0, 255), 0).astype(np.uint8)
    Image.fromarray(rgba).save(mosaic.WEB / f"peatburn_{s:02d}.png", optimize=True)


def main() -> None:
    cached = np.load(mosaic.WORK / "mosaic.npz")
    score = cached["score"]
    glon, glat = mosaic.grid()
    land = mosaic.borneo_mask(score.shape[1:])
    frac = peat_fraction(glon, glat)
    km2_px = (mosaic.RES * 111.32) ** 2 * np.cos(np.radians(glat))
    write_peat(frac, land)
    meta_path = mosaic.WEB / "steps.json"
    meta = json.loads(meta_path.read_text())
    for s, step in enumerate(meta["steps"]):
        lost = land & np.isfinite(score[s]) & (score[s].astype(np.float32) > mosaic.LOSS_MIN)
        peat_km2 = float((km2_px * frac)[lost].sum())
        write_burned_peat(s, lost, frac)
        mt = [peat_km2 * 100 * f * CO2_PER_KG / 1e6 for f in FUEL_T_HA]  # km2 -> ha, t dm -> t CO2 -> Mt
        step.update(peat_km2=round(peat_km2, 1), co2_mt=round(mt[0], 2), co2_lo=round(mt[1], 2), co2_hi=round(mt[2], 2),
                    cars_m=round(mt[0] / CAR_T_YEAR, 2))
        print(s, step["km2"], step["peat_km2"], step["co2_mt"], f"({step['co2_lo']} to {step['co2_hi']})")
    meta["co2_note"] = ("Peat only: lost area on mapped peat (Peat-ML) x 353 t dry matter/ha burnt x 1.70 t CO2/t "
                        "(IPCC 2013 Wetlands Supplement, Tables 2.6 and 2.7). Range from the IPCC 95% interval.")
    meta_path.write_text(json.dumps(meta, indent=1))


if __name__ == "__main__":
    main()
