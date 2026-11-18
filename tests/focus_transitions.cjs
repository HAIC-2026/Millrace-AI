/* Browser regression checks for a local app. Requires the optional developer-only Playwright package
   and its Chromium browser (npx playwright install chromium), or FOCUS_TEST_CHROME for an existing one.
   FOCUS_TEST_URL=http://127.0.0.1:PORT node --test tests/focus_transitions.cjs
   FOCUS_TEST_CHROME selects the browser executable. FOCUS_TEST_MOCK_ASK=1 enables question checks;
   use only a private offline provider fixture accepting "Food assistance in House 28.".
   FOCUS_TEST_EVIDENCE optionally saves screenshots; FOCUS_TEST_BASELINE serves original static JS.
   This suite never runs against a public host and blocks all non-loopback browser requests. */
"use strict";
const { test, before, after } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");
const base = new URL(process.env.FOCUS_TEST_URL || "http://127.0.0.1:8952");
assert.ok(["127.0.0.1", "localhost", "[::1]"].includes(base.hostname), "Use a private loopback app");
let browser;
before(async () => { browser = await chromium.launch({ headless: true, ...(process.env.FOCUS_TEST_CHROME ? { executablePath: process.env.FOCUS_TEST_CHROME } : {}) }); });
after(async () => { if (browser) await browser.close(); });
async function page() {
  const p = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  await p.route("**/*", async route => {
    const u = new URL(route.request().url());
    if (!["127.0.0.1", "localhost", "[::1]"].includes(u.hostname)) return route.abort();
    if (process.env.FOCUS_TEST_BASELINE && /^\/static\/(app|investigation)\.js$/.test(u.pathname)) {
      return route.fulfill({ contentType: "application/javascript", body: fs.readFileSync(path.join(process.env.FOCUS_TEST_BASELINE, path.basename(u.pathname))) });
    }
    return route.continue();
  });
  await p.goto(base.href);
  await p.waitForFunction(() => document.querySelector("#ia-recommend-btn") && !document.querySelector("#ia-recommend").hidden && document.querySelector("#ia-cancel").hidden);
  return p;
}
const focus = p => p.evaluate(() => ({ id: document.activeElement.id, tag: document.activeElement.tagName }));
async function proof(p, name, details) {
  console.log(JSON.stringify({ scenario: name, focus: await focus(p), ...details }));
  if (process.env.FOCUS_TEST_EVIDENCE) {
    fs.mkdirSync(process.env.FOCUS_TEST_EVIDENCE, { recursive: true });
    await p.screenshot({ path: path.join(process.env.FOCUS_TEST_EVIDENCE, name + ".png") });
  }
}
async function recommend(p) {
  await p.locator("#ia-recommend-btn").click();
  await p.waitForFunction(() => !document.querySelector("#ia-print-btn").disabled);
}
async function tabCommit(p, id, key, expected, value) {
  await p.locator("#" + id).fill(value);
  await p.keyboard.press(key);
  await p.waitForTimeout(40); // next browser task: the commit render must have completed
  const actual = await focus(p);
  await proof(p, id + "-" + key.replace("+", "-"), { value: await p.locator("#" + id).inputValue(), expected });
  assert.equal(actual.id, expected);
  assert.equal(await p.locator("#" + id).inputValue(), value);
}

test("staff commits preserve forward/reverse Tab, pointer actions and saved work", async () => {
  const p = await page();
  try {
    await recommend(p);
    const selected = await p.locator("#ia-tray-count").textContent();
    await tabCommit(p, "ia-note", "Tab", "ia-next", "Summary kept");
    await tabCommit(p, "ia-title", "Tab", "ia-note", "Staff title");
    await tabCommit(p, "ia-next", "Tab", "ia-tracking-summary", "Next steps kept");
    await tabCommit(p, "ia-next", "Shift+Tab", "ia-note", "Next steps revised");
    await tabCommit(p, "ia-note", "Shift+Tab", "ia-title", "Summary revised");
    await tabCommit(p, "ia-title", "Shift+Tab", "ia-chk-add", "Staff title revised");
    await p.locator("#ia-next").fill("Pointer next steps");
    await p.locator("#ia-tracking-summary").click({ delay: 150 });
    await p.waitForTimeout(40);
    assert.equal(await p.locator("#ia-tracking").getAttribute("open"), "");
    assert.equal((await focus(p)).id, "ia-tracking-summary");
    await proof(p, "staff-pointer-disclosure", {});
    await p.locator("#ia-note").fill("Final summary");
    await p.locator("#ia-title").click({ delay: 150 });
    await p.waitForTimeout(40);
    assert.equal((await focus(p)).id, "ia-title");
    assert.equal(await p.locator("#ia-note").inputValue(), "Final summary");
    assert.equal(await p.locator("#ia-tray-count").textContent(), selected);
    // Cancelling a pointer gesture or leaving the window must release a queued text refresh too.
    for (const type of ["pointercancel", "blur"]) {
      await p.locator("#ia-note").fill("Gesture cleanup " + type);
      const box = await p.locator("#ia-next").boundingBox();
      await p.mouse.move(box.x + 10, box.y + 10); await p.mouse.down();
      await p.evaluate(type => window.dispatchEvent(type === "pointercancel" ? new PointerEvent(type) : new Event(type)), type);
      await p.waitForTimeout(40); await p.mouse.up();
      assert.equal((await focus(p)).id, "ia-next");
      assert.equal(await p.locator("#ia-note").inputValue(), "Gesture cleanup " + type);
    }
    await p.locator("#ia-note").fill("Final summary");
    await p.locator("#ia-title").fill("Selection preservation");
    await p.evaluate(() => { const next = document.querySelector("#ia-note"); next.focus(); next.setSelectionRange(2, 8, "backward"); });
    await p.waitForTimeout(40);
    assert.deepEqual(await p.locator("#ia-note").evaluate(el => [el.selectionStart, el.selectionEnd, el.selectionDirection]), [2, 8, "backward"]);
    await p.locator("#ia-title").fill("No delayed focus steal");
    await p.evaluate(() => { document.querySelector("#ia-note").focus(); document.querySelector("#ia-download").focus(); });
    await p.waitForTimeout(40);
    assert.equal((await focus(p)).id, "ia-download");
    // A click action must see the state committed during blur, including staff text in the download.
    await p.locator("#ia-title").fill("Title committed before click");
    await p.locator("#ia-download-staff").check();
    const downloading = p.waitForEvent("download");
    await p.locator("#ia-download").click();
    const file = await downloading;
    const saved = JSON.parse(fs.readFileSync(await file.path(), "utf8"));
    const branch = saved.branches[0];
    assert.equal(branch.staff_edits.title, "Title committed before click");
    assert.equal(branch.staff_edits.note, "Final summary");
    assert.equal(branch.staff_edits.next_steps, "Pointer next steps");
    assert.ok(branch.selected_claim_refs.length > 0);
    await proof(p, "staff-saved-work", { selected, savedStaff: branch.staff_edits });
    // A deferred label commit must merge the baseline/date change with the current tracking record.
    if (await p.locator("#ia-tracking").getAttribute("open") === null) await p.locator("#ia-tracking-summary").click();
    for (const target of ["Tab", "ia-track-base", "ia-track-date"]) {
      const label = "Referral sessions arranged " + target;
      await p.locator("#ia-track-label").fill(label);
      if (target === "Tab") await p.keyboard.press("Tab");
      else await p.locator("#" + target).click({ delay: 150 });
      await p.waitForTimeout(40);
      assert.equal((await focus(p)).id, target === "Tab" ? "ia-track-base" : target);
      assert.equal(await p.locator("#ia-track-label").inputValue(), label);
      await p.locator("#ia-track-base").fill("12");
      await p.locator("#ia-track-date").fill("2026-11-16");
      await p.locator("#ia-download").focus();
      const trackingDownload = p.waitForEvent("download");
      await p.locator("#ia-download").click();
      const trackingFile = await trackingDownload;
      const trackingCase = JSON.parse(fs.readFileSync(await trackingFile.path(), "utf8"));
      assert.deepEqual(trackingCase.branches[0].tracking, { label, baseline: 12, as_of: "2026-11-16" });
      await proof(p, "tracking-" + target, { savedTracking: trackingCase.branches[0].tracking });
    }
    // Native typing commits a number on blur; the first Tab or pointer action must reach the date.
    await p.locator("#ia-track-base").focus();
    await p.keyboard.press("ControlOrMeta+A");
    await p.keyboard.type("13");
    await p.keyboard.press("Tab");
    await p.waitForTimeout(40);
    assert.equal((await focus(p)).id, "ia-track-date");
    assert.equal(await p.evaluate(() => document.activeElement.isConnected), true);
    assert.equal(await p.locator("#ia-track-base").inputValue(), "13");
    assert.match(await p.locator("#ia-tracking > p.hint").textContent(), /Baseline: 13 as of 2026-11-16/);
    await proof(p, "tracking-number-tab", {});
    await p.locator("#ia-track-base").focus();
    await p.keyboard.press("ControlOrMeta+A");
    await p.keyboard.type("12");
    await p.locator("#ia-track-date").click({ delay: 150 });
    await p.waitForTimeout(40);
    assert.equal((await focus(p)).id, "ia-track-date");
    assert.equal(await p.evaluate(() => document.activeElement.isConnected), true);
    await proof(p, "tracking-number-first-click", {});
    assert.match(await p.locator("#ia-tracking > p.hint").textContent(), /Baseline: 12 as of 2026-11-16/);
    await p.keyboard.press("ArrowUp");
    const revisedDate = await p.locator("#ia-track-date").inputValue();
    assert.notEqual(revisedDate, "2026-11-16");
    const finalTrackingDownload = p.waitForEvent("download");
    await p.locator("#ia-download").click();
    await p.waitForTimeout(40);
    assert.equal((await focus(p)).id, "ia-download");
    const finalTrackingFile = await finalTrackingDownload;
    const finalTrackingCase = JSON.parse(fs.readFileSync(await finalTrackingFile.path(), "utf8"));
    assert.deepEqual(finalTrackingCase.branches[0].tracking, { label: "Referral sessions arranged ia-track-date", baseline: 12, as_of: revisedDate });
    await proof(p, "tracking-number-date-saved", { savedTracking: finalTrackingCase.branches[0].tracking });
  } finally { await p.close(); }
});

const copyTitle = "Synthetic brief title";
const copySummary = "Synthetic summary for keyboard verification";
async function parkStaffNotes(p) {
  await recommend(p);
  await p.locator("#ia-title").fill(copyTitle);
  await p.keyboard.press("Tab");
  await p.locator("#ia-note").fill(copySummary);
  await p.keyboard.press("Tab");
  await p.locator("#ia-district").selectOption("house:013");
  await p.locator("#ia-context-apply-btn").click();
  await p.locator("#ia-preview-confirm").click();
  await p.waitForFunction(() => document.querySelector("#ia-cancel").hidden);
  const copies = p.getByRole("button", { name: "Copy into this context" });
  assert.equal(await copies.count(), 2);
  return copies;
}

test("copying parked staff notes keeps keyboard focus in review and then in the staff notes", async () => {
  const p = await page();
  try {
    const copies = await parkStaffNotes(p);
    await copies.first().focus();
    await p.keyboard.press("Enter");
    assert.equal((await focus(p)).id, "ia-review-h");
    assert.equal(await copies.count(), 1);
    assert.equal(await p.locator("#ia-title").inputValue(), copyTitle);
    const status = p.getByRole("status").filter({ hasText: "Copied as a staff contribution." });
    assert.equal(await status.textContent(), "Copied as a staff contribution. Review staff notes before creating the brief.");
    await proof(p, "copy-staff-note-one-left", { status: await status.textContent() });

    await p.keyboard.press("Tab");
    assert.equal(await copies.evaluate(el => el === document.activeElement), true);
    await p.keyboard.press("Space");
    assert.equal((await focus(p)).id, "ia-staff-h");
    assert.equal(await copies.count(), 0);
    assert.equal(await p.locator("#ia-note").inputValue(), copySummary);
    await proof(p, "copy-staff-note-last", { status: await status.textContent() });
    await p.keyboard.press("Tab");
    assert.equal((await focus(p)).id, "ia-title");

    await p.locator("#ia-download-staff").check();
    const saved = await savedCase(p);
    assert.equal(saved.branches.length, 2);
    for (const branch of saved.branches) {
      assert.deepEqual(branch.staff_edits, { title: copyTitle, note: copySummary });
    }
  } finally { await p.close(); }
});

test("copying a parked note without focus preserves the remaining row or native date editor", async () => {
  const p = await page();
  try {
    const copies = await parkStaffNotes(p);
    await copies.last().focus();
    await copies.first().evaluate(el => el.click());
    assert.equal(await copies.count(), 1);
    assert.equal(await copies.evaluate(el => el === document.activeElement), true);
    await proof(p, "copy-staff-note-keep-other-row", {});

    await p.locator("#ia-tracking-summary").click();
    const date = p.locator("#ia-track-date");
    await date.focus();
    await p.keyboard.type("1116202");
    await copies.evaluate(el => el.click());
    assert.equal((await focus(p)).id, "ia-track-date");
    assert.equal(await copies.count(), 0);
    await p.keyboard.type("6");
    assert.equal(await date.inputValue(), "2026-11-16");
    await p.keyboard.press("Tab");
    await p.locator("#ia-download-staff").check();
    const saved = await savedCase(p);
    const active = saved.branches.find(b => b.branch_id === saved.active_branch_id);
    assert.deepEqual(active.staff_edits, { title: copyTitle, note: copySummary });
    assert.equal(active.tracking.as_of, "2026-11-16");
    await proof(p, "copy-staff-note-keep-date", { date: active.tracking.as_of });
  } finally { await p.close(); }
});

test("leaving a parked note keeps focus on the next leave action", async () => {
  const p = await page();
  try {
    await parkStaffNotes(p);
    const leave = p.getByRole("button", { name: "Leave in original context" });
    await leave.first().focus();
    await p.keyboard.press("Enter");
    assert.equal(await leave.count(), 1);
    assert.equal(await leave.evaluate(el => el === document.activeElement), true);
    assert.equal(await p.locator("#ia-title").inputValue(), "");
  } finally { await p.close(); }
});

test("parked notes on the same finding retain distinct focus across a render", async () => {
  const p = await page();
  try {
    const finding = p.locator('#ia-evidence input[type="checkbox"]').first();
    for (const note of ["First parked finding note", "Second parked finding note"]) {
      await finding.check();
      await p.locator("#ia-selected input").first().fill(note);
      await p.keyboard.press("Tab");
      await p.getByRole("button", { name: "Remove finding 1 from brief" }).click();
    }
    const copies = p.getByRole("button", { name: "Copy into this context" });
    assert.equal(await copies.count(), 2);
    assert.notEqual(await copies.first().getAttribute("id"), await copies.last().getAttribute("id"));
    const second = p.locator("#ia-review li").filter({ hasText: "Second parked finding note" }).getByRole("button", { name: "Copy into this context" });
    await second.focus();
    await p.locator("#ia-district").selectOption("house:013");
    assert.equal(await second.evaluate(el => el === document.activeElement), true);
  } finally { await p.close(); }
});

test("native date segments commit on leaving or explicit save without interrupting typing", async () => {
  const p = await page();
  try {
    await recommend(p);
    await p.locator("#ia-tracking-summary").click();
    await p.locator("#ia-track-label").fill("Date entry retained");
    await p.locator("#ia-track-base").fill("12");
    await p.locator("#ia-download-staff").check();
    const save = async (programmatic) => {
      const pending = p.waitForEvent("download");
      if (programmatic) await p.locator("#ia-download").evaluate(el => el.click());
      else await p.locator("#ia-download").click({ delay: 150 });
      const file = await pending;
      return JSON.parse(fs.readFileSync(await file.path(), "utf8")).branches[0];
    };
    for (const id of ["ia-track-date", "ia-chk-agency_route-due"]) {
      await p.locator("#" + id).fill("");
      await p.locator("#" + id).focus();
      for (const digit of "11162026") {
        await p.keyboard.type(digit);
        assert.equal((await focus(p)).id, id);
        assert.equal(await p.locator("#ia-alert").evaluate(el => el.hidden), true);
      }
      assert.equal(await p.locator("#" + id).inputValue(), "2026-11-16");
      await p.keyboard.press("Tab");
      await p.waitForTimeout(40);
      assert.notEqual((await focus(p)).tag, "BODY");
      assert.equal(await p.evaluate(() => document.activeElement.isConnected), true);
      const saved = await save(false);
      if (id === "ia-track-date") assert.equal(saved.tracking.as_of, "2026-11-16");
      else assert.equal(saved.checklist_edits.find(x => x.item_id === "agency_route").due_date, "2026-11-16");
      await proof(p, "date-keys-" + id, { tracking: saved.tracking, checklist: saved.checklist_edits });
      // Explicit activation without blur must synchronously collect the provisional complete date.
      await p.locator("#" + id).fill("");
      await p.locator("#" + id).focus();
      await p.keyboard.type("11172026");
      const explicit = await save(true);
      if (id === "ia-track-date") assert.equal(explicit.tracking.as_of, "2026-11-17");
      else assert.equal(explicit.checklist_edits.find(x => x.item_id === "agency_route").due_date, "2026-11-17");
      await p.locator("#" + id).fill("2026-12-18");
      const filled = await save(false);
      if (id === "ia-track-date") assert.equal(filled.tracking.as_of, "2026-12-18");
      else assert.equal(filled.checklist_edits.find(x => x.item_id === "agency_route").due_date, "2026-12-18");
      await p.locator("#" + id).fill("");
      const cleared = await save(false);
      if (id === "ia-track-date") assert.equal(cleared.tracking.as_of, null);
      else assert.equal(cleared.checklist_edits.find(x => x.item_id === "agency_route")?.due_date, undefined);
    }
    // Invalid final dates still reach strict core validation when an explicit save is attempted.
    await p.locator("#ia-track-date").focus();
    await p.keyboard.type("11160002");
    assert.equal(await p.locator("#ia-alert").evaluate(el => el.hidden), true);
    let invalidDownloads = 0;
    p.on("download", () => { invalidDownloads += 1; });
    await p.locator("#ia-download").evaluate(el => el.click());
    await p.waitForTimeout(40);
    assert.equal((await focus(p)).id, "ia-alert");
    assert.match(await p.locator("#ia-alert").textContent(), /real YYYY-MM-DD date/);
    assert.equal(invalidDownloads, 0);
  } finally { await p.close(); }
});

// Gate local plan replies and language protocol fixtures so date keys straddle a known render.
// The language matrix does not consume the real provider fixture's shared three-question allowance.
async function holdDateReply(p, kind) {
  let release, received;
  const gate = new Promise(resolve => { release = resolve; });
  const ready = new Promise(resolve => { received = resolve; });
  if (kind.startsWith("language")) {
    const catalog = await (await p.request.get(new URL("/api/catalog", base).href)).json();
    let envelope, polls = 0;
    await p.route("**/api/language/*", async route => {
      const request = route.request().postDataJSON();
      if (route.request().url().endsWith("/start")) {
        const c = request.context;
        envelope = { schema_version: "ia-language/1", request_id: request.request_id, context: c,
          context_digest: "sha256:" + "a".repeat(64), tokens: { schema_version: "ia-language/1", release_id: catalog.investigation.release_id,
            ...Object.fromEntries(["case_id", "branch_id", "revision", "snapshot_id", "operation_version", "recipe_version"].map(k => [k, c[k]])) } };
        return route.fulfill({ status: 202, json: { ...envelope, status: "pending" } });
      }
      if (route.request().url().endsWith("/cancel")) return route.fulfill({ json: { ...envelope, status: "cancelled" } });
      if (++polls === 1) return route.fulfill({ json: { ...envelope, status: "pending" } });
      received();
      await gate;
      const result = kind === "language-proposal"
        ? { status: "propose", intent: "replace_plan", normalized_plan: { ...catalog.investigation.default_plan, map_session: 2024 }, typed_diff: [] }
        : { status: "clarify", message: "Choose a program.", clarify_field: "program", choices: [] };
      return route.fulfill({ json: { ...envelope, ...result } });
    });
    await p.locator("#ia-question-text").fill(kind === "language-proposal" ? "Show the 2024 map for House 28." : "Food assistance in House 28.");
    await p.locator("#ia-question-submit").click();
  } else {
    await p.route("**/api/investigation", async route => {
      const mode = kind === "brief" || kind === "interpret" ? kind : "run";
      if (route.request().postDataJSON().mode !== mode) return route.continue();
      const response = kind === "network-error" ? null : await route.fetch();
      received();
      await gate;
      if (kind === "network-error") return route.abort("connectionreset");
      if (kind === "http-error") return route.fulfill({ status: 500, json: { status: "error", code: "internal_error", message: "Private date-race fixture failure." } });
      await route.fulfill({ response });
    });
    if (kind === "brief") {
      await p.locator("#ia-review-btn").click();
      await p.locator("#ia-brief-btn").evaluate(el => el.click());
    } else if (kind === "interpret") {
      await p.locator("#ia-advanced").evaluate(el => { el.open = true; });
      await p.locator("#ia-typed").evaluate(el => { el.open = true; });
      await p.locator("#ia-utterance").fill("use house 13");
      await p.locator("#ia-ask").evaluate(el => el.requestSubmit());
    } else await p.locator(kind === "restore" ? "#ia-restore-0" : "#ia-apply").evaluate(el => el.click());
  }
  let timer;
  try { await Promise.race([ready, new Promise((_, reject) => { timer = setTimeout(() => reject(new Error("Date race reply was not reached")), 10000); })]); }
  finally { clearTimeout(timer); }
  return release;
}
async function prepareAsyncDate(p, id) {
  await recommend(p);
  await p.locator("#ia-tracking-summary").click();
  await p.locator("#ia-download-staff").check();
  await p.locator("#ia-track-label").fill("Async date entry");
  await p.locator("#ia-title").focus();
  await p.waitForTimeout(40);
  await p.locator("#" + id).fill("");
}
async function savedDate(p, id) {
  const saved = await savedCase(p);
  const branch = saved.branches.find(b => b.branch_id === saved.active_branch_id);
  return id === "ia-track-date" ? branch.tracking.as_of : branch.checklist_edits.find(x => x.item_id === "agency_route")?.due_date;
}
async function savedCase(p) {
  const pending = p.waitForEvent("download");
  await p.locator("#ia-download").click();
  const file = await pending;
  return JSON.parse(fs.readFileSync(await file.path(), "utf8"));
}
// Record the case already serialized by renderCase; inspecting it neither blurs nor flushes a date.
async function observeCase(p) {
  await p.evaluate(() => {
    const original = window.IACase.exportCase;
    window.IACase.exportCase = function (state, opts) {
      const out = original(state, opts);
      if (opts && opts.include_staff_work) window.dateRaceCase = out;
      return out;
    };
  });
}
for (const kind of ["run", "network-error", "http-error", "brief", "interpret", "language", "cancel-run", "cancel-language"]) {
  for (const id of ["ia-track-date", "ia-chk-agency_route-due"]) {
    for (const [stage, first, rest, provisional] of [
      ["year-one-digit", "11162", "026", "0002-11-16"],
      ["year-three-digits", "1116202", "6", "0202-11-16"],
      ["full-date", "11162026", "", "2026-11-16"],
    ]) {
      test("background " + kind + " preserves native " + id + " " + stage, { skip: kind.includes("language") && process.env.FOCUS_TEST_MOCK_ASK !== "1" }, async () => {
        const p = await page();
        let release;
        try {
          await prepareAsyncDate(p, id);
          release = await holdDateReply(p, kind.startsWith("cancel-") ? kind.slice(7) : kind);
          await p.locator("#" + id).focus();
          await p.waitForTimeout(40);
          await p.evaluate(id => { window.focusRaceDate = document.getElementById(id); }, id);
          await p.keyboard.type(first);
          assert.equal(await p.locator("#" + id).inputValue(), provisional);
          if (kind.startsWith("cancel-")) {
            await p.locator(kind === "cancel-run" ? "#ia-cancel" : "#ia-question-cancel").evaluate(el => el.click());
          }
          release();
          await p.waitForFunction(kind.includes("language")
            ? () => document.querySelector("#ia-question-cancel").hidden
            : () => document.querySelector("#ia-cancel").hidden);
          if (kind === "cancel-run") await p.waitForFunction(() => /late reply.*ignored/.test(document.querySelector("#ia-status").textContent));
          if (kind === "cancel-language") await p.waitForTimeout(100); // the cancelled language job ignores its held status reply
          const atReply = await p.evaluate(id => ({
            sameElement: document.getElementById(id) === window.focusRaceDate,
            connected: window.focusRaceDate.isConnected,
            focus: document.activeElement.id,
            value: document.getElementById(id).value,
            alert: !document.querySelector("#ia-alert").hidden,
          }), id);
          await proof(p, "date-race-" + kind + "-" + id + "-" + stage, { atReply });
          assert.deepEqual(atReply, { sameElement: true, connected: true, focus: id, value: provisional, alert: false });
          if (kind.endsWith("error")) assert.equal(await p.locator("#ia-error").evaluate(el => el.hidden), false);
          if (kind === "brief") assert.match(await p.locator("#ia-status").textContent(), /Brief created/);
          if (kind === "interpret") assert.match(await p.locator("#ia-interpretation").textContent(), /Proposed plan change/);
          if (kind.includes("language")) assert.match(await p.locator("#ia-question-result").textContent(), kind.startsWith("cancel-") ? /Question cancelled/ : /Choose|choice|program/i);
          if (rest) await p.keyboard.type(rest);
          assert.equal(await p.locator("#" + id).inputValue(), "2026-11-16", "the next key must continue the native year segment");
          await p.keyboard.press("Tab");
          await p.waitForTimeout(40);
          assert.notEqual((await focus(p)).tag, "BODY");
          assert.equal(await p.evaluate(() => document.activeElement.isConnected), true);
          assert.equal(await savedDate(p, id), "2026-11-16");
          assert.equal(await p.evaluate(() => window.focusRaceDate.isConnected), false, "leaving refreshes the deferred date section");
        } finally { if (release) release(); await p.close(); }
      });
    }
  }
}

for (const id of ["ia-track-date", "ia-chk-agency_route-due"]) {
  test("real field exit strictly validates unfinished invalid " + id, async () => {
    const p = await page();
    try {
      await prepareAsyncDate(p, id);
      await p.locator("#" + id).focus();
      await p.keyboard.type("11162");
      assert.equal(await p.locator("#ia-alert").evaluate(el => el.hidden), true);
      await p.locator("#ia-download").focus(); // explicitly leave the native editor, including its year segment
      await p.waitForTimeout(40);
      assert.notEqual((await focus(p)).id, id);
      assert.equal(await p.locator("#ia-alert").evaluate(el => el.hidden), false);
      assert.match(await p.locator("#ia-alert").textContent(), /real YYYY-MM-DD date/);
      await proof(p, "invalid-date-exit-" + id, {});
    } finally { await p.close(); }
  });
  for (const action of ["ia-download", "ia-brief-btn", "ia-recommend-btn"]) {
    test("explicit " + action + " rejects unfinished invalid " + id, async () => {
      const p = await page();
      try {
        await prepareAsyncDate(p, id);
        await p.locator("#ia-review-btn").click();
        assert.equal(await p.locator("#" + action).isEnabled(), true);
        await p.locator("#" + id).focus();
        await p.keyboard.type("11162");
        let downloads = 0, requests = 0;
        p.on("download", () => { downloads += 1; });
        p.on("request", r => { if (new URL(r.url()).pathname === "/api/investigation") requests += 1; });
        // Activate without a focus change: the explicit action must perform strict collection itself.
        await p.locator("#" + action).evaluate(el => el.click());
        await p.waitForTimeout(40);
        assert.equal((await focus(p)).id, "ia-alert");
        assert.match(await p.locator("#ia-alert").textContent(), /real YYYY-MM-DD date/);
        assert.equal(downloads, 0);
        assert.equal(requests, 0);
        await proof(p, "invalid-date-" + id + "-" + action, { downloads, requests });
      } finally { await p.close(); }
    });
  }
}

for (const change of ["district", "action"]) {
  for (const activation of ["pointer", "programmatic"]) {
  test("a new " + change + " context does not inherit the active provisional date via " + activation, async () => {
    const p = await page();
    try {
      await observeCase(p);
      await prepareAsyncDate(p, "ia-track-date");
      const origin = await p.evaluate(() => window.dateRaceCase.active_branch_id);
      await p.locator("#ia-track-date").focus();
      await p.keyboard.type("1116202");
      await p.evaluate(() => { window.focusRaceDate = document.querySelector("#ia-track-date"); });
      if (change === "district") {
        await p.locator("#ia-district").selectOption("house:013");
        await p.locator("#ia-apply").evaluate(el => el.click());
      } else await p.locator("#ia-act-none").evaluate(el => { el.checked = true; el.dispatchEvent(new Event("change", { bubbles: true })); });
      assert.equal((await focus(p)).id, "ia-track-date", "opening a preview must not finish the native year");
      assert.equal(await p.evaluate(() => document.querySelector("#ia-track-date") === window.focusRaceDate), true);
      assert.equal(await p.evaluate(origin => window.dateRaceCase.branches.find(b => b.branch_id === origin).tracking.as_of, origin), null);
      if (activation === "pointer") await p.locator("#ia-preview-confirm").click(); // a real field exit still commits strictly
      else await p.locator("#ia-preview-confirm").evaluate(el => el.click());
      await p.waitForFunction(() => document.querySelector("#ia-cancel").hidden);
      assert.equal(await p.evaluate(() => window.focusRaceDate.isConnected), false);
      if (await p.locator("#ia-tracking").getAttribute("open") === null) await p.locator("#ia-tracking-summary").click();
      assert.equal(await p.locator("#ia-track-date").inputValue(), "");
      const pending = p.waitForEvent("download");
      await p.locator("#ia-download").click();
      const file = await pending;
      const saved = JSON.parse(fs.readFileSync(await file.path(), "utf8"));
      const active = saved.branches.find(b => b.branch_id === saved.active_branch_id);
      const prior = saved.branches.find(b => b.branch_id === origin);
      assert.equal(saved.branches.length, 2);
      assert.equal(active.tracking, null);
      assert.equal(active.checklist_edits.some(x => x.due_date), false);
      assert.equal(prior.tracking.as_of, activation === "pointer" ? "0202-11-16" : null, "only a real user field exit may write the origin date");
      if (change === "district") assert.equal(active.plan.district.code, "013");
      else assert.equal(active.selected_action_ref, null);
      await proof(p, "date-context-" + change + "-" + activation, { activeTracking: active.tracking, originTracking: prior.tracking, contexts: saved.branches.length });
    } finally { await p.close(); }
  });
  }
}

for (const firstField of ["baseline", "label"]) {
  test("SNAP tracking removes its preset and stale handler preserves " + firstField + " first entries", async () => {
    const p = await page();
    try {
      await p.locator("#ia-issue").selectOption("food_assistance_outreach");
      await p.locator("#ia-apply").evaluate(el => el.click());
      if (await p.locator("#ia-preview-confirm").count()) await p.locator("#ia-preview-confirm").click();
      await p.waitForFunction(() => document.querySelector("#ia-cancel").hidden && /SNAP/.test(document.querySelector("#ia-context-summary").textContent));
      if (await p.locator("#ia-tracking").getAttribute("open") === null) await p.locator("#ia-tracking-summary").click();
      await p.evaluate(() => { window.staleTrackingPreset = Array.from(document.querySelectorAll("#ia-tracking button")).find(b => /Use SNAP information-request tracking/.test(b.textContent)); });
      assert.equal(await p.evaluate(() => !!window.staleTrackingPreset), true);
      if (firstField === "label") {
        await p.locator("#ia-track-label").fill("Requests logged at front desk");
        await p.locator("#ia-track-date").click({ delay: 150 });
        await p.waitForTimeout(40);
      }
      await p.locator("#ia-track-base").focus();
      await p.keyboard.type("13");
      await p.keyboard.press("Tab");
      await p.waitForTimeout(40);
      assert.equal((await focus(p)).id, "ia-track-date");
      assert.equal(await p.locator("#ia-tracking button", { hasText: "Use SNAP information-request tracking" }).count(), 0);
      await p.evaluate(() => window.staleTrackingPreset.click()); // detached control must also be harmless
      assert.equal(await p.locator("#ia-track-base").inputValue(), "13");
      await p.keyboard.press("Shift+Tab");
      await p.waitForTimeout(40);
      assert.equal(await p.locator("#ia-tracking button", { hasText: "Use SNAP information-request tracking" }).count(), 0);
      await p.locator("#ia-download-staff").check();
      const saved = await savedCase(p), branch = saved.branches.find(b => b.branch_id === saved.active_branch_id);
      assert.deepEqual(branch.tracking, { label: firstField === "label" ? "Requests logged at front desk" : "", baseline: 13, as_of: null });
      await proof(p, "snap-preset-" + firstField, { tracking: branch.tracking });
    } finally { await p.close(); }
  });
}

for (const [stage, first, rest, value] of [["one-digit", "11162", "026", "0002-11-16"], ["three-digits", "1116202", "6", "0202-11-16"], ["complete", "11162026", "", "2026-11-16"]]) {
  test("a pending " + stage + " staff date holds an automatic language proposal in its origin", { skip: process.env.FOCUS_TEST_MOCK_ASK !== "1" }, async () => {
    const p = await page(); let release;
    try {
      await observeCase(p);
      await p.locator("#ia-tracking-summary").click();
      await p.locator("#ia-download-staff").check();
      let runs = 0;
      p.on("request", r => { if (new URL(r.url()).pathname === "/api/investigation" && r.postDataJSON().mode === "run") runs += 1; });
      release = await holdDateReply(p, "language-proposal");
      const origin = await p.evaluate(() => window.dateRaceCase.active_branch_id);
      await p.locator("#ia-track-date").focus();
      await p.evaluate(() => { window.focusRaceDate = document.querySelector("#ia-track-date"); });
      await p.keyboard.type(first);
      release();
      await p.waitForFunction(() => document.querySelector("#ia-question-cancel").hidden);
      assert.equal(await p.evaluate(() => document.activeElement === window.focusRaceDate && window.focusRaceDate.isConnected), true);
      assert.equal(await p.locator("#ia-track-date").inputValue(), value);
      assert.match(await p.locator("#ia-question-result").textContent(), /staff date is still being edited/);
      assert.equal(runs, 0);
      const held = await p.evaluate(() => window.dateRaceCase);
      assert.equal(held.active_branch_id, origin);
      assert.equal(held.branches.length, 1);
      assert.equal(held.branches[0].tracking, null, "the reply must not write the provisional value into the origin");
      if (rest) await p.keyboard.type(rest);
      assert.equal(await p.locator("#ia-track-date").inputValue(), "2026-11-16");
      await p.locator("#ia-download").focus();
      await p.waitForTimeout(40);
      const finished = await savedCase(p);
      assert.equal(finished.branches[0].tracking.as_of, "2026-11-16");
      await p.locator("#ia-proposal-run").click();
      await p.locator("#ia-preview-confirm").click();
      await p.waitForFunction(() => document.querySelector("#ia-cancel").hidden);
      const applied = await savedCase(p), target = applied.branches.find(b => b.branch_id === applied.active_branch_id);
      assert.equal(applied.branches.length, 2);
      assert.equal(applied.branches.find(b => b.branch_id === origin).tracking.as_of, "2026-11-16");
      assert.equal(target.tracking, null);
      assert.equal(target.plan.map_session, 2024);
      await proof(p, "held-date-proposal-" + stage, { heldOrigin: held.branches[0].tracking, originDate: "2026-11-16", targetTracking: target.tracking });
    } finally { if (release) release(); await p.close(); }
  });
}

for (const id of ["ia-track-date", "ia-chk-custom1-due"]) {
  test("a restore reply preserves both contexts without writing provisional " + id, async () => {
    const p = await page(); let release;
    try {
      await observeCase(p);
      await prepareAsyncDate(p, "ia-track-date");
      const targetId = await p.evaluate(() => window.dateRaceCase.active_branch_id);
      await p.locator("#ia-district").selectOption("house:013");
      await p.locator("#ia-apply").evaluate(el => el.click());
      await p.locator("#ia-preview-confirm").click();
      await p.waitForFunction(() => document.querySelector("#ia-cancel").hidden);
      await p.locator("#ia-track-label").fill("Second context tracking");
      await p.locator("#ia-chk-new").fill("Second context checklist");
      await p.locator("#ia-chk-add").click();
      const before = await p.evaluate(() => window.dateRaceCase), originId = before.active_branch_id;
      release = await holdDateReply(p, "restore");
      if (id === "ia-track-date" && await p.locator("#ia-tracking").getAttribute("open") === null) await p.locator("#ia-tracking-summary").click();
      await p.locator("#" + id).focus();
      await p.evaluate(id => { window.focusRaceDate = document.getElementById(id); }, id);
      await p.keyboard.type("1116202");
      assert.equal(await p.locator("#" + id).inputValue(), "0202-11-16");
      release();
      await p.waitForFunction(() => document.querySelector("#ia-cancel").hidden);
      const after = await p.evaluate(() => window.dateRaceCase);
      assert.equal(after.active_branch_id, targetId);
      assert.equal(await p.evaluate(() => window.focusRaceDate.isConnected), false);
      for (const branchId of [originId, targetId]) {
        const prior = before.branches.find(b => b.branch_id === branchId), now = after.branches.find(b => b.branch_id === branchId);
        assert.deepEqual(now.tracking, prior.tracking);
        assert.deepEqual(now.checklist_edits, prior.checklist_edits);
      }
      await proof(p, "date-restore-" + id, { origin: after.branches.find(b => b.branch_id === originId).tracking, target: after.branches.find(b => b.branch_id === targetId).tracking });
    } finally { if (release) release(); await p.close(); }
  });
}

test("question cancellation returns to question and late completion respects moved focus", { skip: process.env.FOCUS_TEST_MOCK_ASK !== "1" }, async () => {
  const p = await page();
  try {
    await recommend(p);
    await p.locator("#ia-note").fill("Ask cancellation keeps this note");
    const selected = await p.locator("#ia-tray-count").textContent();
    await p.locator("#ia-question-text").fill("Food assistance in House 28.");
    await p.locator("#ia-question-submit").click();
    await p.locator("#ia-question-cancel").focus();
    await p.keyboard.press("Enter");
    await p.waitForTimeout(40);
    await proof(p, "ask-cancel", { status: await p.locator("#ia-question-result").textContent() });
    assert.equal((await focus(p)).id, "ia-question-text");
    assert.equal(await p.locator("#ia-question-text").inputValue(), "Food assistance in House 28.");
    assert.equal(await p.locator("#ia-question-text").getAttribute("readonly"), null);
    assert.equal(await p.locator("#ia-question-result").getAttribute("aria-live"), "polite");
    assert.match(await p.locator("#ia-question-result").textContent(), /Question cancelled\. Your work is unchanged\./);
    await p.waitForTimeout(1300);
    assert.equal((await focus(p)).id, "ia-question-text");
    assert.equal(await p.locator("#ia-note").inputValue(), "Ask cancellation keeps this note");
    assert.equal(await p.locator("#ia-tray-count").textContent(), selected);
    await p.locator("#ia-question-submit").click();
    await p.locator("#ia-question-cancel").waitFor({ state: "visible" });
    await p.locator("#ia-title").fill("Typing during asynchronous reply");
    await p.waitForFunction(() => document.querySelector("#ia-question-cancel").hidden);
    assert.equal((await focus(p)).id, "ia-title");
    assert.equal(await p.locator("#ia-title").inputValue(), "Typing during asynchronous reply");
    await proof(p, "question-complete-moved-focus", { status: await p.locator("#ia-question-result").textContent() });
    await p.locator("#ia-question-submit").click();
    await p.locator("#ia-question-cancel").waitFor({ state: "visible" });
    await p.locator("#ia-title").focus();
    // A programmatic activation must not pull focus from a user who already left Cancel.
    await p.locator("#ia-question-cancel").evaluate(el => el.click());
    assert.equal((await focus(p)).id, "ia-title");
    assert.equal(await p.locator("#ia-title").inputValue(), "Typing during asynchronous reply");
    await proof(p, "ask-unfocused-cancel", { status: await p.locator("#ia-question-result").textContent() });
  } finally { await p.close(); }
});

test("lookup Run retains focus, blocks duplicate submission and releases busy state", async () => {
  const p = await page();
  try {
    let resolves = 0, fail = false;
    await p.route("**/api/resolve", async route => {
      resolves += 1; await new Promise(r => setTimeout(r, 800));
      if (fail) return route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ status: "error", reason: "Private focus-test failure" }) });
      await route.continue();
    });
    await p.locator("#tab-btn-workflow").click();
    await p.locator("#run-btn").focus();
    await p.keyboard.press("Enter");
    await p.waitForFunction(() => document.querySelector("#run-btn").getAttribute("aria-busy") === "true");
    const pending = { ariaDisabled: await p.locator("#run-btn").getAttribute("aria-disabled"), disabled: await p.locator("#run-btn").evaluate(el => el.disabled), cursor: await p.locator("#run-btn").evaluate(el => getComputedStyle(el).cursor), focus: await focus(p) };
    await proof(p, "lookup-pending", pending);
    await p.keyboard.press("Enter");
    await p.mouse.move(0, 0);
    await p.keyboard.down("Space");
    const pressed = await p.locator("#run-btn").evaluate(el => ({ background: getComputedStyle(el).backgroundColor, color: getComputedStyle(el).color }));
    await p.keyboard.up("Space");
    assert.deepEqual(pressed, { background: "rgb(236, 238, 242)", color: "rgb(63, 69, 80)" });
    await p.waitForFunction(() => !document.querySelector("#run-btn").hasAttribute("aria-busy"));
    await proof(p, "lookup-complete", { resolves });
    assert.equal(pending.ariaDisabled, "true");
    assert.equal(pending.disabled, false);
    assert.equal(pending.focus.id, "run-btn");
    assert.equal(pending.cursor, "not-allowed");
    assert.equal(resolves, 1);
    assert.equal((await focus(p)).id, "run-btn");
    assert.equal(await p.locator("#run-btn").getAttribute("aria-disabled"), null);
    assert.match(await p.locator("#result").textContent(), /House|District/);
    await p.keyboard.press("Enter");
    await p.waitForFunction(() => document.querySelector("#run-btn").hasAttribute("aria-busy"));
    await p.locator("#ctl-utterance").focus();
    await p.waitForFunction(() => !document.querySelector("#run-btn").hasAttribute("aria-busy"));
    assert.equal(resolves, 2);
    assert.equal((await focus(p)).id, "ctl-utterance");
    await proof(p, "lookup-complete-moved-focus", { resolves });
    fail = true;
    await p.locator("#run-btn").focus(); await p.keyboard.press("Enter");
    await p.waitForFunction(() => document.querySelector("#run-btn").hasAttribute("aria-busy"));
    await p.waitForFunction(() => !document.querySelector("#run-btn").hasAttribute("aria-busy"));
    assert.equal(resolves, 3);
    assert.notEqual((await focus(p)).tag, "BODY");
    assert.equal(await p.locator("#run-btn").getAttribute("aria-disabled"), null);
    await proof(p, "lookup-error", { resolves });
    await p.locator("#run-btn").focus(); await p.keyboard.press("Enter");
    await p.waitForFunction(() => document.querySelector("#run-btn").hasAttribute("aria-busy"));
    await p.locator("#ctl-utterance").focus();
    await p.waitForFunction(() => !document.querySelector("#run-btn").hasAttribute("aria-busy"));
    assert.equal(resolves, 4);
    assert.equal((await focus(p)).id, "ctl-utterance");
    await proof(p, "lookup-error-moved-focus", { resolves });
  } finally { await p.close(); }
});
