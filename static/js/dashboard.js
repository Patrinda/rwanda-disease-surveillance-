/* Dashboard charts: data comes from the chart_data view as JSON. */
(function () {
  "use strict";

  var config = JSON.parse(document.getElementById("chart-config").textContent);
  var charts = {};
  var lastPayload = null;
  var lastForecast = null;

  // Categorical colours in a fixed order (light and dark steps), plus a grey for "Other".
  var PALETTE = {
    light: ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6"],
    dark: ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9"],
  };
  var OTHER = { light: "#9aa0a6", dark: "#7b8087" };

  function theme() {
    return document.documentElement.getAttribute("data-bs-theme") === "dark" ? "dark" : "light";
  }
  function css(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }
  function ink() { return theme() === "dark" ? "#c3c2b7" : "#52514e"; }
  function grid() { return theme() === "dark" ? "rgba(255,255,255,.09)" : "rgba(0,0,0,.07)"; }
  function surface() { return theme() === "dark" ? "#212529" : "#ffffff"; }

  function baseOptions() {
    Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
    Chart.defaults.font.size = 14;
    Chart.defaults.color = ink();
    return { responsive: true, maintainAspectRatio: false, animation: { duration: 500 } };
  }

  function destroy(key) {
    if (charts[key]) { charts[key].destroy(); delete charts[key]; }
  }

  function emptyNote(canvas, hasData) {
    var wrap = canvas.parentElement;
    var note = wrap.querySelector(".empty-note");
    if (!hasData) {
      if (!note) {
        note = document.createElement("div");
        note.className = "empty-note text-secondary text-center position-absolute top-50 start-50 translate-middle";
        note.textContent = "No reports match these filters.";
        wrap.appendChild(note);
      }
    } else if (note) {
      note.remove();
    }
  }

  function render(p) {
    var t = theme(), colors = PALETTE[t];
    var axisCommon = {
      grid: { color: grid() },
      border: { display: false },
      ticks: { color: ink(), precision: 0 },
    };

    // 1. Monthly trend (line)
    destroy("trend");
    var trendCanvas = document.getElementById("trendChart");
    emptyNote(trendCanvas, p.trend.series.some(function (s) { return s.data.some(function (v) { return v > 0; }); }));
    charts.trend = new Chart(trendCanvas, {
      type: "line",
      data: {
        labels: p.trend.labels,
        datasets: p.trend.series.map(function (s, i) {
          return {
            label: s.label, data: s.data, borderColor: colors[i], backgroundColor: colors[i],
            borderWidth: 2, tension: 0.3, pointRadius: 0, pointHoverRadius: 5, pointHoverBorderWidth: 2,
            pointHoverBorderColor: surface(),
          };
        }),
      },
      options: Object.assign(baseOptions(), {
        interaction: { mode: "index", intersect: false },
        plugins: { legend: { display: p.trend.series.length > 1, position: "bottom", labels: { usePointStyle: true, boxWidth: 8 } } },
        scales: { x: { grid: { display: false }, border: { display: false }, ticks: { color: ink() } }, y: Object.assign({ beginAtZero: true }, axisCommon) },
      }),
    });

    // 2. Disease distribution (doughnut)
    destroy("disease");
    var dCanvas = document.getElementById("diseaseChart");
    emptyNote(dCanvas, p.by_disease.length > 0);
    charts.disease = new Chart(dCanvas, {
      type: "doughnut",
      data: {
        labels: p.by_disease.map(function (d) { return d.label + " (" + d.value + ")"; }),
        datasets: [{
          data: p.by_disease.map(function (d) { return d.value; }),
          backgroundColor: p.by_disease.map(function (d, i) { return d.label === "Other diseases" ? OTHER[t] : colors[i % colors.length]; }),
          borderColor: surface(), borderWidth: 2,
        }],
      },
      options: Object.assign(baseOptions(), {
        cutout: "62%",
        plugins: { legend: { position: "bottom", labels: { usePointStyle: true, boxWidth: 8, padding: 10 } } },
      }),
    });

    // 3. Top districts (horizontal bars)
    destroy("district");
    var bCanvas = document.getElementById("districtChart");
    emptyNote(bCanvas, p.by_district.labels.length > 0);
    charts.district = new Chart(bCanvas, {
      type: "bar",
      data: {
        labels: p.by_district.labels,
        datasets: [{ label: "Cases", data: p.by_district.data, backgroundColor: colors[0], borderRadius: 4, maxBarThickness: 18 }],
      },
      options: Object.assign(baseOptions(), {
        indexAxis: "y",
        plugins: { legend: { display: false } },
        scales: { x: Object.assign({ beginAtZero: true }, axisCommon), y: { grid: { display: false }, border: { display: false }, ticks: { color: ink() } } },
      }),
    });

    // 4. Age and sex (grouped bars)
    destroy("age");
    var aCanvas = document.getElementById("ageChart");
    var anyAge = p.age_gender.female.concat(p.age_gender.male).some(function (v) { return v > 0; });
    emptyNote(aCanvas, anyAge);
    charts.age = new Chart(aCanvas, {
      type: "bar",
      data: {
        labels: p.age_gender.labels,
        datasets: [
          { label: "Female", data: p.age_gender.female, backgroundColor: colors[0], borderRadius: 4, maxBarThickness: 26 },
          { label: "Male", data: p.age_gender.male, backgroundColor: colors[1], borderRadius: 4, maxBarThickness: 26 },
        ],
      },
      options: Object.assign(baseOptions(), {
        plugins: { legend: { position: "bottom", labels: { usePointStyle: true, boxWidth: 8 } } },
        scales: { x: { grid: { display: false }, border: { display: false }, ticks: { color: ink() }, title: { display: true, text: "Age in years", color: ink() } }, y: Object.assign({ beginAtZero: true }, axisCommon) },
      }),
    });

    buildTables(p);
    if (lastForecast) { renderForecast(lastForecast); }
  }

  // 5. Weekly reports, the model's estimate for weeks it had not seen, and next week's forecast
  function renderForecast(f) {
    var t = theme(), colors = PALETTE[t];
    destroy("forecast");
    var canvas = document.getElementById("forecastChart");
    if (!canvas) { return; }
    var labels = f.labels.concat([f.forecast.label + " (next)"]);
    var pad = function (arr) { return arr.concat([null]); };
    var model = f.ends.map(function (end) {
      var hit = f.backtest.filter(function (b) { return b.label === end; })[0];
      return hit ? hit.predicted : null;
    });
    var forecastLine = f.actual.map(function () { return null; });
    forecastLine[forecastLine.length - 1] = f.actual[f.actual.length - 1];
    forecastLine.push(f.has_model ? f.forecast.value : null);
    var datasets = [{
      label: "Reports per week", data: pad(f.actual), borderColor: colors[0], backgroundColor: colors[0],
      borderWidth: 2, tension: 0.25, pointRadius: 3, pointHoverRadius: 5, pointBackgroundColor: colors[0],
    }];
    if (model.some(function (v) { return v !== null; })) {
      datasets.push({
        label: "Model on unseen weeks", data: pad(model), borderColor: ink(), backgroundColor: ink(), borderWidth: 1.5,
        borderDash: [5, 4], tension: 0.25, pointRadius: 0, pointHoverRadius: 4,
      });
    }
    if (f.has_model) {
      datasets.push({
        label: "Forecast for next week", data: forecastLine, borderColor: colors[1], backgroundColor: colors[1], borderWidth: 2.5,
        borderDash: [2, 4], tension: 0, pointRadius: forecastLine.map(function (v, i) { return i === forecastLine.length - 1 ? 7 : 0; }),
        pointHoverRadius: 8, pointBorderColor: surface(), pointBorderWidth: 2,
      });
    }
    charts.forecast = new Chart(canvas, {
      type: "line",
      data: { labels: labels, datasets: datasets },
      options: Object.assign(baseOptions(), {
        interaction: { mode: "index", intersect: false },
        plugins: { legend: { position: "bottom", labels: { usePointStyle: true, boxWidth: 8, padding: 14 } } },
        scales: {
          x: { grid: { display: false }, border: { display: false }, ticks: { color: ink(), maxRotation: 0, autoSkip: true }, title: { display: true, text: "Week ending", color: ink() } },
          y: { beginAtZero: true, grid: { color: grid() }, border: { display: false }, ticks: { color: ink(), precision: 0 } },
        },
      }),
    });
    var rows = f.labels.map(function (l, i) {
      return [l, f.actual[i], model[i] === null ? "" : model[i], ""];
    });
    rows.push([f.forecast.label + " (next)", "", "", f.has_model ? f.forecast.value : ""]);
    var box = document.getElementById("table-forecast");
    if (box) { box.innerHTML = table(["Week ending", "Reports", "Model on unseen weeks", "Forecast"], rows); }
  }

  // ----- "Table" buttons: the same numbers as a table, for accessibility and printing -----
  function table(headers, rows) {
    var html = '<table class="table table-sm table-striped mb-0"><thead><tr>' +
      headers.map(function (h) { return "<th>" + h + "</th>"; }).join("") + "</tr></thead><tbody>" +
      rows.map(function (r) { return "<tr>" + r.map(function (c) { return "<td>" + c + "</td>"; }).join("") + "</tr>"; }).join("") +
      "</tbody></table>";
    return html;
  }
  function buildTables(p) {
    var trendHeaders = ["Month"].concat(p.trend.series.map(function (s) { return s.label; }));
    var trendRows = p.trend.labels.map(function (m, i) {
      return [m].concat(p.trend.series.map(function (s) { return s.data[i]; }));
    });
    document.getElementById("table-trend").innerHTML = table(trendHeaders, trendRows);
    document.getElementById("table-disease").innerHTML = table(["Disease", "Reports"], p.by_disease.map(function (d) { return [d.label, d.value]; }));
    document.getElementById("table-district").innerHTML = table(["District", "Reports"], p.by_district.labels.map(function (l, i) { return [l, p.by_district.data[i]]; }));
    document.getElementById("table-age").innerHTML = table(["Age group", "Female", "Male"], p.age_gender.labels.map(function (l, i) { return [l, p.age_gender.female[i], p.age_gender.male[i]]; }));
  }

  document.querySelectorAll("[data-table-toggle]").forEach(function (button) {
    button.addEventListener("click", function () {
      var box = document.getElementById("table-" + button.getAttribute("data-table-toggle"));
      box.classList.toggle("show");
      button.textContent = box.classList.contains("show") ? "Hide table" : "Table";
    });
  });

  // ----- Load data, and redraw when the light/dark theme changes -----
  fetch(config.url + window.location.search, { credentials: "same-origin", headers: { Accept: "application/json" } })
    .then(function (response) { return response.json(); })
    .then(function (payload) { lastPayload = payload; render(payload); })
    .catch(function () {
      document.querySelectorAll(".chart-wrap").forEach(function (el) {
        el.innerHTML = '<p class="text-danger text-center mt-5">The chart data could not be loaded.</p>';
      });
    });

  if (config.forecastUrl) {
    fetch(config.forecastUrl + window.location.search, { credentials: "same-origin", headers: { Accept: "application/json" } })
      .then(function (response) { return response.json(); })
      .then(function (payload) { lastForecast = payload; renderForecast(payload); })
      .catch(function () {
        var wrap = document.querySelector("#forecastChart");
        if (wrap) { wrap.parentElement.innerHTML = '<p class="text-danger text-center mt-5">The forecast data could not be loaded.</p>'; }
      });
  }

  new MutationObserver(function () { if (lastPayload) { render(lastPayload); } })
    .observe(document.documentElement, { attributes: true, attributeFilter: ["data-bs-theme"] });
})();
