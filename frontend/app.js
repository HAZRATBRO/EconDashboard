/* National Accounts Dashboard - frontend */
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const MAX_SERIES = 8;

async function api(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch (_) { /* not json */ }
    throw new Error(msg);
  }
  return r;
}
const getJSON = async (p) => (await api(p)).json();

function banner(el, text, kind = "") {
  el.innerHTML = text ? `<div class="banner ${kind}">${text}</div>` : "";
}

/* ---------------- theme + tabs ---------------- */
function css(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }
const seriesColor = (i) => css(`--s${(i % MAX_SERIES) + 1}`);

(function initTheme() {
  let saved = null;
  try { saved = localStorage.getItem("theme"); } catch (_) { /* storage blocked */ }
  if (saved) document.documentElement.dataset.theme = saved;
  $("#themeToggle").addEventListener("click", () => {
    const dark = document.documentElement.dataset.theme
      ? document.documentElement.dataset.theme === "dark"
      : matchMedia("(prefers-color-scheme: dark)").matches;
    const next = dark ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("theme", next); } catch (_) { /* ignore */ }
    Object.values(charts).forEach((c) => c && c.rerender && c.rerender());
  });
})();

const loaded = {};
$$("nav.tabs [data-view]").forEach((b) => b.addEventListener("click", () => {
  $$("nav.tabs [data-view]").forEach((x) => x.setAttribute("aria-selected", x === b));
  $$("section.view").forEach((s) => s.classList.toggle("active", s.id === b.dataset.view));
  const v = b.dataset.view;
  if (!loaded[v] && initView[v]) { loaded[v] = true; initView[v](); }
}));

/* ---------------- excel export ---------------- */
async function exportExcel(filename, sheets) {
  const r = await api("/api/export", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ filename, sheets }),
  });
  const blob = await r.blob();
  const cd = r.headers.get("Content-Disposition") || "";
  const name = (cd.match(/filename="([^"]+)"/) || [])[1] || `${filename}.xlsx`;
  const a = Object.assign(document.createElement("a"), { href: URL.createObjectURL(blob), download: name });
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000);
}
function withBusy(btn, fn) {
  return async (...args) => {
    btn.disabled = true;
    try { await fn(...args); } catch (e) { alert(e.message); } finally { btn.disabled = false; }
  };
}

/* ---------------- number helpers ---------------- */
function toNum(v) {
  if (typeof v === "number") return v;
  if (typeof v !== "string") return null;
  const s = v.replace(/,/g, "").trim();
  return /^-?\d+(\.\d+)?$/.test(s) ? parseFloat(s) : null;
}
const fmt = (v, d = 2) => (v == null ? "–" : Number(v).toLocaleString("en-IN", { maximumFractionDigits: d, minimumFractionDigits: Math.min(d, 2) }));
const isPeriodLike = (s) => /^(\d{4}(-\d{2,4})?|Q[1-4].*|.*\bQ[1-4]\b.*|\d{4}-\d{2}\s*(Q[1-4])?)$/i.test(String(s ?? "").trim());

/* ---------------- generic table ---------------- */
function renderTable(container, columns, rows, { countEl, searchEl } = {}) {
  let sortCol = -1, sortDir = 1, query = "";
  const numericCol = columns.map((_, j) => rows.length > 0 && rows.filter((r) => r[j] != null && r[j] !== "").every((r) => toNum(r[j]) != null));
  function draw() {
    let view = rows;
    if (query) view = view.filter((r) => r.some((v) => String(v ?? "").toLowerCase().includes(query)));
    if (sortCol >= 0) {
      view = [...view].sort((a, b) => {
        const x = a[sortCol], y = b[sortCol];
        const nx = toNum(x), ny = toNum(y);
        if (nx != null && ny != null) return (nx - ny) * sortDir;
        return String(x ?? "").localeCompare(String(y ?? "")) * sortDir;
      });
    }
    const shown = view.slice(0, 1000);
    container.innerHTML = `<table class="data"><thead><tr>${columns.map((c, j) => `<th data-j="${j}">${esc(c)}${sortCol === j ? (sortDir > 0 ? " ▲" : " ▼") : ""}</th>`).join("")}</tr></thead><tbody>${
      shown.map((r) => `<tr>${columns.map((_, j) => {
        const v = r[j];
        if (numericCol[j] && v != null && v !== "") return `<td class="num">${esc(fmt(toNum(v)))}</td>`;
        if (typeof v === "string" && /^https?:\/\//.test(v)) return `<td><a href="${esc(v)}" target="_blank" rel="noopener">link</a></td>`;
        return `<td>${esc(v)}</td>`;
      }).join("")}</tr>`).join("")
    }</tbody></table>`;
    if (countEl) countEl.textContent = `${view.length.toLocaleString()} row(s)${view.length > shown.length ? ` — showing first ${shown.length}; export includes all` : ""}`;
    $$("th", container).forEach((th) => th.addEventListener("click", () => {
      const j = +th.dataset.j;
      sortDir = sortCol === j ? -sortDir : 1; sortCol = j; draw();
    }));
  }
  if (searchEl) { searchEl.value = ""; searchEl.oninput = () => { query = searchEl.value.toLowerCase().trim(); draw(); }; }
  draw();
}

/* ---------------- charts ---------------- */
const charts = {};
function baseOptions(yTitle, opts = {}) {
  const ink = css("--text-2"), grid = css("--grid");
  return {
    responsive: true, maintainAspectRatio: false, animation: false,
    interaction: { mode: "index", intersect: false },
    plugins: {
      legend: { display: false },
      tooltip: {
        backgroundColor: css("--surface"), titleColor: css("--text"), bodyColor: css("--text-2"),
        borderColor: css("--border"), borderWidth: 1, padding: 10, boxPadding: 4,
        callbacks: { label: (c) => ` ${c.dataset.label}: ${fmt(c.parsed.y)}${opts.unit ? " " + opts.unit : ""}` },
      },
    },
    scales: {
      x: { ticks: { color: ink, maxRotation: 0, autoSkip: true }, grid: { display: false }, border: { color: grid } },
      y: {
        ticks: { color: ink, callback: (v) => fmt(v, 1) }, grid: { color: grid }, border: { display: false },
        title: { display: !!yTitle, text: yTitle, color: ink },
        beginAtZero: opts.beginAtZero ?? false,
      },
    },
  };
}
function drawChart(key, canvas, { type = "line", labels, datasets, yTitle = "", unit = "", legendEl, beginAtZero }) {
  const render = () => {
    if (charts[key] && charts[key].destroy) charts[key].destroy();
    const ds = datasets.map((d, i) => {
      const color = d.color || seriesColor(d.colorIndex ?? i);
      return type === "bar"
        ? { ...d, backgroundColor: d.data.map((v) => (v != null && v < 0 ? css("--s8") : color)), borderRadius: 4, borderSkipped: "start", maxBarThickness: 28 }
        : { ...d, borderColor: color, backgroundColor: color, borderWidth: 2, pointRadius: labels.length > 40 ? 0 : 3, pointHoverRadius: 5, tension: 0, spanGaps: true };
    });
    const chart = new Chart(canvas, { type, data: { labels, datasets: ds }, options: baseOptions(yTitle, { unit, beginAtZero: beginAtZero ?? type === "bar" }) });
    chart.rerender = render;
    charts[key] = chart;
    if (legendEl) {
      legendEl.innerHTML = datasets.length > 1
        ? datasets.map((d, i) => `<span><i style="background:${d.color || seriesColor(d.colorIndex ?? i)}"></i>${esc(d.label)}</span>`).join("")
        : "";
    }
  };
  render();
}

/* Chart builder for arbitrary tables: long format (x col + value col + group col)
   or wide format (rows are series, period-like columns are x). */
function chartBuilder(prefix, columns, rows) {
  const controls = $(`#${prefix}ChartControls`);
  const numericCols = columns.map((c, j) => j).filter((j) => rows.some((r) => toNum(r[j]) != null) && rows.filter((r) => r[j] != null && r[j] !== "").every((r) => toNum(r[j]) != null));
  const periodCols = numericCols.filter((j) => isPeriodLike(columns[j]));
  const wideDefault = periodCols.length >= 3;
  const xGuess = columns.findIndex((c) => /year|quarter|period|date|time/i.test(c));
  const valueGuess = numericCols.find((j) => /value|amount|crore|gdp|gva/i.test(columns[j]) && j !== xGuess) ?? numericCols.find((j) => j !== xGuess);
  const catCols = columns.map((_, j) => j).filter((j) => !numericCols.includes(j) && j !== xGuess);
  const distinct = (j) => new Set(rows.map((r) => r[j])).size;
  const groupGuess = catCols.filter((j) => distinct(j) > 1 && distinct(j) <= 40).sort((a, b) => distinct(a) - distinct(b))[0] ?? -1;
  const labelGuess = columns.findIndex((_, j) => !numericCols.includes(j));

  const opt = (j, sel) => `<option value="${j}" ${j === sel ? "selected" : ""}>${esc(columns[j] ?? "(none)")}</option>`;
  controls.innerHTML = `
    <label class="field">Layout<select data-k="mode"><option value="long" ${!wideDefault ? "selected" : ""}>Long (one row per observation)</option><option value="wide" ${wideDefault ? "selected" : ""}>Wide (rows = series, columns = periods)</option></select></label>
    <span data-long style="display:contents">
      <label class="field">X axis<select data-k="x">${columns.map((_, j) => opt(j, xGuess)).join("")}</select></label>
      <label class="field">Value<select data-k="y">${numericCols.map((j) => opt(j, valueGuess)).join("")}</select></label>
      <label class="field">Series<select data-k="g"><option value="-1">(none)</option>${catCols.map((j) => opt(j, groupGuess)).join("")}</select></label>
    </span>
    <span data-wide style="display:contents">
      <label class="field">Series label<select data-k="lab">${columns.map((_, j) => opt(j, labelGuess)).join("")}</select></label>
      <label class="field">Rows to plot<select data-k="rows" multiple size="1" style="min-width:240px"></select></label>
    </span>
    <label class="field">Chart<select data-k="type"><option value="line">Line</option><option value="bar">Bar</option></select></label>`;
  const get = (k) => $(`[data-k="${k}"]`, controls);

  function fillRowPicker() {
    const lab = +get("lab").value;
    const sel = get("rows");
    sel.size = 6;
    sel.innerHTML = rows.map((r, i) => `<option value="${i}" ${i < 3 ? "selected" : ""}>${esc(String(r[lab] ?? `Row ${i + 1}`).slice(0, 80))}</option>`).join("");
  }
  fillRowPicker();

  function redraw() {
    const wide = get("mode").value === "wide";
    $("[data-long]", controls).style.display = wide ? "none" : "contents";
    $("[data-wide]", controls).style.display = wide ? "contents" : "none";
    const type = get("type").value;
    let labels, datasets, note = "";
    if (wide) {
      const xCols = periodCols.length ? periodCols : numericCols;
      labels = xCols.map((j) => columns[j]);
      const picked = [...get("rows").selectedOptions].map((o) => +o.value);
      const lab = +get("lab").value;
      datasets = picked.slice(0, MAX_SERIES).map((i, k) => ({ label: String(rows[i][lab] ?? `Row ${i + 1}`), data: xCols.map((j) => toNum(rows[i][j])), colorIndex: k }));
      if (picked.length > MAX_SERIES) note = `Showing the first ${MAX_SERIES} selected rows.`;
    } else {
      const x = +get("x").value, y = +get("y").value, g = +get("g").value;
      labels = [...new Set(rows.map((r) => String(r[x] ?? "")))].sort();
      const groups = new Map();
      rows.forEach((r) => {
        const key = g >= 0 ? String(r[g] ?? "") : columns[y];
        if (!groups.has(key)) groups.set(key, new Map());
        const m = groups.get(key);
        const v = toNum(r[y]);
        if (v != null) m.set(String(r[x] ?? ""), (m.get(String(r[x] ?? "")) ?? 0) + v);
      });
      const keys = [...groups.keys()];
      if (keys.length > MAX_SERIES) note = `${keys.length} series found; showing the first ${MAX_SERIES}. Narrow the query or pick another Series column.`;
      datasets = keys.slice(0, MAX_SERIES).map((k, i) => ({ label: k, data: labels.map((l) => groups.get(k).get(l) ?? null), colorIndex: i }));
    }
    drawChart(prefix, $(`#${prefix}Chart`), { type, labels, datasets, legendEl: $(`#${prefix}Legend`) });
    if (note) $(`#${prefix}Legend`).insertAdjacentHTML("beforeend", `<span style="color:var(--muted)">${esc(note)}</span>`);
  }
  controls.onchange = (e) => { if (e.target.dataset.k === "lab") fillRowPicker(); redraw(); };
  if (!numericCols.length) { controls.innerHTML = '<span class="count">No numeric columns to chart.</span>'; return; }
  redraw();
}

/* ---------------- status ---------------- */
getJSON("/api/status").then((s) => {
  const dots = $$("#status .dot");
  [s.website, s.api].forEach((x, i) => { dots[i].classList.add(x.ok ? "ok" : "bad"); dots[i].parentElement.title = x.ok ? `HTTP ${x.status}` : `Unreachable (${x.error || x.status})`; });
}).catch(() => {});

/* ---------------- OVERVIEW ---------------- */
let snapshot = null;
async function initOverview() {
  snapshot = await getJSON("/api/snapshot");
  $("#snapshotBanner").textContent = snapshot.status;
  const years = snapshot.rows.map((r) => r[0]);
  const real = snapshot.rows.map((r) => r[1]);
  const nom = snapshot.rows.map((r) => r[2]);
  const growth = real.map((v, i) => (i === 0 ? null : +(((v / real[i - 1]) - 1) * 100).toFixed(1)));
  const nomGrowth = nom.map((v, i) => (i === 0 ? null : +(((v / nom[i - 1]) - 1) * 100).toFixed(1)));
  const deflator = nom.map((v, i) => +((v / real[i]) * 100).toFixed(1));
  const n = years.length - 1;
  const tiles = [
    { label: `Real GDP growth, ${years[n]}`, value: `${fmt(growth[n], 1)}%`, meta: `${years[n - 1]}: ${fmt(growth[n - 1], 1)}%` },
    { label: `Nominal GDP, ${years[n]}`, value: `₹${fmt(nom[n])}`, meta: `${snapshot.unit} · growth ${fmt(nomGrowth[n], 1)}%` },
    { label: `Real GDP, ${years[n]}`, value: `₹${fmt(real[n])}`, meta: `${snapshot.unit} at 2011-12 prices` },
    { label: `GDP deflator, ${years[n]}`, value: fmt(deflator[n], 1), meta: "2011-12 = 100" },
  ];
  $("#kpis").innerHTML = tiles.map((t) => `<div class="card kpi"><div class="label">${esc(t.label)}</div><div class="value">${esc(t.value)}</div><div class="meta">${esc(t.meta)}</div></div>`).join("");
  drawChart("lvl", $("#lvlChart"), {
    labels: years, unit: snapshot.unit, yTitle: snapshot.unit, legendEl: $("#lvlLegend"),
    datasets: [{ label: "Nominal (current prices)", data: nom, colorIndex: 0 }, { label: "Real (constant 2011-12 prices)", data: real, colorIndex: 1 }],
  });
  drawChart("growth", $("#growthChart"), { type: "bar", labels: years.slice(1), unit: "%", datasets: [{ label: "Real GDP growth", data: growth.slice(1), colorIndex: 0 }] });
  $("#overviewExport").onclick = withBusy($("#overviewExport"), () => exportExcel("gdp-overview", [{
    name: "GDP overview", title: snapshot.title, notes: [snapshot.status, `Unit: ${snapshot.unit}`],
    columns: ["Year", "Real GDP", "Nominal GDP", "Real growth %", "Nominal growth %", "GDP deflator (2011-12=100)"],
    rows: years.map((y, i) => [y, real[i], nom[i], growth[i], nomGrowth[i], deflator[i]]),
  }]));
}

/* ---------------- EXPLORER ---------------- */
let indicators = [], xLast = null;
async function initExplorer() {
  const res = await getJSON("/api/nas/indicators");
  indicators = res.indicators.map((d) => ({ code: d.indicator_code ?? d.code ?? d.id, name: d.name ?? d.indicator_name ?? d.description, description: d.description }));
  if (res.source !== "live") banner($("#xMsg"), `Using the bundled indicator list — MoSPI's indicator API was not reachable (${esc(res.error || "")}). Data fetches still go to MoSPI.`);
  const sel = $("#xIndicator");
  sel.innerHTML = `<optgroup label="National (1–22)">${indicators.filter((d) => +d.code <= 22).map((d) => `<option value="${d.code}">${d.code}. ${esc(d.name)}</option>`).join("")}</optgroup>` +
    `<optgroup label="State (23–34)">${indicators.filter((d) => +d.code > 22).map((d) => `<option value="${d.code}">${d.code}. ${esc(d.name)}</option>`).join("")}</optgroup>`;
  sel.value = "5";
  const sync = () => {
    const code = +sel.value;
    $("#xStateWrap").hidden = code < 23;
    const base = $("#xBase").value;
    $("#xSeries").querySelector('option[value="Back"],option:nth-child(2)').disabled = base === "2022-23";
    if (base === "2022-23") $("#xSeries").value = "Current";
    const qOK = code < 23 && $("#xSeries").value === "Current";
    $("#xFreq").querySelector("option:nth-child(2)").disabled = !qOK;
    if (!qOK) $("#xFreq").value = "Annually";
    const def = glossaryMatch(indicators.find((d) => +d.code === code)?.name);
    $("#xIndicatorDef").innerHTML = def ? `<strong>${esc(def.term)}${def.abbr ? ` (${esc(def.abbr)})` : ""}:</strong> ${esc(def.definition)}` : "";
    $("#xFilterBox").innerHTML = "";
  };
  ["#xIndicator", "#xBase", "#xSeries"].forEach((s) => $(s).addEventListener("change", sync));
  await loadGlossary();
  sync();
  $("#xFilters").onclick = withBusy($("#xFilters"), loadFilterOptions);
  $("#xFetch").onclick = withBusy($("#xFetch"), fetchExplorer);
  $("#xExport").onclick = withBusy($("#xExport"), exportExplorer);
}

function xParams() {
  const p = new URLSearchParams({
    indicator_code: $("#xIndicator").value, base_year: $("#xBase").value,
    series: $("#xSeries").value, frequency_code: $("#xFreq").value,
  });
  if ($("#xYear").value.trim()) p.set("year", $("#xYear").value.replace(/\s/g, ""));
  if (!$("#xStateWrap").hidden && $("#xState").value.trim()) p.set("state_code", $("#xState").value.replace(/\s/g, ""));
  $$("#xFilterBox select").forEach((s) => { const v = [...s.selectedOptions].map((o) => o.value).filter(Boolean).join(","); if (v) p.set(s.dataset.param, v); });
  return p;
}

const FILTER_PARAMS = ["year", "quarterly_code", "state_code", "approach_code", "revision_code", "account_code", "institutional_code", "industry_code", "subindustry_code"];
async function loadFilterOptions() {
  const p = new URLSearchParams({ indicator_code: $("#xIndicator").value, base_year: $("#xBase").value, series: $("#xSeries").value, frequency: $("#xFreq").value });
  const res = await getJSON(`/api/nas/filters?${p}`);
  const data = res.data ?? res;
  const box = $("#xFilterBox");
  box.innerHTML = "";
  const entries = Array.isArray(data) ? [["options", data]] : Object.entries(data || {});
  let made = 0;
  for (const [key, list] of entries) {
    if (!Array.isArray(list) || !list.length || typeof list[0] !== "object") continue;
    const sample = list[0];
    const keys = Object.keys(sample);
    const codeKey = keys.find((k) => /code$/i.test(k)) ?? keys[0];
    const nameKey = keys.find((k) => k !== codeKey && /name|desc|label|year|title/i.test(k)) ?? codeKey;
    const param = FILTER_PARAMS.find((f) => f === codeKey || f === key || f.startsWith(key.replace(/s$/, "")) || codeKey.startsWith(f.replace("_code", ""))) ?? (/year/i.test(codeKey) ? "year" : null);
    if (!param || param === "year" && $("#xYear").value) continue;
    const sel = document.createElement("select");
    sel.multiple = true; sel.size = Math.min(5, list.length); sel.dataset.param = param;
    sel.innerHTML = list.map((o) => `<option value="${esc(o[codeKey])}">${esc(o[nameKey] ?? o[codeKey])}</option>`).join("");
    const lab = document.createElement("label");
    lab.className = "field"; lab.textContent = `${key} (any)`;
    lab.appendChild(sel); box.appendChild(lab); made++;
  }
  if (!made) box.innerHTML = `<span class="count">No selectable filters returned for this indicator.</span>`;
}

async function fetchExplorer() {
  banner($("#xMsg"), "Fetching from MoSPI…");
  const p = xParams();
  let res;
  try { res = await getJSON(`/api/nas/data?${p}`); } catch (e) { banner($("#xMsg"), esc(e.message), "error"); throw e; }
  const recs = res.records || [];
  if (!recs.length) { banner($("#xMsg"), "MoSPI returned no records for this query. Try another base year, series or frequency."); $("#xResult").hidden = true; return; }
  banner($("#xMsg"), "");
  const columns = [...new Set(recs.flatMap((r) => Object.keys(r)))];
  const rows = recs.map((r) => columns.map((c) => (r[c] !== null && typeof r[c] === "object" ? JSON.stringify(r[c]) : r[c])));
  const ind = indicators.find((d) => String(d.code) === $("#xIndicator").value);
  xLast = { columns, rows, params: Object.fromEntries(p), indicator: ind };
  $("#xResult").hidden = false;
  renderTable($("#xTable"), columns, rows, { countEl: $("#xCount"), searchEl: $("#xSearch") });
  $("#xRaw").textContent = JSON.stringify({ query: xLast.params, meta: res.meta }, null, 2);
  chartBuilder("x", columns, rows);
}

function exportExplorer() {
  if (!xLast) return;
  const { columns, rows, params, indicator } = xLast;
  const def = glossaryMatch(indicator?.name);
  const sheets = [{
    name: (indicator?.name || "Data").slice(0, 31), title: `${indicator?.name || "NAS data"} — MoSPI National Accounts`,
    notes: [`Query: ${Object.entries(params).map(([k, v]) => `${k}=${v}`).join(", ")}`, "Source: MoSPI API (api.mospi.gov.in)"],
    columns, rows,
  }];
  if (def) sheets.push({ name: "Definition", columns: ["Term", "Abbreviation", "Definition", "Formula", "Note"], rows: [[def.term, def.abbr, def.definition, def.formula || "", def.note || ""]] });
  return exportExcel(`nas-${(indicator?.name || "data").toLowerCase().replace(/\W+/g, "-")}`, sheets);
}

/* ---------------- REPORTS ---------------- */
let rData = null, rItems = [];
async function initReports() {
  const [sources, series] = await Promise.all([getJSON("/api/reports/sources"), getJSON("/api/report-series")]);
  $("#rSource").innerHTML = sources.map((s, i) => `<option value="${esc(s.url)}" ${i === 1 ? "selected" : ""}>${esc(s.label)}</option>`).join("");
  $("#seriesList").innerHTML = series.map((s) => `<div class="s"><div><strong>${esc(s.name)}</strong></div><div class="m">${esc(s.frequency)} · ${esc(s.timing)}</div><div>${esc(s.description)}</div></div>`).join("");
  $("#rLoad").onclick = withBusy($("#rLoad"), () => loadReports($("#rUrl").value.trim() || $("#rSource").value));
  $("#rNext").onclick = () => rData?.next_page && loadReports(rData.next_page, true);
  ["#rSearch", "#rFrom", "#rType"].forEach((s) => $(s).addEventListener("input", drawReports));
  $("#rExport").onclick = withBusy($("#rExport"), () => exportExcel("mospi-reports", [{
    name: "Reports", title: rData?.page_title || "MoSPI reports", notes: [`Source page: ${rData?.page_url || ""}`, `Fetched: ${rData?.fetched_at || ""}`],
    columns: ["Release date", "Title", "File type", "Download URL", "Other files"],
    rows: filteredReports().map((r) => [r.date || "", r.title, r.file_type, r.url, (r.other_files || []).map((f) => f.url).join(" ")]),
  }, ...(series ? [{ name: "Release cycle", columns: ["Release", "Frequency", "Timing", "Description"], rows: series.map((s) => [s.name, s.frequency, s.timing, s.description]) }] : [])]));
  loadReports($("#rSource").value).catch(() => {});
}

async function loadReports(url, append = false) {
  banner($("#rMsg"), `Loading ${esc(url)} …`);
  try {
    const d = await getJSON(`/api/reports?url=${encodeURIComponent(url)}`);
    rData = d;
    rItems = append ? [...rItems, ...d.reports] : d.reports;
    banner($("#rMsg"), d.reports.length ? "" : `No downloadable documents were found on <a href="${esc(url)}" target="_blank" rel="noopener">this page</a>. Try one of its sections on the right.`);
    const types = [...new Set(rItems.map((r) => r.file_type))].sort();
    const cur = $("#rType").value;
    $("#rType").innerHTML = `<option value="">All</option>${types.map((t) => `<option ${t === cur ? "selected" : ""}>${esc(t)}</option>`).join("")}`;
    $("#rCats").hidden = !d.categories.length;
    $("#rCatList").innerHTML = d.categories.map((c) => `<button class="chip" data-url="${esc(c.url)}">${esc(c.label)}</button>`).join("");
    $$("#rCatList .chip").forEach((b) => b.addEventListener("click", () => { $("#rUrl").value = b.dataset.url; loadReports(b.dataset.url); }));
    $("#rNext").hidden = !d.next_page;
    drawReports();
  } catch (e) {
    banner($("#rMsg"), `Could not load reports: ${esc(e.message)}. <a href="${esc(url)}" target="_blank" rel="noopener">Open the page on mospi.gov.in</a>.`, "error");
  }
}
function filteredReports() {
  const q = $("#rSearch").value.toLowerCase().trim(), from = $("#rFrom").value.trim(), t = $("#rType").value;
  return rItems.filter((r) => (!q || (r.title + " " + (r.context || "")).toLowerCase().includes(q)) && (!from || (r.date && r.date >= from)) && (!t || r.file_type === t));
}
function drawReports() {
  const list = filteredReports();
  $("#rCount").textContent = `${list.length} of ${rItems.length} document(s)`;
  $("#rList").innerHTML = list.map((r) => `
    <div class="report">
      <div><div class="t">${esc(r.title)}</div><div class="m">${r.date ? esc(new Date(r.date).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })) : "Date not listed"}</div></div>
      <div class="files"><a class="tag" href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.file_type)}</a>${(r.other_files || []).map((f) => `<a class="tag" href="${esc(f.url)}" target="_blank" rel="noopener">${esc(f.file_type)}</a>`).join("")}</div>
    </div>`).join("") || (rItems.length ? '<div class="empty">No reports match the filters.</div>' : "");
}

/* ---------------- DEFINITIONS ---------------- */
let glossary = null, gCat = "";
async function loadGlossary() { if (!glossary) glossary = await getJSON("/api/glossary"); return glossary; }
function glossaryMatch(name) {
  if (!name || !glossary) return null;
  const n = name.toLowerCase();
  return glossary.find((g) => g.term.toLowerCase() === n) || glossary.find((g) => n.includes(g.term.toLowerCase()) || g.term.toLowerCase().includes(n))
    || glossary.find((g) => g.abbr && n.split(/\W+/).includes(g.abbr.toLowerCase()));
}
async function initDefinitions() {
  await loadGlossary();
  const cats = [...new Set(glossary.map((g) => g.category))];
  $("#gCats").innerHTML = [`<button class="chip" aria-pressed="true" data-c="">All</button>`, ...cats.map((c) => `<button class="chip" aria-pressed="false" data-c="${esc(c)}">${esc(c)}</button>`)].join("");
  $$("#gCats .chip").forEach((b) => b.addEventListener("click", () => { gCat = b.dataset.c; $$("#gCats .chip").forEach((x) => x.setAttribute("aria-pressed", x === b)); drawGlossary(); }));
  $("#gSearch").addEventListener("input", drawGlossary);
  $("#gExport").onclick = withBusy($("#gExport"), () => exportExcel("national-accounts-definitions", [{
    name: "Definitions", title: "National Accounts Statistics — key definitions",
    columns: ["Category", "Term", "Abbreviation", "Definition", "Formula", "Note"],
    rows: glossaryFiltered().map((g) => [g.category, g.term, g.abbr, g.definition, g.formula || "", g.note || ""]),
  }]));
  drawGlossary();
}
function glossaryFiltered() {
  const q = $("#gSearch").value.toLowerCase().trim();
  return glossary.filter((g) => (!gCat || g.category === gCat) && (!q || [g.term, g.abbr, g.definition, g.formula].join(" ").toLowerCase().includes(q)));
}
function drawGlossary() {
  $("#gList").innerHTML = glossaryFiltered().map((g) => `
    <div class="card"><h3>${esc(g.term)} ${g.abbr ? `<span class="abbr">${esc(g.abbr)}</span>` : ""}<span class="tag">${esc(g.category)}</span></h3>
    <p>${esc(g.definition)}</p>${g.formula ? `<div class="formula">${esc(g.formula)}</div>` : ""}${g.note ? `<div class="note">${esc(g.note)}</div>` : ""}</div>`).join("") || '<div class="empty">No matching terms.</div>';
}

/* ---------------- IMPORT ---------------- */
let iSheets = null;
function initImport() {
  $("#iUpload").onclick = withBusy($("#iUpload"), async () => {
    const f = $("#iFile").files[0];
    if (!f) return banner($("#iMsg"), "Choose an .xlsx file first.");
    const fd = new FormData(); fd.append("file", f);
    try {
      const res = await (await api("/api/import", { method: "POST", body: fd })).json();
      iSheets = res.sheets;
    } catch (e) { banner($("#iMsg"), esc(e.message), "error"); return; }
    banner($("#iMsg"), iSheets.length ? "" : "The workbook has no data.");
    $("#iExport").hidden = !iSheets.length;
    $("#iTabs").innerHTML = iSheets.map((s, i) => `<button class="chip" data-i="${i}" aria-pressed="${i === 0}">${esc(s.name)}</button>`).join("");
    $$("#iTabs .chip").forEach((b) => b.addEventListener("click", () => { $$("#iTabs .chip").forEach((x) => x.setAttribute("aria-pressed", x === b)); showSheet(+b.dataset.i); }));
    if (iSheets.length) showSheet(0);
  });
  $("#iExport").onclick = withBusy($("#iExport"), () => exportExcel("imported-statement", iSheets));
}
function showSheet(i) {
  const s = iSheets[i];
  $("#iResult").hidden = false;
  $("#iNotes").textContent = (s.notes || []).join(" · ");
  renderTable($("#iTable"), s.columns, s.rows, { countEl: $("#iCount"), searchEl: $("#iSearch") });
  chartBuilder("i", s.columns, s.rows);
}

const initView = { overview: initOverview, explorer: initExplorer, reports: initReports, definitions: initDefinitions, import: initImport };
loaded.overview = true;
initOverview().catch((e) => { $("#snapshotBanner").textContent = `Could not load overview: ${e.message}`; });
