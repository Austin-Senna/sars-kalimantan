// Borneo through the smoke: static viewer for the precomputed NISAR HV loss layers in data/.
(async function () {
  const meta = await (await fetch("data/steps.json")).json();
  const steps = meta.steps;
  const bounds = L.latLngBounds(meta.bounds);
  const KETAPANG = meta.ketapang || [-2.2, 110.3];

  // Canvas rendering: tens of thousands of fire dots stay smooth while scrubbing.
  const map = L.map("map", { zoomSnap: 0.25, attributionControl: true, maxBounds: bounds.pad(0.3), preferCanvas: true });
  const narrow = () => window.innerWidth <= 700;
  const fit = () => map.fitBounds(bounds, narrow()
    ? { paddingBottomRight: [0, window.innerHeight * 0.5] }
    : { paddingTopLeft: [400, 0] });
  fit();
  map.attributionControl.setPrefix(false);
  map.attributionControl.addAttribution(
    "Radar: NISAR GCOV (NASA/ISRO, ASF DAAC) · Basemap: NASA Blue Marble (GIBS) · Fires: NASA FIRMS");

  L.imageOverlay("data/basemap.jpg", bounds, { opacity: 0.55 }).addTo(map);
  L.imageOverlay("data/base_hv.png", bounds, { opacity: 0.85, className: "pixelated" }).addTo(map);
  const forest = L.imageOverlay("data/forest.png", bounds).addTo(map);

  // One overlay per step, all preloaded, only the current one visible: scrubbing never waits on the network.
  const loss = steps.map((s) => L.imageOverlay(`data/loss_${String(s.step).padStart(2, "0")}.png`, bounds, { opacity: 0 }).addTo(map));

  const fires = L.layerGroup();
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
    const s = steps[i];
    document.getElementById("date").textContent = `${fmtDate(s.start)} to ${fmtDate(s.end)}`;
    document.getElementById("km2").textContent = fmtNum(s.km2);
    if (s.co2_mt != null) {
      document.getElementById("co2wrap").hidden = false;
      document.getElementById("co2").textContent = s.co2_mt.toFixed(s.co2_mt < 10 ? 1 : 0);
    }
    slider.value = i;
    drawFires();
    drawChart();
  }

  function drawFires() {
    fires.clearLayers();
    if (!fireData || !document.getElementById("tFires").checked) return;
    const end = steps[current].end;
    for (const [lat, lon, d] of fireData.points) {
      if (d <= end) fires.addLayer(L.circleMarker([lat, lon], { radius: 2, stroke: false, fillColor: "#ffd23f", fillOpacity: 0.8, interactive: false }));
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
  const marker = L.circleMarker([0, 0], { radius: 7, color: "#fff", weight: 2, fill: false });
  function sampleAt(latlng) {
    const x = Math.floor((latlng.lng - bounds.getWest()) / (bounds.getEast() - bounds.getWest()) * probe.w);
    const y = Math.floor((bounds.getNorth() - latlng.lat) / (bounds.getNorth() - bounds.getSouth()) * probe.h);
    if (x < 0 || y < 0 || x >= probe.w || y >= probe.h) return null;
    const k = (y * probe.w + x) * 4;
    const v = (arr) => arr.map((d) => (d[k + 3] ? d[k] : null));
    return { hv: v(probe.hv), hh: v(probe.hh) };
  }
  function openProbe(latlng, title) {
    if (!probe.ready) return;
    const s = sampleAt(latlng);
    if (!s || s.hv.every((v) => v == null)) return;
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
    map.once("moveend", () => openProbe(L.latLng(KETAPANG), "Ketapang peat dome"));
  });

  function drawChart() {
    if (!probeAt) return;
    const svg = document.getElementById("chart");
    const W = 300, H = 130, l = 26, r = 6, t = 8, b = 22;
    const n = steps.length;
    const xs = (i) => l + (i / (n - 1)) * (W - l - r);
    const ys = (v) => t + (1 - v / 255) * (H - t - b);
    const path = (vals) => vals.map((v, i) => (v == null ? null : `${xs(i)},${ys(v)}`)).filter(Boolean).map((p, i) => (i ? "L" : "M") + p).join("");
    const months = steps.map((s, i) => [i, s.start]).filter(([i, d]) => i === 0 || d.slice(5, 7) !== steps[i - 1].start.slice(5, 7));
    svg.innerHTML =
      [0, 128, 255].map((v) => `<line class="grid" x1="${l}" x2="${W - r}" y1="${ys(v)}" y2="${ys(v)}"/>`).join("") +
      `<text x="2" y="${ys(255) + 3}">bright</text><text x="2" y="${ys(0)}">dark</text>` +
      months.map(([i, d]) => `<text x="${xs(i)}" y="${H - 6}">${new Date(d + "T00:00:00Z").toLocaleDateString("en-US", { month: "short", timeZone: "UTC" })}</text>`).join("") +
      `<line class="now" x1="${xs(current)}" x2="${xs(current)}" y1="${t}" y2="${H - b}"/>` +
      `<path class="hh" d="${path(probeAt.hh)}"/><path class="hv" d="${path(probeAt.hv)}"/>`;
  }

  window.addEventListener("resize", () => {});
  show(0);
})();
