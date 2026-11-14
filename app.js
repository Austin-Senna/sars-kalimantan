// Borneo through the smoke: static viewer for the precomputed NISAR HV loss layers in data/.
(async function () {
  const meta = await (await fetch("data/steps.json")).json();
  const steps = meta.steps;
  const bounds = L.latLngBounds(meta.bounds);
  const KETAPANG = meta.ketapang || [-2.2, 110.3];

  // Canvas rendering: tens of thousands of fire dots stay smooth while scrubbing.
  // No maxBounds on phones: the view there spans more latitude than the island, and the clamp would undo the fit above the sheet.
  const region = meta.smoke ? L.latLngBounds(meta.smoke.bounds) : bounds;  // Borneo plus Singapore and Kuala Lumpur
  const map = L.map("map", { zoomSnap: 0.25, attributionControl: true, maxBounds: window.innerWidth > 700 ? region.pad(0.3) : null, preferCanvas: true, zoomControl: false });
  L.control.zoom({ position: "topright" }).addTo(map);  // top left sits under the panel
  const narrow = () => window.innerWidth <= 700;
  const fit = () => map.fitBounds(bounds, narrow()
    ? { paddingBottomRight: [0, document.getElementById("panel").offsetHeight], paddingTopLeft: [0, 8] }
    : { paddingTopLeft: [400, 0] });
  fit();
  map.attributionControl.setPrefix(false);
  map.attributionControl.addAttribution(
    "Radar: NISAR GCOV (NASA/ISRO, ASF DAAC) · Basemap: NASA Blue Marble (GIBS) · Fires: NASA FIRMS · Smoke: NASA VIIRS Deep Blue AOD (GIBS) · Peat: Peat-ML");

  if (meta.smoke) L.imageOverlay("data/basemap_region.jpg", region, { opacity: 0.55 }).addTo(map);  // Sumatra to Sulawesi
  else L.imageOverlay("data/basemap.jpg", bounds, { opacity: 0.55 }).addTo(map);
  L.imageOverlay("data/base_hv.png", bounds, { opacity: 0.85, className: "pixelated" }).addTo(map);
  const forest = L.imageOverlay("data/forest.png", bounds).addTo(map);
  const peat = L.imageOverlay("data/peat.png", bounds, { className: "pixelated" });

  map.createPane("loss").style.zIndex = 420;  // above the fire dots (410), which sit above the radar base (400)
  // One overlay per step, all preloaded, only the current one visible: scrubbing never waits on the network.
  // Burned peat, per step: the loss on peat drawn as dark char above the red, shown with the peat toggle.
  map.createPane("peatburn").style.zIndex = 425;
  const peatburn = steps.map((s) => L.imageOverlay(`data/peatburn_${String(s.step).padStart(2, "0")}.png`, bounds, { opacity: 0, pane: "peatburn" }).addTo(map));
  const loss = steps.map((s) => L.imageOverlay(`data/loss_${String(s.step).padStart(2, "0")}.png`, bounds, { opacity: 0, pane: "loss" }).addTo(map));

  // Fires draw in their own pane between the radar base and the loss layers, so the red stays on top.
  const firePane = map.createPane("fires");
  firePane.style.zIndex = 410;
  firePane.style.opacity = 0.45;  // dense at island zoom: dim enough that the red loss reads on top
  const fireRenderer = L.canvas({ pane: "fires" });
  const fires = L.layerGroup();

  // Smoke: VIIRS aerosol optical depth per step over the wider region, above everything, with city readings.
  map.createPane("smoke").style.zIndex = 430;
  const smoke = meta.smoke ? steps.map((s) => L.imageOverlay(`data/smoke_${String(s.step).padStart(2, "0")}.png`, region, { opacity: 0, pane: "smoke" }).addTo(map)) : [];
  const cityLayer = L.layerGroup();
  const cityMarkers = meta.smoke ? Object.entries(meta.smoke.cities).map(([name, c]) =>
    [c, L.marker(c.latlon, { interactive: false, icon: L.divIcon({ className: "city", html: "", iconSize: null }) }).addTo(cityLayer), name]) : [];
  function drawSmoke() {
    const on = document.getElementById("tSmoke").checked;
    smoke.forEach((o, j) => o.setOpacity(on && j === current ? 1 : 0));
    for (const [c, m, name] of cityMarkers) {
      const v = c.aod[current];
      const level = v == null ? "none" : v >= 1 ? "thick" : v >= 0.3 ? "hazy" : "clear";
      m.setIcon(L.divIcon({ className: `city ${level}`, iconSize: null,
        html: `<b>${name}</b> ${v == null ? "no reading" : v.toFixed(1)}` }));
    }
  }
  let fireData = null;
  try {
    fireData = await (await fetch("data/firms.json")).json();
  } catch (e) {
    document.getElementById("tFires").disabled = true;
  }

  const slider = document.getElementById("slider");
  slider.max = steps.length - 1;
  const fmtDate = (iso) => new Date(iso + "T00:00:00Z").toLocaleDateString("en-US", { month: "long", day: "numeric", timeZone: "UTC" });
  const fmtNum = (n) => Math.round(n).toLocaleString("en-US");
  let current = 0;

  function show(i) {
    current = i;
    loss.forEach((o, j) => o.setOpacity(j === i ? 1 : 0));
    const peatOn = document.getElementById("tPeat").checked;
    peatburn.forEach((o, j) => o.setOpacity(peatOn && j === i ? 1 : 0));
    const s = steps[i];
    document.getElementById("date").textContent = `${fmtDate(s.start)} to ${fmtDate(s.end)}`;
    document.getElementById("km2").textContent = fmtNum(s.km2);
    if (s.co2_mt != null) {
      document.getElementById("co2wrap").hidden = false;
      document.getElementById("co2").textContent = s.co2_mt.toFixed(s.co2_mt < 10 ? 1 : 0);
      const r = (v) => v.toFixed(v < 10 ? 1 : 0);
      document.getElementById("co2label").textContent = s.co2_mt ? `Mt CO₂ from burning peat (IPCC range ${r(s.co2_lo)} to ${r(s.co2_hi)})` : "Mt CO₂ from burning peat";
      document.getElementById("co2wrap").title = meta.co2_note || "";
      document.getElementById("cars").textContent = s.cars_m >= 0.05
        ? `About as much as ${s.cars_m.toFixed(1)} million cars give off in a year` : "";
    }
    slider.value = i;
    drawFires();
    drawSmoke();
    drawChart();
  }

  function drawFires() {
    fires.clearLayers();
    if (!fireData || !document.getElementById("tFires").checked) return;
    const end = steps[current].end;
    for (const [lat, lon, d] of fireData.points) {
      if (d <= end) fires.addLayer(L.circleMarker([lat, lon], { radius: 1.2, stroke: false, fillColor: "#ffd23f", fillOpacity: 1, interactive: false, renderer: fireRenderer, pane: "fires" }));
    }
    const a = document.getElementById("agree");
    if (fireData.agreement) {
      a.hidden = false;
      a.textContent = fireData.agreement;
    }
  }

  // Play through the steps.
  let timer = null;
  const play = document.getElementById("play");
  play.addEventListener("click", () => {
    if (timer) { clearInterval(timer); timer = null; play.textContent = "▶"; play.setAttribute("aria-label", "Play"); return; }
    if (current === steps.length - 1) show(0);
    play.textContent = "❚❚"; play.setAttribute("aria-label", "Pause");
    timer = setInterval(() => {
      if (current >= steps.length - 1) { play.click(); return; }
      show(current + 1);
    }, 900);
  });
  slider.addEventListener("input", () => show(+slider.value));
  document.getElementById("tForest").addEventListener("change", (e) => e.target.checked ? forest.addTo(map) : forest.remove());
  document.getElementById("tPeat").addEventListener("change", (e) => { e.target.checked ? peat.addTo(map) : peat.remove(); show(current); });
  document.getElementById("tSmoke").addEventListener("change", (e) => {
    document.getElementById("smokeNote").hidden = !e.target.checked;
    if (e.target.checked) {
      cityLayer.addTo(map);
      map.flyToBounds(region, { duration: 1, ...(narrow()
        ? { paddingBottomRight: [0, document.getElementById("panel").offsetHeight] }
        : { paddingTopLeft: [400, 0] }) });
    } else {
      cityLayer.remove();
      map.flyToBounds(bounds, { duration: 1, ...(narrow()
        ? { paddingBottomRight: [0, document.getElementById("panel").offsetHeight] }
        : { paddingTopLeft: [400, 0] }) });
    }
    drawSmoke();
  });
  document.getElementById("tFires").addEventListener("change", (e) => { e.target.checked ? fires.addTo(map) : fires.remove(); drawFires(); });

  // Click probe: per-step HV and HH brightness from the probe PNGs.
  const probe = { hv: [], hh: [], w: 0, h: 0, ready: false };
  async function loadProbe() {
    const load = (src) => new Promise((ok, fail) => { const im = new Image(); im.onload = () => ok(im); im.onerror = fail; im.src = src; });
    const read = (im) => {
      const c = document.createElement("canvas"); c.width = im.width; c.height = im.height;
      const ctx = c.getContext("2d", { willReadFrequently: true }); ctx.drawImage(im, 0, 0);
      return ctx.getImageData(0, 0, im.width, im.height).data;
    };
    try {
      for (const s of steps) {
        const n = String(s.step).padStart(2, "0");
        const [hv, hh] = await Promise.all([load(`data/probe_hv_${n}.png`), load(`data/probe_hh_${n}.png`)]);
        probe.hv.push(read(hv)); probe.hh.push(read(hh)); probe.w = hv.width; probe.h = hv.height;
      }
      probe.ready = true;
    } catch (e) { /* no probe layers yet: clicks do nothing */ }
  }
  loadProbe();

  let probeAt = null;
  map.createPane("probe").style.zIndex = 600;  // the click marker sits above every layer
  const marker = L.circleMarker([0, 0], { radius: 9, color: "#fff", weight: 2.5, fill: false, pane: "probe", renderer: L.svg({ pane: "probe" }) });
  function sampleAt(latlng) {
    const x = Math.floor((latlng.lng - bounds.getWest()) / (bounds.getEast() - bounds.getWest()) * probe.w);
    const y = Math.floor((bounds.getNorth() - latlng.lat) / (bounds.getNorth() - bounds.getSouth()) * probe.h);
    if (x < 0 || y < 0 || x >= probe.w || y >= probe.h) return null;
    const k = (y * probe.w + x) * 4;
    const mid = (s) => new Date(Date.parse(s.start) + 6 * 864e5).toISOString().slice(0, 10);
    const v = (arr) => arr.map((d, i) => (d[k + 3] ? [mid(steps[i]), d[k]] : null)).filter(Boolean);
    return { hv: v(probe.hv), hh: v(probe.hh) };
  }
  function openProbe(latlng, title, series) {
    const s = series || (probe.ready ? sampleAt(latlng) : null);
    if (!s || !s.hv.length) return;
    probeAt = s;
    marker.setLatLng(latlng).addTo(map);
    document.getElementById("probeTitle").textContent = title || `${latlng.lat.toFixed(2)}°, ${latlng.lng.toFixed(2)}°`;
    document.getElementById("probe").hidden = false;
    drawChart();
  }
  map.on("click", (e) => openProbe(e.latlng));
  document.getElementById("probeClose").addEventListener("click", () => { document.getElementById("probe").hidden = true; marker.remove(); probeAt = null; });
  document.getElementById("jump").addEventListener("click", () => {
    map.flyTo(KETAPANG, 10, { duration: 1.2 });
    // The Ketapang chart is the burn itself: its burned pixels only, from one radar pass, at each real look date.
    map.once("moveend", () => openProbe(L.latLng(KETAPANG), "Ketapang peat dome", meta.ketapang_series));
  });
  if (meta.ketapang_km2) {
    document.getElementById("jumpNote").textContent =
      `Biggest burn in West Kalimantan: ${Math.round(meta.ketapang_km2)} km², #${meta.ketapang_rank} on the island.`;
  }

  function drawChart() {
    if (!probeAt) return;
    const svg = document.getElementById("chart");
    const W = 300, H = 130, l = 26, r = 6, t = 8, b = 22;
    const t0 = Date.parse(steps[0].start), t1 = Date.parse(steps[steps.length - 1].end);
    const xs = (d) => l + ((Date.parse(d) - t0) / (t1 - t0)) * (W - l - r);
    // Zoom the y axis to the data so a real drop is visible; the axis is relative brightness, not zero-based.
    const vals = [...probeAt.hv, ...probeAt.hh].map((p) => p[1]);
    const pad = Math.max(8, (Math.max(...vals) - Math.min(...vals)) * 0.15);
    const lo = Math.max(0, Math.min(...vals) - pad), hi = Math.min(255, Math.max(...vals) + pad);
    const ys = (v) => t + (1 - (v - lo) / (hi - lo)) * (H - t - b);
    const path = (pts) => pts.map(([d, v], i) => (i ? "L" : "M") + `${xs(d)},${ys(v)}`).join("");
    const dots = (pts, cls) => pts.map(([d, v]) => `<circle class="${cls}" cx="${xs(d)}" cy="${ys(v)}" r="2"/>`).join("");
    const months = steps.map((s) => s.start.slice(0, 7)).filter((m, i, a) => a.indexOf(m) === i);
    const now = steps[current].end;
    svg.innerHTML =
      [hi, (hi + lo) / 2, lo].map((v) => `<line class="grid" x1="${l}" x2="${W - r}" y1="${ys(v)}" y2="${ys(v)}"/>`).join("") +
      `<text x="2" y="${ys(hi) + 3}">brighter</text><text x="2" y="${ys(lo)}">darker</text>` +
      months.map((m) => `<text x="${xs(m + "-01") < l ? l : xs(m + "-01")}" y="${H - 6}">${new Date(m + "-15T00:00:00Z").toLocaleDateString("en-US", { month: "short", timeZone: "UTC" })}</text>`).join("") +
      `<line class="now" x1="${xs(now)}" x2="${xs(now)}" y1="${t}" y2="${H - b}"/>` +
      `<path class="hh" d="${path(probeAt.hh)}"/><path class="hv" d="${path(probeAt.hv)}"/>` +
      dots(probeAt.hh, "hh") + dots(probeAt.hv, "hv");
    const first = probeAt.hv[0][1], last = probeAt.hv[probeAt.hv.length - 1][1];
    const pct = Math.round((last - first) / first * 100);
    document.getElementById("probeNote").textContent = pct <= -5
      ? `Leaf echo (HV) is ${-pct}% below June by the last look.`
      : `Leaf echo (HV) changed ${pct >= 0 ? "+" : ""}${pct}% since June: no clear canopy loss here.`;
  }

  window.addEventListener("resize", () => {});
  show(0);
})();
