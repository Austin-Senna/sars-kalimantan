// Borneo through the smoke: a four-chapter story over precomputed NISAR, FIRMS, VIIRS and peat layers in data/,
// then a free Explore mode. Everything is static: no network calls beyond these files.
(async function () {
  const meta = await (await fetch("data/steps.json", { cache: "no-cache" })).json();
  let fireData = null;
  try { fireData = await (await fetch("data/firms.json", { cache: "no-cache" })).json(); } catch (e) { /* fires chapter shows no dots */ }
  let optical = null;
  try { optical = await (await fetch("data/optical.json", { cache: "no-cache" })).json(); } catch (e) { /* no optical line */ }
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
    "Smoke: NASA VIIRS Deep Blue AOD · CO: NASA AIRS · Optical: NASA OPERA · Basemap: NASA Blue Marble (GIBS) · Peat: Peat-ML");
  const pane = (name, z) => { const p = map.createPane(name); p.style.zIndex = z; return p; };
  pane("radar", 402); pane("peat", 405); pane("fires", 410); pane("loss", 420); pane("peatburn", 425);
  pane("smoke", 430); pane("probe", 600);
  const pad = (n) => String(n).padStart(2, "0");

  L.imageOverlay(meta.smoke ? "data/basemap_region.jpg" : "data/basemap.jpg", meta.smoke ? region : bounds, { opacity: 0.5, className: "feather" }).addTo(map);
  L.imageOverlay("data/base_hv.png", bounds, { pane: "radar", className: "pixelated fadetop" }).addTo(map);
  L.imageOverlay("data/peat.png", bounds, { pane: "peat" }).addTo(map);  // smoothed: the peat map's 9 km cells read as blocks otherwise
  // One overlay per step for each time layer, all preloaded; only the current step is visible.
  // One retry with a cache-buster if an image fails (a busy CDN can answer 503 once); otherwise a step stays blank.
  const retry = (o) => o.once("error", () => setTimeout(() => o.setUrl(`${o._url.split("?")[0]}?r=${Date.now()}`), 1500));
  const perStep = (prefix, b, p, cls) => steps.map((s) => { const o = L.imageOverlay(`data/${prefix}_${pad(s.step)}.png`, b, { opacity: 0, pane: p, className: cls }); retry(o); return o.addTo(map); });
  const loss = perStep("loss", bounds, "loss", "pixelated");
  const peatburn = perStep("peatburn", bounds, "peatburn", "pixelated");
  const smoke = meta.smoke ? perStep("smoke", region, "smoke", "feather") : [];
  const coLayers = meta.co ? perStep("co", region, "smoke", "feather") : [];  // fire gas shares the smoke view
  // Every fire detection, drawn per step as an image (36 days up to that step; bright next to an appeared burn).
  const fireLayers = perStep("fires", bounds, "fires", "fires");
  const cities = L.layerGroup().addTo(map);
  const cityMarkers = meta.smoke ? Object.entries(meta.smoke.cities).map(([name, c]) =>
    ({ name, c, m: L.marker(c.latlon, { interactive: false, icon: L.divIcon({ className: "city", iconSize: null }) }).addTo(cities) })) : [];
  const marker = L.circleMarker([0, 0], { radius: 10, color: "#fff", weight: 2.5, fill: false, pane: "probe", renderer: L.svg({ pane: "probe" }) });

  // Burns are a few pixels wide at island zoom: give the loss pane a glow when zoomed out.
  const glow = () => { const z = map.getZoom() < 8; map.getPane("loss").classList.toggle("glow", z); map.getPane("fires").classList.toggle("glow", z); };
  map.on("zoomend", glow);

  // --- State: which layers show, and the current 12-day step.
  const view = { smoke: false, fires: false, peat: false, gas: "aod" };  // gas: what the smoke view shows, haze or CO
  // One reading per city per step, for whichever the smoke view shows.
  const reading = (name, i) => view.gas === "co" ? meta.co.cities[name].ppbv[i] : meta.smoke.cities[name].aod[i];
  const level = (v) => v == null ? "none" : view.gas === "co"
    ? (v >= 200 ? "thick" : v >= 110 ? "hazy" : "clear")   // CO: June is about 80 ppbv
    : (v >= 2 ? "thick" : v >= 0.3 ? "hazy" : "clear");    // haze: matches the scale bar
  const fmtReading = (v) => v == null ? "no reading" : view.gas === "co" ? (narrow() ? `${v}` : `${v} ppb`) : v.toFixed(1);
  let current = 0;
  function render() {
    const show = (el, on, o = 1) => { el.style.opacity = on ? o : 0; };
    show(map.getPane("smoke"), view.smoke);
    show(map.getPane("radar"), !view.smoke, 0.92);
    show(map.getPane("loss"), !view.smoke);
    show(map.getPane("fires"), view.fires && !view.smoke, 1);
    show(map.getPane("peat"), view.peat && !view.smoke);
    show(map.getPane("peatburn"), view.peat && !view.smoke);
    loss.forEach((o, j) => o.setOpacity(j === current ? 1 : 0));
    peatburn.forEach((o, j) => o.setOpacity(j === current ? 1 : 0));
    smoke.forEach((o, j) => o.setOpacity(view.gas === "aod" && j === current ? 1 : 0));
    coLayers.forEach((o, j) => o.setOpacity(view.gas === "co" && j === current ? 1 : 0));
    fireLayers.forEach((o, j) => o.setOpacity(j === current ? 1 : 0));
    view.smoke ? cities.addTo(map) : cities.remove();
    for (const { name, m } of cityMarkers) {
      const v = reading(name, current);
      m.setIcon(L.divIcon({ className: `city ${level(v)} city-${name.replace(/\W/g, "")}`, iconSize: null, html: `<b>${name}</b> ${fmtReading(v)}` }));
    }
    document.querySelectorAll("[data-gas]").forEach((b) => b.classList.toggle("on", b.dataset.gas === view.gas));
    document.querySelectorAll(".gas-aod").forEach((el) => { el.hidden = view.gas !== "aod"; });
    document.querySelectorAll(".gas-co").forEach((el) => { el.hidden = view.gas !== "co"; });
    $("tPeat").checked = view.peat; $("tFires").checked = view.fires;
    $("tSmoke").checked = view.smoke && view.gas === "aod"; $("tCO").checked = view.smoke && view.gas === "co";
    $("tPeat").disabled = $("tFires").disabled = view.smoke;  // hidden under the smoke anyway
    $("smokeHides").hidden = !view.smoke;
    $("smokeHides").textContent = `${view.gas === "co" ? "Fire gas" : "Smoke"} is on: the radar layers are hidden under it.`;
    $("exploreScales").hidden = !view.smoke;
  }

  // --- Time.
  const slider = $("slider");
  slider.max = last;
  const fmtDate = (iso) => new Date(iso + "T00:00:00Z").toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
  const fmtNum = (n) => Math.round(n).toLocaleString("en-US");
  const fmtMt = (v) => v.toFixed(v < 10 ? 1 : 0);
  function setStep(i) {
    current = i;
    const s = steps[i];
    slider.value = i;
    const sm = s.start.slice(5, 7) === s.end.slice(5, 7);
    $("date").textContent = sm ? `${fmtDate(s.start)}–${Number(s.end.slice(8))}, 2026` : `${fmtDate(s.start)} – ${fmtDate(s.end)}, 2026`;
    const live = {
      km2: fmtNum(s.km2),
      co2: s.co2_mt != null ? fmtMt(s.co2_mt) : "–",
      co2range: s.co2_mt ? `range ${fmtMt(s.co2_lo)} to ${fmtMt(s.co2_hi)} Mt, from the IPCC uncertainty in how much peat burns` : "",
      co2short: s.co2_mt ? `${fmtMt(s.co2_lo)} to ${fmtMt(s.co2_hi)}` : "",
      cars: s.cars_m >= 0.05 ? `like ${s.cars_m.toFixed(1)} million cars for a year` : "",
      cities: cityMarkers.filter((x) => reading(x.name, i) != null).sort((a, b) => reading(b.name, i) - reading(a.name, i)).slice(0, 3)
        .map((x, j) => `<span class="cv">${j ? "· " : ""}${x.name} <b>${fmtReading(reading(x.name, i))}</b></span>`).join(" ") || "no readings this step",
    };
    document.querySelectorAll("[data-live]").forEach((el) => { el.innerHTML = live[el.dataset.live] ?? ""; });
    render();
    drawChart();
  }
  let timer = null;
  let pending = null;  // a delayed start: cancelled by a chapter change, the slider or play
  function later(fn, ms) { pending = setTimeout(() => { pending = null; fn(); }, ms); }
  const play = $("play");
  function stop() { clearTimeout(pending); pending = null; clearInterval(timer); timer = null; play.textContent = "▶"; play.setAttribute("aria-label", "Play"); }
  function animate(from, to, ms) {
    stop();
    setStep(from);
    if (from === to) return;
    play.textContent = "❚❚"; play.setAttribute("aria-label", "Pause");
    timer = setInterval(() => { if (current >= to) { stop(); return; } setStep(current + 1); }, ms);
  }
  play.addEventListener("click", () => (timer ? stop() : animate(current === last ? 0 : current, last, 800)));
  slider.addEventListener("input", () => { stop(); setStep(+slider.value); });
  slider.addEventListener("change", () => slider.blur());  // arrow keys go back to stepping chapters

  // --- Camera.
  const panelPad = () => (narrow()
    ? { paddingTopLeft: [0, 8], paddingBottomRight: [0, $("panel").offsetHeight] }
    : { paddingTopLeft: [$("panel").offsetWidth + 32, 16], paddingBottomRight: [16, 16] });
  const flyTo = (b, opts = {}) => map.flyToBounds(b, { duration: 1.2, ...panelPad(), ...opts });

  // --- Probe chart.
  let probeAt = null;
  const probe = { hv: [], hh: [], forest: null, loss: null, w: 0, h: 0, ready: false };
  let probeStarted = false;
  async function loadProbe() {  // 24 history images (27 MB): fetched on first use, not at startup
    if (probeStarted) return; probeStarted = true;
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
      probe.forest = read(await load("data/probe_forest.png"));
      probe.loss = read(await load("data/probe_loss.png"));
      probe.ready = true;
    } catch (e) { probeStarted = false; /* a failed image: the next click tries again */ }
  }
  function sampleAt(latlng) {
    const x = Math.floor((latlng.lng - bounds.getWest()) / (bounds.getEast() - bounds.getWest()) * probe.w);
    const y = Math.floor((bounds.getNorth() - latlng.lat) / (bounds.getNorth() - bounds.getSouth()) * probe.h);
    if (x < 0 || y < 0 || x >= probe.w || y >= probe.h) return { none: true, outside: true };
    const k = (y * probe.w + x) * 4;
    if (!probe.forest[k]) return { none: true };  // sea, towns, farms: no tree cover to follow
    const mid = (s) => new Date(Date.parse(s.start) + 6 * 864e5).toISOString().slice(0, 10);
    const v = (arr) => arr.map((d, i) => (d[k + 3] ? [mid(steps[i]), d[k]] : null)).filter(Boolean);
    const reach = map.getZoom() < 8 ? 1 : 0;
    let flagged = false;
    for (let dy = -reach; dy <= reach; dy++) for (let dx = -reach; dx <= reach; dx++) {
      const yy = y + dy, xx = x + dx;
      if (yy >= 0 && xx >= 0 && yy < probe.h && xx < probe.w && probe.loss[(yy * probe.w + xx) * 4] > 0) flagged = true;
    }
    return { hv: v(probe.hv), hh: v(probe.hh), flagged };
  }
  async function openProbe(latlng, title, series, quiet) {
    if (!series && !probe.ready) { $("probe").hidden = false; $("probeTitle").textContent = "Loading radar history…"; $("chart").innerHTML = ""; $("probeNote").textContent = ""; await loadProbe(); }
    const s = series || (probe.ready ? sampleAt(latlng) : null);
    if (s && s.none) {
      marker.remove(); probeAt = null;
      $("probe").hidden = false;
      $("probeTitle").textContent = s.outside ? "Outside the radar map" : "No tree cover here";
      $("chart").innerHTML = ""; $("probeNote").textContent = "Click green tree cover or a red burn to see its radar history.";
      showProbe();
      return;
    }
    if (!s || !s.hv.length) return;
    probeAt = s;
    marker.setLatLng(latlng).addTo(map);
    const ns = (v, p, m) => `${Math.abs(v).toFixed(1)}° ${v >= 0 ? p : m}`;
    $("probeTitle").textContent = title || `This spot (${ns(latlng.lat, "N", "S")}, ${ns(latlng.lng, "E", "W")})`;
    drawChart();
    if (quiet) $("probe").hidden = false; else showProbe();  // in a story chapter, keep the chapter's headline on screen
  }
  // Bring the chart fully into view above the sticky dock, at every width.
  function showProbe() {
    const el = $("probe");
    el.hidden = false;
    el.style.scrollMarginBottom = `${document.querySelector(".dock").offsetHeight + 12}px`;
    requestAnimationFrame(() => el.scrollIntoView({ behavior: "smooth", block: "nearest" }));
  }
  function closeProbe() { $("probe").hidden = true; marker.remove(); probeAt = null; }
  map.on("click", (e) => {
    if (!view.smoke) { openProbe(e.latlng); return; }
    marker.remove(); probeAt = null; $("chart").innerHTML = "";
    $("probeTitle").textContent = "Radar hidden under smoke"; $("probeNote").textContent = "Turn smoke off to see a spot's radar history.";
    showProbe();
  });
  $("probeClose").addEventListener("click", closeProbe);
  function drawChart() {
    if (!probeAt) return;
    const svg = $("chart");
    const W = 300, H = 100, l = 30, r = 6, t = 6, b = 18;  // wide and short: fits under the chapter text
    const t0 = Date.parse(steps[0].start), t1 = Date.parse(steps[last].end);
    const xs = (d) => l + ((Date.parse(d) - t0) / (t1 - t0)) * (W - l - r);
    // Each line in % change from its own first (June) value. The axis spans at least -25% to +25% so ordinary
    // noise stays small; 0% is marked.
    const rel = (pts) => pts.map(([d, v]) => [d, (v - pts[0][1]) / pts[0][1] * 100]);
    const hv = rel(probeAt.hv), hh = rel(probeAt.hh);
    const vals = [...hv, ...hh].map((p) => p[1]);
    const lo = Math.min(-25, Math.floor(Math.min(...vals) / 5) * 5 - 5), hi = Math.max(5, Math.ceil(Math.max(...vals) / 5) * 5);
    const ys = (v) => t + (1 - (v - lo) / (hi - lo)) * (H - t - b);
    const path = (pts) => pts.map(([d, v], i) => (i ? "L" : "M") + `${xs(d)},${ys(v)}`).join("");
    const dots = (pts, cls) => pts.map(([d, v]) => `<circle class="${cls}" cx="${xs(d)}" cy="${ys(v)}" r="2"/>`).join("");
    const months = steps.map((s) => s.start.slice(0, 7)).filter((m, i, a) => a.indexOf(m) === i);
    const lastLook = probeAt.hv[probeAt.hv.length - 1][0];
    const now = steps[current].end < lastLook ? steps[current].end : lastLook;  // never past the last radar look
    const ticks = [hi, 0, lo];
    svg.innerHTML =
      ticks.map((v) => `<line class="${v === 0 ? "zero" : "grid"}" x1="${l}" x2="${W - r}" y1="${ys(v)}" y2="${ys(v)}"/>` +
        `<text x="${l - 3}" y="${ys(v) + 3}" text-anchor="end">${v > 0 ? "+" : ""}${v}%</text>`).join("") +
      months.slice(1).map((m) => `<text x="${xs(m + "-01")}" y="${H - 6}" text-anchor="middle">${new Date(m + "-15T00:00:00Z").toLocaleDateString("en-US", { month: "short", timeZone: "UTC" })}</text>`).join("") +
      `<line class="now" x1="${xs(now)}" x2="${xs(now)}" y1="${t}" y2="${H - b}"/>` +
      `<text x="${l + 4}" y="${t + 8}">change since June</text>` +
      `<path class="hh" d="${path(hh)}"/><path class="hv" d="${path(hv)}"/>` + dots(hh, "hh") + dots(hv, "hv");
    // The verdict follows the loss map, so the chart never contradicts the red; the % is context.
    const upto = hv.filter(([d]) => d <= now);
    const pct = Math.round((upto.length ? upto[upto.length - 1] : hv[0])[1]);
    const flagged = probeAt.flagged !== false;  // Ketapang's series is a flagged burn
    const sign = `${pct >= 0 ? "+" : ""}${pct}%`;
    $("probeNote").textContent = flagged
      ? `Radar flagged this spot as lost. Leaf echo ${sign} since June.`
      : `Not flagged as lost. Leaf echo ${sign} since June` +
        (pct >= 30 ? ": a rise like this is usually wet ground or radar noise." :
         pct <= -10 ? ": a drop, but not deep or lasting enough to flag." : ", normal variation.");
  }
  let arrive = null;  // the chart opening on arrival at Ketapang; cancelled when the chapter changes mid-flight
  const ketapangJump = () => {
    const [la, lo] = KETAPANG;
    flyTo(L.latLngBounds([[la - 0.25, lo - 0.3], [la + 0.25, lo + 0.3]]), { duration: 1.4 });  // centred in the visible map
    if (arrive) map.off("moveend", arrive);
    arrive = () => { arrive = null; openProbe(L.latLng(KETAPANG), "Ketapang peat dome", meta.ketapang_series, chapter < EXPLORE);
    if (chapter < EXPLORE && narrow()) document.querySelector("#chWidget .big")?.scrollIntoView({ behavior: "smooth", block: "start" }); };
    map.once("moveend", arrive);
  };

  // --- Chapters.
  const timed = fireData && fireData.timed;
  const near = timed ? Math.round(timed.loss_matched * 100) : null;
  const chance = timed ? Math.round(timed.chance_matched * 100) : null;
  const burns = timed ? Math.round(timed.burns_matched * 100) : null;
  const lastStep = steps[last];
  const confirmed = optical && optical.loss_fire_or_optical != null ? Math.round(optical.loss_fire_or_optical * 10) : null;
  const peatShare = lastStep.peat_km2 ? Math.round(lastStep.km2 / lastStep.peat_km2) : null;
  const keys = `<p class="keys"><span><i class="key green"></i>tree cover in June</span><span><i class="key red"></i>lost (radar)</span><span><i class="key grey"></i>no tree cover</span></p>`;
  const optPct = optical ? Math.round(optical.loss_confirmed * 100) : null;
  const optChance = optical ? Math.round(optical.chance_confirmed * 100) : null;
  const chapters = [
    {
      title: "Smoke hid the fire season",
      body: `<span class="gas-aod">Aug to Oct 2026: haze from burning forest and peat covered Borneo and reached Singapore. This is what normal satellites saw.</span>` +
        `<span class="gas-co" hidden>Fire gas: carbon monoxide from the burning, measured by NASA's AIRS even through haze. By late October it was about 4 times its June level at every city.</span>`,
      widget: (meta.co ? `<div class="seg"><button type="button" data-gas="aod">Haze</button><button type="button" data-gas="co">Fire gas (CO)</button></div>` : "") +
        `<p class="cityline" data-live="cities"></p>
        <div class="gas-co" hidden><div class="cobar"></div>
          <div class="aodticks"><span style="left:0">80 June</span><span style="left:45%">200</span><span style="right:0">330+ ppb</span></div>
          <p class="hint">Carbon monoxide in parts per billion, 5 km up (NASA AIRS). Smouldering peat makes the most of it.</p></div>
        <div class="gas-aod"><div class="aodbar"></div>
        <div class="aodticks"><span style="left:0">clear</span><span style="left:26%">1 very hazy</span><span style="left:63%">2</span><span style="right:0">3+ smoke</span></div>
        <p class="hint">Haze level (aerosol optical depth): under 0.1 is a clear sky, 1 is very hazy (NASA Earth Observatory). <i class="key nodata"></i>Striped: no reading.</p></div>`,
      enter() { Object.assign(view, { smoke: true, fires: false, peat: false }); flyTo(narrow() ? region : region.pad(-0.08)); animate(4, last - 1, 420); },  // from late July: June is mostly cloud with no reading
    },
    {
      title: "Radar sees through it",
      body: "NISAR's radar passes through smoke. When the canopy burns, its echo collapses. Red is where it did.",
      widget: `<div class="big loss" data-live="km2"></div><small>km² of tree cover lost since June</small>${keys}` +
        (confirmed ? `<p class="confirm"><b>${confirmed} in 10</b> confirmed by other NASA satellites.</p>` : ""),
      enter() { Object.assign(view, { smoke: false, fires: false, peat: false }); stop(); current = 0; flyTo(narrow() ? FIRE_ZONE.pad(0.12) : FIRE_ZONE); later(() => animate(0, last, 650), 1200); },
    },
    {
      title: "It lines up with fire",
      body: "The glow is NASA fire detections from the 36 days up to the slider date. Bright yellow sits right next to a radar burn.",
      widget: near == null ? "" : `
        <div class="headline"><span class="big">${Math.round(near / chance)}×</span><span>more fire than chance</span></div>
        <div class="bars two">
          <div><div class="bar"><span style="width:${near}%"></span><b>${near}%</b></div><small>of radar loss had a fire within 1 km</small></div>
          <div><div class="bar dim"><span style="width:${chance}%"></span><b>${chance}%</b></div><small>of unburned tree cover nearby</small></div>
        </div>
        <p class="keys"><span><i class="key fire"></i>fire next to a burn</span><span><i class="key firefaint"></i>other fire</span></p>` +
        (optical ? `<p class="second">Optical satellites agree: <b>${optPct}%</b> vs <b>${optChance}%</b> by chance.</p>` : ""),
      enter() { Object.assign(view, { smoke: false, fires: true, peat: false }); stop(); current = 3; flyTo(PROOF_ZONE); later(() => animate(3, last, 900), 1300); },
    },
    {
      title: "The cost: peat carbon",
      body: (peatShare ? `1 in ${peatShare} lost km² was peat: centuries of stored carbon. ` : "") +
        "Ketapang's peat dome is West Kalimantan's biggest burn.",
      // Two honest ends: the floor counts only peat loss a second NASA source confirmed; the top counts all radar loss.
      widget: (optical && optical.confirmed_co2_mt
        ? `<div class="big">${Math.floor(optical.confirmed_co2_mt[0])}–${Math.round(lastStep.co2_mt)}</div><small>million tonnes of CO₂ (low end: confirmed by a second satellite; high end: all radar loss on peat).<span class="carline"> Like ${Math.round(Math.floor(optical.confirmed_co2_mt[0]) / 4.6)}–${Math.round(lastStep.cars_m)} million cars for a year.</span></small>`
        : `<div class="big" data-live="co2"></div><small>million tonnes of CO₂ (estimate, <span data-live="co2short"></span>): <span data-live="cars"></span></small>`) + `
        <p class="keys"><span><i class="key peat"></i>peat</span><span><i class="key peatburn"></i>burned peat</span><span><i class="key red"></i>other burns</span></p>`,
      enter() { Object.assign(view, { smoke: false, fires: false, peat: true }); stop(); setStep(last); ketapangJump(); },
    },
  ];
  const EXPLORE = chapters.length;
  let chapter = -1;
  const dots = $("dots");
  dots.innerHTML = [...chapters.map((c, i) => `<button type="button" data-ch="${i}" aria-label="Chapter ${i + 1}: ${c.title}">${i + 1}</button>`),
    `<button type="button" data-ch="${EXPLORE}" class="explore-dot">Explore</button>`].join("");
  dots.addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) go(+b.dataset.ch); });

  function go(n) {
    n = Math.max(0, Math.min(EXPLORE, n));
    if (n === chapter) return;
    chapter = n;
    stop();
    if (arrive) { map.off("moveend", arrive); arrive = null; }
    closeProbe();
    dots.querySelectorAll("button").forEach((b) => b.classList.toggle("on", +b.dataset.ch === n));
    const story = n < EXPLORE;
    $("chapter").hidden = !story;
    $("explore").hidden = story;
    document.querySelector(".limits").hidden = story;
    $("prev").disabled = n === 0;
    $("next").textContent = n === EXPLORE - 1 ? "Explore the map →" : n === EXPLORE ? "Back to the start" : "Next →";
    if (story) {
      const c = chapters[n];
      $("chNo").textContent = `${n + 1} of ${chapters.length}`;
      $("chTitle").textContent = c.title;
      $("chBody").innerHTML = c.body;  // chapter text is ours, not user input
      $("chWidget").innerHTML = c.widget;
      c.enter();
    } else {
      Object.assign(view, { smoke: false, fires: false, peat: false, gas: "aod" });  // explore starts from the plain radar view
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
    const fwd = e.key === "PageDown" || (e.key === "ArrowRight" && !e.target.matches("input[type=range]"));
    const back = e.key === "PageUp" || (e.key === "ArrowLeft" && !e.target.matches("input[type=range]"));
    if (!fwd && !back) return;
    e.preventDefault();
    if (document.activeElement && document.activeElement !== document.body) document.activeElement.blur();
    go(fwd ? chapter + 1 : chapter - 1);
  });

  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-gas]");
    if (!b) return;
    view.gas = b.dataset.gas;
    stop();
    // October is near the top of the CO scale everywhere; mid-September shows the plume's shape.
    setStep(view.gas === "co" && chapter === 0 ? 7 : current);
  });

  // Explore controls.
  $("tPeat").addEventListener("change", (e) => { view.peat = e.target.checked; render(); });
  $("tFires").addEventListener("change", (e) => { view.fires = e.target.checked; render(); });
  const smokeToggle = (gas) => (e) => {
    const was = view.smoke;
    view.smoke = e.target.checked; if (view.smoke) view.gas = gas;
    setStep(current);
    if (view.smoke && !was) { closeProbe(); flyTo(region); }
    if (!view.smoke && was) flyTo(bounds);  // back to the island the radar covers
  };
  $("tSmoke").addEventListener("change", smokeToggle("aod"));
  $("tCO").addEventListener("change", smokeToggle("co"));
  document.querySelectorAll("[data-jump]").forEach((b) => b.addEventListener("click", () => { stop(); Object.assign(view, { peat: true, smoke: false }); setStep(last); ketapangJump(); }));

  map.fitBounds(region, panelPad());
  glow();
  go(0);
})();
