// HashRing dashboard: polls the gateway and draws the ring, nodes, traffic and events.

const POLL_MS = 500;
const R = 200; // ring radius in SVG units
const HISTORY = 60; // chart points (60 x 0.5 s = 30 s)
const KEY_RE = /^[A-Za-z0-9_.:-]{1,200}$/;
const PALETTE = ["#7F77DD", "#1D9E75", "#D85A30", "#D4537E", "#378ADD", "#BA7517", "#639922", "#E24B4A"];

// ---- small helpers -------------------------------------------------------

const colors = new Map();
function color(name) {
  if (!colors.has(name)) colors.set(name, PALETTE[colors.size % PALETTE.length]);
  return colors.get(name);
}

function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

const $ = (id) => document.getElementById(id);

async function api(path, options = {}) {
  const r = await fetch(path, {
    ...options,
    headers: options.body ? { "Content-Type": "application/json" } : undefined,
  });
  const body = await r.json().catch(() => null);
  if (!r.ok) {
    const err = new Error(`HTTP ${r.status}`);
    err.status = r.status;
    err.body = body;
    throw err;
  }
  return body;
}

function errorText(e) {
  const d = e.body && e.body.detail;
  if (typeof d === "string") return d;
  if (d && d.error) return d.error;
  return e.message;
}

// Position (0 .. 2^32) -> angle on screen, 12 o'clock is 0, clockwise.
function angle(pos, size) {
  return (pos / size) * 2 * Math.PI - Math.PI / 2;
}
function xy(pos, size, r) {
  const a = angle(pos, size);
  return [r * Math.cos(a), r * Math.sin(a)];
}

// Same binary search as Python's bisect_left, but it also records each step.
function bisectLeft(arr, x, steps) {
  let lo = 0;
  let hi = arr.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    steps.push({ lo, hi, mid, value: arr[mid], goRight: arr[mid] < x });
    if (arr[mid] < x) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

// ---- state -----------------------------------------------------------------

let snap = null; // last /cluster answer
let prevRequests = null; // requests per node at the previous poll
let prevTime = null;
const history = []; // [{A: rate, B: rate, ...}]
let lastEventTime = 0;
let lookup = null; // {key, position, stored}
let rateTouched = false;

// ---- ring drawing ----------------------------------------------------------

const ringSvg = d3.select("#ring");
ringSvg.append("circle").attr("class", "track").attr("r", R);
const gPoints = ringSvg.append("g");
const gParticles = ringSvg.append("g");
const gLookup = ringSvg.append("g");
const centerBig = ringSvg.append("text").attr("class", "center-big").attr("y", -2);
const centerSmall = ringSvg.append("text").attr("class", "center-small").attr("y", 22);

function drawRing() {
  const size = snap.ring_size;
  const pts = gPoints.selectAll("circle.pt").data(snap.points, (d) => d.pos);
  pts.exit().transition().duration(500).attr("r", 0).remove();
  pts.enter()
    .append("circle")
    .attr("class", "pt")
    .attr("cx", (d) => xy(d.pos, size, R)[0])
    .attr("cy", (d) => xy(d.pos, size, R)[1])
    .attr("fill", (d) => color(d.node))
    .attr("r", 0)
    .transition()
    .duration(500)
    .attr("r", 4);

  const alive = snap.nodes.filter((n) => n.alive);
  const keys = alive.reduce((s, n) => s + n.keys, 0);
  centerBig.text(keys.toLocaleString());
  centerSmall.text(`keys on ${alive.length} node${alive.length === 1 ? "" : "s"}`);
}

// Little dots fly from the center to a node: one dot ~ some requests it served.
function drawParticles(deltas) {
  const byNode = d3.group(snap.points, (d) => d.node);
  for (const [name, delta] of Object.entries(deltas)) {
    const pts = byNode.get(name);
    if (!pts || delta <= 0) continue;
    const n = Math.min(Math.ceil(delta / 3), 5);
    for (let i = 0; i < n; i++) {
      const p = pts[Math.floor(Math.random() * pts.length)];
      const [x, y] = xy(p.pos, snap.ring_size, R);
      gParticles.append("circle")
        .attr("r", 3)
        .attr("fill", color(name))
        .attr("opacity", 0.9)
        .transition()
        .delay(i * 90)
        .duration(650)
        .ease(d3.easeCubicOut)
        .attr("cx", x)
        .attr("cy", y)
        .attr("opacity", 0)
        .remove();
    }
  }
}

// ---- lookup (binary search) ---------------------------------------------

function drawLookup() {
  gLookup.selectAll("*").remove();
  const box = $("lookup-result");
  if (!lookup || !snap) return;
  const points = snap.points;
  if (points.length === 0) {
    box.innerHTML = "<p>No live nodes: the ring is empty.</p>";
    return;
  }
  const size = snap.ring_size;
  const positions = points.map((p) => p.pos);
  const steps = [];
  const i = bisectLeft(positions, lookup.position, steps);
  const wrapped = i === positions.length;
  const owner = points[wrapped ? 0 : i];

  // Clockwise arc from the key to its owner point.
  const a1 = angle(lookup.position, size);
  let a2 = angle(owner.pos, size);
  if (a2 < a1) a2 += 2 * Math.PI;
  const rArc = R + 14;
  const large = a2 - a1 > Math.PI ? 1 : 0;
  gLookup.append("path")
    .attr("d", `M ${rArc * Math.cos(a1)} ${rArc * Math.sin(a1)} A ${rArc} ${rArc} 0 ${large} 1 ${rArc * Math.cos(a2)} ${rArc * Math.sin(a2)}`)
    .attr("fill", "none")
    .attr("stroke", color(owner.node))
    .attr("stroke-width", 3)
    .attr("stroke-linecap", "round");
  const [kx, ky] = xy(lookup.position, size, R + 26);
  gLookup.append("rect")
    .attr("x", kx - 6).attr("y", ky - 6).attr("width", 12).attr("height", 12)
    .attr("transform", `rotate(45 ${kx} ${ky})`)
    .attr("fill", "var(--text)");
  const [ox, oy] = xy(owner.pos, size, R);
  gLookup.append("circle")
    .attr("cx", ox).attr("cy", oy).attr("r", 8)
    .attr("fill", "none").attr("stroke", color(owner.node)).attr("stroke-width", 3);

  const stored = lookup.stored === undefined
    ? "not stored yet"
    : `value: <code>${esc(JSON.stringify(lookup.stored))}</code>`;
  const stepList = steps.map((s) =>
    `<li>lo=${s.lo} hi=${s.hi} mid=${s.mid}: ${s.value.toLocaleString()} ${s.goRight ? "&lt; key → right" : "≥ key → left"}</li>`
  ).join("");
  box.innerHTML = `
    <p><span class="dot" style="background:${color(owner.node)}"></span>
       <span class="owner">${esc(lookup.key)} → node ${esc(owner.node)}</span></p>
    <p>Position ${lookup.position.toLocaleString()} · ${stored}</p>
    <p>Binary search: <b>${steps.length} steps</b> over ${positions.length} points
       (log₂ ${positions.length} ≈ ${Math.log2(positions.length).toFixed(1)}).
       A linear scan would check ${wrapped ? positions.length : i + 1}.
       ${wrapped ? "Key is past the last point, so it wraps to the first one." : ""}</p>
    <ol>${stepList}</ol>`;
}

async function locate() {
  const key = $("key").value.trim();
  $("key-err").textContent = "";
  if (!KEY_RE.test(key)) {
    $("key-err").textContent = "Use 1–200 letters, digits or _ . : -";
    return null;
  }
  const loc = await api(`/locate/${encodeURIComponent(key)}`);
  let stored;
  try {
    stored = (await api(`/keys/${encodeURIComponent(key)}`)).value;
  } catch (e) {
    if (e.status !== 404 && e.status !== 503) throw e;
  }
  lookup = { key, position: loc.position, stored };
  drawLookup();
  return key;
}

$("lookup").addEventListener("submit", async (e) => {
  e.preventDefault();
  try { await locate(); } catch (err) { $("key-err").textContent = errorText(err); }
});

$("write").addEventListener("click", async () => {
  const key = $("key").value.trim();
  if (!KEY_RE.test(key)) {
    $("key-err").textContent = "Use 1–200 letters, digits or _ . : -";
    return;
  }
  try {
    await api(`/keys/${encodeURIComponent(key)}`, {
      method: "PUT",
      body: JSON.stringify({ value: `written at ${new Date().toLocaleTimeString()}` }),
    });
    await locate();
  } catch (err) {
    $("key-err").textContent = errorText(err);
  }
});

$("key").addEventListener("input", () => { $("key-err").textContent = ""; });

// ---- nodes table -----------------------------------------------------------

function drawNodes(rates) {
  $("nodes").innerHTML = snap.nodes.map((n) => `
    <tr class="${n.alive ? "" : "down"}">
      <td><span class="dot" style="background:${n.alive ? color(n.name) : "var(--track)"}"></span>${esc(n.name)}</td>
      <td class="${n.alive ? "status-ok" : "status-down"}">${n.alive ? "alive" : "down"}</td>
      <td>${n.alive ? n.keys : "–"}</td>
      <td>${n.alive ? Math.round(rates[n.name] || 0) : "–"}</td>
      <td>
        <button class="small danger" data-act="crash" data-node="${esc(n.name)}" ${n.alive ? "" : "disabled"}>Crash</button>
        <button class="small" data-act="remove" data-node="${esc(n.name)}">Remove</button>
      </td>
    </tr>`).join("");
}

$("nodes").addEventListener("click", async (e) => {
  const btn = e.target.closest("button[data-act]");
  if (!btn) return;
  const name = btn.dataset.node;
  btn.disabled = true;
  try {
    if (btn.dataset.act === "crash") {
      await api(`/nodes/${encodeURIComponent(name)}/crash`, { method: "POST" });
      $("node-msg").textContent = `Node ${name} crashed. Its data is gone; the health check will notice it.`;
    } else {
      const r = await api(`/nodes/${encodeURIComponent(name)}`, { method: "DELETE" });
      $("node-msg").textContent = `Node ${name} removed gracefully, ${r.moved} keys handed over.`;
    }
  } catch (err) {
    $("node-msg").textContent = errorText(err);
    btn.disabled = false;
  }
});

// Prefill the form with a spare node the gateway knows about (until the user types).
let addFormTouched = false;
["new-name", "new-url"].forEach((id) => $(id).addEventListener("input", () => { addFormTouched = true; }));

function prefillSpare() {
  if (addFormTouched) return;
  const spare = (snap.spares || [])[0];
  $("new-name").value = spare ? spare.name : "";
  $("new-url").value = spare ? spare.url : "";
}

$("add-node").addEventListener("submit", async (e) => {
  e.preventDefault();
  const name = $("new-name").value.trim();
  const url = $("new-url").value.trim();
  if (!/^[A-Za-z0-9_-]{1,32}$/.test(name) || !/^https?:\/\//.test(url)) {
    $("node-msg").textContent = "Name: letters/digits; URL must start with http://";
    return;
  }
  try {
    const r = await api("/nodes", { method: "POST", body: JSON.stringify({ name, url }) });
    $("node-msg").textContent = r.alive
      ? `Node ${name} joined the ring.`
      : `Node ${name} registered, but it does not answer yet.`;
    addFormTouched = false;
  } catch (err) {
    $("node-msg").textContent = errorText(err);
  }
});

// ---- simulator -------------------------------------------------------------

function drawSimulator() {
  const sim = snap.simulator;
  const btn = $("sim-toggle");
  btn.textContent = sim.running ? "Stop" : "Start";
  btn.classList.toggle("primary", !sim.running);
  if (!rateTouched) {
    $("rate").value = sim.rate;
    $("rate-label").textContent = `${sim.rate} req/s`;
  }
  const s = snap.stats;
  const hits = s.hits || 0;
  const misses = s.misses || 0;
  $("s-writes").textContent = (s.writes || 0).toLocaleString();
  $("s-hits").textContent = hits.toLocaleString();
  $("s-misses").textContent = misses.toLocaleString();
  $("s-hitrate").textContent = hits + misses ? `${Math.round((hits / (hits + misses)) * 100)}%` : "–";
}

async function sendSimulator(running) {
  const rate = Number($("rate").value);
  await api("/simulator", { method: "POST", body: JSON.stringify({ running, rate }) });
  rateTouched = false;
}

$("sim-toggle").addEventListener("click", () => sendSimulator(!snap.simulator.running).catch(() => {}));
$("rate").addEventListener("input", () => {
  rateTouched = true;
  $("rate-label").textContent = `${$("rate").value} req/s`;
});
$("rate").addEventListener("change", () => sendSimulator(snap.simulator.running).catch(() => {}));

// ---- chart -----------------------------------------------------------------

const chart = d3.select("#chart");
const CH = { w: 640, h: 170, left: 34, right: 8, top: 8, bottom: 20 };
const gAxis = chart.append("g").attr("class", "axis").attr("transform", `translate(${CH.left},0)`);
const gLines = chart.append("g");

function drawChart() {
  const names = snap.nodes.map((n) => n.name);
  const max = Math.max(5, ...history.flatMap((h) => Object.values(h)));
  const x = d3.scaleLinear().domain([0, HISTORY - 1]).range([CH.left, CH.w - CH.right]);
  const y = d3.scaleLinear().domain([0, max]).nice().range([CH.h - CH.bottom, CH.top]);
  gAxis.call(d3.axisLeft(y).ticks(4).tickSize(-(CH.w - CH.left - CH.right)));
  const offset = HISTORY - history.length;
  const line = d3.line()
    .x((_, i) => x(i + offset))
    .y((d) => y(d))
    .curve(d3.curveMonotoneX);
  const series = names.map((name) => ({ name, values: history.map((h) => h[name] || 0) }));
  gLines.selectAll("path")
    .data(series, (d) => d.name)
    .join("path")
    .attr("fill", "none")
    .attr("stroke", (d) => color(d.name))
    .attr("stroke-width", 2)
    .attr("d", (d) => line(d.values));
}

// ---- events ----------------------------------------------------------------

const EVENT_TEXT = {
  node_up: (e) => `node ${e.node} joined the ring` + (e.moved ? `, ${e.moved} keys moved to it` : ""),
  node_down: (e) => `node ${e.node} is down, taken off the ring`,
  node_removed: (e) => `node ${e.node} removed on purpose, ${e.moved} keys handed over`,
};

function addEvents(events) {
  const list = $("events");
  for (const e of events) {
    const li = document.createElement("li");
    li.className = `ev-${e.type}`;
    const time = new Date(e.time * 1000).toLocaleTimeString();
    const text = (EVENT_TEXT[e.type] || ((ev) => `${ev.type} ${ev.node}`))(e);
    li.innerHTML = `<time>${esc(time)}</time>${esc(text)}`;
    list.prepend(li);
  }
  while (list.children.length > 50) list.lastChild.remove();
}

// ---- main loop -------------------------------------------------------------

function update(next) {
  snap = next;
  snap.nodes.forEach((n) => color(n.name)); // nodes come sorted, so A always gets the same color
  const now = performance.now();
  const rates = {};
  const deltas = {};
  if (prevRequests) {
    const dt = (now - prevTime) / 1000;
    for (const n of snap.nodes) {
      const delta = Math.max(0, n.requests - (prevRequests[n.name] || 0));
      deltas[n.name] = delta;
      rates[n.name] = n.alive ? delta / dt : 0;
    }
    history.push(rates);
    if (history.length > HISTORY) history.shift();
  }
  prevRequests = Object.fromEntries(snap.nodes.map((n) => [n.name, n.requests]));
  prevTime = now;

  drawRing();
  drawParticles(deltas);
  drawNodes(rates);
  prefillSpare();
  drawSimulator();
  drawChart();
  drawLookup();
}

function setConn(ok) {
  const pill = $("conn");
  pill.textContent = ok ? "live" : "gateway offline";
  pill.className = `pill ${ok ? "ok" : "bad"}`;
}

async function poll() {
  try {
    update(await api("/cluster"));
    setConn(true);
    const events = await api(`/events?since=${lastEventTime}`);
    if (events.length) {
      lastEventTime = events[events.length - 1].time;
      addEvents(events);
    }
  } catch (e) {
    setConn(false);
  }
  setTimeout(poll, POLL_MS);
}

poll();
