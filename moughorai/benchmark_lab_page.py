"""Self-contained presentation assets for the local Benchmark Lab workspace."""

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
  <header class="topbar">
    <div class="brand">
      <p class="eyebrow">ATLAS AI OC · BENCHMARK LAB</p>
      <h1>Fire Strike <span>HWBOT Workspace</span></h1>
    </div>
    <button id="reset" class="ghost" type="button">Reset local session</button>
  </header>

  <section class="search-deck" aria-label="Workspace searches">
    <form id="hwbot-search-form" class="search-row">
      <label for="hwbot-search">HWBOT Search</label>
      <input id="hwbot-search" type="search" autocomplete="off" placeholder="Search HWBOT">
      <button class="primary" type="submit">Search HWBOT ↗</button>
      <small>Opens HWBOT's own search in a new top-level tab.</small>
    </form>
    <form id="atlas-search-form" class="search-row">
      <label for="atlas-search">Atlas Search — Current session</label>
      <input id="atlas-search" type="search" maxlength="128" autocomplete="off" placeholder="Source, ID, benchmark, or observed score">
      <button class="secondary" type="submit">Search</button>
      <small>Only currently parsed local evidence; no historical index yet.</small>
    </form>
  </section>

  <div class="offline-notice">
    <strong>External browsing + offline evidence.</strong>
    HWBOT framing is blocked, so browsing opens externally. Atlas does not fetch source URLs,
    render captured third-party HTML, or infer that two equal scores are the same run.
  </div>

  <main>
    <div class="upper-workspace">
      <section class="panel hwbot-workspace" aria-labelledby="hwbot-workspace-title">
        <div class="panel-head">
          <div><p class="eyebrow">PRIMARY BROWSING SURFACE</p><h2 id="hwbot-workspace-title">HWBOT WORKSPACE</h2></div>
          <span id="hwbot-status" class="badge neutral">NO SOURCE CAPTURE</span>
        </div>

        <nav class="quick-actions" aria-label="Fixed HWBOT quick actions">
          <a href="https://hwbot.org/" target="_blank" rel="noopener noreferrer">Home ↗</a>
          <a href="https://hwbot.org/benchmarks/3dmark_-_fire_strike" target="_blank" rel="noopener noreferrer">Fire Strike ↗</a>
          <a href="https://hwbot.org/benchmarks/3dmark_-_fire_strike/rankings" target="_blank" rel="noopener noreferrer">Rankings ↗</a>
          <a href="https://hwbot.org/submissions" target="_blank" rel="noopener noreferrer">Submissions ↗</a>
          <a href="https://hwbot.org/users" target="_blank" rel="noopener noreferrer">Members ↗</a>
        </nav>

        <div class="reference-row">
          <label for="hwbot-reference">HWBOT reference URL
            <input id="hwbot-reference" type="url" autocomplete="off" spellcheck="false" value="https://hwbot.org/benchmarks/3dmark_-_fire_strike/submissions/">
          </label>
          <div class="actions aligned">
            <button id="detect-hwbot" class="secondary" type="button">Detect</button>
            <button id="open-hwbot-reference" class="ghost" type="button" disabled>Open external ↗</button>
          </div>
        </div>
        <p class="microcopy">A detected path is navigation context only. It never becomes benchmark evidence.</p>

        <div class="source-view">
          <div class="source-view-head">
            <div><p class="eyebrow">ATLAS SOURCE VIEW — NOT LIVE HWBOT</p><h3>Local parsed representation</h3></div>
            <label class="file-button">Upload saved HWBOT HTML
              <input id="hwbot-file" type="file" accept="text/html,.html,.htm">
            </label>
          </div>
          <div id="hwbot-route" class="route-state">No HWBOT reference URL detected.</div>
          <div id="hwbot-summary" class="source-summary empty">Awaiting user-selected captured source bytes.</div>
        </div>

        <section class="atlas-results" aria-labelledby="atlas-results-title">
          <h3 id="atlas-results-title">Atlas Search results</h3>
          <div id="atlas-results" class="empty">No parsed local evidence. Historical Benchmark Intelligence is not indexed yet.</div>
        </section>
      </section>

      <aside class="panel sidecar" aria-labelledby="sidecar-title">
        <div class="panel-head compact"><div><p class="eyebrow">DETERMINISTIC SIDECAR</p><h2 id="sidecar-title">ATLAS INTELLIGENCE</h2></div></div>
        <div class="tabs" role="tablist" aria-label="Atlas intelligence views">
          <button class="tab active" type="button" role="tab" data-tab="atlas">ATLAS</button>
          <button class="tab" type="button" role="tab" data-tab="threedmark">3DMARK</button>
          <button class="tab" type="button" role="tab" data-tab="compare">COMPARE</button>
          <button class="tab" type="button" role="tab" data-tab="evidence">EVIDENCE</button>
        </div>

        <section id="tab-atlas" class="tab-panel active" data-panel="atlas">
          <div class="fact-list">
            <div><span>URL detection</span><strong id="atlas-route-state">None</strong></div>
            <div><span>Capture state</span><strong id="atlas-capture-state">NO SOURCE CAPTURE</strong></div>
            <div><span>Benchmark</span><strong id="atlas-benchmark">—</strong></div>
            <div><span>Native ID</span><strong id="atlas-native">—</strong></div>
            <div><span>Overall</span><strong id="atlas-overall">—</strong></div>
            <div><span>Capture SHA-256</span><strong id="atlas-capture-sha">—</strong></div>
          </div>
          <button id="analyze" class="primary full" type="button" disabled>Analyze deterministic evidence</button>
          <p class="microcopy">Analyze inspects parsed evidence and calculation only. It is not an OC recommendation.</p>
        </section>

        <section id="tab-threedmark" class="tab-panel" data-panel="threedmark" hidden>
          <div class="side-actions">
            <label class="file-button">Upload saved UL HTML
              <input id="ul-file" type="file" accept="text/html,.html,.htm">
            </label>
            <button id="open-3dmark" class="ghost" type="button" disabled>Open 3DMark ↗</button>
          </div>
          <span id="ul-status" class="badge neutral">NO SOURCE CAPTURE</span>
          <div id="ul-summary" class="source-summary empty">Awaiting user-selected saved UL result HTML.</div>
          <button id="load-ul" class="secondary full" type="button" disabled>Load unique UL components into CURRENT</button>
        </section>

        <section id="tab-compare" class="tab-panel" data-panel="compare" hidden>
          <span class="badge warning">Run linkage unknown</span>
          <div id="comparison" class="comparison empty">Load both sources to compare presented score evidence.</div>
          <p class="microcopy">Equal scores mean agreement only. They do not establish one physical run.</p>
        </section>

        <section id="tab-evidence" class="tab-panel" data-panel="evidence" hidden>
          <details open><summary>HWBOT field evidence</summary><pre id="hwbot-evidence">No evidence loaded.</pre></details>
          <details><summary>UL / 3DMark field evidence</summary><pre id="ul-evidence">No evidence loaded.</pre></details>
          <p class="microcopy">Raw captured HTML is never returned to or rendered by this page.</p>
        </section>
      </aside>
    </div>

    <section class="panel calculator-workspace" aria-labelledby="calculator-title">
      <div class="panel-head compact">
        <div><p class="eyebrow">PR150 · SERVER-AUTHORITATIVE</p><h2 id="calculator-title">FIRE STRIKE WORKSPACE</h2></div>
        <button id="calculate" class="primary" type="button">Calculate atomic snapshot</button>
      </div>
      <div class="calculator-grid">
        <fieldset>
          <legend>CURRENT</legend>
          <label>Graphics <input id="base-graphics" inputmode="numeric" value="22447"></label>
          <label>Physics <input id="base-physics" inputmode="numeric" value="56270"></label>
          <label>Combined <input id="base-combined" inputmode="numeric" value="7668"></label>
          <output><span>Atlas-derived Overall</span><strong id="calc-current">—</strong></output>
        </fieldset>
        <fieldset>
          <legend>WHAT IF</legend>
          <label>Graphics <input id="next-graphics" inputmode="numeric" value="22447"></label>
          <label>Physics <input id="next-physics" inputmode="numeric" value="56270"></label>
          <label>Combined <input id="next-combined" inputmode="numeric" value="7668"></label>
          <output><span>Atlas-derived Overall</span><strong id="calc-new">—</strong></output>
          <div class="delta-line"><span>Delta</span><strong id="calc-delta">—</strong><span id="calc-percent">—</span></div>
        </fieldset>
        <section class="sensitivity" aria-labelledby="sensitivity-title">
          <p class="eyebrow">DETERMINISTIC SCENARIOS</p>
          <h3 id="sensitivity-title">+1% SENSITIVITY</h3>
          <p class="microcopy">+1% sensitivity, rounded up to a whole mark</p>
          <div id="sensitivity-results" class="sensitivity-list empty">Calculate CURRENT to model component effects.</div>
          <div class="largest-effect"><span>Largest modeled component-score effect</span><strong id="largest-effect">—</strong></div>
        </section>
      </div>
      <p class="microcopy">One server request receives one immutable CURRENT + WHAT IF snapshot. Atlas calculated values are derived, not source observations.</p>
      <div class="external-links">
        <a href="https://hwbot.org/benchmarks/3dmark_-_fire_strike" target="_blank" rel="noopener noreferrer">Open HWBOT</a>
        <a href="https://www.3dmark.com/" target="_blank" rel="noopener noreferrer">Open 3DMark</a>
        <a href="https://elmor.se/3dmark" target="_blank" rel="noopener noreferrer">Open Elmor reference</a>
      </div>
    </section>
  </main>

  <footer>
    Parsed means the captured source presented these values. It does not establish validity,
    eligibility, stability, safe tuning, recommendation, or same-run linkage.
  </footer>
  <div id="toast" role="status" aria-live="polite"></div>
  <script src="/app.js" defer></script>
</body>
</html>
"""


PAGE_CSS = """
:root { color-scheme: dark; --bg: #050b11; --surface: #0b151f; --line: #243746; --text: #edf5fa; --muted: #91a6b5; --cyan: #39d7ff; --green: #70e0a2; --amber: #f4c66b; --red: #ff7c86; --shadow: 0 18px 48px rgba(0,0,0,.30); }
* { box-sizing: border-box; }
body { margin: 0; min-height: 100vh; color: var(--text); background: linear-gradient(90deg,rgba(57,215,255,.035) 1px,transparent 1px) 0 0/42px 42px, radial-gradient(circle at 72% -5%,rgba(57,215,255,.13),transparent 32rem), var(--bg); font-family: Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }
.topbar,.search-deck,.offline-notice,main,footer { width: min(1500px,calc(100% - 30px)); margin-inline: auto; }
.topbar { display:flex; align-items:center; justify-content:space-between; gap:20px; padding:25px 0 15px; }
.brand h1 { margin:3px 0 0; font-size:clamp(1.55rem,3vw,2.5rem); letter-spacing:-.035em; }
.brand h1 span { color:var(--muted); font-weight:500; }
.eyebrow { margin:0; color:var(--cyan); font-size:.68rem; letter-spacing:.18em; font-weight:850; }
.search-deck { display:grid; grid-template-columns:1fr 1fr; gap:10px; padding-bottom:11px; }
.search-row { display:grid; grid-template-columns:auto minmax(130px,1fr) auto; align-items:center; gap:9px; background:rgba(11,21,31,.94); border:1px solid var(--line); border-radius:10px; padding:9px; }
.search-row>label { white-space:nowrap; } .search-row small { grid-column:2/-1; }
.offline-notice { padding:10px 13px; border:1px solid rgba(244,198,107,.28); background:rgba(244,198,107,.055); border-radius:9px; color:#c7d4dc; font-size:.76rem; }
main { padding:12px 0 32px; display:grid; gap:12px; }
.upper-workspace { display:grid; grid-template-columns:minmax(0,3fr) minmax(310px,1fr); gap:12px; min-height:590px; }
.panel { min-width:0; background:linear-gradient(145deg,rgba(16,30,42,.97),rgba(7,16,24,.98)); border:1px solid var(--line); border-radius:13px; padding:17px; box-shadow:var(--shadow); }
.hwbot-workspace { border-top:2px solid var(--cyan); } .sidecar { border-top:2px solid var(--green); }
.panel-head { display:flex; justify-content:space-between; align-items:start; gap:14px; margin-bottom:14px; } .panel-head.compact { margin-bottom:11px; }
h2 { margin:3px 0 0; font-size:1.08rem; letter-spacing:.025em; } h3 { margin:3px 0 8px; font-size:.93rem; }
label { color:#c8d6df; font-size:.76rem; font-weight:750; }
input { width:100%; border:1px solid #294050; border-radius:7px; padding:9px 10px; color:var(--text); background:#07111a; outline:none; font:inherit; }
input:focus { border-color:var(--cyan); box-shadow:0 0 0 3px rgba(57,215,255,.10); }
button,.file-button,.quick-actions a,.external-links a { border:0; border-radius:7px; padding:9px 11px; font:inherit; font-size:.74rem; font-weight:800; cursor:pointer; text-decoration:none; }
button:disabled { opacity:.42; cursor:not-allowed; }
.primary,.file-button { color:#031018; background:var(--cyan); }
.secondary { color:#d7e5ed; background:#173044; border:1px solid #31536a; }
.ghost,.quick-actions a,.external-links a { color:#c8d7e1; background:#132430; border:1px solid #2a4050; }
.full { width:100%; margin-top:12px; } .actions { display:flex; gap:8px; } .actions.aligned { align-self:end; }
.file-button { display:inline-flex; align-items:center; justify-content:center; } .file-button input { position:absolute; width:1px; height:1px; opacity:0; pointer-events:none; }
.quick-actions { display:flex; flex-wrap:wrap; gap:7px; padding-bottom:13px; border-bottom:1px solid var(--line); }
.quick-actions a:hover,.external-links a:hover { color:var(--cyan); border-color:#35546b; }
.reference-row { display:grid; grid-template-columns:1fr auto; gap:10px; margin-top:14px; } .reference-row label { display:grid; gap:6px; }
.microcopy,.search-row small,.muted { color:var(--muted); font-size:.70rem; line-height:1.45; }
.source-view { margin-top:13px; padding:14px; min-height:245px; border:1px solid #284152; border-radius:10px; background:rgba(5,13,20,.66); }
.source-view-head { display:flex; align-items:start; justify-content:space-between; gap:12px; }
.route-state { margin:10px 0; padding:9px; color:#bed0dc; border-left:2px solid var(--amber); background:rgba(244,198,107,.045); font-size:.76rem; overflow-wrap:anywhere; }
.badge { display:inline-flex; border-radius:99px; padding:5px 8px; font-size:.61rem; font-weight:850; white-space:nowrap; }
.badge.neutral { color:#afc1cd; background:#192b38; } .badge.good { color:var(--green); background:rgba(112,224,162,.10); } .badge.bad { color:var(--red); background:rgba(255,124,134,.10); } .badge.warning { color:var(--amber); background:rgba(244,198,107,.10); }
.source-summary { display:grid; gap:7px; } .source-summary.empty,.comparison.empty,.atlas-results .empty,.sensitivity-list.empty { color:var(--muted); font-size:.78rem; }
.source-line { display:grid; grid-template-columns:minmax(95px,.5fr) 1fr; gap:10px; border-bottom:1px solid rgba(36,55,70,.65); padding:6px 0; font-size:.75rem; }
.source-line span { color:var(--muted); } .source-line strong { text-align:right; overflow-wrap:anywhere; }
.atlas-results { margin-top:12px; border-top:1px solid var(--line); padding-top:11px; }
.search-result { display:grid; gap:4px; padding:8px; margin-top:6px; background:#09151f; border:1px solid #1f3545; border-radius:7px; font-size:.74rem; }
.tabs { display:grid; grid-template-columns:repeat(4,1fr); gap:4px; margin-bottom:12px; }
.tab { padding-inline:5px; color:var(--muted); background:#09141d; border:1px solid #213543; } .tab.active { color:var(--cyan); border-color:#32708d; background:rgba(57,215,255,.07); }
.tab-panel { min-height:425px; }
.fact-list { display:grid; } .fact-list div { display:grid; grid-template-columns:.75fr 1.25fr; gap:8px; border-bottom:1px solid var(--line); padding:9px 0; font-size:.72rem; }
.fact-list span { color:var(--muted); } .fact-list strong { text-align:right; overflow-wrap:anywhere; }
.side-actions { display:flex; gap:7px; flex-wrap:wrap; margin-bottom:11px; }
.comparison { display:grid; gap:2px; margin-top:10px; } .comparison-row { display:grid; grid-template-columns:1fr auto; gap:8px; border-bottom:1px solid var(--line); padding:8px 0; font-size:.74rem; }
.comparison-row strong { font-size:.67rem; text-transform:uppercase; letter-spacing:.05em; } .state-agreement { color:var(--green); } .state-disagreement { color:var(--red); } .state-missing { color:var(--amber); } .state-not_comparable { color:var(--muted); }
details { border-top:1px solid var(--line); padding:9px 0; } summary { color:#c7d8e2; cursor:pointer; font-size:.75rem; font-weight:750; }
pre { max-height:240px; overflow:auto; color:#a8becc; background:#050c12; border-radius:7px; padding:10px; font-size:.65rem; white-space:pre-wrap; overflow-wrap:anywhere; }
.calculator-workspace { border-top:2px solid var(--cyan); } .calculator-grid { display:grid; grid-template-columns:1fr 1fr 1.35fr; gap:11px; }
fieldset,.sensitivity { min-width:0; border:1px solid var(--line); border-radius:9px; padding:12px; } fieldset { display:grid; gap:8px; }
fieldset label { display:grid; grid-template-columns:75px 1fr; align-items:center; gap:7px; } legend { color:var(--cyan); padding:0 6px; font-size:.71rem; font-weight:850; letter-spacing:.08em; }
output,.delta-line,.largest-effect { display:flex; justify-content:space-between; align-items:center; gap:8px; padding-top:9px; border-top:1px solid var(--line); }
output span,.delta-line span,.largest-effect span { color:var(--muted); font-size:.68rem; } output strong { font-size:1.2rem; }
.sensitivity-list { display:grid; gap:6px; margin:9px 0; } .sensitivity-row { display:grid; grid-template-columns:1fr auto auto; gap:8px; padding:7px; background:#08141d; border-radius:6px; font-size:.71rem; }
.sensitivity-row span { color:var(--muted); } .sensitivity-row strong:last-child { color:var(--green); }
.external-links { display:flex; flex-wrap:wrap; gap:7px; margin-top:10px; }
footer { color:var(--muted); border-top:1px solid var(--line); padding:15px 0 28px; font-size:.72rem; }
#toast { position:fixed; right:16px; bottom:16px; max-width:min(430px,calc(100% - 32px)); color:var(--text); background:#142634; border:1px solid #315068; border-radius:8px; box-shadow:var(--shadow); padding:10px 13px; font-size:.76rem; opacity:0; transform:translateY(8px); pointer-events:none; transition:.18s ease; }
#toast.show { opacity:1; transform:none; }
@media (max-width:980px) { .search-deck,.upper-workspace { grid-template-columns:1fr; } .tab-panel { min-height:auto; } .calculator-grid { grid-template-columns:1fr 1fr; } .sensitivity { grid-column:1/-1; } }
@media (max-width:650px) { .topbar,.source-view-head { align-items:start; flex-direction:column; } .search-row { grid-template-columns:1fr; } .search-row small { grid-column:auto; } .reference-row,.calculator-grid { grid-template-columns:1fr; } .sensitivity { grid-column:auto; } .actions.aligned { align-self:auto; } .tabs { grid-template-columns:repeat(2,1fr); } }
"""


PAGE_JS = r"""
"use strict";

const token = document.querySelector('meta[name="atlas-lab-token"]').content;
const byId = (id) => document.getElementById(id);
const channels = new Map();
let labState = null;
let hwbotDetection = null;
let captureStates = {hwbot: "NO SOURCE CAPTURE", ul_3dmark: "NO SOURCE CAPTURE"};

function beginRequest(channel) {
  const previous = channels.get(channel);
  if (previous) previous.controller.abort();
  const generation = previous ? previous.generation + 1 : 1;
  const controller = new AbortController();
  const request = {channel, controller, generation};
  channels.set(channel, request);
  return request;
}

function isCurrent(request) {
  const current = channels.get(request.channel);
  return Boolean(current && current.generation === request.generation);
}

function invalidate(channel) {
  const previous = channels.get(channel);
  if (previous) previous.controller.abort();
  channels.set(channel, {channel, controller: new AbortController(), generation: previous ? previous.generation + 1 : 1});
}

function invalidateAll() {
  for (const channel of ["state", "detect", "search", "calculation"]) invalidate(channel);
}

function showMessage(message, bad = false) {
  const toast = byId("toast");
  toast.textContent = message;
  toast.style.borderColor = bad ? "#7d3c46" : "#315068";
  toast.classList.add("show");
  window.setTimeout(() => toast.classList.remove("show"), 3200);
}

async function responseJson(response) {
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || "Benchmark Lab request failed");
  return value;
}

async function postJson(path, value, request) {
  return responseJson(await fetch(path, {
    method: "POST",
    headers: {"Content-Type": "application/json", "X-Atlas-Lab-Token": token},
    body: JSON.stringify(value),
    signal: request.controller.signal,
  }));
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

function setCaptureBadge(prefix, state) {
  const status = byId(`${prefix}-status`);
  status.textContent = state;
  status.className = "badge " + (state === "CAPTURED AND PARSED" ? "good" : state === "PARSE FAILED" ? "bad" : state === "CAPTURE UPLOADED — PARSING" || state === "URL DETECTED — NOT EVIDENCE" ? "warning" : "neutral");
}

function renderSource(key, prefix) {
  const source = labState && labState.sources[key];
  const summary = byId(`${prefix}-summary`);
  const evidence = byId(`${prefix}-evidence`);
  summary.replaceChildren();
  setCaptureBadge(prefix, captureStates[key]);
  if (!source) {
    summary.className = "source-summary empty";
    summary.textContent = key === "hwbot" ? "Awaiting user-selected captured source bytes." : "Awaiting user-selected saved UL result HTML.";
    evidence.textContent = "No evidence loaded.";
    return;
  }
  summary.className = "source-summary";
  addSummaryLine(summary, "Benchmark", source.benchmark_id);
  addSummaryLine(summary, "Native ID", source.native_submission_identifier);
  addSummaryLine(summary, "Overall", displayScore(source.scores.overall_score));
  addSummaryLine(summary, "Graphics", displayScore(source.scores.graphics_score));
  addSummaryLine(summary, "Physics", displayScore(source.scores.physics_score));
  addSummaryLine(summary, "Combined", displayScore(source.scores.combined_score));
  addSummaryLine(summary, "Capture SHA-256", source.capture_sha256);
  evidence.textContent = JSON.stringify({
    canonical_sha256: source.canonical_sha256,
    capture_sha256: source.capture_sha256,
    native_submission_identifier: source.native_submission_identifier,
    scores: source.scores,
    source_identifier: source.source_identifier,
    submission_id: source.submission_id,
  }, null, 2);
}

function renderAtlas() {
  const source = labState && labState.sources.hwbot;
  byId("atlas-route-state").textContent = hwbotDetection ? `${hwbotDetection.route_family} · navigation only` : "None";
  byId("atlas-capture-state").textContent = captureStates.hwbot;
  byId("atlas-benchmark").textContent = source ? source.benchmark_id : "—";
  byId("atlas-native").textContent = source ? source.native_submission_identifier : "—";
  byId("atlas-overall").textContent = source ? displayScore(source.scores.overall_score) : "—";
  byId("atlas-capture-sha").textContent = source ? source.capture_sha256 : "—";
  byId("analyze").disabled = !source;
  byId("open-hwbot-reference").disabled = !hwbotDetection;
  byId("open-3dmark").disabled = !(labState && labState.sources.ul_3dmark);
  byId("load-ul").disabled = !(labState && labState.sources.ul_3dmark);
}

function renderRoute() {
  const box = byId("hwbot-route");
  if (!hwbotDetection) { box.textContent = "No HWBOT reference URL detected."; return; }
  const parts = [`Route: ${hwbotDetection.route_family}`, `Authority: ${hwbotDetection.authority}`, `Semantic evidence: ${String(hwbotDetection.semantic_evidence)}`];
  if (hwbotDetection.path_submission_segment) parts.push(`Unverified path ID: ${hwbotDetection.path_submission_segment}`);
  const comparison = hwbotDetection.capture_comparison;
  if (comparison && comparison.parsed_native_submission_identifier) parts.push(`Parser-native ID: ${comparison.parsed_native_submission_identifier}`);
  if (comparison && comparison.warning) parts.push(`WARNING: ${comparison.warning}`);
  box.textContent = parts.join(" · ");
}

function renderComparison() {
  const box = byId("comparison");
  box.replaceChildren();
  if (!labState || !labState.comparison) {
    box.className = "comparison empty";
    box.textContent = "Load both sources to compare presented score evidence.";
    return;
  }
  box.className = "comparison";
  for (const [name, field] of Object.entries(labState.comparison.fields)) {
    const row = document.createElement("div"); row.className = "comparison-row";
    const label = document.createElement("span"); label.textContent = name.replace("_score", "").replace("_", " ");
    const state = document.createElement("strong"); state.className = `state-${field.state}`; state.textContent = field.state.replace("_", " ");
    row.append(label, state); box.append(row);
  }
}

function renderState() {
  renderSource("hwbot", "hwbot"); renderSource("ul_3dmark", "ul"); renderAtlas(); renderRoute(); renderComparison();
}

async function refreshState() {
  const request = beginRequest("state");
  try {
    const value = await responseJson(await fetch("/api/v1/state", {cache:"no-store", signal:request.controller.signal}));
    if (!isCurrent(request)) return;
    labState = value;
    captureStates = {hwbot:value.sources.hwbot ? "CAPTURED AND PARSED" : "NO SOURCE CAPTURE", ul_3dmark:value.sources.ul_3dmark ? "CAPTURED AND PARSED" : "NO SOURCE CAPTURE"};
    renderState();
  } catch (error) { if (error.name !== "AbortError" && isCurrent(request)) showMessage(error.message, true); }
}

async function uploadCapture(kind, input) {
  const file = input.files[0]; if (!file) return;
  const key = kind === "hwbot" ? "hwbot" : "ul_3dmark";
  invalidate("search");
  if (kind === "hwbot") invalidate("detect");
  const request = beginRequest("state");
  captureStates[key] = "CAPTURE UPLOADED — PARSING"; renderState();
  try {
    const bytes = await file.arrayBuffer();
    if (!isCurrent(request)) return;
    const response = await fetch(`/api/v1/captures/${kind}`, {method:"POST", headers:{"Content-Type":"text/html","X-Atlas-Lab-Token":token}, body:bytes, signal:request.controller.signal});
    const value = await responseJson(response);
    if (!isCurrent(request)) return;
    labState = value; captureStates[key] = "CAPTURED AND PARSED";
    invalidate("search"); renderSearchResults([]); renderState();
    if (kind === "hwbot" && hwbotDetection) await detectReference();
    showMessage(`${kind === "hwbot" ? "HWBOT" : "UL / 3DMark"} evidence parsed.`);
  } catch (error) {
    if (error.name !== "AbortError" && isCurrent(request)) { captureStates[key] = "PARSE FAILED"; renderState(); showMessage(error.message, true); }
  } finally { input.value = ""; }
}

async function detectReference() {
  const request = beginRequest("detect");
  try {
    const value = await postJson("/api/v1/navigation/hwbot/detect", {url:byId("hwbot-reference").value}, request);
    if (!isCurrent(request)) return;
    hwbotDetection = {...value.detection, capture_comparison:value.capture_comparison};
    if (!(labState && labState.sources.hwbot)) captureStates.hwbot = "URL DETECTED — NOT EVIDENCE";
    renderState();
  } catch (error) { if (error.name !== "AbortError" && isCurrent(request)) showMessage(error.message, true); }
}

function safeOpen(value, hosts) {
  try {
    const url = new URL(value);
    if (url.protocol !== "https:" || url.username || url.password || url.port || !hosts.includes(url.hostname)) throw new Error("External destination is outside the fixed HTTPS allowlist.");
    window.open(url.href, "_blank", "noopener,noreferrer");
  } catch (error) { showMessage(error.message, true); }
}

function searchHwbot(event) {
  event.preventDefault();
  const url = new URL("/search", "https://hwbot.org");
  url.searchParams.set("query", byId("hwbot-search").value);
  safeOpen(url.href, ["hwbot.org"]);
}

async function searchAtlas(event) {
  event.preventDefault(); const request = beginRequest("search");
  try {
    const value = await postJson("/api/v1/search/current-session", {query:byId("atlas-search").value}, request);
    if (isCurrent(request)) renderSearchResults(value.results);
  } catch (error) { if (error.name !== "AbortError" && isCurrent(request)) showMessage(error.message, true); }
}

function renderSearchResults(results) {
  const box = byId("atlas-results"); box.replaceChildren();
  if (!results.length) {
    box.className = "empty";
    box.textContent = labState && (labState.sources.hwbot || labState.sources.ul_3dmark) ? "No current-session evidence matched." : "No parsed local evidence. Historical Benchmark Intelligence is not indexed yet.";
    return;
  }
  box.className = "";
  for (const result of results) {
    const row = document.createElement("div"); row.className = "search-result";
    const title = document.createElement("strong"); title.textContent = `${result.source_label} · ${result.native_submission_identifier}`;
    const detail = document.createElement("span"); detail.textContent = `Matched: ${result.matched_fields.join(", ")}`;
    row.append(title, detail); box.append(row);
  }
}

function scoreSet(prefix) {
  return Object.freeze({graphics_score:byId(`${prefix}-graphics`).value, physics_score:byId(`${prefix}-physics`).value, combined_score:byId(`${prefix}-combined`).value});
}

async function calculate() {
  const request = beginRequest("calculation");
  const snapshot = Object.freeze({baseline:scoreSet("base"), candidate:scoreSet("next")});
  try {
    const value = await postJson("/api/v1/calculations/fire-strike", snapshot, request);
    if (!isCurrent(request)) return;
    byId("calc-current").textContent = value.baseline.overall_score;
    byId("calc-new").textContent = value.candidate.overall_score;
    byId("calc-delta").textContent = value.delta_score;
    byId("calc-percent").textContent = `${value.percentage_delta}%`;
    renderSensitivity(value.sensitivity);
    showMessage("Exact Atlas calculation and sensitivity complete.");
  } catch (error) { if (error.name !== "AbortError" && isCurrent(request)) showMessage(error.message, true); }
}

function renderSensitivity(value) {
  const box = byId("sensitivity-results"); box.replaceChildren(); box.className = "sensitivity-list";
  const labels = {graphics_score:"Graphics", physics_score:"Physics", combined_score:"Combined"};
  for (const scenario of value.scenarios) {
    const row = document.createElement("div"); row.className = "sensitivity-row";
    const label = document.createElement("span"); label.textContent = labels[scenario.component];
    const target = document.createElement("strong"); target.textContent = `→ ${scenario.candidate_component_score} / ${scenario.calculated_overall_score}`;
    const delta = document.createElement("strong"); delta.textContent = `+${scenario.overall_delta}`;
    row.append(label, target, delta); box.append(row);
  }
  byId("largest-effect").textContent = value.largest_delta_components.map((item) => labels[item]).join(" / ");
}

function clearCalculation() {
  invalidate("calculation");
  for (const id of ["calc-current","calc-new","calc-delta","calc-percent","largest-effect"]) byId(id).textContent = "—";
  const box = byId("sensitivity-results"); box.replaceChildren(); box.className = "sensitivity-list empty"; box.textContent = "Calculate CURRENT to model component effects.";
}

function loadUlComponents() {
  const source = labState && labState.sources.ul_3dmark;
  if (!source) { showMessage("Load UL evidence first.", true); return; }
  const names = ["graphics","physics","combined"];
  const values = names.map((name) => source.scores[`${name}_score`]);
  if (values.some((field) => field.state !== "observed")) { showMessage("UL component evidence is not uniquely observed.", true); return; }
  names.forEach((name,index) => { byId(`base-${name}`).value = values[index].normalized_value; byId(`next-${name}`).value = values[index].normalized_value; });
  clearCalculation(); showMessage("Unique UL components loaded into CURRENT and WHAT IF.");
}

async function resetLab() {
  invalidateAll(); const request = beginRequest("state");
  try {
    const value = await postJson("/api/v1/reset", {}, request);
    if (!isCurrent(request)) return;
    labState = value; hwbotDetection = null; captureStates = {hwbot:"NO SOURCE CAPTURE",ul_3dmark:"NO SOURCE CAPTURE"};
    renderSearchResults([]); clearCalculation(); renderState(); showMessage("Local Benchmark Lab session cleared.");
  } catch (error) { if (error.name !== "AbortError" && isCurrent(request)) showMessage(error.message, true); }
}

function activateTab(name) {
  for (const button of document.querySelectorAll("[data-tab]")) button.classList.toggle("active", button.dataset.tab === name);
  for (const panel of document.querySelectorAll("[data-panel]")) { const active = panel.dataset.panel === name; panel.classList.toggle("active", active); panel.hidden = !active; }
}

for (const button of document.querySelectorAll("[data-tab]")) button.addEventListener("click", () => activateTab(button.dataset.tab));
for (const id of ["base-graphics","base-physics","base-combined","next-graphics","next-physics","next-combined"]) byId(id).addEventListener("input", clearCalculation);
byId("hwbot-reference").addEventListener("input", () => { invalidate("detect"); hwbotDetection = null; if (!(labState && labState.sources.hwbot)) captureStates.hwbot = "NO SOURCE CAPTURE"; renderState(); });
byId("hwbot-search-form").addEventListener("submit", searchHwbot);
byId("atlas-search-form").addEventListener("submit", searchAtlas);
byId("detect-hwbot").addEventListener("click", detectReference);
byId("open-hwbot-reference").addEventListener("click", () => {
  if (hwbotDetection) safeOpen(hwbotDetection.normalized_reference_url, ["hwbot.org"]);
});
byId("hwbot-file").addEventListener("change", (event) => uploadCapture("hwbot", event.target));
byId("ul-file").addEventListener("change", (event) => uploadCapture("ul-3dmark", event.target));
byId("calculate").addEventListener("click", calculate);
byId("load-ul").addEventListener("click", loadUlComponents);
byId("open-3dmark").addEventListener("click", () => { const source = labState && labState.sources.ul_3dmark; if (source) safeOpen(source.open_original_url,["www.3dmark.com"]); });
byId("analyze").addEventListener("click", () => activateTab("evidence"));
byId("reset").addEventListener("click", resetLab);

refreshState();
"""
