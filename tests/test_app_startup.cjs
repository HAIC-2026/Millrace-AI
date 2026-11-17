/* Startup recovery and catalog pager checks for static/app.js. Run: node --test tests/test_app_startup.cjs
   app.js runs in a vm context with a small stand-in document (elements are created on first lookup by
   selector) and a scripted fetch. These tests cover the startup state machine, listener counts and request
   ordering only. Layout, focus rendering and real network transport are not covered here. */
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const SOURCE = fs.readFileSync(path.join(__dirname, "../static/app.js"), "utf8");
const tick = (ms) => new Promise((r) => setTimeout(r, ms || 0));

class El {
  constructor(doc, id, tag) {
    Object.assign(this, { doc, id: id || "", tag: tag || "div", children: [], listeners: {}, attrs: {}, dataset: {}, sub: new Map(),
      hidden: false, disabled: false, value: "", open: false, isConnected: true, style: {}, _text: "", _html: "" });
    this.classList = { toggle() {}, add() {}, remove() {} };
  }
  addEventListener(t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); }
  count(t) { return (this.listeners[t] || []).length; }
  fire(t, ev) { (this.listeners[t] || []).forEach((f) => f(Object.assign({ type: t, target: this, preventDefault() {} }, ev))); }
  get textContent() { return this._text; } set textContent(v) { this._text = String(v); this.children = []; }
  get innerHTML() { return this._html; } set innerHTML(v) { this._html = String(v); this.children = []; }
  appendChild(c) { this.children.push(c); return c; }
  append(...c) { this.children.push(...c); }
  replaceChildren(...c) { this.children = c; this._html = ""; this._text = ""; }
  after() {}
  querySelector(sel) { if (!this.sub.has(sel)) this.sub.set(sel, new El(this.doc)); return this.sub.get(sel); }
  querySelectorAll() { return []; }
  closest(sel) { return sel === "button" && this.tag === "button" ? this : null; }
  contains(x) { return x === this; }
  focus() { this.doc.activeElement = this; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  removeAttribute(k) { delete this.attrs[k]; }
  hasAttribute(k) { return k in this.attrs; }
  get options() { return this.children.filter((c) => c.tag === "option"); }
  get selectedOptions() { return []; }
  showModal() { this.open = true; }
  close() { this.open = false; this.fire("close"); }
}

const TABS = ["investigation", "workflow", "catalog", "sources", "commands"];
function makeDocument() {
  const doc = { listeners: {}, byId: new Map(), activeElement: null };
  doc.el = (sel) => {
    if (!doc.byId.has(sel)) doc.byId.set(sel, new El(doc, sel.startsWith("#") ? sel.slice(1) : "", /^#(cat-prev|cat-next|cat-clear|cat-retry|app-startup-retry|run-btn)$/.test(sel) ? "button" : "div"));
    return doc.byId.get(sel);
  };
  const tabs = TABS.map((t, i) => { const b = doc.el("#tab-btn-" + t); b.setAttribute("aria-controls", "tab-" + t); b.setAttribute("aria-selected", i ? "false" : "true"); doc.el("#tab-" + t).hidden = i > 0; return b; });
  doc.querySelector = (sel) => sel === '[role="tab"][aria-selected="true"]' ? tabs.find((b) => b.getAttribute("aria-selected") === "true") : doc.el(sel);
  doc.querySelectorAll = (sel) => sel === '[role="tab"]' ? tabs : [];
  doc.createElement = (tag) => new El(doc, "", tag);
  doc.addEventListener = (t, f) => { (doc.listeners[t] = doc.listeners[t] || []).push(f); };
  doc.fire = (t, ev) => (doc.listeners[t] || []).forEach((f) => f(Object.assign({ type: t, preventDefault() {} }, ev)));
  doc.body = new El(doc); doc.head = new El(doc);
  return doc;
}

const CATALOG = {
  templates: [{ task: "profile", label: "District profile" }, { task: "compare", label: "Compare" }],
  metrics: [{ metric_id: "m1", label: "Measure one", group: "Group" }], geographies: [{ geography_id: "g1", label: "Place" }],
  unavailable_geographies: [], programs: [], districts: [], participation: [],
  commands: { forms: [{ task: "profile", forms: ["profile house 1"] }], rules: ["Literal forms only."] },
  html: "<table id=\"cat-table\"></table>", sources_html: "", coverage: { statistics_observations: 120 }, runtime: { variant: "A" },
};
const json = (body, status) => Promise.resolve({ status: status || 200, json: async () => body });
const abortError = () => Object.assign(new Error("aborted"), { name: "AbortError" });

// routes: url prefix -> function(url, opts) returning a response promise (or a thrown error for network failure).
function boot(routes) {
  const doc = makeDocument(), calls = [], unhandled = [];
  const onUnhandled = (r) => unhandled.push(r);
  process.on("unhandledRejection", onUnhandled);
  const fetch = (url, opts) => {
    calls.push(url);
    const key = Object.keys(routes).filter((k) => url.startsWith(k)).sort((a, b) => b.length - a.length)[0];
    if (!key) return json({ status: "ok" });
    const p = Promise.resolve().then(() => routes[key](url, opts));
    if (!opts || !opts.signal) return p;
    return new Promise((resolve, reject) => {
      if (opts.signal.aborted) return reject(abortError());
      opts.signal.addEventListener("abort", () => reject(abortError()));
      p.then(resolve, reject);
    });
  };
  const win = { addEventListener() {} };
  const ctx = vm.createContext({ document: doc, window: win, fetch, crypto: { randomUUID: () => crypto.randomUUID() }, setTimeout, clearTimeout,
    AbortController, URLSearchParams, console });
  vm.runInContext(SOURCE, ctx, { filename: "app.js" });
  // The catalog table and its rows: the stand-in reports one row per "<tr" in the tbody markup.
  const table = doc.el("#cat-table");
  Object.assign(table.dataset, { total: "120", matched: "120", offset: "0", limit: "50" });
  table.querySelector("tbody").innerHTML = "<tr>".repeat(50);
  table.querySelectorAll = () => Array.from({ length: (table.querySelector("tbody").innerHTML.match(/<tr/g) || []).length }, () => new El(doc));
  doc.fire("DOMContentLoaded");
  return { doc, calls, unhandled, done: () => process.off("unhandledRejection", onUnhandled) };
}
const count = (calls, prefix) => calls.filter((u) => u === prefix || u.startsWith(prefix + "?")).length;
const page = (offset, rows, extra) => json(Object.assign({ status: "ok", total: 120, matched: 120, offset, limit: 50,
  filters: { geography_id: "", metric_id: "", q: "" }, finding_ids: [], rows_html: ("<tr data-page=\"" + offset + "\">").repeat(rows) }, extra));

test("catalog failure keeps source inspection working; Retry twice resumes only the catalog without duplicate listeners", async () => {
  let catalogFailures = 2, release;
  const t = boot({
    "/api/health": () => json({ status: "ok", snapshot_id: "sha256:" + "a".repeat(64) }),
    "/api/catalog": () => { if (catalogFailures-- > 0) throw new TypeError("Failed to fetch"); return new Promise((r) => { release = () => r({ status: 200, json: async () => CATALOG }); }); },
    "/api/source": () => json({ status: "ok", html: "<p>Source</p>" }),
  });
  const d = t.doc;
  // Page-wide wiring is in place before the server answers.
  assert.equal(d.listeners.click.length, 1);
  assert.equal(d.el("#app-startup-retry").count("click"), 1);
  await tick(20);
  assert.equal(d.el("#app-startup").hidden, false);
  assert.match(d.el("#app-startup-msg").textContent, /^The catalog did not load: The server did not respond\./);
  assert.equal(d.el("#run-btn").disabled, true);
  // Source inspection works while startup has failed.
  const src = new El(d, "", "button"); src.dataset = { sourceId: "acs", findingId: "stat:x" };
  const target = { closest: (sel) => sel === ".source-btn" ? src : null };
  d.fire("click", { target });
  await tick(20);
  assert.equal(d.el("#source-dialog").open, true);
  assert.equal(count(t.calls, "/api/source"), 1);
  // Retry 1 fails again; focus stays on Retry and the notice says so.
  d.el("#app-startup-retry").fire("click");
  await tick(20);
  assert.match(d.el("#app-startup-progress").textContent, /Retry 1 did not succeed/);
  // Retry 2 is in flight; a second click is ignored.
  d.el("#app-startup-retry").fire("click");
  d.el("#app-startup-retry").fire("click");
  await tick(20);
  release(); await tick(20);
  assert.equal(count(t.calls, "/api/health"), 1, "the data check is not repeated");
  assert.equal(count(t.calls, "/api/catalog"), 3, "one initial request and two retries");
  assert.equal(d.el("#app-startup").hidden, true);
  assert.equal(d.el("#run-btn").disabled, false);
  assert.equal(d.el("#task-options").children.length, 2);
  assert.equal(d.listeners.click.length, 1);
  assert.equal(d.el("#controls").count("submit"), 1);
  assert.equal(d.el("#task-options").count("change"), 1);
  assert.equal(d.el("#catalog-body").count("click"), 1);
  assert.equal(d.el("#app-startup-retry").count("click"), 1);
  assert.deepEqual(t.unhandled, []);
  t.done();
});

for (const [label, reply] of [["malformed JSON", () => ({ status: 502, json: async () => { throw new SyntaxError("Unexpected token <"); } })],
  ["incomplete shape", () => json({ status: "ok" })], ["error JSON", () => json({ status: "error", reason: "The request failed." }, 500)]]) {
  test("catalog " + label + " shows the startup notice and never a partial ready state", async () => {
    const t = boot({ "/api/health": () => json({ status: "ok", snapshot_id: "sha256:" + "b".repeat(64) }), "/api/catalog": reply });
    await tick(20);
    assert.equal(t.doc.el("#app-startup").hidden, false);
    assert.equal(t.doc.el("#run-btn").disabled, true);
    assert.equal(t.doc.el("#task-options").children.length, 0);
    assert.deepEqual(t.unhandled, []);
    t.done();
  });
}

async function readyPager(obsRoute) {
  const t = boot({ "/api/health": () => json({ status: "ok", snapshot_id: "sha256:" + "c".repeat(64) }), "/api/catalog": () => json(CATALOG),
    "/api/catalog/observations": obsRoute });
  await tick(20);
  assert.equal(t.doc.el("#app-startup").hidden, true);
  return t;
}

test("an older slow filter reply is cancelled and never replaces the newer rows", async () => {
  const pending = [];
  const t = await readyPager((url) => new Promise((resolve) => pending.push({ url, resolve })));
  const d = t.doc, body = d.el("#catalog-body"), geo = d.el("#cat-geo");
  geo.value = "g1"; body.fire("change", { target: geo });
  geo.value = ""; d.el("#cat-metric").value = "m1"; body.fire("change", { target: d.el("#cat-metric") });
  await tick(5);
  assert.equal(pending.length, 2);
  pending[1].resolve({ status: 200, json: async () => ({ status: "ok", total: 120, matched: 6, offset: 0, limit: 50,
    filters: { geography_id: "", metric_id: "m1", q: "" }, finding_ids: [], rows_html: "<tr new>".repeat(6) }) });
  await tick(5);
  pending[0].resolve({ status: 200, json: async () => ({ status: "ok", total: 120, matched: 20, offset: 0, limit: 50,
    filters: { geography_id: "g1", metric_id: "", q: "" }, finding_ids: [], rows_html: "<tr old>".repeat(20) }) });
  await tick(5);
  assert.equal(d.el("#cat-table").querySelector("tbody").innerHTML, "<tr new>".repeat(6));
  assert.match(d.el("#cat-count").textContent, /^Showing 1–6 of 6 matching statistics \(120 in the catalog\)\. Page 1 of 1\.$/);
  assert.deepEqual(t.unhandled, []);
  t.done();
});

test("a failed page keeps the rows shown, offers one Retry, and Previous/Next respect the bounds", async () => {
  let fail = true;
  const t = await readyPager((url) => {
    const offset = Number(new URLSearchParams(url.split("?")[1]).get("offset"));
    if (fail) { fail = false; throw new TypeError("Failed to fetch"); }
    return page(offset, offset >= 100 ? 20 : 50);
  });
  const d = t.doc, body = d.el("#catalog-body"), tbody = d.el("#cat-table").querySelector("tbody"), before = tbody.innerHTML;
  assert.equal(d.el("#cat-prev").disabled, true);
  assert.equal(d.el("#cat-count").textContent, "Showing 1–50 of 120 statistics. Page 1 of 3.");
  body.fire("click", { target: d.el("#cat-next") });
  await tick(20);
  assert.equal(tbody.innerHTML, before);
  assert.equal(d.el("#cat-error").hidden, false);
  assert.equal(d.el("#cat-count").textContent, "Showing 1–50 of 120 statistics. Page 1 of 3.");
  body.fire("click", { target: d.el("#cat-retry") });
  await tick(20);
  assert.equal(d.el("#cat-error").hidden, true);
  assert.equal(d.el("#cat-count").textContent, "Showing 51–100 of 120 statistics. Page 2 of 3.");
  body.fire("click", { target: d.el("#cat-next") }); await tick(20);
  assert.equal(d.el("#cat-count").textContent, "Showing 101–120 of 120 statistics. Page 3 of 3.");
  assert.equal(d.el("#cat-next").disabled, true);
  const n = count(t.calls, "/api/catalog/observations");
  body.fire("click", { target: d.el("#cat-next") }); await tick(20);
  assert.equal(count(t.calls, "/api/catalog/observations"), n, "no request past the last page");
  assert.deepEqual(t.unhandled, []);
  t.done();
});

test("catalog Retry restores focus only when the replaced button still owns it", async () => {
  let fail = true;
  const t = await readyPager((url) => fail ? json({ status: "error", reason: "Still unavailable." }, 503) : page(50, 50));
  const d = t.doc, body = d.el("#catalog-body"), error = d.el("#cat-error"), rows = d.el("#cat-table").querySelector("tbody");
  const before = rows.innerHTML;
  body.fire("click", { target: d.el("#cat-next") }); await tick(20);
  for (let attempt = 0; attempt < 2; attempt += 1) {
    const retry = error.children.find((el) => el.id === "cat-retry"), n = count(t.calls, "/api/catalog/observations");
    retry.focus(); body.fire("click", { target: retry }); await tick(20);
    assert.equal(d.activeElement, error.children.find((el) => el.id === "cat-retry"));
    assert.equal(count(t.calls, "/api/catalog/observations"), n + 1);
    assert.equal(rows.innerHTML, before);
  }
  // A response must leave focus alone if staff already moved to a different control.
  body.fire("click", { target: error.children.find((el) => el.id === "cat-retry") });
  d.el("#cat-q").focus(); await tick(20);
  assert.equal(d.activeElement, d.el("#cat-q"));
  fail = false;
  const retry = error.children.find((el) => el.id === "cat-retry");
  retry.focus(); body.fire("click", { target: retry }); await tick(20);
  assert.equal(d.activeElement, d.el("#cat-count"));
  assert.equal(error.hidden, true);
  assert.equal(body.count("click"), 1);
  assert.deepEqual(t.unhandled, []);
  t.done();
});
