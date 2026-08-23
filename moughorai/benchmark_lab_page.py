"""Self-contained presentation assets for the local Benchmark Lab V0 adapter."""

from __future__ import annotations


TOKEN_PLACEHOLDER = "__ATLAS_BENCHMARK_LAB_TOKEN__"


PAGE_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="atlas-lab-token" content="__ATLAS_BENCHMARK_LAB_TOKEN__">
  <title>Atlas AI OC — Benchmark Lab</title>
  <link rel="stylesheet" href="/app.css">
</head>
<body>
  <header class="hero">
    <div>
      <p class="eyebrow">ATLAS AI OC</p>
      <h1>Benchmark Lab</h1>
      <p class="subtitle">Fire Strike evidence, comparison, and exact what-if scoring.</p>
    </div>
    <div class="hero-score">
      <span>BENCHMARK</span>
      <strong>Fire Strike</strong>
      <small>Standard · local-only</small>
    </div>
  </header>

  <div class="notice">
    <strong>Offline evidence workflow.</strong>
    Select locally saved HTML. Atlas does not fetch source URLs, render captured
    third-party HTML, or infer that two equal scores are the same run.
  </div>

  <main class="grid">
    <section class="panel source-panel" aria-labelledby="hwbot-title">
      <div class="panel-head">
        <div><p class="eyebrow">SOURCE A</p><h2 id="hwbot-title">HWBOT</h2></div>
        <span id="hwbot-status" class="badge neutral">Not loaded</span>
      </div>
      <label>Reference URL <small>(reference only — never fetched)</small>
        <input id="hwbot-url" type="url" value="https://hwbot.org/benchmarks/3dmark_-_fire_strike/submissions/">
      </label>
      <div class="actions">
        <label class="file-button">Select saved HTML
          <input id="hwbot-file" type="file" accept="text/html,.html,.htm">
        </label>
        <button id="hwbot-open" class="secondary" type="button">Open reference</button>
      </div>
      <div id="hwbot-summary" class="score-summary empty">Awaiting captured source bytes.</div>
    </section>

    <section class="panel evidence-panel" aria-labelledby="evidence-title">
      <div class="panel-head">
        <div><p class="eyebrow">ATLAS</p><h2 id="evidence-title">Evidence</h2></div>
        <button id="reset" class="ghost" type="button">Reset lab</button>
      </div>
      <div class="score-grid">
        <div><span>Overall</span><strong id="evidence-overall">—</strong></div>
        <div><span>Graphics</span><strong id="evidence-graphics">—</strong></div>
        <div><span>Physics</span><strong id="evidence-physics">—</strong></div>
        <div><span>Combined</span><strong id="evidence-combined">—</strong></div>
      </div>
      <p id="evidence-source" class="muted">Load a source to inspect provenance.</p>
    </section>

    <section class="panel source-panel" aria-labelledby="ul-title">
      <div class="panel-head">
        <div><p class="eyebrow">SOURCE B</p><h2 id="ul-title">UL / 3DMark</h2></div>
        <span id="ul-status" class="badge neutral">Not loaded</span>
      </div>
      <label>Reference URL <small>(reference only — never fetched)</small>
        <input id="ul-url" type="url" value="https://www.3dmark.com/fs/">
      </label>
      <div class="actions">
        <label class="file-button">Select saved HTML
          <input id="ul-file" type="file" accept="text/html,.html,.htm">
        </label>
        <button id="ul-open" class="secondary" type="button">Open reference</button>
      </div>
      <div id="ul-summary" class="score-summary empty">Awaiting captured source bytes.</div>
    </section>

    <section class="panel comparison-panel" aria-labelledby="comparison-title">
      <div class="panel-head">
        <div><p class="eyebrow">DETERMINISTIC</p><h2 id="comparison-title">Source comparison</h2></div>
        <span class="badge warning">Run linkage unknown</span>
      </div>
      <div id="comparison" class="comparison empty">
        Load both sources to compare their presented score evidence.
      </div>
      <p class="muted">Equal scores are agreement, not proof of one physical run.</p>
    </section>

    <section class="panel calculator-panel" aria-labelledby="calculator-title">
      <div class="panel-head">
        <div><p class="eyebrow">PR150 · EXACT</p><h2 id="calculator-title">Fire Strike calculator</h2></div>
        <button id="load-ul" class="ghost" type="button">Load UL components</button>
      </div>
      <div class="calculator-columns">
        <fieldset>
          <legend>Baseline</legend>
          <label>Graphics <input id="base-graphics" inputmode="numeric" value="22447"></label>
          <label>Physics <input id="base-physics" inputmode="numeric" value="56270"></label>
          <label>Combined <input id="base-combined" inputmode="numeric" value="7668"></label>
        </fieldset>
        <fieldset>
          <legend>What-if</legend>
          <label>Graphics <input id="next-graphics" inputmode="numeric" value="23000"></label>
          <label>Physics <input id="next-physics" inputmode="numeric" value="56270"></label>
          <label>Combined <input id="next-combined" inputmode="numeric" value="7668"></label>
        </fieldset>
      </div>
      <button id="calculate" class="primary" type="button">Calculate exact score change</button>
      <div class="result-strip">
        <div><span>Current</span><strong id="calc-current">—</strong></div>
        <div><span>New</span><strong id="calc-new">—</strong></div>
        <div><span>Delta</span><strong id="calc-delta">—</strong></div>
        <div><span>Change</span><strong id="calc-percent">—</strong></div>
      </div>
      <p class="muted">Atlas calculated values are derived, not source observations.</p>
    </section>

    <section class="panel provenance-panel" aria-labelledby="provenance-title">
      <div class="panel-head">
        <div><p class="eyebrow">LINEAGE</p><h2 id="provenance-title">Evidence & provenance</h2></div>
      </div>
      <details><summary>HWBOT field evidence</summary><pre id="hwbot-evidence">No evidence loaded.</pre></details>
      <details><summary>UL field evidence</summary><pre id="ul-evidence">No evidence loaded.</pre></details>
      <div class="external-links">
        <a href="https://hwbot.org/benchmarks/3dmark_-_fire_strike" target="_blank" rel="noopener noreferrer">Open HWBOT</a>
        <a href="https://www.3dmark.com/" target="_blank" rel="noopener noreferrer">Open 3DMark</a>
        <a href="https://elmor.se/3dmark" target="_blank" rel="noopener noreferrer">Open Elmor reference</a>
      </div>
    </section>
  </main>

  <footer>
    Parsed means the captured source presented these values. It does not establish
    validity, eligibility, stability, safe tuning, or same-run linkage.
  </footer>
  <div id="toast" role="status" aria-live="polite"></div>
  <script src="/app.js" defer></script>
</body>
</html>
"""


PAGE_CSS = """
:root {
  color-scheme: dark;
  --bg: #071019;
  --panel: #0e1a25;
  --panel-2: #111f2d;
  --line: #23384a;
  --text: #eaf2f8;
  --muted: #8fa5b7;
  --cyan: #39d7ff;
  --green: #70e0a2;
  --amber: #f4c66b;
  --red: #ff7c86;
  --shadow: 0 18px 50px rgba(0, 0, 0, .28);
}
* { box-sizing: border-box; }
body {
  margin: 0;
  min-height: 100vh;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  background:
    radial-gradient(circle at 85% -10%, rgba(57, 215, 255, .15), transparent 32rem),
    radial-gradient(circle at -10% 35%, rgba(112, 224, 162, .08), transparent 26rem),
    var(--bg);
  color: var(--text);
}
.hero, main, .notice, footer { width: min(1380px, calc(100% - 32px)); margin-inline: auto; }
.hero { display: flex; justify-content: space-between; gap: 24px; align-items: end; padding: 44px 0 24px; }
.hero h1 { margin: 3px 0 6px; font-size: clamp(2.2rem, 6vw, 4.6rem); line-height: .95; letter-spacing: -.055em; }
.eyebrow { margin: 0; color: var(--cyan); font-size: .72rem; letter-spacing: .22em; font-weight: 800; }
.subtitle, .muted, label small { color: var(--muted); }
.subtitle { margin: 0; font-size: 1rem; }
.hero-score { min-width: 210px; border-left: 2px solid var(--cyan); padding: 5px 0 5px 18px; display: grid; }
.hero-score span, .hero-score small { color: var(--muted); font-size: .68rem; letter-spacing: .12em; }
.hero-score strong { font-size: 1.3rem; margin: 3px 0; }
.notice { padding: 13px 16px; border: 1px solid rgba(57, 215, 255, .25); background: rgba(57, 215, 255, .06); color: #c6d7e3; border-radius: 10px; font-size: .86rem; }
.grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; padding: 16px 0 32px; }
.panel { min-width: 0; background: linear-gradient(145deg, rgba(17, 31, 45, .96), rgba(10, 21, 31, .98)); border: 1px solid var(--line); border-radius: 15px; padding: 20px; box-shadow: var(--shadow); }
.panel-head { display: flex; justify-content: space-between; align-items: start; gap: 15px; margin-bottom: 16px; }
h2 { font-size: 1.15rem; margin: 4px 0 0; }
label { display: grid; gap: 7px; color: #c5d4df; font-size: .78rem; font-weight: 700; }
input { width: 100%; border: 1px solid #2a4052; border-radius: 8px; padding: 10px 11px; color: var(--text); background: #09131d; outline: none; }
input:focus { border-color: var(--cyan); box-shadow: 0 0 0 3px rgba(57, 215, 255, .10); }
button, .file-button, .external-links a { border: 0; border-radius: 8px; padding: 10px 13px; font: inherit; font-size: .78rem; font-weight: 800; cursor: pointer; text-decoration: none; }
.primary, .file-button { color: #031018; background: var(--cyan); }
.secondary, .ghost { color: #c8d8e3; background: #182a39; border: 1px solid #2b4254; }
.ghost { padding: 7px 10px; }
.actions { display: flex; gap: 9px; margin: 13px 0; }
.file-button { display: inline-flex; align-items: center; justify-content: center; }
.file-button input { position: absolute; width: 1px; height: 1px; opacity: 0; pointer-events: none; }
.badge { border-radius: 99px; padding: 5px 9px; font-size: .66rem; font-weight: 850; white-space: nowrap; }
.badge.neutral { color: #a8bac8; background: #1a2a37; }
.badge.good { color: var(--green); background: rgba(112, 224, 162, .1); }
.badge.bad { color: var(--red); background: rgba(255, 124, 134, .1); }
.badge.warning { color: var(--amber); background: rgba(244, 198, 107, .1); }
.score-summary { min-height: 78px; border-top: 1px solid var(--line); padding-top: 13px; display: grid; gap: 8px; }
.score-summary.empty, .comparison.empty { color: var(--muted); font-size: .84rem; }
.source-line { display: flex; justify-content: space-between; gap: 14px; color: #afc1ce; font-size: .78rem; }
.source-line strong { color: var(--text); text-align: right; overflow-wrap: anywhere; }
.score-grid, .result-strip { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }
.score-grid div, .result-strip div { background: #09131d; border: 1px solid #1d3142; border-radius: 10px; padding: 12px; display: grid; gap: 5px; }
.score-grid span, .result-strip span { color: var(--muted); font-size: .66rem; text-transform: uppercase; letter-spacing: .08em; }
.score-grid strong, .result-strip strong { font-size: 1.15rem; }
.comparison { display: grid; gap: 8px; }
.comparison-row { display: grid; grid-template-columns: 1fr auto; gap: 10px; border-bottom: 1px solid var(--line); padding: 9px 0; }
.comparison-row:last-child { border-bottom: 0; }
.comparison-row span { text-transform: capitalize; }
.comparison-row strong { font-size: .76rem; text-transform: uppercase; letter-spacing: .06em; }
.state-agreement { color: var(--green); }
.state-disagreement { color: var(--red); }
.state-missing { color: var(--amber); }
.state-not_comparable { color: var(--muted); }
.calculator-columns { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
fieldset { border: 1px solid var(--line); border-radius: 10px; display: grid; gap: 10px; padding: 12px; }
legend { color: var(--cyan); padding: 0 6px; font-size: .72rem; font-weight: 800; }
.calculator-panel .primary { width: 100%; margin: 14px 0; }
details { border-top: 1px solid var(--line); padding: 11px 0; }
summary { color: #c7d7e2; cursor: pointer; font-size: .82rem; font-weight: 700; }
pre { max-height: 250px; overflow: auto; color: #a9c1d1; background: #071019; border-radius: 8px; padding: 12px; font-size: .7rem; white-space: pre-wrap; overflow-wrap: anywhere; }
.external-links { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
.external-links a { color: var(--cyan); background: #142635; border: 1px solid #294256; }
footer { color: var(--muted); border-top: 1px solid var(--line); padding: 18px 0 34px; font-size: .76rem; }
#toast { position: fixed; right: 18px; bottom: 18px; max-width: min(420px, calc(100% - 36px)); color: var(--text); background: #152735; border: 1px solid #315068; border-radius: 9px; box-shadow: var(--shadow); padding: 11px 14px; font-size: .8rem; opacity: 0; transform: translateY(8px); pointer-events: none; transition: .18s ease; }
#toast.show { opacity: 1; transform: none; }
@media (max-width: 820px) {
  .hero { align-items: start; flex-direction: column; }
  .grid { grid-template-columns: 1fr; }
  .hero-score { width: 100%; }
}
@media (max-width: 540px) {
  .hero, main, .notice, footer { width: min(100% - 20px, 1380px); }
  .panel { padding: 15px; }
  .calculator-columns { grid-template-columns: 1fr; }
  .score-grid, .result-strip { grid-template-columns: repeat(2, 1fr); }
  .actions { flex-direction: column; }
}
"""


PAGE_JS = r"""
"use strict";

const token = document.querySelector('meta[name="atlas-lab-token"]').content;
let labState = null;

const byId = (id) => document.getElementById(id);

function showMessage(message, bad = false) {
  const toast = byId("toast");
  toast.textContent = message;
  toast.style.borderColor = bad ? "#7d3c46" : "#315068";
  toast.classList.add("show");
  window.setTimeout(() => toast.classList.remove("show"), 3200);
}

async function responseJson(response) {
  const value = await response.json();
  if (!response.ok) {
    throw new Error(value.error || "Benchmark Lab request failed");
  }
  return value;
}

async function refreshState() {
  labState = await responseJson(await fetch("/api/v1/state", {cache: "no-store"}));
  renderState();
}

function displayScore(field) {
  if (!field) return "—";
  if (field.state === "observed") return field.normalized_value;
  if (field.state === "conflicting") return "conflict";
  return field.state;
}

function addSummaryLine(parent, label, value) {
  const row = document.createElement("div");
  row.className = "source-line";
  const name = document.createElement("span");
  const data = document.createElement("strong");
  name.textContent = label;
  data.textContent = value;
  row.append(name, data);
  parent.append(row);
}

function renderSource(key, prefix) {
  const source = labState.sources[key];
  const status = byId(`${prefix}-status`);
  const summary = byId(`${prefix}-summary`);
  const evidence = byId(`${prefix}-evidence`);
  summary.replaceChildren();
  if (!source) {
    status.textContent = "Not loaded";
    status.className = "badge neutral";
    summary.className = "score-summary empty";
    summary.textContent = "Awaiting captured source bytes.";
    evidence.textContent = "No evidence loaded.";
    return;
  }
  status.textContent = "Evidence parsed";
  status.className = "badge good";
  summary.className = "score-summary";
  addSummaryLine(summary, "Native ID", source.native_submission_identifier);
  addSummaryLine(summary, "Overall", displayScore(source.scores.overall_score));
  addSummaryLine(summary, "Components", [
    displayScore(source.scores.graphics_score),
    displayScore(source.scores.physics_score),
    displayScore(source.scores.combined_score),
  ].join(" / "));
  addSummaryLine(summary, "Capture SHA", source.capture_sha256.slice(0, 18) + "…");
  const open = document.createElement("a");
  open.href = source.open_original_url;
  open.target = "_blank";
  open.rel = "noopener noreferrer";
  open.textContent = "Open authoritative source ↗";
  summary.append(open);
  evidence.textContent = JSON.stringify(source.scores, null, 2);
}

function renderEvidence() {
  const source = labState.sources.ul_3dmark || labState.sources.hwbot;
  const names = ["overall", "graphics", "physics", "combined"];
  for (const name of names) {
    byId(`evidence-${name}`).textContent = source
      ? displayScore(source.scores[`${name}_score`])
      : "—";
  }
  byId("evidence-source").textContent = source
    ? `${source.source_identifier} · ${source.submission_id} · SHA ${source.capture_sha256}`
    : "Load a source to inspect provenance.";
}

function renderComparison() {
  const box = byId("comparison");
  box.replaceChildren();
  if (!labState.comparison) {
    box.className = "comparison empty";
    box.textContent = "Load both sources to compare their presented score evidence.";
    return;
  }
  box.className = "comparison";
  for (const [name, field] of Object.entries(labState.comparison.fields)) {
    const row = document.createElement("div");
    row.className = "comparison-row";
    const label = document.createElement("span");
    label.textContent = name.replace("_score", "").replace("_", " ");
    const state = document.createElement("strong");
    state.className = `state-${field.state}`;
    state.textContent = field.state.replace("_", " ");
    row.append(label, state);
    box.append(row);
  }
}

function renderState() {
  renderSource("hwbot", "hwbot");
  renderSource("ul_3dmark", "ul");
  renderEvidence();
  renderComparison();
}

async function uploadCapture(kind, input) {
  const file = input.files[0];
  if (!file) return;
  const prefix = kind === "hwbot" ? "hwbot" : "ul";
  const status = byId(`${prefix}-status`);
  status.textContent = "Parsing…";
  status.className = "badge warning";
  try {
    const bytes = await file.arrayBuffer();
    const response = await fetch(`/api/v1/captures/${kind}`, {
      method: "POST",
      headers: {
        "Content-Type": "text/html",
        "X-Atlas-Lab-Token": token,
      },
      body: bytes,
    });
    labState = await responseJson(response);
    renderState();
    showMessage(`${kind === "hwbot" ? "HWBOT" : "UL"} evidence parsed.`);
  } catch (error) {
    status.textContent = "Parse failed";
    status.className = "badge bad";
    showMessage(error.message, true);
  } finally {
    input.value = "";
  }
}

function scoreSet(prefix) {
  return {
    graphics_score: byId(`${prefix}-graphics`).value,
    physics_score: byId(`${prefix}-physics`).value,
    combined_score: byId(`${prefix}-combined`).value,
  };
}

async function calculate() {
  try {
    const response = await fetch("/api/v1/calculations/fire-strike", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Atlas-Lab-Token": token,
      },
      body: JSON.stringify({baseline: scoreSet("base"), candidate: scoreSet("next")}),
    });
    const value = await responseJson(response);
    byId("calc-current").textContent = value.baseline.overall_score;
    byId("calc-new").textContent = value.candidate.overall_score;
    byId("calc-delta").textContent = value.delta_score;
    byId("calc-percent").textContent = `${value.percentage_delta}%`;
    showMessage("Exact Atlas calculation complete.");
  } catch (error) {
    showMessage(error.message, true);
  }
}

function loadUlComponents() {
  const source = labState && labState.sources.ul_3dmark;
  if (!source) {
    showMessage("Load UL evidence first.", true);
    return;
  }
  const values = ["graphics", "physics", "combined"].map(
    (name) => source.scores[`${name}_score`],
  );
  if (values.some((field) => field.state !== "observed")) {
    showMessage("UL component evidence is not fully observed.", true);
    return;
  }
  ["graphics", "physics", "combined"].forEach((name, index) => {
    byId(`base-${name}`).value = values[index].normalized_value;
    byId(`next-${name}`).value = values[index].normalized_value;
  });
  showMessage("UL component evidence loaded into the calculator.");
}

function openReference(inputId, allowedHosts) {
  try {
    const url = new URL(byId(inputId).value);
    if (url.protocol !== "https:" || !allowedHosts.includes(url.hostname)) {
      throw new Error("Reference must use the supported HTTPS source host.");
    }
    window.open(url.href, "_blank", "noopener,noreferrer");
  } catch (error) {
    showMessage(error.message, true);
  }
}

async function resetLab() {
  try {
    const response = await fetch("/api/v1/reset", {
      method: "POST",
      headers: {"X-Atlas-Lab-Token": token, "Content-Type": "application/json"},
      body: "{}",
    });
    labState = await responseJson(response);
    renderState();
    showMessage("Local lab state cleared.");
  } catch (error) {
    showMessage(error.message, true);
  }
}

byId("hwbot-file").addEventListener("change", (event) => uploadCapture("hwbot", event.target));
byId("ul-file").addEventListener("change", (event) => uploadCapture("ul-3dmark", event.target));
byId("calculate").addEventListener("click", calculate);
byId("load-ul").addEventListener("click", loadUlComponents);
byId("reset").addEventListener("click", resetLab);
byId("hwbot-open").addEventListener("click", () => openReference("hwbot-url", ["hwbot.org", "www.hwbot.org"]));
byId("ul-open").addEventListener("click", () => openReference("ul-url", ["3dmark.com", "www.3dmark.com"]));

refreshState().catch((error) => showMessage(error.message, true));
"""
