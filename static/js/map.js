/* Outbreak map: district choropleth with alert markers (Leaflet). */
(function () {
  "use strict";
  var cfg = window.RW_MAP;
  var COLORS = ["#eaf2fb", "#c3dbf3", "#8fbbe8", "#5b97d8", "#2a6fbf", "#12437f"];
  var NO_DATA = "#f3f4f6";

  var map = L.map("rwMap", { zoomControl: true, scrollWheelZoom: false, minZoom: 7, maxZoom: 12, zoomSnap: 0.25 });
  map.setView([-1.94, 29.9], 8.25);
  map.on("click", function () { map.scrollWheelZoom.enable(); });

  var streets = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "&copy; OpenStreetMap contributors", opacity: 0.55
  });

  var state = { data: null, byName: {}, metric: "total", geo: null, geoJson: null, markers: L.layerGroup(), labels: L.layerGroup(), thresholds: [] };

  function esc(s) { var d = document.createElement("div"); d.textContent = s == null ? "" : s; return d.innerHTML; }

  function valueOf(d) { return d ? d[state.metric] || 0 : 0; }

  function buildThresholds() {
    var max = 0;
    state.data.districts.forEach(function (d) { max = Math.max(max, valueOf(d)); });
    if (max <= 0) { state.thresholds = [1, 2, 3, 4, 5]; return; }
    var t = [];
    for (var i = 1; i <= 5; i++) { t.push(Math.max(i, Math.round(max * Math.pow(i / 6, 1.35)))); }
    state.thresholds = t.filter(function (v, i, a) { return i === 0 || v > a[i - 1]; });
  }

  function colorFor(v) {
    if (v <= 0) return NO_DATA;
    var i = 0;
    while (i < state.thresholds.length && v > state.thresholds[i]) i++;
    return COLORS[Math.min(i + 1, COLORS.length - 1)];
  }

  function styleFor(feature) {
    var d = state.byName[feature.properties.name];
    var level = d ? d.level : "normal";
    var base = { fillColor: colorFor(valueOf(d)), fillOpacity: 0.92, weight: 1, color: "#ffffff", opacity: 1 };
    if (level === "alert") { base.color = "#c23b3b"; base.weight = 2.6; }
    else if (level === "watch") { base.color = "#e0a100"; base.weight = 2.2; }
    return base;
  }

  /* ---------- hover card ---------- */
  var info = L.control({ position: "topright" });
  info.onAdd = function () { this._div = L.DomUtil.create("div", "rw-info"); this.update(); return this._div; };
  info.update = function (d) {
    if (!d) { this._div.innerHTML = "<h6>Rwanda</h6><div class='sub'>Hover over a district</div><div class='row-kv'><span>Total cases</span><b>" + state.data.total_cases + "</b></div>"; return; }
    var html = "<h6>" + esc(d.name) + "</h6><div class='sub'>" + esc(d.province) + "</div>" +
      "<div class='row-kv'><span>Total cases</span><b>" + d.total + "</b></div>" +
      "<div class='row-kv'><span>Active</span><b>" + d.active + "</b></div>" +
      "<div class='row-kv'><span>Deaths</span><b>" + d.deceased + "</b></div>";
    if (d.alerts.length) {
      html += "<div class='mini'>";
      d.alerts.forEach(function (a) {
        html += "<div><b>" + (a.level === "alert" ? "Alert" : "Watch") + ":</b> " + esc(a.disease) + " (" + a.current + " this week)</div>";
      });
      html += "</div>";
    }
    if (d.top_diseases.length) {
      var top = d.top_diseases[0].cases || 1;
      html += "<div class='mini'>";
      d.top_diseases.slice(0, 3).forEach(function (t) {
        html += "<div>" + esc(t.disease) + " <span style='float:right'>" + t.cases + "</span></div><div class='mini-bar' style='width:" + Math.round(100 * t.cases / top) + "%'></div>";
      });
      html += "</div>";
    }
    this._div.innerHTML = html;
  };

  /* ---------- legend ---------- */
  var legend = L.control({ position: "bottomright" });
  legend.onAdd = function () { this._div = L.DomUtil.create("div", "rw-legend"); return this._div; };
  legend.refresh = function () {
    var names = { total: "All cases", active: "Active cases", deceased: "Deaths" };
    var html = "<div class='title'>" + names[state.metric] + "</div>";
    html += "<div><span class='swatch' style='background:" + NO_DATA + "'></span>None</div>";
    var prev = 1;
    state.thresholds.forEach(function (t, i) {
      html += "<div><span class='swatch' style='background:" + COLORS[i + 1 > 5 ? 5 : i + 1] + "'></span>" + (prev === t ? t : prev + " to " + t) + "</div>";
      prev = t + 1;
    });
    html += "<div><span class='swatch' style='background:" + COLORS[5] + "'></span>" + prev + "+</div>";
    html += "<hr class='my-1'><div><span class='swatch' style='background:#fff;border:2px solid #c23b3b'></span>Alert</div>" +
            "<div><span class='swatch' style='background:#fff;border:2px solid #e0a100'></span>Watch</div>";
    this._div.innerHTML = html;
  };

  /* ---------- title + street toggle ---------- */
  var title = L.control({ position: "topleft" });
  title.onAdd = function () {
    var div = L.DomUtil.create("div", "rw-title");
    div.innerHTML = "<h6>Rwanda disease map</h6><small>30 districts</small>";
    return div;
  };
  var toggle = L.control({ position: "bottomleft" });
  toggle.onAdd = function () {
    var div = L.DomUtil.create("div", "rw-toggle");
    div.innerHTML = "<label class='mb-0'><input type='checkbox' id='streetToggle'> Show streets</label>";
    L.DomEvent.disableClickPropagation(div);
    return div;
  };

  /* ---------- layers ---------- */
  function onEach(feature, layer) {
    var d = state.byName[feature.properties.name];
    layer.on({
      mouseover: function (e) {
        e.target.setStyle({ weight: 3.2, color: "#0e2a47" });
        e.target.bringToFront();
        info.update(d);
      },
      mouseout: function (e) { state.geoJson.resetStyle(e.target); info.update(); },
      click: function () { if (d) window.location.href = d.url; }
    });
    layer.bindTooltip(feature.properties.name, { permanent: true, direction: "center", offset: [0, 11], className: "rw-label", opacity: 1 });
  }

  function updateLabels() {
    if (!state.geoJson) return;
    state.geoJson.eachLayer(function (layer) {
      var b = layer.getBounds();
      var sw = map.latLngToContainerPoint(b.getSouthWest());
      var ne = map.latLngToContainerPoint(b.getNorthEast());
      var w = Math.abs(ne.x - sw.x), h = Math.abs(ne.y - sw.y);
      var fits = w > 58 && h > 26;
      if (fits) {
        layer.openTooltip();
        var tip = layer.getTooltip(), el = tip && tip.getElement();
        if (el) {
          var dark = COLORS.indexOf(layer.options.fillColor) >= 3;
          el.classList.toggle("on-dark", dark);
        }
      } else { layer.closeTooltip(); }
    });
  }

  function drawMarkers() {
    state.markers.clearLayers();
    state.data.districts.forEach(function (d) {
      if (d.level === "normal") return;
      var icon = L.divIcon({ className: "", html: "<div class='rw-pulse " + (d.level === "watch" ? "watch" : "") + "'><span></span></div>", iconSize: [18, 18] });
      L.marker([d.latitude, d.longitude], { icon: icon, keyboard: false, title: d.name + " " + d.level }).on("click", function () { window.location.href = d.url; }).addTo(state.markers);
    });
  }

  function sidePanels() {
    var sig = document.getElementById("signalList");
    var items = [];
    state.data.districts.forEach(function (d) {
      d.alerts.forEach(function (a) { items.push({ d: d, a: a }); });
    });
    items.sort(function (x, y) { return (y.a.level === "alert") - (x.a.level === "alert") || y.a.current - x.a.current; });
    if (!items.length) {
      sig.innerHTML = "<p class='text-secondary small m-2'>No signals for this selection.</p>";
    } else {
      sig.innerHTML = items.map(function (it) {
        var cls = it.a.level === "alert" ? "danger" : "warning";
        var icon = it.a.level === "alert" ? "bi-exclamation-octagon-fill" : "bi-eye-fill";
        return "<a class='d-flex align-items-start gap-2 p-2 rounded text-decoration-none text-reset signal-row' href='" + it.d.url + "'>" +
          "<i class='bi " + icon + " text-" + cls + " mt-1'></i><div><div class='fw-semibold'>" + esc(it.d.name) + "</div>" +
          "<div class='small text-secondary'>" + esc(it.a.disease) + ": " + it.a.current + " this week, usual " + it.a.baseline.toFixed(1) + "</div></div></a>";
      }).join("");
    }
    var top = state.data.districts.slice().sort(function (a, b) { return valueOf(b) - valueOf(a); }).slice(0, 8);
    var max = valueOf(top[0]) || 1;
    document.getElementById("topList").innerHTML = top.map(function (d, i) {
      return "<div class='top-row'><div class='d-flex justify-content-between small'><a href='" + d.url + "' class='text-reset text-decoration-none'>" +
        (i + 1) + ". " + esc(d.name) + "</a><b>" + valueOf(d) + "</b></div>" +
        "<div class='progress' style='height:6px'><div class='progress-bar' style='width:" + Math.round(100 * valueOf(d) / max) + "%;background:#2a6fbf'></div></div></div>";
    }).join("");
  }

  function refresh() {
    buildThresholds();
    if (state.geoJson) { state.geoJson.setStyle(styleFor); updateLabels(); }
    legend.refresh();
    info.update();
    sidePanels();
  }

  function load() {
    var q = window.location.search;
    Promise.all([
      fetch(cfg.dataUrl + q, { credentials: "same-origin" }).then(function (r) { return r.json(); }),
      fetch(cfg.geoUrl).then(function (r) { return r.json(); })
    ]).then(function (res) {
      state.data = res[0];
      state.data.districts.forEach(function (d) { state.byName[d.name] = d; });
      buildThresholds();
      title.addTo(map); toggle.addTo(map); info.addTo(map); legend.addTo(map);
      state.geoJson = L.geoJSON(res[1], { style: styleFor, onEachFeature: onEach }).addTo(map);
      map.fitBounds(state.geoJson.getBounds(), { padding: [10, 10] });
      state.markers.addTo(map);
      drawMarkers();
      map.on("zoomend moveend", updateLabels);
      updateLabels();
      legend.refresh();
      sidePanels();
      var st = document.getElementById("streetToggle");
      st.addEventListener("change", function () {
        if (st.checked) { streets.addTo(map); streets.bringToBack(); } else { map.removeLayer(streets); }
      });
    }).catch(function () {
      document.getElementById("signalList").innerHTML = "<p class='text-danger small m-2'>The map data could not be loaded.</p>";
    });
  }

  /* keep the filter inputs in sync with the URL */
  var params = new URLSearchParams(window.location.search);
  ["date_from", "date_to"].forEach(function (k) {
    var el = document.querySelector("[name=" + k + "]");
    if (el && params.get(k)) el.value = params.get(k);
  });
  document.getElementById("m-metric").addEventListener("change", function (e) { state.metric = e.target.value; refresh(); });

  load();
})();
