// Borneo through the smoke: a four-chapter story over precomputed NISAR, FIRMS, VIIRS and peat layers in data/,
// then a free Explore mode. Everything is static: no network calls beyond these files.
(async function () {
  const meta = await (await fetch("data/steps.json", { cache: "no-cache" })).json();
  let fireData = null;
  try { fireData = await (await fetch("data/firms.json", { cache: "no-cache" })).json(); } catch (e) { /* fires chapter shows no dots */ }
  const steps = meta.steps;
  const last = steps.length - 1;
  const bounds = L.latLngBounds(meta.bounds);
  const region = meta.smoke ? L.latLngBounds(meta.smoke.bounds) : bounds;  // Borneo plus Singapore and Kuala Lumpur
  const FIRE_ZONE = L.latLngBounds([[-4.2, 108.9], [1.4, 117.8]]);          // where the burns cluster
  const PROOF_ZONE = L.latLngBounds([[-3.1, 109.7], [-1.3, 111.3]]);       // Ketapang's burns, close enough to see dots
  const KETAPANG = meta.ketapang || [-2.2, 110.48];
  const $ = (id) => document.getElementById(id);
  const narrow = () => window.innerWidth <= 700;

  // --- Map and panes, bottom to top: basemap, radar base, peat, fires, loss, burned peat, smoke, probe marker.
  const map = L.map("map", { zoomSnap: 0.25, zoomControl: false, preferCanvas: true,
    maxBounds: narrow() ? null : region.pad(0.4) });
  L.control.zoom({ position: "topright" }).addTo(map);
  map.attributionControl.setPrefix(false);
  map.attributionControl.addAttribution("Radar: NISAR GCOV (NASA/ISRO, ASF DAAC) · Fires: NASA FIRMS · " +
    "Smoke: NASA VIIRS Deep Blue AOD · Basemap: NASA Blue Marble (GIBS) · Peat: Peat-ML");
  const pane = (name, z) => { const p = map.createPane(name); p.style.zIndex = z; return p; };
  pane("radar", 402); pane("peat", 405); pane("fires", 410); pane("loss", 420); pane("peatburn", 425);
  pane("smoke", 430); pane("probe", 600);
  const pad = (n) => String(n).padStart(2, "0");

  L.imageOverlay(meta.smoke ? "data/basemap_region.jpg" : "data/basemap.jpg", meta.smoke ? region : bounds, { opacity: 0.5 }).addTo(map);
  L.imageOverlay("data/base_hv.png", bounds, { pane: "radar", className: "pixelated" }).addTo(map);
  L.imageOverlay("data/peat.png", bounds, { pane: "peat", className: "pixelated" }).addTo(map);
  // One overlay per step for each time layer, all preloaded; only the current step is visible.
  const perStep = (prefix, b, p) => steps.map((s) => L.imageOverlay(`data/${prefix}_${pad(s.step)}.png`, b, { opacity: 0, pane: p }).addTo(map));
  const loss = perStep("loss", bounds, "loss");
  const peatburn = perStep("peatburn", bounds, "peatburn");
  const smoke = meta.smoke ? perStep("smoke", region, "smoke") : [];
  const fireRenderer = L.canvas({ pane: "fires" });
  const fires = L.layerGroup().addTo(map);
  const cities = L.layerGroup().addTo(map);
  const cityMarkers = meta.smoke ? Object.entries(meta.smoke.cities).map(([name, c]) =>
    ({ name, c, m: L.marker(c.latlon, { interactive: false, icon: L.divIcon({ className: "city", iconSize: null }) }).addTo(cities) })) : [];
  const marker = L.circleMarker([0, 0], { radius: 10, color: "#fff", weight: 2.5, fill: false, pane: "probe", renderer: L.svg({ pane: "probe" }) });

  // Burns are a few pixels wide at island zoom: give the loss pane a glow when zoomed out.
  const glow = () => map.getPane("loss").classList.toggle("glow", map.getZoom() < 8);
  map.on("zoomend", () => { glow(); firesDrawnFor = null; drawFires(); });

  // --- State: which layers show, and the current 12-day step.
  const view = { smoke: false, fires: false, peat: false };
  let firesDrawnFor = null;
  let current = 0;
  function render() {
    const show = (el, on, o = 1) => { el.style.opacity = on ? o : 0; };
    show(map.getPane("smoke"), view.smoke);
    show(map.getPane("radar"), !view.smoke, 0.92);
    show(map.getPane("loss"), !view.smoke);
    show(map.getPane("fires"), view.fires && !view.smoke, 0.38);
    show(map.getPane("peat"), view.peat && !view.smoke);
    show(map.getPane("peatburn"), view.peat && !view.smoke);
    loss.forEach((o, j) => o.setOpacity(j === current ? 1 : 0));
    peatburn.forEach((o, j) => o.setOpacity(j === current ? 1 : 0));
    smoke.forEach((o, j) => o.setOpacity(j === current ? 1 : 0));
    view.smoke ? cities.addTo(map) : cities.remove();
    for (const { name, c, m } of cityMarkers) {
      const v = c.aod[current];
      const level = v == null ? "none" : v >= 1 ? "thick" : v >= 0.3 ? "hazy" : "clear";
      m.setIcon(L.divIcon({ className: `city ${level}`, iconSize: null, html: `<b>${name}</b> ${v == null ? "no reading" : v.toFixed(1)}` }));
    }
    drawFires();
    $("tPeat").checked = view.peat; $("tFires").checked = view.fires; $("tSmoke").checked = view.smoke;
  }

  function drawFires() {
    const key = view.fires && fireData ? current : null;
    if (key === firesDrawnFor) return;
    firesDrawnFor = key;
    fires.clearLayers();
    if (key == null) return;
    // Only fires from this step and the two before it (36 days): the dots follow the fire front instead of piling up.
    const end = steps[current].end, start = steps[Math.max(0, current - 2)].start;
    const radius = map.getZoom() >= 8 ? 2.2 : 1.3;  // bigger dots once zoomed in to a region
    for (const [lat, lon, d] of fireData.points) {
      if (d >= start && d <= end) fires.addLayer(L.circleMarker([lat, lon], { radius, stroke: false, fillColor: "#ffd23f", fillOpacity: 1, interactive: false, renderer: fireRenderer, pane: "fires" }));
    }
  }

  // --- Time.
  const slider = $("slider");
  slider.max = last;
  const fmtDate = (iso) => new Date(iso + "T00:00:00Z").toLocaleDateString("en-US", { month: "long", day: "numeric", timeZone: "UTC" });
  const fmtNum = (n) => Math.round(n).toLocaleString("en-US");
  const fmtMt = (v) => v.toFixed(v < 10 ? 1 : 0);
  function setStep(i) {
    current = i;
    const s = steps[i];
    slider.value = i;
    $("date").textContent = `${fmtDate(s.start)} to ${fmtDate(s.end)}`;
    const live = {
      km2: fmtNum(s.km2),
      co2: s.co2_mt != null ? fmtMt(s.co2_mt) : "–",
      co2range: s.co2_mt ? `IPCC range ${fmtMt(s.co2_lo)} to ${fmtMt(s.co2_hi)} Mt` : "",
      cars: s.cars_m >= 0.05 ? `about what ${s.cars_m.toFixed(1)} million cars give off in a year` : "",
      cities: cityMarkers.filter((x) => x.c.aod[i] != null).sort((a, b) => b.c.aod[i] - a.c.aod[i]).slice(0, 3)
        .map((x) => `${x.name} <b>${x.c.aod[i].toFixed(1)}</b>`).join(" · ") || "no readings this step",
    };
    document.querySelectorAll("[data-live]").forEach((el) => { el.innerHTML = live[el.dataset.live] ?? ""; });
    render();
    drawChart();
  }
  let timer = null;
  const play = $("play");
  function stop() { clearInterval(timer); timer = null; play.textContent = "▶"; play.setAttribute("aria-label", "Play"); }
  function animate(from, to, ms) {
    stop();
    setStep(from);
    if (from === to) return;
    play.textContent = "❚❚"; play.setAttribute("aria-label", "Pause");
    timer = setInterval(() => { if (current >= to) { stop(); return; } setStep(current + 1); }, ms);
  }
  play.addEventListener("click", () => (timer ? stop() : animate(current === last ? 0 : current, last, 800)));
  slider.addEventListener("input", () => { stop(); setStep(+slider.value); });

  // --- Camera.
  const panelPad = () => (narrow()
    ? { paddingTopLeft: [0, 8], paddingBottomRight: [0, $("panel").offsetHeight] }
    : { paddingTopLeft: [$("panel").offsetWidth + 32, 16], paddingBottomRight: [16, 16] });
  const flyTo = (b, opts = {}) => map.flyToBounds(b, { duration: 1.2, ...panelPad(), ...opts });

  // --- Probe chart.
  let probeAt = null;
  const probe = { hv: [], hh: [], w: 0, h: 0, ready: false };
  (async () => {
    const load = (src) => new Promise((ok, fail) => { const im = new Image(); im.onload = () => ok(im); im.onerror = fail; im.src = src; });
    const read = (im) => {
      const c = document.createElement("canvas"); c.width = im.width; c.height = im.height;
      const ctx = c.getContext("2d", { willReadFrequently: true }); ctx.drawImage(im, 0, 0);
      return ctx.getImageData(0, 0, im.width, im.height).data;
    };
    try {
      for (const s of steps) {
        const [hv, hh] = await Promise.all([load(`data/probe_hv_${pad(s.step)}.png`), load(`data/probe_hh_${pad(s.step)}.png`)]);
        probe.hv.push(read(hv)); probe.hh.push(read(hh)); probe.w = hv.width; probe.h = hv.height;
      }
      probe.ready = true;
    } catch (e) { /* no probe layers: clicks do nothing */ }
  })();
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
    $("probeTitle").textContent = title || `${latlng.lat.toFixed(2)}°, ${latlng.lng.toFixed(2)}°`;
    $("probe").hidden = false;
    drawChart();
  }
  function closeProbe() { $("probe").hidden = true; marker.remove(); probeAt = null; }
  map.on("click", (e) => openProbe(e.latlng));
  $("probeClose").addEventListener("click", closeProbe);
  function drawChart() {
    if (!probeAt) return;
    const svg = $("chart");
    const W = 300, H = 130, l = 26, r = 6, t = 8, b = 22;
    const t0 = Date.parse(steps[0].start), t1 = Date.parse(steps[last].end);
    const xs = (d) => l + ((Date.parse(d) - t0) / (t1 - t0)) * (W - l - r);
    // The y axis zooms to the data so a real drop is visible; it is relative brightness, not zero-based.
    const vals = [...probeAt.hv, ...probeAt.hh].map((p) => p[1]);
    const padY = Math.max(8, (Math.max(...vals) - Math.min(...vals)) * 0.15);
    const lo = Math.max(0, Math.min(...vals) - padY), hi = Math.min(255, Math.max(...vals) + padY);
    const ys = (v) => t + (1 - (v - lo) / (hi - lo)) * (H - t - b);
    const path = (pts) => pts.map(([d, v], i) => (i ? "L" : "M") + `${xs(d)},${ys(v)}`).join("");
    const dots = (pts, cls) => pts.map(([d, v]) => `<circle class="${cls}" cx="${xs(d)}" cy="${ys(v)}" r="2"/>`).join("");
    const months = steps.map((s) => s.start.slice(0, 7)).filter((m, i, a) => a.indexOf(m) === i);
    svg.innerHTML =
      [hi, (hi + lo) / 2, lo].map((v) => `<line class="grid" x1="${l}" x2="${W - r}" y1="${ys(v)}" y2="${ys(v)}"/>`).join("") +
      `<text x="2" y="${ys(hi) + 3}">brighter</text><text x="2" y="${ys(lo)}">darker</text>` +
      months.slice(1).map((m) => `<text x="${xs(m + "-01")}" y="${H - 6}" text-anchor="middle">${new Date(m + "-15T00:00:00Z").toLocaleDateString("en-US", { month: "short", timeZone: "UTC" })}</text>`).join("") +
      `<line class="now" x1="${xs(steps[current].end)}" x2="${xs(steps[current].end)}" y1="${t}" y2="${H - b}"/>` +
      `<path class="hh" d="${path(probeAt.hh)}"/><path class="hv" d="${path(probeAt.hv)}"/>` + dots(probeAt.hh, "hh") + dots(probeAt.hv, "hv");
    const first = probeAt.hv[0][1], end = probeAt.hv[probeAt.hv.length - 1][1];
    const pct = Math.round((end - first) / first * 100);
    $("probeNote").textContent = pct <= -5
      ? `Leaf echo (HV) is ${-pct}% below June by the last look.`
      : `Leaf echo (HV) changed ${pct >= 0 ? "+" : ""}${pct}% since June: no clear canopy loss here.`;
  }
  const ketapangJump = () => {
    map.flyTo(KETAPANG, narrow() ? 9.5 : 10, { duration: 1.4 });
    map.once("moveend", () => openProbe(L.latLng(KETAPANG), "Ketapang peat dome", meta.ketapang_series));
  };

  // --- Chapters.
  const timed = fireData && fireData.timed;
  const near = timed ? Math.round(timed.loss_matched * 100) : null;
  const chance = timed ? Math.round(timed.chance_matched * 100) : null;
  const burns = timed ? Math.round(timed.burns_matched * 100) : null;
  const lastStep = steps[last];
  const keys = `<p class="keys"><span><i class="key green"></i>tree cover in June</span><span><i class="key red"></i>radar echo collapsed</span><span><i class="key grey"></i>no tree cover</span></p>`;
  const chapters = [
    {
      title: "Smoke hid Borneo's fire season",
      body: "From August to October 2026, haze from burning forest and peat covered Borneo and drifted to Singapore and Kuala Lumpur. This is what ordinary satellites see.",
      widget: `<p class="cityline" data-live="cities"></p>
        <div class="aodbar"></div>
        <div class="aodticks"><span style="left:0">0.3 clear</span><span style="left:26%">1 hazy</span><span style="left:63%">2</span><span style="right:0">3+ thick</span></div>
        <p class="hint"><i class="key nodata"></i>No reading: cloud, or smoke too thick to measure. Numbers are aerosol optical depth, how much sunlight the haze blocks (NASA VIIRS).</p>`,
      enter() { Object.assign(view, { smoke: true, fires: false, peat: false }); flyTo(region); animate(0, 8, 450); },
    },
    {
      title: "Radar sees through it",
      body: "NISAR's L-band radar passes through smoke and cloud. Its HV channel echoes off leaves and branches, so when canopy burns, the echo collapses. Red is where it did, 12 days at a time.",
      widget: `<div class="big loss" data-live="km2"></div><small>km² of tree cover lost since June</small>${keys}`,
      enter() { Object.assign(view, { smoke: false, fires: false, peat: false }); stop(); current = 0; flyTo(FIRE_ZONE); later(() => animate(0, last, 650), 1200); },
    },
    {
      title: "It lines up with fire",
      body: "Yellow dots are NASA fire detections from the last 36 days, seen by heat sensors on two other satellites. " +
        "A lost patch counts as matched when a fire lands within 1 km of it, in the weeks its canopy disappeared.",
      widget: near == null ? "" : `
        <div class="bars">
          <div class="bar"><span style="width:${near}%"></span><b>${near}%</b></div><small>of radar loss has a matching fire</small>
          <div class="bar dim"><span style="width:${chance}%"></span><b>${chance}%</b></div><small>of unburned tree cover nearby would, by chance</small>
        </div>
        <p class="hint">${Math.round(near / chance)}× chance. ${burns}% of the ${timed.burns} burns over 0.8 km² have a matching fire.</p>`,
      // Zoomed into the southwest burns, playing from August: fires move through, red follows.
      enter() { Object.assign(view, { smoke: false, fires: true, peat: false }); stop(); current = 3; flyTo(PROOF_ZONE); later(() => animate(3, last, 900), 1300); },
    },
    {
      title: "The burns released peat carbon",
      body: "Much of it burned on peat, soil built from centuries of dead plants. Dark marks burns on peat. Ketapang's peat dome is the biggest burn in West Kalimantan" +
        (meta.ketapang_km2 ? ` (${Math.round(meta.ketapang_km2)} km²)` : "") + ": its leaf echo fell steadily from August.",
      widget: `<div class="big" data-live="co2"></div><small>Mt CO₂ from burning peat, <span data-live="cars"></span></small>
        <p class="hint" data-live="co2range"></p>`,
      enter() { Object.assign(view, { smoke: false, fires: false, peat: true }); stop(); setStep(last); ketapangJump(); },
    },
  ];
  const EXPLORE = chapters.length;
  let pending = null;  // a delayed start that must not fire after the chapter changes
  function later(fn, ms) { pending = setTimeout(() => { pending = null; fn(); }, ms); }
  let chapter = -1;
  const dots = $("dots");
  dots.innerHTML = [...chapters.map((c, i) => `<button type="button" data-ch="${i}" aria-label="Chapter ${i + 1}: ${c.title}">${i + 1}</button>`),
    `<button type="button" data-ch="${EXPLORE}" class="explore-dot">Explore</button>`].join("");
  dots.addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) go(+b.dataset.ch); });

  function go(n) {
    n = Math.max(0, Math.min(EXPLORE, n));
    if (n === chapter) return;
    chapter = n;
    clearTimeout(pending);
    closeProbe();
    dots.querySelectorAll("button").forEach((b) => b.classList.toggle("on", +b.dataset.ch === n));
    const story = n < EXPLORE;
    $("chapter").hidden = !story;
    $("explore").hidden = story;
    $("prev").disabled = n === 0;
    $("next").textContent = n === EXPLORE - 1 ? "Explore the map →" : n === EXPLORE ? "Back to the start" : "Next →";
    if (story) {
      const c = chapters[n];
      $("chNo").textContent = `${n + 1} of ${chapters.length}`;
      $("chTitle").textContent = c.title;
      $("chBody").textContent = c.body;
      $("chWidget").innerHTML = c.widget;
      c.enter();
    } else {
      Object.assign(view, { smoke: false, fires: false, peat: false });  // explore starts from the plain radar view
      stop();
      setStep(last);
      flyTo(bounds);
    }
    setStep(current);
    $("panel").scrollTop = 0;
  }
  $("prev").addEventListener("click", () => go(chapter - 1));
  $("next").addEventListener("click", () => go(chapter === EXPLORE ? 0 : chapter + 1));
  document.addEventListener("keydown", (e) => {
    if (e.target.matches("input, textarea")) return;
    if (e.key === "ArrowRight" || e.key === "PageDown") go(chapter === EXPLORE ? EXPLORE : chapter + 1);
    if (e.key === "ArrowLeft" || e.key === "PageUp") go(chapter - 1);
  });

  // Explore controls.
  $("tPeat").addEventListener("change", (e) => { view.peat = e.target.checked; render(); });
  $("tFires").addEventListener("change", (e) => { view.fires = e.target.checked; render(); });
  $("tSmoke").addEventListener("change", (e) => { view.smoke = e.target.checked; render(); flyTo(view.smoke ? region : bounds); });
  document.querySelectorAll("[data-jump]").forEach((b) => b.addEventListener("click", () => { stop(); setStep(last); ketapangJump(); }));

  map.fitBounds(region, panelPad());
  glow();
  go(0);
})();
