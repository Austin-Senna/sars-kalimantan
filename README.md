# Borneo through the smoke

Tracking where Borneo's forest went quiet in the 2026 fire season, 12 days at a time, with NISAR L-band radar.
NASA Space Apps Challenge 2026, challenge [Dancing with the SARs](https://www.spaceappschallenge.org/2026/challenges/dancing-with-the-sars/). Team ResearcherX.

Radar sees through smoke and cloud. NISAR's cross-polarized channel (HV) echoes off leaves and branches, so when a forest burns, its HV return collapses. This app maps that collapse across Borneo from June to October 2026.

## Run it

The app is static. From the repo root:

```sh
python3 -m http.server 8000 --directory web
```

Then open http://localhost:8000. The app is a four-chapter story (Next, or the arrow keys): the smoke, the radar loss under it, the check against NASA fire detections, and the peat carbon. Then Explore opens the free map. No network needed: the map layers, the basemap and Leaflet are all in `web/`.

## Rebuild the layers

Requires [uv](https://docs.astral.sh/uv/). From `pipeline/`:

```sh
uv run python inventory.py   # list NISAR GCOV dual-pol granules over Borneo from NASA CMR
uv run python fetch.py       # download the public HH and HV browse images (about 1.2 GB)
uv run python mosaic.py      # 12-day HV loss mosaic -> web/data/loss_*.png, steps.json
uv run python probe.py       # per-pixel HV and HH history for the click-in chart
uv run python firms.py       # fire detections and agreement (needs FIRMS_MAP_KEY in .env)
uv run python co2.py         # CO2 from lost area on peat (needs the Peat-ML GeoTIFF in data/raw/peat/)
uv run python smoke.py       # regional smoke: VIIRS Deep Blue aerosol optical depth per step, with city readings
```

## Method

- **Data:** NISAR L2 GCOV provisional browse images (HH and HV, frequency A), public from the ASF DAAC. 612 dual-pol granules, 68 track-frames, Jun 17 to Oct 26, 2026.
- **Placement:** each browse image is a north-up UTM grid. Its four data corners match the four vertices of the granule's CMR footprint, which fixes its position (0.4 px residual on the test granule).
- **Stretch:** each browse image is stretched to its own 5th and 95th percentiles, so every date is matched to the pre-season baseline on its forest pixels before comparison.
- **Loss:** baseline is the median of every look before Jul 23 (before the Aug to Oct fire season). A pixel counts as lost when its HV drops by more than 3 robust standard deviations of that track-frame's own date-to-date noise above the threshold, in two consecutive looks.
- **Map colours:** green is tree cover in June (HV above the track-frame's 40th percentile: forest or plantation, the radar cannot tell them apart), grey is the rest of the land.
- **Mask:** land of the island of Borneo, from the NASA Blue Marble basemap.
- **Fire check (timed, local):** each lost pixel gets an onset, the 12-day step it first crossed the loss threshold. It is matched when a NASA FIRMS VIIRS detection (nominal or high confidence) lies within 1 km of it during that step or the two before (36 days). Chance is the same test on unburned tree cover in the same 0.5 degree cells, each pixel given an onset drawn from that cell's real burns. Result: 40% of radar-loss area matched against 10% by chance (4x), and 63% of the 767 burns over 0.8 km² have a matching fire. A looser first test (any detection all season within 2 km) gave 65% against 34% of all tree cover. FIRMS standard processing to Jul 31, near real time after.
- **CO2:** lost area on peat (Peat-ML peat fraction) x 353 t dry matter burnt per ha x 1.70 t CO2 per t (IPCC 2013 Wetlands Supplement, Tables 2.6 and 2.7, tropical drained-peat wildfire). The range uses the IPCC 95% interval for fuel burnt. Peat only: the trees above it are not counted. For scale, the panel converts it to cars at 4.6 t CO2 per car per year (US EPA). The "Peat" layer shows the Peat-ML peat share, so red on brown is where the CO2 comes from.
- **Smoke:** daily NASA VIIRS Deep Blue aerosol optical depth (Suomi-NPP and NOAA-20) from GIBS, each colour turned back into its value with the GIBS colormap and averaged per 12-day step, from Sumatra to Sulawesi. Holes (cloud, or smoke too thick to retrieve) are filled from the steps either side, then from readings up to about 40 km away, and smoothed. City readings average about 25 km around each city on the filled field. AOD under 0.3 is clear, over 1 is thick smoke. Pontianak reaches about 2.4 and Palangka Raya 3.0 from September; Singapore and Kuala Lumpur reach 1.7 by late October.
- **Ketapang chart:** the burned pixels of the largest loss cluster in West Kalimantan (38 km², 6th on the island), from the single track-frame with the most looks over it, each look matched to that frame's own baseline. Leaf echo (HV) falls 20% from June to Oct 10. Clicks elsewhere use a coarser 1 km, multi-pass composite.

## Limits

- Values are relative browse brightness, not calibrated backscatter.
- July reads zero by construction: it is part of the baseline.
- Gaps on the map are missing or partial NISAR frames.
- The NISAR provisional archive ends at Oct 21, 2026 (checked Nov 14), so the map ends there.
- The CO2 figure assumes every lost pixel on peat burned to the IPCC default depth. Peat-ML is a 1/12 degree (about 9 km) map, so the peat share is coarse.

## Sources

- NISAR L2 GCOV provisional, NASA/ISRO, via the ASF DAAC: https://nisar-docs.asf.alaska.edu/gcov/
- NASA CMR granule search: https://cmr.earthdata.nasa.gov/
- NASA VIIRS Deep Blue aerosol optical depth (Suomi-NPP, NOAA-20) via GIBS: https://gibs.earthdata.nasa.gov/
- NASA FIRMS VIIRS active fire detections: https://firms.modaps.eosdis.nasa.gov/
- Peat-ML global peatland extent, Melton et al. (2022), CC-BY 4.0: https://doi.org/10.5281/zenodo.7352284
- IPCC (2014), 2013 Supplement to the 2006 IPCC Guidelines: Wetlands, Chapter 2, Tables 2.6 and 2.7: https://www.ipcc-nggip.iges.or.jp/public/wetlands/
- US EPA, Greenhouse Gas Emissions from a Typical Passenger Vehicle: https://www.epa.gov/greenvehicles/greenhouse-gas-emissions-typical-passenger-vehicle
- Basemap: NASA Blue Marble via GIBS: https://gibs.earthdata.nasa.gov/
- Leaflet 1.9.4 (BSD-2-Clause): https://leafletjs.com/

## Licence

Apache-2.0. See `LICENSE`.
