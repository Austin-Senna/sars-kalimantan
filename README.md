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
uv run python co.py          # fire gas: NASA AIRS carbon monoxide per step, with city readings (after smoke.py)
uv run python firms.py --sweep  # fire check across match radius and time window -> web/data/fire_sweep.json
uv run python optical.py     # independent optical check: NASA OPERA DIST-ALERT (run after firms.py)
uv run python review.py      # hand-check sample with before/after HLS images -> web/review/ (run after optical.py)
```

## Method

- **Data:** NISAR L2 GCOV provisional browse images (HH and HV, frequency A), public from the ASF DAAC. 612 dual-pol granules, 68 track-frames, Jun 17 to Oct 26, 2026.
- **Placement:** each browse image is a north-up UTM grid. Its four data corners match the four vertices of the granule's CMR footprint, which fixes its position (0.4 px residual on the test granule).
- **Stretch:** each browse image is stretched to its own 5th and 95th percentiles, so every date is matched to the pre-season baseline on its forest pixels before comparison.
- **Loss:** baseline is the median of every look before Jul 23 (before the Aug to Oct fire season). A pixel counts as lost when its HV drops by more than 3 robust standard deviations of that track-frame's own date-to-date noise above the threshold, in two consecutive looks.
- **Map colours:** green is tree cover in June (HV above the track-frame's 40th percentile: forest or plantation, the radar cannot tell them apart), grey is the rest of the land.
- **Mask:** land of the island of Borneo, from the NASA Blue Marble basemap. The top 0.175 degrees of the grid (4.225 to 4.4 N) is dropped: the partial frames there flagged loss at 5 to 20 times the background rate.
- **Fire check (timed, local):** each lost pixel gets an onset, the 12-day step it first crossed the loss threshold. It is matched when a NASA FIRMS VIIRS detection (nominal or high confidence) lies within 1 km of it during that step or the two before (36 days). Chance is the same test on unburned tree cover in the same 0.5 degree cells, each pixel given an onset drawn from that cell's real burns. Result: 44% of radar-loss area matched against 10% by chance (4.2x), and 65% of the 738 burns over 0.8 km² have a matching fire. A looser first test (any detection all season within 2 km) gave 70% against 34% of all tree cover. FIRMS standard processing to Jul 31, near real time after.
- **Fire gas:** NASA AIRS L3 daily carbon monoxide at 500 hPa (day and night passes), decoded from GIBS like the smoke layer, averaged per step and smoothed (the cells are 1 degree). Every city rises about 4x from June (75 to 85 ppbv) to late October (290 to 330 ppbv); the colormap tops out at 350, so peak values are lower bounds.
- **Fire detections on the map:** every nominal or high confidence detection of the 36 days up to the slider date, drawn as soft clusters (density over about 1.5 km) so they stay visible at island zoom; yellow where a radar burn within 1 km has appeared, see-through elsewhere.
- **Fire check, sensitivity:** across match radii of 0.5, 1 and 2 km and windows of 24, 36 and 48 days, radar loss matches a fire 2.5 to 6.3 times as often as chance. Tighter radii give higher ratios; the 1 km, 36 day setting used in the app is mid-range (4.2x).
- **Optical check:** NASA OPERA DIST-ALERT (vegetation disturbance from Landsat and Sentinel-2 HLS), latest status per pixel for Jun 5 to Jul 10 and Oct 1 to Nov 6. New disturbance = provisional or confirmed loss after, no disturbance before. 41% of the radar loss (where optical saw clearly both times, 90% of it) shows new disturbance, against 6% of unburned tree cover in the same 0.5 degree cells. 10% of the radar loss was already disturbed in June and is left out. Fire or optical confirms 63% of the radar loss. MODIS and VIIRS burned-area products end Aug 1, 2026, so they cannot check this season yet.
- **Hand check:** `web/review.html` shows a random sample of 24 burns (0.8 km² or more) as cloud-masked before/after HLS composites with the radar outline, for people to label before revealing the fire and optical results.
- **CO2:** lost area on peat (Peat-ML peat fraction) x 353 t dry matter burnt per ha x 1.70 t CO2 per t (IPCC 2013 Wetlands Supplement, Tables 2.6 and 2.7, tropical drained-peat wildfire). The range uses the IPCC 95% interval for fuel burnt. Peat only: the trees above it are not counted. For scale, the panel converts it to cars at 4.6 t CO2 per car per year (US EPA). The "Peat" layer shows the Peat-ML peat share, so red on brown is where the CO2 comes from.
- **Smoke:** daily NASA VIIRS Deep Blue aerosol optical depth (Suomi-NPP and NOAA-20) from GIBS, each colour turned back into its value with the GIBS colormap and averaged per 12-day step, from Sumatra to Sulawesi. Holes (cloud, or smoke too thick to retrieve) are filled from the steps either side, then from readings up to about 40 km away, and smoothed. City readings average about 25 km around each city on the filled field. NASA Earth Observatory reads AOD under 0.1 as a clear sky and 1 as very hazy; the city chips call under 0.3 clear and 2 or more thick. Pontianak reaches about 2.4 and Palangka Raya 3.0 from September; Singapore and Kuala Lumpur reach 1.7 by late October.
- **CO2, confirmed floor:** counting only peat loss that fire or optical confirms (375 of 472 km²) gives 22.5 Mt (11 to 34); counting all radar loss on peat gives 28 Mt (14 to 43). The app shows 22 to 28 Mt (the floor rounded down).
- **Haze words:** the app's "clear" and "very hazy" follow NASA Earth Observatory's reading of aerosol optical depth (under 0.1 a clear sky, 1 very hazy). "Thick" (2 and over) on the city chips is our own cut-off.
- **Ketapang chart:** the burned pixels of the largest loss cluster in West Kalimantan (38 km², 5th on the island), from the single track-frame with the most looks over it, each look matched to that frame's own baseline. Leaf echo (HV) falls 20% from June to Oct 10. Clicks elsewhere use a coarser 1 km, multi-pass composite.

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
- NASA OPERA L3 DIST-ALERT-HLS vegetation disturbance, via GIBS: https://www.earthdata.nasa.gov/data/catalog/lpcloud-opera-l3-dist-alert-hls-v1-1
- NASA HLS (Harmonized Landsat and Sentinel-2) true colour, via GIBS: https://www.earthdata.nasa.gov/data/projects/hls
- NASA AIRS L3 carbon monoxide (500 hPa), via GIBS: https://airs.jpl.nasa.gov/
- NASA FIRMS VIIRS active fire detections: https://firms.modaps.eosdis.nasa.gov/
- Peat-ML global peatland extent, Melton et al. (2022), CC-BY 4.0: https://doi.org/10.5281/zenodo.7352284
- IPCC (2014), 2013 Supplement to the 2006 IPCC Guidelines: Wetlands, Chapter 2, Tables 2.6 and 2.7: https://www.ipcc-nggip.iges.or.jp/public/wetlands/
- NASA Earth Observatory, Aerosol Optical Depth (reading the scale): https://science.nasa.gov/earth/earth-observatory/global-maps/aerosol-optical-depth
- US EPA, Greenhouse Gas Emissions from a Typical Passenger Vehicle: https://www.epa.gov/greenvehicles/greenhouse-gas-emissions-typical-passenger-vehicle
- Basemap: NASA Blue Marble via GIBS: https://gibs.earthdata.nasa.gov/
- Leaflet 1.9.4 (BSD-2-Clause): https://leafletjs.com/

## Licence

Apache-2.0. See `LICENSE`.
