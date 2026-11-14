# Borneo through the smoke

Tracking where Borneo's forest went quiet in the 2026 fire season, 12 days at a time, with NISAR L-band radar.
NASA Space Apps Challenge 2026, challenge [Dancing with the SARs](https://www.spaceappschallenge.org/2026/challenges/dancing-with-the-sars/). Team ResearcherX.

Radar sees through smoke and cloud. NISAR's cross-polarized channel (HV) echoes off leaves and branches, so when a forest burns, its HV return collapses. This app maps that collapse across Borneo from June to October 2026.

## Run it

The app is static. From the repo root:

```sh
python3 -m http.server 8000 --directory web
```

Then open http://localhost:8000. No network needed: the map layers, the basemap and Leaflet are all in `web/`.

## Rebuild the layers

Requires [uv](https://docs.astral.sh/uv/). From `pipeline/`:

```sh
uv run python inventory.py   # list NISAR GCOV dual-pol granules over Borneo from NASA CMR
uv run python fetch.py       # download the public HH and HV browse images (about 1.2 GB)
uv run python mosaic.py      # 12-day HV loss mosaic -> web/data/loss_*.png, steps.json
uv run python probe.py       # per-pixel HV and HH history for the click-in chart
uv run python firms.py       # fire detections and agreement (needs FIRMS_MAP_KEY in .env)
```

## Method

- **Data:** NISAR L2 GCOV provisional browse images (HH and HV, frequency A), public from the ASF DAAC. 612 dual-pol granules, 68 track-frames, Jun 17 to Oct 26, 2026.
- **Placement:** each browse image is a north-up UTM grid. Its four data corners match the four vertices of the granule's CMR footprint, which fixes its position (0.4 px residual on the test granule).
- **Stretch:** each browse image is stretched to its own 5th and 95th percentiles, so every date is matched to the pre-season baseline on its forest pixels before comparison.
- **Loss:** baseline is the median of every look before Jul 23 (before the Aug to Oct fire season). A pixel counts as lost when its HV drops by more than 3 robust standard deviations of that track-frame's own date-to-date noise above the threshold, in two consecutive looks.
- **Mask:** land of the island of Borneo, from the NASA Blue Marble basemap.

## Limits

- Values are relative browse brightness, not calibrated backscatter.
- July reads zero by construction: it is part of the baseline.
- Gaps on the map are missing or partial NISAR frames.

## Sources

- NISAR L2 GCOV provisional, NASA/ISRO, via the ASF DAAC: https://nisar-docs.asf.alaska.edu/gcov/
- NASA CMR granule search: https://cmr.earthdata.nasa.gov/
- NASA FIRMS VIIRS active fire detections: https://firms.modaps.eosdis.nasa.gov/
- Basemap: NASA Blue Marble via GIBS: https://gibs.earthdata.nasa.gov/
- Leaflet 1.9.4 (BSD-2-Clause): https://leafletjs.com/

## Licence

Apache-2.0. See `LICENSE`.
