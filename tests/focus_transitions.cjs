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
async function page(url = base, { viewport = { width: 1280, height: 900 }, mockAsk = false } = {}) {
  assert.ok(["127.0.0.1", "localhost", "[::1]"].includes(url.hostname), "Use a private loopback app");
  const p = await browser.newPage({ viewport });
  await p.route("**/*", async route => {
    const u = new URL(route.request().url());
    if (!["127.0.0.1", "localhost", "[::1]"].includes(u.hostname)) return route.abort();
    if (process.env.FOCUS_TEST_BASELINE && /^\/static\/(app|investigation)\.js$/.test(u.pathname)) {
      return route.fulfill({ contentType: "application/javascript", body: fs.readFileSync(path.join(process.env.FOCUS_TEST_BASELINE, path.basename(u.pathname))) });
    }
    if (mockAsk && u.pathname === "/api/catalog") {
      const response = await route.fetch(), json = await response.json();
      json.language = { enabled: true, schema_version: "ia-language/1", limits: { deadline_seconds: 25 } };
      return route.fulfill({ response, json });
    }
    return route.continue();
  });
  await p.goto(url.href);
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

const firstFindingNote = "First parked finding note";
const secondFindingNote = "Second parked finding note";
const thirdFindingNote = "Third parked finding note";
const parkedFindingRow = (p, note) => p.locator("#ia-review li").filter({ hasText: note });
async function parkFindingNote(p, finding, note) {
  await finding.check();
  await p.locator("#ia-selected input").first().fill(note);
  await p.keyboard.press("Tab");
  await p.getByRole("button", { name: "Remove finding 1 from brief" }).click();
}
async function parkDuplicateFindingNotes(p) {
  const finding = p.locator('#ia-evidence input[type="checkbox"]').first();
  await parkFindingNote(p, finding, firstFindingNote);
  await parkFindingNote(p, finding, secondFindingNote);
  return finding;
}

test("leaving the last parked note moves focus to the staff notes and the next Tab continues there", async () => {
  const p = await page();
  try {
    await parkStaffNotes(p);
    const leave = p.getByRole("button", { name: "Leave in original context" });
    await leave.first().focus();
    await p.keyboard.press("Enter");
    assert.equal(await leave.count(), 1);
    assert.equal(await leave.evaluate(el => el === document.activeElement), true);
    await p.keyboard.press("Space");
    assert.equal(await leave.count(), 0);
    await proof(p, "leave-last-parked-note", {});
    assert.equal((await focus(p)).id, "ia-staff-h");
    await p.keyboard.press("Tab");
    assert.equal((await focus(p)).id, "ia-title");
  } finally { await p.close(); }
});

test("leaving the tail parked note with others remaining focuses the review heading", async () => {
  const p = await page();
  try {
    await parkStaffNotes(p);
    const leave = p.getByRole("button", { name: "Leave in original context" });
    await leave.last().focus();
    await p.keyboard.press("Space");
    assert.equal(await leave.count(), 1);
    await proof(p, "leave-tail-parked-note", {});
    assert.equal((await focus(p)).id, "ia-review-h");
    await p.keyboard.press("Tab");
    assert.equal(await p.getByRole("button", { name: "Copy into this context" }).evaluate(el => el === document.activeElement), true);
  } finally { await p.close(); }
});

test("leaving a parked note by pointer does not take focus from another control", async () => {
  const p = await page();
  try {
    await parkStaffNotes(p);
    const leave = p.getByRole("button", { name: "Leave in original context" });
    await p.locator("#ia-title").focus();
    await leave.last().evaluate(el => el.click());
    assert.equal(await leave.count(), 1);
    assert.equal((await focus(p)).id, "ia-title");
    await leave.evaluate(el => el.click());
    assert.equal(await leave.count(), 0);
    assert.equal((await focus(p)).id, "ia-title");
    await proof(p, "leave-parked-notes-without-focus", {});
  } finally { await p.close(); }
});

test("discarding parked notes keeps focus on the next Discard, then the review heading, then the staff notes", async () => {
  const p = await page();
  try {
    const finding = p.locator('#ia-evidence input[type="checkbox"]').first();
    for (const note of [firstFindingNote, secondFindingNote, thirdFindingNote]) await parkFindingNote(p, finding, note);
    const discard = p.getByRole("button", { name: "Discard this note" });
    assert.equal(await discard.count(), 3);
    await discard.first().focus();
    await p.keyboard.press("Enter");
    assert.equal(await discard.count(), 2);
    const second = parkedFindingRow(p, secondFindingNote).getByRole("button", { name: "Discard this note" });
    assert.equal(await second.evaluate(el => el === document.activeElement), true);
    await discard.last().focus();
    await p.keyboard.press("Space");
    assert.equal(await discard.count(), 1);
    assert.equal((await focus(p)).id, "ia-review-h");
    await p.keyboard.press("Tab");
    assert.equal(await p.getByRole("button", { name: "Copy into this context" }).evaluate(el => el === document.activeElement), true);
    await discard.focus();
    await p.keyboard.press("Enter");
    assert.equal(await discard.count(), 0);
    await proof(p, "discard-last-parked-note", {});
    assert.equal((await focus(p)).id, "ia-staff-h");
    await p.keyboard.press("Tab");
    assert.equal((await focus(p)).id, "ia-title");
  } finally { await p.close(); }
});

test("parked notes on the same finding retain distinct focus across a render", async () => {
  const p = await page();
  try {
    await parkDuplicateFindingNotes(p);
    const copies = p.getByRole("button", { name: "Copy into this context" });
    assert.equal(await copies.count(), 2);
    assert.notEqual(await copies.first().getAttribute("id"), await copies.last().getAttribute("id"));
    const second = parkedFindingRow(p, secondFindingNote).getByRole("button", { name: "Copy into this context" });
    await second.focus();
    await p.locator("#ia-district").selectOption("house:013");
    assert.equal(await second.evaluate(el => el === document.activeElement), true);
  } finally { await p.close(); }
});

test("copying the second parked note on the same finding copies its exact text", async () => {
  const p = await page();
  try {
    const finding = await parkDuplicateFindingNotes(p);
    await finding.check();
    const second = parkedFindingRow(p, secondFindingNote);
    await second.getByRole("button", { name: "Copy into this context" }).focus();
    await p.keyboard.press("Enter");
    const note = await p.locator("#ia-selected input").first().inputValue();
    const first = parkedFindingRow(p, firstFindingNote);
    await proof(p, "copy-second-parked-finding-note", { note, remaining: await p.locator("#ia-review li > p:first-child").allTextContents() });
    assert.equal(note, secondFindingNote);
    assert.equal(await second.count(), 0);
    assert.equal(await first.count(), 1);
    assert.equal((await focus(p)).id, "ia-review-h");
    await p.keyboard.press("Tab");
    assert.equal(await first.getByRole("button", { name: "Copy into this context" }).evaluate(el => el === document.activeElement), true);
  } finally { await p.close(); }
});

test("discarding the second parked note on the same finding leaves the first pending", async () => {
  const p = await page();
  try {
    const finding = await parkDuplicateFindingNotes(p);
    const first = parkedFindingRow(p, firstFindingNote), second = parkedFindingRow(p, secondFindingNote);
    await second.getByRole("button", { name: "Discard this note" }).click();
    await proof(p, "discard-second-parked-finding-note", { remaining: await p.locator("#ia-review li > p:first-child").allTextContents() });
    assert.equal(await first.count(), 1);
    assert.equal(await second.count(), 0);

    await parkFindingNote(p, finding, thirdFindingNote);
    const third = parkedFindingRow(p, thirdFindingNote);
    const discardThird = third.getByRole("button", { name: "Discard this note" });
    const thirdId = await discardThird.getAttribute("id");
    await first.getByRole("button", { name: "Discard this note" }).focus();
    await p.keyboard.press("Enter");
    assert.equal(await first.count(), 0);
    assert.equal(await discardThird.getAttribute("id"), thirdId);
    assert.equal((await focus(p)).id, thirdId);

    await finding.check();
    await third.getByRole("button", { name: "Copy into this context" }).focus();
    await p.keyboard.press("Space");
    const note = await p.locator("#ia-selected input").first().inputValue();
    await proof(p, "copy-parked-finding-note-after-resolved-slots", { note });
    assert.equal(note, thirdFindingNote);
    assert.equal(await p.locator("#ia-review li").count(), 0);
    assert.equal((await focus(p)).id, "ia-staff-h");
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

// Case files use browser downloads, the real file picker handler and the real replay endpoint.
const activeBranch = saved => saved.branches.find(b => b.branch_id === saved.active_branch_id);
const typedCard = p => p.locator("#ia-interpretation");
const importCard = p => p.locator("#ia-import-preview");
const requestDone = p => p.locator("#ia-cancel").waitFor({ state: "hidden" });
async function chooseCase(p, saved) {
  await p.locator("#ia-import-file").setInputFiles({
    name: "synthetic-case.json", mimeType: "application/json",
    buffer: Buffer.from(typeof saved === "string" ? saved : JSON.stringify(saved)),
  });
  await importCard(p).waitFor({ state: "visible" });
}
async function replayCase(p) {
  await p.locator("#ia-import-go").click();
  await requestDone(p);
  await importCard(p).waitFor({ state: "hidden" });
}
async function changeDistrict(p, district) {
  await p.locator("#ia-district").selectOption(district);
  await p.locator("#ia-context-apply-btn").click();
  await p.locator("#ia-preview-confirm").click();
  await requestDone(p);
}
function investigationCalls(p) {
  const calls = [];
  p.on("request", request => {
    if (new URL(request.url()).pathname === "/api/investigation") calls.push(request.postDataJSON());
  });
  return calls;
}
// Keep the real response in the loop unless a fault is explicitly injected.
async function gateInvestigation(p, mode, fault) {
  let open, arrive;
  const gate = new Promise(resolve => { open = resolve; });
  const received = new Promise(resolve => { arrive = resolve; });
  await p.route("**/api/investigation", async route => {
    const wire = route.request().postDataJSON();
    if (wire.mode !== mode) return route.fallback();
    const response = fault ? null : await route.fetch();
    arrive(wire);
    await gate;
    return fault ? fault(route) : route.fulfill({ response });
  }, { times: 1 });
  return { received, open };
}

for (const sameId of [true, false]) {
  for (const acceptStaff of [true, false]) {
    const scenario = (sameId ? "same" : "different") + "-id-" + (acceptStaff ? "accepted" : "clean");
    test("Phase 1 import resets staff export consent after " + scenario + " replay", { timeout: 30000 }, async () => {
      const p = await page();
      try {
        await p.locator("#ia-title").fill("Synthetic outgoing title");
        await p.locator("#ia-download-staff").check();
        const outgoing = await savedCase(p);
        assert.equal(activeBranch(outgoing).staff_edits.title, "Synthetic outgoing title");
        const incoming = structuredClone(outgoing);
        if (!sameId) incoming.case_id = "8fa7fc0b-b349-4ae7-8671-1c3c949da882";
        activeBranch(incoming).staff_edits.title = "Synthetic incoming title";
        const calls = investigationCalls(p);
        await chooseCase(p, incoming);
        assert.equal(await p.locator("#ia-download-staff").isChecked(), true, "preview keeps outgoing consent");
        assert.match(await importCard(p).textContent(), /Synthetic incoming title/);
        if (acceptStaff) await p.locator("#ia-import-staff").check();
        await replayCase(p);
        assert.equal(await p.locator("#ia-title").inputValue(), acceptStaff ? "Synthetic incoming title" : "");
        if (acceptStaff) assert.match(await p.locator("#ia-context-summary").textContent(), /Staff review required/);
        assert.equal(calls.filter(wire => wire.mode === "run").length, 1);
        for (const wire of calls) assert.doesNotMatch(JSON.stringify(wire), /Synthetic (incoming|outgoing) title|staff_edits/);
        const consent = await p.locator("#ia-download-staff").isChecked();
        const clean = await savedCase(p);
        await proof(p, "phase1-import-" + scenario, {
          expectedCaseId: incoming.case_id, downloadedCaseId: clean.case_id, consent,
          staffWorkIncluded: clean.staff_work_included, downloadedStaff: activeBranch(clean).staff_edits,
        });
        assert.equal(clean.case_id, incoming.case_id);
        assert.equal(consent, false);
        assert.equal(clean.staff_work_included, false);
        assert.deepEqual(activeBranch(clean).staff_edits, {});
        if (acceptStaff) {
          await p.locator("#ia-download-staff").check();
          assert.equal(activeBranch(await savedCase(p)).staff_edits.title, "Synthetic incoming title");
        }
      } finally { await p.close(); }
    });
  }
}

test("Phase 1 import preview, cancellation, failure and context restore keep outgoing consent", { timeout: 30000 }, async () => {
  const p = await page();
  let held;
  try {
    await p.locator("#ia-title").fill("Synthetic title that stays");
    await p.locator("#ia-download-staff").check();
    const outgoing = await savedCase(p);
    const checkOutgoing = async () => {
      assert.equal(await p.locator("#ia-download-staff").isChecked(), true);
      const saved = await savedCase(p);
      assert.equal(saved.case_id, outgoing.case_id);
      assert.equal(activeBranch(saved).staff_edits.title, "Synthetic title that stays");
    };
    const incoming = structuredClone(outgoing);
    incoming.case_id = "8fa7fc0b-b349-4ae7-8671-1c3c949da882";
    activeBranch(incoming).staff_edits.title = "Synthetic title from the file";
    await chooseCase(p, "{broken");
    await p.locator("#ia-import-close").click();
    await checkOutgoing();

    await chooseCase(p, incoming);
    await p.locator("#ia-import-cancel").click();
    await checkOutgoing();

    held = await gateInvestigation(p, "run");
    await chooseCase(p, incoming);
    await p.locator("#ia-import-go").click();
    await held.received;
    assert.equal(await p.locator(".ia-grid").evaluate(el => el.inert), true);
    const late = p.waitForResponse(r => new URL(r.url()).pathname === "/api/investigation");
    await p.locator("#ia-import-cancel").click();
    held.open();
    await (await late).finished();
    await checkOutgoing();

    held = await gateInvestigation(p, "run", route => route.abort("connectionreset"));
    await chooseCase(p, incoming);
    await p.locator("#ia-import-go").click();
    await held.received;
    held.open();
    await requestDone(p);
    assert.match(await p.locator("#ia-error").textContent(), /Choose the case file again/);
    if (await importCard(p).isVisible()) await p.locator("#ia-import-cancel").click();
    await checkOutgoing();

    await changeDistrict(p, "house:013");
    await p.locator("#ia-restore-0").click();
    await requestDone(p);
    await checkOutgoing();
    await proof(p, "phase1-import-consent-preserved", { stages: ["invalid file", "preview cancel", "pending replay cancel", "transport failure", "context restore"] });
  } finally { if (held) held.open(); await p.close(); }
});

test("Phase 1 import previews replacement and guards unsaved plans", { timeout: 30000 }, async () => {
  const p = await page();
  try {
    const clean = await savedCase(p);
    const calls = investigationCalls(p);
    await chooseCase(p, clean);
    const emptyPreview = await importCard(p).textContent();
    await p.locator("#ia-import-cancel").click();
    await p.locator("#ia-district").selectOption("house:013");
    await chooseCase(p, clean);
    await p.locator("#ia-import-go").click();
    const guard = await p.locator("#ia-alert").textContent();
    await proof(p, "phase1-import-empty-and-dirty", { emptyPreview, guard, calls: calls.length });
    assert.match(guard, /unapplied edits/i);
    assert.equal(await p.locator("#ia-district").inputValue(), "house:013");
    assert.equal(calls.length, 0);
    assert.match(emptyPreview, /replaces? (?:your current case|the case open in this page)/i);
  } finally { await p.close(); }
});

test("Phase 1 import inventories outgoing active and inactive work until the matching full download", { timeout: 30000 }, async () => {
  const p = await page();
  try {
    const incoming = await savedCase(p);
    await recommend(p);
    await p.locator("#ia-title").fill("Synthetic inactive title");
    await p.locator("#ia-chk-new").fill("Synthetic checklist item");
    await p.locator("#ia-chk-add").click();
    await p.locator("#ia-tracking-summary").click();
    await p.locator("#ia-track-label").fill("Synthetic inactive tracking");
    await p.locator("#ia-track-base").fill("12");
    await p.locator("#ia-download").focus();
    await changeDistrict(p, "house:013");
    await p.locator('#ia-evidence input[type="checkbox"]').first().check();
    await p.locator("#ia-note").fill("Synthetic active summary");
    await p.locator("#ia-download").focus();

    async function preview() {
      await chooseCase(p, incoming);
      const text = await importCard(p).textContent();
      await p.locator("#ia-import-cancel").click();
      return text;
    }
    const unsaved = await preview();
    const defaultExport = await savedCase(p);
    assert.equal(defaultExport.staff_work_included, false);
    assert.ok(defaultExport.branches.every(b => Object.keys(b.staff_edits).length === 0 && b.checklist_edits.length === 0 && b.tracking === null));
    assert.ok(defaultExport.branches.every(b => b.selected_claim_refs.length > 0));
    const partial = await preview();
    await p.locator("#ia-download-staff").check();
    const full = await savedCase(p);
    assert.equal(full.staff_work_included, true);
    assert.equal(full.branches[0].staff_edits.title, "Synthetic inactive title");
    assert.equal(full.branches[0].checklist_edits[0].text, "Synthetic checklist item");
    assert.equal(full.branches[0].tracking.label, "Synthetic inactive tracking");
    assert.equal(activeBranch(full).staff_edits.note, "Synthetic active summary");
    const covered = await preview();
    await p.locator("#ia-note").fill("Synthetic post-download change");
    await p.locator("#ia-download").focus();
    const changed = await preview();

    await proof(p, "phase1-import-download-coverage", { unsaved, partial, covered, changed });
    for (const text of [unsaved, partial, covered, changed]) assert.match(text, /replaces? (?:your current case|the case open in this page)/i);
    for (const text of [unsaved, partial, changed]) {
      assert.match(text, /select(ed|ion)/i);
      assert.match(text, /staff (notes|work|entr)/i);
      assert.match(text, /(?:save or reopen|download|cancel)/i);
      assert.match(text, /staff entr[^.]+Investigation 1, Investigation 2/i);
      assert.match(text, /selected finding[^.]+Investigation 1, Investigation 2/i);
      assert.doesNotMatch(text, /Synthetic (?:in)?active (?:summary|title|tracking)|Synthetic checklist item/);
    }
    assert.match(covered, /download.*was requested/i);
    assert.doesNotMatch(covered, /staff entr|selected findings? \(/i, "the outgoing contexts no longer need an inventory");
  } finally { await p.close(); }
});

test("Phase 1 import names held orphan notes and unfinished text even after a full download", { timeout: 30000 }, async () => {
  const p = await page();
  try {
    const incoming = await savedCase(p);
    await p.locator("#ia-download-staff").check();
    await savedCase(p);
    await parkFindingNote(p, p.locator('#ia-evidence input[type="checkbox"]').first(), "Synthetic orphan note");
    await p.locator("#ia-chk-new").fill("Synthetic unfinished item");
    await changeDistrict(p, "house:013");
    assert.equal(await p.locator("#ia-download").isDisabled(), true);
    assert.equal(await p.locator("#ia-rmbranch-0").isDisabled(), true);
    const held = await p.locator("#ia-download-held").textContent();
    await chooseCase(p, incoming);
    const preview = await importCard(p).textContent();
    await p.locator("#ia-import-cancel").click();
    await p.locator("#ia-restore-0").click();
    await requestDone(p);
    assert.equal(await p.locator("#ia-chk-new").inputValue(), "Synthetic unfinished item");
    assert.equal(await parkedFindingRow(p, "Synthetic orphan note").count(), 1);
    await proof(p, "phase1-import-held-work", { held, preview });
    assert.match(preview, /replaces? (?:your current case|the case open in this page)/i);
    assert.match(preview, /(?:removed|orphan|waiting).*finding|note.*removed finding/i);
    assert.match(preview, /unfinished custom checklist/i);
    assert.match(preview, /cancel.*(?:review|save or reopen)/i);
    assert.doesNotMatch(preview, /Synthetic orphan note|Synthetic unfinished item/);
  } finally { await p.close(); }
});

test("Phase 1 import updates its warning for checklist text entered after preview", { timeout: 30000 }, async () => {
  const p = await page();
  try {
    const incoming = await savedCase(p), calls = investigationCalls(p);
    await chooseCase(p, incoming);
    const before = await importCard(p).textContent();
    assert.doesNotMatch(before, /unfinished custom checklist/i);
    const item = p.locator("#ia-chk-new");
    await item.fill("Synthetic unfinished after preview");
    // Either show the new risk immediately, or use the attempted replay to refresh the preview without replaying.
    if (!/unfinished custom checklist/i.test(await importCard(p).textContent())) {
      await p.locator("#ia-import-go").click();
      await requestDone(p);
    }
    const updated = await importCard(p).textContent();
    await proof(p, "phase1-import-updated-held-warning", { before, updated, calls: calls.length, unfinished: await item.inputValue() });
    assert.equal(calls.length, 0);
    assert.match(updated, /unfinished custom checklist/i);
    assert.equal(await item.inputValue(), "Synthetic unfinished after preview");
    await p.locator("#ia-import-cancel").click();
    assert.equal(await item.inputValue(), "Synthetic unfinished after preview");

    await chooseCase(p, incoming);
    assert.match(await importCard(p).textContent(), /unfinished custom checklist/i);
    await replayCase(p);
    assert.equal(calls.length, 1);
    assert.equal(await item.inputValue(), "");
  } finally { await p.close(); }
});

test("Phase 1 Replay warns about staff text still focused at activation", { timeout: 30000 }, async () => {
  const p = await page();
  try {
    const incoming = await savedCase(p), calls = investigationCalls(p);
    await chooseCase(p, incoming);
    const summary = p.locator("#ia-note");
    await summary.fill("Synthetic summary still being edited");
    assert.equal((await focus(p)).id, "ia-note");
    // A connected button can activate from the accessibility action without first blurring the editor.
    await p.locator("#ia-import-go").evaluate(el => el.click());
    await requestDone(p);
    const warning = await importCard(p).textContent();
    const after = await summary.inputValue();
    await proof(p, "phase1-replay-flushes-active-summary", { warning, calls: calls.length, summary: after });
    assert.equal(calls.length, 0);
    assert.match(warning, /staff entr|staff notes/i);
    assert.equal(after, "Synthetic summary still being edited");
    await p.locator("#ia-import-cancel").click();
    await p.locator("#ia-download-staff").check();
    assert.equal(activeBranch(await savedCase(p)).staff_edits.note, "Synthetic summary still being edited");
  } finally { await p.close(); }
});

test("Phase 1 four-context review uses content-sensitive download guidance and keeps the removal gate", { timeout: 30000 }, async () => {
  const p = await page();
  try {
    for (const d of ["house:013", "house:010", "senate:008"]) await changeDistrict(p, d);
    async function cap() {
      await p.locator("#ia-district").selectOption("house:051");
      await p.locator("#ia-context-apply-btn").click();
      assert.equal(await p.locator("#ia-preview-confirm").isDisabled(), true);
      const warning = await p.locator("#ia-preview .alert").textContent();
      await p.locator("#ia-preview-cancel").click();
      await p.locator("#ia-discard").click();
      return warning;
    }
    const cleanWarning = await cap();
    assert.equal(await p.locator("#ia-rmbranch-0").isDisabled(), true);
    assert.equal((await savedCase(p)).staff_work_included, false);
    assert.equal(await p.locator("#ia-rmbranch-0").isEnabled(), true);
    await p.locator("#ia-title").fill("Synthetic fourth context title");
    await p.locator("#ia-download").focus();
    const staffWarning = await cap();
    assert.equal(await p.locator("#ia-rmbranch-0").isDisabled(), true);
    await savedCase(p);
    assert.equal(await p.locator("#ia-rmbranch-0").isDisabled(), true);
    await p.locator("#ia-download-staff").check();
    assert.equal(activeBranch(await savedCase(p)).staff_edits.title, "Synthetic fourth context title");
    assert.equal(await p.locator("#ia-rmbranch-0").isEnabled(), true);
    await p.locator("#ia-chk-new").fill("Unfinished even after full download");
    await cap();
    assert.equal(await p.locator("#ia-rmbranch-0").isDisabled(), true);
    await proof(p, "phase1-context-cap", { cleanWarning, staffWarning });
    assert.match(cleanWarning, /download.*remove a context/i);
    assert.doesNotMatch(cleanWarning, /with staff notes/i);
    assert.match(staffWarning, /download.*with staff notes.*remove a context/i);
  } finally { await p.close(); }
});

test("Phase 1 context removal rechecks held work at activation", { timeout: 30000 }, async () => {
  const p = await page();
  try {
    await changeDistrict(p, "house:013");
    const saved = await savedCase(p);
    assert.equal(saved.branches.length, 2);
    const remove = p.locator("#ia-rmbranch-0"), item = p.locator("#ia-chk-new");
    await item.fill("Synthetic unfinished text before Remove");
    const wasEnabled = await remove.isEnabled();
    if (wasEnabled) await remove.click();
    const remaining = await p.locator("#ia-branches > li").count();
    await proof(p, "phase1-remove-rechecks-held-work", { wasEnabled, remaining, text: await item.inputValue() });
    assert.equal(remaining, 2);
    assert.equal(await item.inputValue(), "Synthetic unfinished text before Remove");
    await item.fill("");
    await p.locator("#ia-download-staff").check(); // render without requesting another download
    assert.equal(await remove.isEnabled(), true);
    const summary = p.locator("#ia-note");
    await summary.fill("Synthetic summary still focused before Remove");
    assert.equal((await focus(p)).id, "ia-note");
    await remove.evaluate(el => el.click());
    const afterSummary = await summary.inputValue(), remainingAfterSummary = await p.locator("#ia-branches > li").count();
    await proof(p, "phase1-remove-flushes-active-summary", { summary: afterSummary, remaining: remainingAfterSummary });
    assert.equal(remainingAfterSummary, 2);
    assert.equal(afterSummary, "Synthetic summary still focused before Remove");
    assert.equal(activeBranch(await savedCase(p)).staff_edits.note, afterSummary);
    assert.equal(await remove.isEnabled(), true);
    await remove.click();
    assert.equal(await p.locator("#ia-branches > li").count(), 1);
  } finally { await p.close(); }
});

async function openTyped(p) {
  if (await p.locator("#ia-advanced").getAttribute("open") === null) await p.locator("#ia-advanced > summary").click();
  await p.locator("#ia-typed > summary").click();
}
async function readTyped(p, text) {
  if (text !== undefined) await p.locator("#ia-utterance").fill(text);
  await p.locator("#ia-interpret-btn").click();
}
const proposalButton = p => p.getByRole("button", { name: "Put in draft plan" });
const senateChoice = p => p.getByRole("button", { name: "Use Senate 013" });

for (const [kind, text, action] of [
  ["proposal", "add snap", proposalButton],
  ["clarification", "use district 13", senateChoice],
]) {
  for (const commit of [false, true]) {
    const scenario = kind + (commit ? "-after-fork" : "-after-draft-edit");
    test("Phase 1 typed " + scenario + " cannot replace a newer district draft", { timeout: 30000 }, async () => {
      const p = await page();
      try {
        const calls = investigationCalls(p);
        await openTyped(p);
        await readTyped(p, text);
        await action(p).waitFor();
        assert.equal(calls[0].plan.district.code, "028");
        if (commit) await changeDistrict(p, "house:010");
        else await p.locator("#ia-district").selectOption("house:010");
        if (await action(p).isVisible() && await action(p).isEnabled()) await action(p).click();
        const draftDistrict = await p.locator("#ia-district").inputValue();
        const recoveryText = await typedCard(p).textContent() + " " + await p.locator("#ia-status").textContent();
        await proof(p, "phase1-typed-" + scenario, { draftDistrict, recoveryText, modes: calls.map(wire => wire.mode) });
        assert.equal(draftDistrict, "house:010");
        assert.match(recoveryText, /read.*again|changed.*(?:request|plan)|(?:request|plan).*changed/i);
        assert.deepEqual(calls.map(wire => wire.mode), commit ? ["interpret", "run"] : ["interpret"]);
        await typedCard(p).getByRole("button", { name: /read.*again/i }).click();
        await requestDone(p);
        await action(p).click();
        assert.equal(await p.locator("#ia-district").inputValue(), kind === "clarification" ? "senate:013" : "house:010");
        assert.equal(calls.filter(wire => wire.mode === "run").length, commit ? 1 : 0);
      } finally { await p.close(); }
    });
  }
}

for (const [kind, first, next, oldAction, newAction] of [
  ["proposal", "use house 13", "use senate 8", proposalButton, proposalButton],
  ["clarification", "use district 13", "use district 8", senateChoice, p => p.getByRole("button", { name: "Use Senate 008" })],
]) {
  test("Phase 1 superseded typed " + kind + " cannot activate a newer card", { timeout: 30000 }, async () => {
    const p = await page();
    try {
      const calls = investigationCalls(p);
      await openTyped(p);
      await readTyped(p, first);
      const old = await oldAction(p).elementHandle();
      await readTyped(p, next);
      await requestDone(p);
      await newAction(p).waitFor();
      const detached = await old.evaluate(el => { const connected = el.isConnected; el.click(); return !connected; });
      const draftDistrict = await p.locator("#ia-district").inputValue();
      const card = await typedCard(p).textContent();
      await proof(p, "phase1-typed-superseded-" + kind, { detached, draftDistrict, card, modes: calls.map(wire => wire.mode) });
      assert.equal(detached, true);
      assert.equal(draftDistrict, "house:028");
      assert.ok(card.includes(next));
      assert.equal(await newAction(p).isVisible(), true);
      await newAction(p).click();
      assert.equal(await p.locator("#ia-district").inputValue(), "senate:008");
      assert.deepEqual(calls.map(wire => wire.mode), ["interpret", "interpret"]);
    } finally { await p.close(); }
  });
}

test("Phase 1 typed explicit district places only a draft and the next apply triggers one run", { timeout: 30000 }, async () => {
  const p = await page();
  try {
    const calls = investigationCalls(p);
    await openTyped(p);
    await readTyped(p, "use senate 8");
    await proposalButton(p).click();
    assert.equal(await p.locator("#ia-district").inputValue(), "senate:008");
    assert.match(await p.locator("#ia-context-summary").textContent(), /Showing results for House 028/);
    assert.deepEqual(calls.map(wire => wire.mode), ["interpret"]);
    await p.locator("#ia-context-apply-btn").click();
    await p.locator("#ia-preview-confirm").click();
    await requestDone(p);
    assert.deepEqual(calls.map(wire => wire.mode), ["interpret", "run"]);
    assert.equal(calls[1].plan.district.code, "008");
    assert.equal(calls[1].plan.district.chamber, "senate");
    await proof(p, "phase1-typed-explicit-district", { applied: calls[1].plan.district });
  } finally { await p.close(); }
});

for (const [kind, fault] of [
  ["cancel", null],
  ["HTTP error", route => route.fulfill({ status: 500, json: { status: "error", code: "internal_error", message: "Synthetic typed request error" } })],
  ["403", route => route.fulfill({ status: 403, json: { status: "error", code: "forbidden" } })],
  ["abort", route => route.abort("connectionreset")],
]) {
  test("Phase 1 typed " + kind + " ends Reading and preserves text, focus and retry", { timeout: 30000 }, async () => {
    const p = await page();
    let held;
    try {
      const calls = investigationCalls(p), refreshes = [];
      p.on("request", r => { if (new URL(r.url()).pathname === "/api/health") refreshes.push(r.url()); });
      await openTyped(p);
      held = await gateInvestigation(p, "interpret", fault);
      const original = "use house 13";
      await readTyped(p, original);
      const first = await held.received;
      assert.match(await typedCard(p).textContent(), /Reading the request/);
      if (kind === "cancel") {
        await p.locator("#ia-cancel").focus();
        await p.keyboard.press("Enter");
      } else held.open();
      await requestDone(p);
      const stalledCard = await typedCard(p).textContent();
      const settledFocus = await focus(p);
      await proof(p, "phase1-typed-" + kind.replace(" ", "-").toLowerCase(), { card: stalledCard, settledFocus, healthRefreshes: refreshes.length });
      assert.doesNotMatch(stalledCard, /Reading the request/);
      assert.equal(await p.locator("#ia-utterance").inputValue(), original);
      assert.notEqual(settledFocus.tag, "BODY");
      assert.equal(await typedCard(p).getAttribute("aria-live"), "polite");
      if (kind === "403") assert.equal(refreshes.length, 1);
      const retry = p.getByRole("button", { name: /read.*again/i }).first();
      if (await retry.isVisible() && await retry.isEnabled()) await retry.click();
      else await readTyped(p);
      await proposalButton(p).waitFor();
      assert.equal(calls.length, 2);
      assert.notEqual(calls[1].request_id, first.request_id);
      assert.equal(calls[1].utterance, original);
      assert.equal(await p.locator("#ia-district").inputValue(), "house:028");
      if (kind === "cancel") {
        const old = p.waitForResponse(r => r.request().postDataJSON()?.request_id === first.request_id);
        held.open();
        await (await old).finished();
        await proposalButton(p).waitFor();
      }
      await proposalButton(p).click();
      assert.equal(await p.locator("#ia-district").inputValue(), "house:013");
    } finally { if (held) held.open(); await p.close(); }
  });
}

test("Phase 1 late old typed error cannot end a newer request or steal focus", { timeout: 30000 }, async () => {
  const p = await page();
  let old, fresh;
  try {
    p.setDefaultTimeout(7000);
    const calls = investigationCalls(p);
    await openTyped(p);
    old = await gateInvestigation(p, "interpret", route => route.fulfill({ status: 403, json: { status: "error", code: "forbidden" } }));
    await readTyped(p, "use house 13");
    const first = await old.received;
    await p.locator("#ia-cancel").click();
    fresh = await gateInvestigation(p, "interpret");
    await readTyped(p, "use senate 8");
    await fresh.received;
    const late = p.waitForResponse(r => r.request().postDataJSON()?.request_id === first.request_id);
    await p.locator("#ia-district").focus();
    old.open();
    await late;
    assert.equal(await p.locator("#ia-cancel").isVisible(), true);
    assert.match(await typedCard(p).textContent(), /Reading the request.*use senate 8/s);
    assert.equal((await focus(p)).id, "ia-district");
    fresh.open();
    await proposalButton(p).waitFor();
    await proof(p, "phase1-typed-late-old", { old: first.utterance, current: calls[1].utterance, card: await typedCard(p).textContent() });
    assert.match(await typedCard(p).textContent(), /use senate 8/);
    assert.doesNotMatch(await typedCard(p).textContent(), /use house 13|Reading the request/);
    await proposalButton(p).click();
    assert.equal(await p.locator("#ia-district").inputValue(), "senate:008");
    assert.deepEqual(calls.map(wire => wire.mode), ["interpret", "interpret"]);
  } finally { if (old) old.open(); if (fresh) fresh.open(); await p.close(); }
});

// ------------------------------------------------------------------ Phase 2 flow (#8 #12 #14 #15 #21)
const MAP_YEAR = "2026 map display, 2024 district statistics";
test("Phase 2 context, restore, remove and import labels name the display map year apart from 2024 statistics", { timeout: 30000 }, async () => {
  const p = await page();
  try {
    await changeDistrict(p, "house:013");
    const first = p.locator("#ia-branches > li").first();
    assert.ok((await first.locator("strong").textContent()).endsWith(" · " + MAP_YEAR));
    assert.match(await p.locator("#ia-restore-0").getAttribute("aria-label"), new RegExp("^Restore context 1 \\(House 028 · .* · " + MAP_YEAR + "\\) by replaying its evidence$"));
    assert.match(await p.locator("#ia-rmbranch-0").getAttribute("aria-label"), new RegExp(" · " + MAP_YEAR + "\\) from this page$"));
    const saved = await savedCase(p);
    assert.deepEqual(saved.branches.map(b => b.plan.map_session), [2026, 2026], "the plan is unchanged");
    await chooseCase(p, saved);
    assert.match(await importCard(p).textContent(), new RegExp("House 013 · .* · " + MAP_YEAR));
    await proof(p, "phase2-map-year-labels", {});
    await p.locator("#ia-import-cancel").click();
  } finally { await p.close(); }
});

test("Phase 2 both Apply controls say whether a change opens the context review or runs at once", { timeout: 45000 }, async () => {
  const p = await page();
  try {
    const calls = investigationCalls(p);
    const upper = async () => ({ name: await p.getByRole("button", { name: /these changes$/ }).textContent(),
      description: await p.locator("#ia-context-apply-btn").evaluate(b => document.getElementById(b.getAttribute("aria-describedby")).textContent) });
    if (await p.locator("#ia-advanced").getAttribute("open") === null) await p.locator("#ia-advanced > summary").click();
    // Direct run: Move up for step 2 of the default House 028 plan.
    await p.locator("#ia-up-s2").click();
    for (const id of ["#ia-context-apply-why", "#ia-apply-reason"]) assert.match(await p.locator(id).textContent(), /^Runs the reordered plan at once in this context; no review is needed/);
    const direct = await upper();
    assert.equal(direct.name, "Apply these changes");
    assert.match(direct.description, /^Runs the reordered plan at once/);
    await p.locator("#ia-context-apply-btn").focus();
    await p.keyboard.press("Enter");
    assert.equal(await p.locator("#ia-preview").isVisible(), false);
    await requestDone(p);
    assert.deepEqual(calls.map(w => w.mode), ["run"], "the reorder ran directly");
    assert.equal((await focus(p)).id, "ia-evidence-h", "unchanged focus contract after a direct run");
    // Review: a district change.
    await p.locator("#ia-district").selectOption("house:013");
    assert.match(await p.locator("#ia-status").textContent(), /^Context edited\. Choose Review and apply these changes to review it before it runs\.$/);
    const review = await upper();
    assert.equal(review.name, "Review and apply these changes");
    assert.match(review.description, /^Opens the context review first:.*Nothing runs until you confirm\.$/);
    assert.match(await p.locator(".ia-draft-note").textContent(), /Choose Review and apply these changes to review it before it runs/);
    for (const id of ["#ia-context-apply-why", "#ia-apply-reason"]) assert.match(await p.locator(id).textContent(), /^Opens the context review first:.*Nothing runs until you confirm\.$/);
    await p.locator("#ia-apply").click();
    assert.equal(await p.locator("#ia-preview").isVisible(), true);
    assert.deepEqual(calls.map(w => w.mode), ["run"], "nothing ran before confirmation");
    await proof(p, "phase2-apply-prediction", { direct, review });
    await p.locator("#ia-preview-cancel").click();
    assert.equal((await focus(p)).id, "ia-apply");
    // Four-context limit: the upper action only opens a review that cannot confirm.
    await p.locator("#ia-discard").click();
    for (const d of ["house:013", "house:010", "senate:008"]) await changeDistrict(p, d);
    await p.locator("#ia-district").selectOption("house:051");
    const cap = await upper();
    assert.equal(cap.name, "Review these changes");
    assert.match(cap.description, /four contexts, so one must be removed/);
    assert.match(await p.locator("#ia-status").textContent(), /^Context edited\. Choose Review these changes to review it before it runs\.$/);
    await p.locator("#ia-context-apply-btn").focus();
    await p.keyboard.press("Enter");
    assert.equal(await p.locator("#ia-preview-confirm").isDisabled(), true);
    assert.deepEqual(calls.map(w => w.mode), ["run", "run", "run", "run"], "only the three context changes ran");
  } finally { await p.close(); }
});

test("Phase 2 a held Ask pure reorder offers focus-only scope routes for moved unchanged steps", { timeout: 30000 }, async () => {
  // Offline fake Ask transport in this page only: no provider, no server language route.
  const p = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  try {
    let env = null; const language = [];
    await p.route("**/*", async route => {
      const u = new URL(route.request().url());
      if (!["127.0.0.1", "localhost", "[::1]"].includes(u.hostname)) return route.abort();
      if (u.pathname === "/api/catalog") { const r = await route.fetch(), j = await r.json(); j.language = { enabled: true, schema_version: "ia-language/1", message: "fixture", limits: { deadline_seconds: 25 } }; return route.fulfill({ response: r, json: j }); }
      if (!u.pathname.startsWith("/api/language/")) return route.continue();
      const action = u.pathname.split("/").pop(), body = route.request().postDataJSON(); language.push(action);
      if (action === "start") {
        const c = body.context, rel = await route.request().frame().page().evaluate(async () => (await (await fetch("/api/catalog")).json()).investigation.release_id || "");
        env = { request_id: body.request_id, context: c, context_digest: "sha256:" + "b".repeat(64), tokens: { schema_version: "ia-language/1", release_id: rel, ...Object.fromEntries(["case_id", "branch_id", "revision", "snapshot_id", "operation_version", "recipe_version"].map(k => [k, c[k]])) } };
        return route.fulfill({ status: 202, json: { ...env, status: "pending" } });
      }
      if (action === "cancel") return route.fulfill({ json: { status: "cancelled" } });
      const before = env.context.confirmed_plan, after = JSON.parse(JSON.stringify(before)), [a, b, c, d] = after.steps;
      after.steps = [c, a, b, d];
      return route.fulfill({ json: { ...env, status: "propose", intent: "replace_plan", message: "fixture", reason_code: "", normalized_plan: after,
        typed_diff: [{ field: "step_order", change: "changed", before: ["s1", "s2", "s3", "s4"], after: ["s3", "s1", "s2", "s4"] }], inherited_fields: ["district"], source_inspection_refs: [], choices: [], clarify_field: "" } });
    });
    await p.goto(base.href);
    await p.waitForFunction(() => !document.querySelector("#ia-recommend").hidden && document.querySelector("#ia-cancel").hidden);
    const calls = investigationCalls(p);
    await p.locator("#ia-question-text").fill("In my district, please review this plan.");
    await p.locator("#ia-question-submit").click();
    const diff = p.locator("#ia-proposal-diff");
    await diff.waitFor({ state: "attached" });
    await diff.locator("summary").focus();
    await p.keyboard.press("Enter");
    const routes = await diff.locator("button").evaluateAll(bs => bs.map(b => [b.id, b.textContent, b.getAttribute("aria-label")]));
    assert.deepEqual(routes.map(r => r[1]), ["Open step 3 scope (step 1 in the proposal)", "Open step 1 scope (step 2 in the proposal)", "Open step 2 scope (step 3 in the proposal)"]);
    assert.match(routes[0][2], /^Open the scope editor for step 3 of your draft plan, step 1 of the proposed plan: Program reference — Kūpuna Care$/);
    const steps = () => p.locator("#ia-steps > li").evaluateAll(xs => xs.map(x => x.id + "|" + x.querySelector(".ia-step-scope").textContent));
    const draft = await steps();
    await p.locator("#ia-order-scope-s3").focus();
    await p.keyboard.press("Enter");
    assert.equal(await p.evaluate(() => document.activeElement.parentElement.id), "ia-scope-s3");
    assert.equal(await p.locator("#ia-scope-s3").getAttribute("open"), "");
    assert.deepEqual(await steps(), draft, "focus only: the draft is unchanged");
    assert.equal(await p.locator("#ia-proposal-run").isVisible(), true, "the held proposal is still shown, not acknowledged");
    assert.deepEqual(calls, [], "nothing ran");
    assert.deepEqual(language, ["start", "status"], "no further question was sent");
    await proof(p, "phase2-ask-reorder-routes", { routes });
  } finally { await p.close(); }
});

test("Phase 2 a confirmed-basis reorder names routes by the live draft position, not the plan the question used", { timeout: 30000 }, async () => {
  // Offline fake Ask transport in this page only: a control-conflict clarification, then a guarded reorder of the confirmed plan.
  const p = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  try {
    let env = null, statuses = 0; const language = [], starts = [];
    await p.route("**/*", async route => {
      const u = new URL(route.request().url());
      if (!["127.0.0.1", "localhost", "[::1]"].includes(u.hostname)) return route.abort();
      if (u.pathname === "/api/catalog") { const r = await route.fetch(), j = await r.json(); j.language = { enabled: true, schema_version: "ia-language/1", message: "fixture", limits: { deadline_seconds: 25 } }; return route.fulfill({ response: r, json: j }); }
      if (!u.pathname.startsWith("/api/language/")) return route.continue();
      const action = u.pathname.split("/").pop(), body = route.request().postDataJSON(); language.push(action);
      if (action === "start") {
        const c = body.context; starts.push(JSON.parse(JSON.stringify(c)));
        const rel = await route.request().frame().page().evaluate(async () => (await (await fetch("/api/catalog")).json()).investigation.release_id || "");
        env = { request_id: body.request_id, context: c, context_digest: "sha256:" + "c".repeat(64), tokens: { schema_version: "ia-language/1", release_id: rel, ...Object.fromEntries(["case_id", "branch_id", "revision", "snapshot_id", "operation_version", "recipe_version"].map(k => [k, c[k]])) } };
        return route.fulfill({ status: 202, json: { ...env, status: "pending" } });
      }
      if (action === "cancel") return route.fulfill({ json: { status: "cancelled" } });
      const empty = { normalized_plan: null, typed_diff: [], inherited_fields: [], source_inspection_refs: [] };
      if (++statuses === 1) return route.fulfill({ json: { ...env, ...empty, status: "clarify", intent: "none", message: "fixture", reason_code: "control_conflict", clarify_field: "control_conflict",
        choices: [{ alias: "x_confirmed", field: "control_conflict", value: "confirmed", label: "Use confirmed plan" }, { alias: "x_draft", field: "control_conflict", value: "draft", label: "Use draft plan" }] } });
      const before = env.context.confirmed_plan, after = JSON.parse(JSON.stringify(before)), [a, b, c, d] = after.steps;
      after.steps = [c, a, b, d];
      return route.fulfill({ json: { ...env, status: "propose", intent: "replace_plan", message: "fixture", reason_code: "", normalized_plan: after,
        typed_diff: [{ field: "step_order", change: "changed", before: ["s1", "s2", "s3", "s4"], after: ["s3", "s1", "s2", "s4"] }], inherited_fields: ["district"], source_inspection_refs: [], choices: [], clarify_field: "" } });
    });
    await p.goto(base.href);
    await p.waitForFunction(() => !document.querySelector("#ia-recommend").hidden && document.querySelector("#ia-cancel").hidden);
    const calls = investigationCalls(p);
    if (await p.locator("#ia-advanced").getAttribute("open") === null) await p.locator("#ia-advanced > summary").click();
    await p.locator("#ia-up-s3").click();   // live unapplied draft: [s1, s3, s2, s4]
    const order = () => p.locator("#ia-steps > li").evaluateAll(xs => xs.map(x => x.id + "|" + x.querySelector(".ia-step-scope").textContent));
    const draft = await order();
    assert.deepEqual(draft.map(x => x.split("|")[0]), ["ia-step-s1", "ia-step-s3", "ia-step-s2", "ia-step-s4"]);
    await p.locator("#ia-question-text").fill("In my district, please review this plan.");
    await p.locator("#ia-question-submit").click();
    await p.getByRole("button", { name: "Use Use confirmed plan" }).click();
    assert.match(await p.locator("#ia-question-scope").textContent(), /confirmed plan/);
    await p.locator("#ia-question-submit").click();
    const diff = p.locator("#ia-proposal-diff");
    await diff.waitFor({ state: "attached" });
    assert.deepEqual(starts[1].draft_plan.steps.map(s => s.step_id), ["s1", "s2", "s3", "s4"], "the confirmed basis was sent as the question's plan");
    await diff.locator("summary").focus();
    await p.keyboard.press("Enter");
    const routes = await diff.locator("button").evaluateAll(bs => bs.map(b => [b.id, b.textContent, b.getAttribute("aria-label")]));
    assert.deepEqual(routes.map(r => [r[0], r[1]]), [["ia-order-scope-s3", "Open step 2 scope (step 1 in the proposal)"], ["ia-order-scope-s1", "Open step 1 scope (step 2 in the proposal)"], ["ia-order-scope-s2", "Open step 3 scope (step 3 in the proposal)"]]);
    assert.equal(routes[0][2], "Open the scope editor for step 2 of your draft plan, step 1 of the proposed plan: Program reference — Kūpuna Care");
    assert.match(await diff.locator("li").last().textContent(), /1\. Program reference — Kūpuna Care \(step 3 in the plan the question used\)/);
    const sent = calls.length + language.length;
    const seen = []; p.on("request", r => seen.push(r.url()));
    await p.locator("#ia-order-scope-s3").focus();
    await p.keyboard.press("Enter");
    assert.equal(await p.evaluate(() => document.activeElement.parentElement.id), "ia-scope-s3");
    assert.equal(await p.evaluate(() => [...document.querySelectorAll("#ia-steps > li")].indexOf(document.activeElement.closest("li.ia-step")) + 1), 2, "the editor opened is live draft step 2");
    assert.deepEqual(await order(), draft, "live draft unchanged");
    assert.match(await p.locator("#ia-question-scope").textContent(), /confirmed plan/, "chosen basis kept");
    assert.equal(await p.locator("#ia-proposal-run").isVisible(), true);
    await p.waitForTimeout(100);
    assert.deepEqual(seen, [], "no request at route activation");
    assert.equal(calls.length + language.length, sent);
    assert.deepEqual(calls, [], "nothing ran");
    await proof(p, "phase2-ask-confirmed-basis-routes", { routes });
  } finally { await p.close(); }
});

for (const [label, width, height, cap, next] of [["320x568 four-context", 320, 568, true, "ia-preview-cancel"], ["320x568", 320, 568, false, "ia-preview-confirm"],
  ["390x844 four-context", 390, 844, true, "ia-preview-cancel"], ["desktop", 1280, 900, false, "ia-preview-confirm"]]) {
  test("Phase 2 " + label + " review shows its heading and Tab reaches " + next, { timeout: 45000 }, async () => {
    const p = await page();
    try {
      if (cap) for (const d of ["house:013", "house:010", "senate:008"]) await changeDistrict(p, d);
      await p.setViewportSize({ width, height });
      await p.locator("#ia-district").selectOption(cap ? "house:051" : "house:020");
      await p.locator("#ia-context-apply-btn").focus();
      await p.keyboard.press("Enter");
      await p.waitForTimeout(80);
      const opened = await p.evaluate(() => {
        const r = document.querySelector("#ia-preview h3").getBoundingClientRect(), panel = document.querySelector("#ia-preview").getBoundingClientRect();
        return { focus: document.activeElement.id, top: r.top, bottom: r.bottom, tall: panel.height > innerHeight, viewport: innerHeight };
      });
      assert.equal(opened.focus, "ia-preview");
      assert.ok(opened.top >= 0 && opened.bottom <= opened.viewport, JSON.stringify(opened));
      assert.equal(await p.locator("#ia-preview").count(), 1);
      await p.keyboard.press("Tab");
      assert.equal((await focus(p)).id, next);
      await proof(p, "phase2-review-" + label.replace(/\W+/g, "-"), opened);
    } finally { await p.close(); }
  });
}

test("Phase 2 typed step choices name each step and open its existing scope editor without changing the plan", { timeout: 30000 }, async () => {
  const p = await page();
  try {
    await openTyped(p);
    await p.locator("#ia-add-op").selectOption("compare");
    await p.locator("#ia-add-btn").click();
    await readTyped(p, "compare senior poverty with maui county");
    await requestDone(p);
    const card = await typedCard(p).textContent();
    assert.match(card, /Step 2 · Compare with a geography — .*comparison: State of Hawaiʻi \(typed-request name s2\)/);
    assert.match(card, /Step 5 · Compare with a geography/);
    const before = await p.locator("#ia-steps > li").allTextContents();
    const route = p.getByRole("button", { name: "Open the scope editor for step 5, Compare with a geography, in your draft plan" });
    await route.focus();
    await p.keyboard.press("Enter");
    assert.equal(await p.evaluate(() => document.activeElement.parentElement.id), "ia-scope-s5");
    assert.equal(await p.locator("#ia-scope-s5").getAttribute("open"), "");
    assert.deepEqual(await p.locator("#ia-steps > li").allTextContents(), before, "focus only; the draft is unchanged");
    await proof(p, "phase2-typed-step-route", { card });
    // Once the draft changes, the card keeps readable step references but offers no route.
    await p.locator("#ia-scope-s5 select").selectOption("HI-COUNTY-009-2024");
    assert.match(await typedCard(p).textContent(), /Step 5 · Compare with a geography — .*comparison: State of Hawaiʻi/);
    assert.equal(await typedCard(p).getByRole("button", { name: /Open the scope editor/ }).count(), 0);
  } finally { await p.close(); }
});

test("Phase 2 typed add of a program step already in the plan reports it and adds no step", { timeout: 30000 }, async () => {
  const p = await page();
  try {
    const calls = investigationCalls(p);
    await openTyped(p);
    await readTyped(p, "add kupuna care");
    await requestDone(p);
    assert.match(await typedCard(p).textContent(), /Already in the plan \(no change\).*Step 3 of the plan is already this program reference, so no step was added\./s);
    assert.equal(await proposalButton(p).count(), 0, "nothing to place: no mutating control");
    await typedCard(p).getByRole("button", { name: "Discard" }).click();
    assert.equal(await p.locator("#ia-steps > li").count(), 4);
    assert.match(await p.locator("#ia-status").textContent(), /discarded\. The plan is unchanged/);
    // An explicit district with the same step still changes the plan, so placement stays available.
    await readTyped(p, "add kupuna care for house 5");
    await requestDone(p);
    assert.match(await typedCard(p).textContent(), /Proposed plan change \(not applied\)/);
    await proposalButton(p).click();
    assert.equal(await p.locator("#ia-district").inputValue(), "house:005");
    assert.equal(await p.locator("#ia-steps > li").count(), 4);
    assert.deepEqual(calls.map(w => w.mode), ["interpret", "interpret"]);
    await proof(p, "phase2-typed-duplicate", {});
  } finally { await p.close(); }
});

test("Phase 2 an untouched initial plan with no results never says it already ran", { timeout: 30000 }, async () => {
  const p = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  try {
    let first = true;
    await p.route("**/*", async route => {
      const u = new URL(route.request().url());
      if (!["127.0.0.1", "localhost", "[::1]"].includes(u.hostname)) return route.abort();
      if (u.pathname === "/api/investigation" && first) { first = false; return route.abort("connectionreset"); }   // the automatic first run fails
      return route.continue();
    });
    await p.goto(base.href);
    await p.locator("#ia-error").waitFor({ state: "visible" });
    if (await p.locator("#ia-advanced").getAttribute("open") === null) await p.locator("#ia-advanced > summary").click();
    assert.equal(await p.locator("#ia-apply").textContent(), "Apply plan");
    const reason = await p.locator("#ia-apply-reason").textContent();
    assert.match(reason, /^Runs the plan at once in this context and lists its findings; no review is needed\.$/);
    assert.equal(await p.locator("#ia-context-apply").isHidden(), true);
    await p.locator("#ia-apply").click();
    await p.locator("#ia-cancel").waitFor({ state: "hidden" });
    assert.equal(await p.locator("#ia-apply").textContent(), "Run again");
    assert.equal((await focus(p)).id, "ia-evidence-h", "existing contract: busy Apply hands focus to Cancel, then to the findings");
    await proof(p, "phase2-initial-no-results", { reason });
  } finally { await p.close(); }
});

// ------------------------------------------------------------------ Phase 3
async function p3Advanced(p) { if (await p.locator("#ia-advanced").getAttribute("open") === null) await p.locator("#ia-advanced > summary").click(); }
async function p3Scope(p, step) { await p3Advanced(p); await p.evaluate(s => { document.querySelector("#ia-scope-" + s).open = true; }, step); }
async function p3Programs(p, step, programs) {
  await p3Scope(p, step);
  for (const want of [true, false]) {
    const values = await p.$$eval(`input[id^="ia-${step}-programs-"]`, xs => xs.map(x => [x.value, x.checked]));
    for (const [v, on] of values) {
      const box = p.locator(`input[id^="ia-${step}-programs-"][value="${v}"]`);
      if (want && programs.includes(v) && !on) await box.check();
      if (!want && !programs.includes(v) && on) await box.uncheck();
    }
  }
}
async function p3Lead(p, step, program) { await p3Scope(p, step); await p.locator("#ia-" + step + "-program").selectOption(program); }
async function p3Apply(p) {
  await p3Advanced(p);
  await p.locator("#ia-apply").click();
  if (await p.locator("#ia-preview").isVisible()) await p.locator("#ia-preview-confirm").click();
  await requestDone(p);
}
const p3Tray = p => p.evaluate(() => ({ count: document.querySelector("#ia-tray-count").textContent, selected: document.querySelectorAll("#ia-selected > li[id]").length,
  action: (document.querySelector('input[name="ia-action"]:checked') || {}).id || null, recommendHidden: document.querySelector("#ia-recommend").hidden,
  conflictHidden: document.querySelector("#ia-recommend-conflict").hidden, conflict: document.querySelector("#ia-recommend-conflict").textContent }));
const P3_MIXED = {
  "A reference switched": async p => { await p3Programs(p, "s3", ["snap_hi"]); },
  "B hypothesis switched": async p => { await p3Lead(p, "s4", "snap_hi"); },
  "C complete switch": async p => { await p3Programs(p, "s3", ["snap_hi"]); await p3Lead(p, "s4", "snap_hi"); },
  "D reference switched, hypothesis step first": async p => { await p3Programs(p, "s3", ["snap_hi"]); await p.locator("#ia-up-s4").click(); },
};
for (const [label, edit] of Object.entries(P3_MIXED)) {
  test("Phase 3 #4 " + label + ": Create recommended brief is withheld before any selection or action change", { timeout: 45000 }, async () => {
    const p = await page();
    try {
      await edit(p); await p3Apply(p);
      const calls = investigationCalls(p);
      await p.locator('#ia-evidence input[aria-label^="Select for brief: Population age 65 and over, House"]').first().check();   // a manual choice
      const t = await p3Tray(p);
      assert.equal(t.recommendHidden, true, "the shortcut is not offered"); assert.equal(t.conflictHidden, false);
      assert.equal(t.count, "1 finding selected · no agency action."); assert.equal(t.action, "ia-act-none");
      assert.match(t.conflict, /Choose this brief yourself/);
      assert.match(t.conflict, /Guided issue\s*Older-adult support at home \(its recipe uses Kūpuna Care\)/);
      assert.match(t.conflict, /Agency actions you can choose\s*.*Supplemental Nutrition Assistance Program \(SNAP\).*; or No agency action in the brief/);
      assert.match(t.conflict, /These suggestions leave your selections unchanged\./);
      if (label.startsWith("C")) assert.match(t.conflict, /not Kūpuna Care, the program of the Older-adult support at home recipe/);
      else {
        assert.match(t.conflict, /more than one program, and the program references and outreach hypotheses differ/);
        assert.match(t.conflict, /Program references in these results\s*(Supplemental Nutrition Assistance Program \(SNAP\)|Kūpuna Care)/);
      }
      assert.match(await p.locator("#ia-start").innerText(), /no agency action is suggested/);
      await p.locator("#ia-conflict-agency").click();
      assert.equal((await focus(p)).id, "ia-responses-h");
      assert.deepEqual(await p3Tray(p).then(x => [x.count, x.action]), [t.count, t.action], "following the pointers changes nothing");
      assert.equal(calls.length, 0, "no brief or run request");
      await proof(p, "phase3-4-" + label.split(" ")[0], { conflict: t.conflict.slice(0, 400) });
    } finally { await p.close(); }
  });
}

test("Phase 3 #4 mixed programs: manual no-action and hypothesis briefs use the existing controls and their own checklist", { timeout: 60000 }, async () => {
  const p = await page();
  try {
    await P3_MIXED["A reference switched"](p); await p3Apply(p);
    const calls = investigationCalls(p);
    await p.locator('#ia-evidence input[aria-label^="Select for brief: Poverty rate, age 65 and over, House 028 vs"]').check();
    assert.equal((await p3Tray(p)).count, "1 finding selected · no agency action.");
    assert.match(await p.locator('#ia-recommend-conflict dt:text-is("Suggested findings") + dd').textContent(), /Poverty rate, age 65 and over, House 028 vs State of Hawaiʻi/);
    assert.match(await p.locator("#ia-conflict-why").textContent(), /These suggestions leave your selections unchanged\./);
    const snap = p.locator("#ia-responses article", { hasText: "Supplemental Nutrition Assistance Program" }).locator('input[name="ia-action"]');
    await snap.check(); await p.waitForTimeout(50);
    assert.match(await p.locator("#ia-checklist").innerText(), /^Supplemental Nutrition Assistance Program \(SNAP\) — office checklist/);
    await p.locator("#ia-act-none").check(); await p.waitForTimeout(50);
    assert.match(await p.locator("#ia-checklist").innerText(), /No agency action selected/);
    await p.locator("#ia-brief-btn").click(); await requestDone(p);
    await p.waitForFunction(() => !document.querySelector("#ia-print-btn").disabled);
    const brief = calls.filter(c => c.mode === "brief");
    assert.equal(brief.length, 1); assert.equal(brief[0].selected_action_ref, null, "the existing null, sent explicitly");
    // No agency action section prints; a single selected comparison's lead says that none was selected.
    assert.equal(await p.locator("#ia-brief-out .brief-action").count(), 0);
    assert.deepEqual((await p.locator("#ia-brief-out h3").allTextContents()).filter(t => /agency action/i.test(t)), []);
    assert.doesNotMatch(await p.locator("#ia-brief-out").innerText(), /Next step:|Recorded next step/);
    assert.match(await p.locator("#ia-brief-out .brief-takeaway").innerText(), /^What this shows: Poverty rate, age 65 and over: House District 028 29\.0% and State of Hawaiʻi 9\.2%, a point difference of \+19\.8 percentage points between published estimates \(no significance implied\)\. \[1\]\[2\]\s+Agency action: None selected\. These published figures do not identify an agency action\. Staff decide any follow-up\.$/);
    // Hypothesis by hand: the Kūpuna hypothesis finding and its own agency action and checklist.
    await p.locator('#ia-evidence input[aria-label^="Select for brief: Outreach hypothesis"]').check();
    await p.locator("#ia-responses article", { hasText: "Kūpuna Care" }).locator('input[name="ia-action"]').check(); await p.waitForTimeout(50);
    assert.match(await p.locator("#ia-checklist").innerText(), /^Kūpuna Care — office checklist/);
    await p.locator("#ia-brief-btn").click(); await requestDone(p);
    const last = calls.filter(c => c.mode === "brief").pop();
    assert.equal(last.selected_action_ref.action_id, "kupuna_verify/1");
    assert.equal(await p3Tray(p).then(x => x.recommendHidden), true);
    await proof(p, "phase3-4-manual", { briefs: calls.filter(c => c.mode === "brief").length });
  } finally { await p.close(); }
});

test("Phase 3 #4 reference-only plans: the recipe program keeps its shortcut; two references are withheld", { timeout: 45000 }, async () => {
  const p = await page();
  try {
    await p3Advanced(p); await p.locator("#ia-rm-s4").click(); await p3Apply(p);
    let t = await p3Tray(p);
    assert.equal(t.recommendHidden, false); assert.equal(t.conflictHidden, true);
    await recommend(p);
    assert.equal((await p3Tray(p)).action, "ia-act-0", "the recipe's Kūpuna Care action");
    await p3Programs(p, "s3", ["kupuna_care_hi", "snap_hi"]); await p3Apply(p);
    t = await p3Tray(p);
    assert.equal(t.recommendHidden, true); assert.match(t.conflict, /Outreach hypotheses in these results\s*None/);
    await proof(p, "phase3-4-reference-only", {});
  } finally { await p.close(); }
});

test("Phase 3 #4 a complete Med-QUEST rescope keeps the SNAP recipe and saved tracking, names Med-QUEST and uses neutral tracking guidance", { timeout: 60000 }, async () => {
  const p = await page();
  try {
    await p.locator("#ia-issue").selectOption("food_assistance_outreach"); await p3Apply(p);
    await p.locator("#ia-tracking-summary").click();
    await p.locator("#ia-track-preset").click();
    assert.equal(await p.locator("#ia-track-label").inputValue(), "Office requests for SNAP information");
    await p3Programs(p, "s2", ["medquest_hi"]); await p3Lead(p, "s3", "medquest_hi"); await p3Apply(p);
    await p.locator("#ia-review button", { hasText: "Copy into this context" }).first().click();
    if (await p.locator("#ia-tracking").getAttribute("open") === null) await p.locator("#ia-tracking-summary").click();
    assert.equal(await p.locator("#ia-track-label").inputValue(), "Office requests for SNAP information", "saved tracking unchanged");
    assert.match(await p.locator("#ia-tracking > p.hint").textContent(), /^A staff record such as/);
    assert.equal(await p.locator("#ia-track-preset").count(), 0);
    assert.equal(await p.locator('label[for="ia-track-date"]').textContent(), "As of");
    assert.match(await p.locator("#ia-context-summary").textContent(), /SNAP outreach \(program steps use Med-QUEST/);
    assert.match(await p.locator("#ia-issue-help").textContent(), /use Med-QUEST.*not Supplemental Nutrition Assistance Program \(SNAP\).*staff can choose Custom/);
    const t = await p3Tray(p);
    assert.equal(t.recommendHidden, true); assert.match(t.conflict, /Guided issue\s*SNAP outreach \(its recipe uses Supplemental Nutrition Assistance Program \(SNAP\)\)/);
    assert.match(t.conflict, /staff can choose Custom/);
    assert.equal(await p.locator("#ia-issue").inputValue(), "food_assistance_outreach", "Custom stays a staff choice");
    const saved = await savedCase(p), b = saved.branches.find(x => x.branch_id === saved.active_branch_id);
    assert.equal(b.recipe_version, "food_assistance_outreach/1"); assert.equal(b.plan.issue_id, "food_assistance_outreach");
    assert.deepEqual(b.plan.steps.filter(s => s.operation !== "profile").map(s => s.args), [{ program_ids: ["medquest_hi"] }, { program_id: "medquest_hi" }]);
    await proof(p, "phase3-4-medquest", { conflict: t.conflict.slice(0, 300) });
  } finally { await p.close(); }
});

// Controlled language replies, with no request sent to a provider.
async function mockAskStatus(p, status) {
  const catalog = await (await p.request.get(new URL("/api/catalog", base).href)).json();
  const calls = [];
  let envelope;
  await p.unroute("**/api/language/*");
  await p.route("**/api/language/*", async route => {
    const request = route.request().postDataJSON();
    calls.push(new URL(route.request().url()).pathname.split("/").at(-1));
    if (route.request().url().endsWith("/start")) {
      const c = request.context;
      envelope = { schema_version: "ia-language/1", request_id: request.request_id, context: c, context_digest: "sha256:" + "b".repeat(64),
        tokens: { schema_version: "ia-language/1", release_id: catalog.investigation.release_id, ...Object.fromEntries(["case_id", "branch_id", "revision", "snapshot_id", "operation_version", "recipe_version"].map(k => [k, c[k]])) } };
      return route.fulfill({ status: 202, json: { ...envelope, status: "pending" } });
    }
    if (route.request().url().endsWith("/cancel")) return route.fulfill({ json: { ...envelope, status: "cancelled" } });
    const result = await status();
    return result ? route.fulfill({ json: { ...envelope, ...result } }) : route.abort("connectionreset");
  });
  return calls;
}

async function offerAskProposal(p, question, plan, typedDiff) {
  const calls = await mockAskStatus(p, () => ({ status: "propose", intent: "replace_plan", normalized_plan: plan, typed_diff: typedDiff }));
  await p.locator("#ia-question-text").fill(question);
  await p.locator("#ia-question-submit").click();
  await p.waitForFunction(() => document.querySelector("#ia-question-cancel").hidden && !document.querySelector("#ia-question-result .loading"));
  return calls;
}
async function p3Ask(p, question, plan, typedDiff) {
  await offerAskProposal(p, question, plan, typedDiff);
  if (await p.locator("#ia-proposal-run").isVisible()) await p.locator("#ia-proposal-run").click();
  if (await p.locator("#ia-preview").isVisible()) await p.locator("#ia-preview-confirm").click();
  await requestDone(p);
  await p.locator("#ia-answer-h").waitFor({ state: "visible" });
}

async function offerPopulationSwitch(p, question = "How many people live in Senate District 8? Put that next to the statewide count in a brief I can save.", comparison = "HI-STATE-2024") {
  const { investigation } = await (await p.request.get(new URL("/api/catalog", base).href)).json();
  const district = { ...investigation.default_plan.district, chamber: "senate", code: "008" };
  const step = { step_id: "s5", operation: "compare", args: { metric_ids: ["total_population"], comparison_geography: comparison } };
  const plan = { ...investigation.default_plan, district, issue_id: "custom", steps: [step] };
  return offerAskProposal(p, question, plan, [{ field: "steps", change: "added", step_id: step.step_id, before: null, after: step }]);
}

async function assertDistrictClarification(p, question) {
  assert.match(await p.locator("#ia-question-result").textContent(), /Which district should the investigation use\? Ask again naming one district with House or Senate/, question);
  assert.equal(await p.locator("#ia-proposal-run").count(), 0, question);
  assert.equal(await p.locator("#ia-proposal-draft").count(), 0, question);
  assert.equal(await p.locator("#ia-preview").isVisible(), false, question);
  assert.equal(await p.locator("#ia-question-text").inputValue(), question);
}

test("Ask clarifies compound district numbers before offering a switch", { timeout: 30000 }, async () => {
  const p = await page(base, { mockAsk: true });
  try {
    const before = await savedCase(p), calls = investigationCalls(p);
    for (const question of [
      "How many people live in Senate 8 or 9?",
      "How many people live in 9 or Senate 8?",
      "What is the population in Senate 8 or in 9?",
      "What is the population in 9 or in Senate 8?",
      "How many people live in Senate 8 plus 9?",
      "Compare the population in Senate 8 vs. 9",
      "Senate 8 & 28",
      "Senate 8 and 9",
      "Senate 8–9",
      "Senate 8/9",
      "Senate 8, 9",
      "SD 8, or 9",
    ]) {
      // The reply includes only Senate 8. Staff need to clarify the question before any switch can be offered.
      const language = await offerPopulationSwitch(p, question);
      await assertDistrictClarification(p, question);
      assert.deepEqual(language, ["start", "status"], question);
    }
    assert.deepEqual(calls, []);
    assert.deepEqual(await savedCase(p), before);
  } finally { await p.close(); }
});

test("Ask clarifies a missing comparison peer or alternate district in a profile proposal", { timeout: 30000 }, async () => {
  const p = await page(base, { mockAsk: true });
  try {
    const before = await savedCase(p), calls = investigationCalls(p);
    const profile = { step_id: "s5", operation: "profile", args: { metric_ids: ["median_household_income"] } };
    const defaultPlan = activeBranch(before).plan;
    const plan = { ...defaultPlan, district: { ...defaultPlan.district, chamber: "senate", code: "011" }, issue_id: "custom", steps: [profile] };
    for (const question of ["Compare median household income in Senate 11 with 12.", "Change to Senate 11 or to 12."]) {
      const language = await offerAskProposal(p, question, plan, [{ field: "steps", change: "added", step_id: profile.step_id, before: null, after: profile }]);
      await assertDistrictClarification(p, question);
      assert.deepEqual(language, ["start", "status"], question);
    }
    assert.deepEqual(calls, []);
    assert.deepEqual(await savedCase(p), before);
  } finally { await p.close(); }
});

test("Ask keeps the separate context review for qualifiers and explicit district comparisons", { timeout: 30000 }, async () => {
  const p = await page(base, { mockAsk: true });
  try {
    const calls = investigationCalls(p), run = p.locator("#ia-proposal-run"), preview = p.locator("#ia-preview");
    for (const [question, comparison] of [
      ["The district next to Senate 8"],
      ["Population near Senate 8"],
      ["The district containing Senate 8"],
      ["What is the population of the district bordering Senate 8?"],
      ["Show population, but not for Senate 8"],
      ["Show Senate 8 population. What about 12?"],
      ["Compare Senate 8 with Senate 9", "HI-SENATE-009-2024"],
    ]) {
      const language = await offerPopulationSwitch(p, question, comparison);
      assert.equal(await run.textContent(), "Run this proposal", question);
      assert.equal(await preview.isVisible(), false, question);
      assert.deepEqual(calls, [], question);
      await run.click();
      assert.equal(await preview.isVisible(), true, question);
      assert.deepEqual(calls, [], question);
      await p.locator("#ia-preview-cancel").click();
      assert.equal(await p.locator("#ia-district").inputValue(), "house:028", question);
      assert.deepEqual(language, ["start", "status"], question);
    }
  } finally { await p.close(); }
});

test("Ask recognizes the Senate district abbreviation for a clean switch", { timeout: 30000 }, async () => {
  const p = await page(base, { mockAsk: true });
  try {
    const calls = investigationCalls(p);
    const language = await offerPopulationSwitch(p, "SD 8");
    const run = p.locator("#ia-proposal-run");
    assert.equal(await run.textContent(), "Switch to Senate 008 and run");
    assert.deepEqual(calls, []);
    await run.click();
    await p.locator("#ia-answer-h").waitFor();
    assert.equal(await p.locator("#ia-preview").isVisible(), false);
    assert.deepEqual(calls.map(c => c.mode), ["run"]);
    assert.deepEqual(language, ["start", "status"]);
  } finally { await p.close(); }
});

test("Ask confirms a clean district switch once at 320×568 and keeps the earlier context", { timeout: 30000 }, async () => {
  const p = await page(base, { viewport: { width: 320, height: 568 }, mockAsk: true });
  try {
    const before = await savedCase(p), calls = investigationCalls(p);
    const dismissed = await offerPopulationSwitch(p);
    const review = p.locator("#ia-question-result"), run = p.locator("#ia-proposal-run"), keep = p.locator("#ia-proposal-discard");
    assert.equal(await keep.textContent(), "Keep House 028");
    await keep.focus();
    await p.keyboard.press("Enter");
    assert.equal((await focus(p)).id, "ia-question-text");
    assert.deepEqual(await savedCase(p), before);
    assert.deepEqual(dismissed, ["start", "status"]);

    const accepted = await offerPopulationSwitch(p);
    assert.deepEqual(calls, []);
    assert.equal(await p.locator("#ia-district").inputValue(), "house:028");
    const reviewText = await review.innerText();
    assert.match(reviewText, /House 028 to Senate 008/);
    assert.match(reviewText, /new context.*Save or reopen the case/);
    assert.equal(await run.textContent(), "Switch to Senate 008 and run");
    assert.equal((await focus(p)).id, "ia-question-result");
    await p.keyboard.press("Tab");
    assert.equal((await focus(p)).id, "ia-proposal-run");
    await p.keyboard.press("Enter");
    await p.locator("#ia-answer-h").waitFor();
    assert.equal((await focus(p)).id, "ia-answer-h");
    assert.equal(await p.locator("#ia-preview").isVisible(), false);
    assert.deepEqual(calls.map(c => c.mode), ["run"]);
    assert.match(await p.locator("#ia-answer").innerText(), /District\s+Senate 008\s+73,731 persons[\s\S]*Compared with\s+State of Hawaiʻi\s+1,445,235 persons/i);
    await recommend(p);
    assert.deepEqual(calls.map(c => c.mode), ["run", "brief"]);
    const after = await savedCase(p);
    assert.equal(after.branches.length, 2);
    assert.deepEqual(after.branches.find(b => b.branch_id === before.active_branch_id), before.branches[0]);
    const current = after.branches.find(b => b.branch_id === after.active_branch_id);
    assert.equal(current.plan.district.chamber, "senate");
    assert.equal(current.plan.district.code, "008");
    assert.deepEqual(current.selected_claim_refs, calls[1].selected_claim_refs);
    assert.equal(current.selected_claim_refs.length, 1);
    assert.deepEqual(accepted, ["start", "status"]);
  } finally { await p.close(); }
});

test("Ask checks the district confirmation again when there is new focused staff work", { timeout: 30000 }, async () => {
  const p = await page(base, { mockAsk: true });
  try {
    const calls = investigationCalls(p), language = await offerPopulationSwitch(p);
    const run = p.locator("#ia-proposal-run"), note = p.locator("#ia-title");
    assert.equal(await run.textContent(), "Switch to Senate 008 and run");
    await note.fill("Staff title started after the question");
    await run.evaluate(el => el.click()); // the title still has focus and has not committed on blur
    assert.equal((await focus(p)).id, "ia-title");
    assert.equal(await run.textContent(), "Run this proposal");
    assert.match(await p.locator("#ia-question-result").textContent(), /This context has staff notes or checklist entries/);
    assert.deepEqual(calls, []);
    await run.click();
    await p.locator("#ia-preview-cancel").click();
    assert.equal(await note.inputValue(), "Staff title started after the question");
    assert.equal(await p.locator("#ia-district").inputValue(), "house:028");
    assert.deepEqual(calls, []);
    assert.deepEqual(language, ["start", "status"]);
  } finally { await p.close(); }
});

async function startIncompleteTrackingDate(p) {
  if (await p.locator("#ia-tracking").getAttribute("open") === null) await p.locator("#ia-tracking-summary").click();
  const date = p.locator("#ia-track-date");
  await date.focus();
  await p.keyboard.type("1116");
  assert.equal(await date.evaluate(el => el.value === "" && el.validity.badInput), true);
  await date.evaluate(el => { window.focusRaceDate = el; });
  return date;
}

async function assertIncompleteTrackingDateKept(date) {
  assert.equal(await date.evaluate(el => el === window.focusRaceDate && el === document.activeElement && el.validity.badInput), true);
}

test("Ask holds an incomplete staff date on pointer confirmation or cancellation of the clean switch", { timeout: 30000 }, async () => {
  const p = await page(base, { mockAsk: true });
  try {
    const before = await savedCase(p), calls = investigationCalls(p), run = p.locator("#ia-proposal-run");
    const cancelled = await offerPopulationSwitch(p);
    assert.equal(await run.textContent(), "Switch to Senate 008 and run");
    const date = await startIncompleteTrackingDate(p);
    await run.click();
    assert.deepEqual(calls, []);
    assert.equal(await p.locator("#ia-preview").isVisible(), false);
    assert.match(await p.locator("#ia-status").textContent(), /Finish or clear the staff date/);
    await assertIncompleteTrackingDateKept(date);
    await p.locator("#ia-proposal-discard").click();
    assert.equal(await run.count(), 0);
    await assertIncompleteTrackingDateKept(date);
    await p.keyboard.type("2026");
    assert.equal(await date.inputValue(), "2026-11-16", "the year continues the existing native month and day");
    await date.fill("");
    assert.deepEqual(await savedCase(p), before);
    const accepted = await offerPopulationSwitch(p);
    await startIncompleteTrackingDate(p);
    await run.focus(); // the invalid field must also be protected when it was already left
    await run.click();
    await assertIncompleteTrackingDateKept(date);
    await date.fill("");
    await run.click();
    await p.locator("#ia-answer-h").waitFor();
    assert.equal(await p.locator("#ia-preview").isVisible(), false);
    assert.deepEqual(calls.map(c => c.mode), ["run"]);
    assert.deepEqual(cancelled, ["start", "status"]);
    assert.deepEqual(accepted, ["start", "status"]);
  } finally { await p.close(); }
});

test("Ask holds an incomplete staff date in the ordinary proposal and its separate context review", { timeout: 30000 }, async () => {
  const p = await page(base, { mockAsk: true });
  try {
    await p.locator("#ia-title").fill("Office title in House 028");
    const calls = investigationCalls(p), language = await offerPopulationSwitch(p);
    const run = p.locator("#ia-proposal-run");
    assert.equal(await run.textContent(), "Run this proposal");
    const date = await startIncompleteTrackingDate(p);
    await run.click();
    assert.equal(await p.locator("#ia-preview").isVisible(), false);
    await assertIncompleteTrackingDateKept(date);
    await date.fill("");
    await run.click();
    await startIncompleteTrackingDate(p);
    await p.locator("#ia-preview-confirm").click();
    assert.deepEqual(calls, []);
    assert.equal(await p.locator("#ia-preview").isVisible(), true);
    await assertIncompleteTrackingDateKept(date);
    await p.locator("#ia-preview-cancel").click();
    assert.equal(await p.locator("#ia-preview").isVisible(), false);
    await assertIncompleteTrackingDateKept(date);
    assert.equal(await p.locator("#ia-district").inputValue(), "house:028");
    assert.equal(await p.locator("#ia-title").inputValue(), "Office title in House 028");
    assert.deepEqual(calls, []);
    assert.deepEqual(language, ["start", "status"]);
  } finally { await p.close(); }
});

test("Phase 3 #4 Ask: an answer about one program keeps its own action; a measure answer in mixed results is not a shortcut", { timeout: 90000 }, async () => {
  const p = await page();
  try {
    if (await p.locator("#ia-question-form").isHidden()) return;   // language questions are off in this app
    await P3_MIXED["A reference switched"](p); await p3Apply(p);
    const applied = (await savedCase(p)).branches.pop().plan, calls = investigationCalls(p);
    const withMq = JSON.parse(JSON.stringify(applied)); withMq.steps.push({ step_id: "s5", operation: "program_evidence", args: { program_ids: ["medquest_hi"] } });
    await p3Ask(p, "What does Med-QUEST offer in House 28?", withMq, [{ field: "steps", change: "added", step_id: "s5", after: withMq.steps[4] }]);
    assert.equal(await p.locator("#ia-answer-brief").isVisible(), true, "the Ask-scoped program answer keeps its brief");
    assert.match(await p.locator("#ia-answer-brief-what").textContent(), /agency verification step for Med-QUEST/);
    assert.equal(await p.locator("#ia-recommend-conflict").isHidden(), true);
    await p.locator("#ia-answer-brief").click(); await requestDone(p);
    assert.equal(calls.filter(c => c.mode === "brief").pop().selected_action_ref.action_id, "medquest_verify/1");
    const county = JSON.parse(JSON.stringify(withMq)); county.steps[1].args.comparison_geography = "HI-COUNTY-003-2024";
    await p3Ask(p, "Compare senior poverty in House 28 with Honolulu County.", county, [{ field: "steps", change: "changed", step_id: "s2", before: withMq.steps[1], after: county.steps[1] }]);
    const before = await p3Tray(p);
    assert.equal(await p.locator("#ia-answer-brief").count(), 0, "no one-step answer brief that would guess the agency action");
    assert.match(await p.locator("#ia-answer-brief-what").textContent(), /not offered.*No agency action in the brief.*Create brief from my selection/);
    await p.locator("#ia-answer-brief-choices").click();
    assert.equal((await focus(p)).id, "ia-conflict-h");
    assert.deepEqual(await p3Tray(p), before, "nothing selected or changed");
    await proof(p, "phase3-4-ask", {});
  } finally { await p.close(); }
});

test("Phase 3 #20 a retained supporting selection with no tile is explained, removable and still briefable", { timeout: 45000 }, async () => {
  const p = await page();
  try {
    await p.locator('#ia-evidence input[aria-label^="Select for brief: Poverty rate, age 65 and over, House 028"]:not([aria-label*=" vs "])').check();
    await p3Scope(p, "s1"); await p.locator('input[id^="ia-s1-metrics-"][value="poverty_rate_65_plus"]').uncheck();
    await p3Apply(p);
    assert.equal((await p3Tray(p)).count, "1 finding selected · no agency action.", "the server retained the exact finding");
    const why = p.locator(".ia-supporting-why");
    assert.match(await why.textContent(), /^Supporting finding: it has no tile of its own in these results; it is part of the basis of Poverty rate, age 65 and over, House 028 vs State of Hawaiʻi; Outreach hypothesis, Kūpuna Care\./);
    assert.match(await p.locator("#ia-supporting").innerText(), /1 selected finding has no tile of its own below/);
    const go = p.locator('#ia-supporting button');
    await go.focus(); await p.keyboard.press("Enter");
    const f = await focus(p);
    assert.match(f.id, /^ia-sel-[0-9a-f]{12}-rm$/);
    assert.equal(await p.locator("#" + f.id).getAttribute("aria-describedby"), f.id.replace(/-rm$/, "-why"));
    await p.locator("#ia-brief-btn").click(); await requestDone(p);
    await p.waitForFunction(() => !document.querySelector("#ia-print-btn").disabled);
    await p.locator("#" + f.id).focus();
    await p.keyboard.press("Enter");
    assert.equal((await focus(p)).id, "ia-tray-h");
    await p.keyboard.press("Tab");
    assert.equal((await focus(p)).id, "ia-recommend-btn");
    assert.equal((await p3Tray(p)).count, "No findings selected yet.");
    assert.equal(await p.locator("#ia-supporting").count(), 0);
    await proof(p, "phase3-20-supporting", {});
  } finally { await p.close(); }
});

async function p3MapChange(p, year, extra) {
  await p.locator("#ia-map-session").selectOption(String(year));
  if (extra) await extra(p);
  await p.locator("#ia-context-apply-btn").click();
  const preview = await p.locator("#ia-preview").isVisible() ? await p.locator("#ia-preview").innerText() : null;
  if (preview) await p.locator("#ia-preview-confirm").click();
  await requestDone(p);
  return preview;
}
const p3Stat = '#ia-evidence input[aria-label^="Select for brief: Poverty rate, age 65 and over, House 028"]:not([aria-label*=" vs "])';
const p3Population = '#ia-evidence input[aria-label^="Select for brief: Population age 65 and over, House 028"]';
const p3Comparison = '#ia-evidence input[aria-label^="Select for brief: Poverty rate, age 65 and over, House 028 vs"]';

function p3Response(p, mode, year) {
  return p.waitForResponse((r) => {
    if (new URL(r.url()).pathname !== "/api/investigation" || r.request().method() !== "POST") return false;
    const wire = r.request().postDataJSON();
    return wire.mode === mode && wire.plan.map_session === year;
  });
}
async function p3Brief(p, year) {
  const reply = p3Response(p, "brief", year);
  await p.locator("#ia-brief-btn").click();
  await requestDone(p);
  await p.waitForFunction(() => !document.querySelector("#ia-print-btn").disabled);
  const response = await reply;
  assert.equal(response.status(), 200);
  return (await response.json()).brief;
}
async function p3Unavailable(p) {
  assert.equal(await p.locator("#ia-reselect-btn").count(), 0);
  assert.match(await p.locator("#ia-reselect-why").textContent(), /recorded identity includes the map display year, and that identity changed/);
  await p.locator("#ia-reselect-evidence").click();
  assert.equal((await focus(p)).id, "ia-evidence-h");
  assert.equal((await p3Tray(p)).count, "No findings selected yet.");
}

test("Phase 3 #6 House 028 2026→2024: explained up front, keyboard Select again uses current refs, the brief keeps the same estimate", { timeout: 60000 }, async () => {
  const p = await page();
  try {
    await recommend(p);
    await p.locator(p3Comparison).uncheck();
    await p.locator(p3Stat).check();
    const firstBrief = await p3Brief(p, 2026);
    const before = await savedCase(p), origin = before.branches[0];
    assert.ok(origin.selected_action_ref);
    const geometry = [];
    p.on("request", (request) => {
      const u = new URL(request.url());
      if (u.pathname === "/api/geometry") geometry.push(u.searchParams.get("session"));
    });
    const run = p3Response(p, "run", 2024);
    const preview = await p3MapChange(p, 2024);
    const { map_reselection: issued } = await (await run).json();
    assert.equal(issued.from_map_session, 2026);
    assert.equal(issued.to_map_session, 2024);
    const pair = issued.refs.find((x) => x.previous_ref.finding_id === origin.selected_claim_refs[0].finding_id);
    assert.deepEqual(pair.previous_ref, origin.selected_claim_refs[0]);
    assert.match(preview, /map display year is part of each district finding's recorded identity, so 1 selected finding is not kept automatically/);
    assert.match(preview, /matches a selected profile statistic to the current results, you can choose Select again in the Brief panel\. The agency action is not carried/);
    await p.locator("#ia-reselect-btn").waitFor({ state: "visible" });
    assert.deepEqual(geometry, ["2024"], "only the displayed boundary map was fetched");
    assert.match(await p.locator("#ia-retired").innerText(), /selected with the 2026 map display\. Its recorded identity changed with the map year/);
    assert.match(await p.locator("#ia-reselect-why").textContent(), /server reports that the 2024 and 2026 boundaries of House 028 are the same/);
    assert.equal((await p3Tray(p)).count, "No findings selected yet.");
    const calls = investigationCalls(p);
    await p.locator("#ia-reselect-btn").focus();
    await p.keyboard.press("Enter");
    assert.equal((await focus(p)).id, "ia-tray-h");
    assert.equal(calls.length, 0, "Select again is an ordinary local selection");
    const t = await p3Tray(p);
    assert.equal(t.count, "1 finding selected · no agency action.");
    assert.equal(t.action, "ia-act-none");
    assert.equal(await p.locator("#ia-reselect-btn").count(), 0);
    // The tray and status agree: the reselected statistic is no longer listed as not reselected; the action note stays.
    assert.match(await p.locator("#ia-status").textContent(), /^1 finding was selected again from the current results\./);
    const retiredAfter = await p.locator("#ia-retired").innerText();
    assert.doesNotMatch(retiredAfter, /Poverty rate, age 65 and over, House 028:/);
    assert.doesNotMatch(retiredAfter, /saved wording no longer matches/);
    assert.match(retiredAfter, /^1 saved selection is not selected in this context:[\s\S]*The agency action chosen earlier: it was chosen with the 2026 map display and is not carried/);
    const secondBrief = await p3Brief(p, 2024);
    assert.equal(firstBrief.entries[0].kind, "statistic");
    assert.equal(secondBrief.entries[0].text, firstBrief.entries[0].text);
    assert.equal(secondBrief.entries[0].finding_id, pair.current_ref.finding_id);
    const after = await savedCase(p), [b0, b1] = after.branches;
    assert.deepEqual(b0.selected_claim_refs, origin.selected_claim_refs);
    assert.deepEqual(b0.selected_action_ref, origin.selected_action_ref);
    assert.equal(b1.plan.map_session, 2024);
    assert.deepEqual(b1.selected_claim_refs, [pair.current_ref]);
    assert.notEqual(pair.current_ref.semantic_hash, pair.previous_ref.semantic_hash);
    assert.equal(b1.selected_action_ref, null);
    assert.deepEqual(calls[0].selected_claim_refs, [pair.current_ref]);
    await p.route("**/api/investigation", async (route) => {
      const wire = route.request().postDataJSON();
      if (wire.mode !== "brief") return route.fallback();
      return route.continue({ postData: JSON.stringify({ ...wire, selected_claim_refs: [pair.previous_ref] }) });
    }, { times: 1 });
    const refused = p3Response(p, "brief", 2024);
    await p.locator("#ia-brief-btn").click();
    const response = await refused;
    assert.equal(response.status(), 409);
    assert.equal((await response.json()).code, "selection_conflict");
    await requestDone(p);
    await proof(p, "phase3-6-2026-to-2024", { geometry });
  } finally { await p.close(); }
});

test("Phase 3 #6 House 028 2024→2026 reselects two primary statistics and creates the brief", { timeout: 60000 }, async () => {
  const p = await page();
  try {
    await p3MapChange(p, 2024);
    await p.locator(p3Stat).check();
    await p.locator(p3Population).check();
    const firstBrief = await p3Brief(p, 2024);
    const run = p3Response(p, "run", 2026);
    const preview = await p3MapChange(p, 2026);
    const { map_reselection: issued } = await (await run).json();
    assert.equal(issued.from_map_session, 2024);
    assert.equal(issued.to_map_session, 2026);
    assert.match(preview, /so 2 selected findings are not kept automatically/);
    assert.equal((await p3Tray(p)).count, "No findings selected yet.");
    await p.locator("#ia-reselect-btn").focus();
    await p.keyboard.press("Enter");
    assert.equal((await focus(p)).id, "ia-tray-h");
    assert.equal((await p3Tray(p)).count, "2 findings selected · no agency action.");
    assert.match(await p.locator("#ia-status").textContent(), /^2 findings were selected again from the current results\./);
    assert.equal(await p.locator("#ia-retired").innerText(), "", "nothing reselected is listed as not reselected");
    assert.equal(await p.locator("#ia-reselect-btn").count(), 0, "one explicit use");
    const secondBrief = await p3Brief(p, 2026);
    const saved = await savedCase(p);
    assert.deepEqual(saved.branches.map((b) => b.plan.map_session), [2026, 2024, 2026]);
    assert.deepEqual(secondBrief.entries.map((e) => e.text), firstBrief.entries.map((e) => e.text));
    const expected = saved.branches[1].selected_claim_refs.map((ref) => {
      const pair = issued.refs.find((x) => x.previous_ref.finding_id === ref.finding_id);
      assert.deepEqual(pair.previous_ref, ref);
      assert.notEqual(pair.current_ref.semantic_hash, ref.semantic_hash);
      return pair.current_ref;
    });
    assert.deepEqual(saved.branches[2].selected_claim_refs, expected);
    await proof(p, "phase3-6-2024-to-2026", {});
  } finally { await p.close(); }
});

test("Phase 3 #6 after Select again of a statistic, the unpaired old comparison keeps its map-year explanation", { timeout: 60000 }, async () => {
  const p = await page();
  try {
    await recommend(p);   // comparison and agency action
    await p.locator(p3Stat).check();
    const before = await savedCase(p), origin = before.branches[0];
    assert.equal(origin.selected_claim_refs.length, 2);
    await p3MapChange(p, 2024);
    await p.locator("#ia-reselect-btn").waitFor({ state: "visible" });
    await p.locator("#ia-reselect-btn").focus();
    await p.keyboard.press("Enter");
    assert.equal((await focus(p)).id, "ia-tray-h");
    assert.equal(await p.locator("#ia-reselect-btn").count(), 0, "one explicit use");
    assert.equal((await p3Tray(p)).count, "1 finding selected · no agency action.");
    assert.match(await p.locator("#ia-status").textContent(), /^1 finding was selected again from the current results\./);
    const retired = await p.locator("#ia-retired").innerText();
    assert.match(retired, /^2 saved selections are not selected in this context:/);
    assert.match(retired, /Poverty rate, age 65 and over, House 028 vs State of Hawaiʻi: selected with the 2026 map display\. Its recorded identity changed with the map year\. It is not selected in this context\. Choose from the current findings under Findings and evidence\./);
    assert.match(retired, /The agency action chosen earlier: it was chosen with the 2026 map display and is not carried/);
    assert.doesNotMatch(retired, /Poverty rate, age 65 and over, House 028:/, "the reselected statistic is not listed");
    assert.doesNotMatch(retired, /saved wording no longer matches/);
    const after = await savedCase(p);
    assert.deepEqual(after.branches[0], origin, "the original context is unchanged");
    await proof(p, "phase3-6-mixed-consumed", {});
  } finally { await p.close(); }
});

for (const useOffer of [true, false]) {
  test("Phase 3 #6 paired retired notices track " + (useOffer ? "manual selection and one use of Select again" : "all-manual selections"), { timeout: 45000 }, async () => {
    const p = await page();
    try {
      const profile = p.locator('#ia-evidence input[aria-label^="Select for brief:"]');
      const first = profile.nth(0), second = profile.nth(1);
      const firstNotice = /Male householders age 65\+ living alone, House 028: selected with the 2026 map display/;
      const secondNotice = /Female householders age 65\+ living alone, House 028: selected with the 2026 map display/;
      const comparisonNotice = /House 028 vs State of Hawaiʻi: selected with the 2026 map display/;
      const retired = p.locator("#ia-retired"), offer = p.locator("#ia-reselect-btn");
      await first.check();
      await second.check();
      await p.locator(p3Comparison).check();
      const origin = (await savedCase(p)).branches[0];
      const reply = p3Response(p, "run", 2024);
      await p3MapChange(p, 2024);
      const { map_reselection: proof } = await (await reply).json();
      const currentRefs = origin.selected_claim_refs.slice(0, 2).map((ref) => proof.refs.find((x) => x.previous_ref.semantic_hash === ref.semantic_hash).current_ref);
      assert.match(await retired.innerText(), firstNotice);
      assert.match(await retired.innerText(), secondNotice);
      await first.check();
      assert.doesNotMatch(await retired.innerText(), firstNotice, "the manually selected exact stat is recovered");
      assert.match(await retired.innerText(), secondNotice);
      assert.equal(await offer.count(), 1);
      await p.locator("#ia-service").selectOption("oahu");
      assert.equal(await offer.count(), 0);
      assert.doesNotMatch(await retired.innerText(), firstNotice, "unapplied edits do not change the committed refs");
      await p.locator("#ia-service").selectOption("");
      assert.equal(await offer.count(), 1);
      if (useOffer) {
        await offer.focus();
        await p.keyboard.press("Enter");
        assert.equal((await focus(p)).id, "ia-tray-h");
      } else {
        await second.check();
      }
      assert.equal(await offer.count(), 0);
      assert.doesNotMatch(await retired.innerText(), firstNotice);
      assert.doesNotMatch(await retired.innerText(), secondNotice);
      assert.match(await retired.innerText(), comparisonNotice);
      assert.match(await retired.innerText(), /Findings and evidence/);
      const after = await savedCase(p);
      assert.deepEqual(after.branches[0], origin);
      assert.deepEqual(after.branches[1].selected_claim_refs, currentRefs);
      const brief = await p3Brief(p, 2024);
      assert.deepEqual(brief.entries.map((entry) => entry.finding_id), currentRefs.map((ref) => ref.finding_id));
      await first.uncheck();
      assert.match(await retired.innerText(), firstNotice);
      assert.match(await retired.innerText(), /It is not selected in this context\./);
      assert.doesNotMatch(await retired.innerText(), /was not reselected/);
      assert.equal(await offer.count(), useOffer ? 0 : 1, "the shortcut remains single-use");
      await first.check();
      assert.doesNotMatch(await retired.innerText(), firstNotice);
      assert.equal(await offer.count(), 0);
    } finally { await p.close(); }
  });
}

for (const [label, change] of Object.entries({
  "the server omits its proof": (body) => { delete body.map_reselection; },
  "the previous hash differs": (body) => { for (const pair of body.map_reselection.refs) pair.previous_ref.semantic_hash = "sha256:" + "1".repeat(64); },
  "the current hash differs": (body) => { for (const pair of body.map_reselection.refs) pair.current_ref.semantic_hash = "sha256:" + "2".repeat(64); },
  "the proof reports another snapshot": (body) => { for (const pair of body.map_reselection.refs) pair.current_ref.snapshot_id = "sha256:" + "3".repeat(64); },
  "the map direction differs": (body) => { body.map_reselection.from_map_session = 2024; },
  "the matching profile step failed": (body) => { body.status = "partial"; body.steps.find((s) => s.operation === "profile").status = "error"; },
})) {
  test("Phase 3 #6 no Select again when " + label, { timeout: 45000 }, async () => {
    const p = await page();
    try {
      await p.locator(p3Stat).check();
      await p.route("**/api/investigation", async (route) => {
        const wire = route.request().postDataJSON();
        if (wire.mode !== "run" || wire.plan.map_session !== 2024) return route.fallback();
        const response = await route.fetch();
        const json = await response.json();
        assert.ok(json.map_reselection.refs.length);
        change(json);
        return route.fulfill({ response, json });
      });
      await p3MapChange(p, 2024);
      await p3Unavailable(p);
    } finally { await p.close(); }
  });
}

test("Phase 3 #6 House 028 comparison stays a manual selection after a map fork", { timeout: 45000 }, async () => {
  const p = await page();
  try {
    await p.locator(p3Comparison).check();
    const reply = p3Response(p, "run", 2024);
    await p3MapChange(p, 2024);
    const result = await (await reply).json();
    assert.ok(result.map_reselection.refs.length);
    assert.ok(result.map_reselection.refs.every((pair) => pair.current_ref.finding_id.startsWith("stat:")));
    await p3Unavailable(p);
    await p.locator(p3Comparison).check();
    const brief = await p3Brief(p, 2024);
    assert.equal(brief.entries[0].kind, "comparison");
    assert.equal(brief.action, null);
  } finally { await p.close(); }
});

const differingGeometryUrl = process.env.FOCUS_TEST_DIFFERENT_GEOMETRY_URL;
test("Phase 3 #6 the server gives no proof for differing House 028 geometry", { timeout: 45000, skip: !differingGeometryUrl }, async () => {
  const p = await page(new URL(differingGeometryUrl));
  try {
    await p.locator(p3Stat).check();
    const reply = p3Response(p, "run", 2024);
    await p3MapChange(p, 2024);
    assert.equal((await (await reply).json()).map_reselection, undefined);
    await p3Unavailable(p);
    await proof(p, "phase3-6-different-boundary", {});
  } finally { await p.close(); }
});

test("Phase 3 #6 a map change with another field, a cancelled fork run and an old case replay never offer Select again", { timeout: 90000 }, async () => {
  const p = await page();
  try {
    await p.locator(p3Stat).check();
    // Map display and program area together: not a map-only fork.
    const preview = await p3MapChange(p, 2024, async q => { await q.locator("#ia-service").selectOption("oahu"); });
    assert.doesNotMatch(preview, /map display year is part/);
    assert.match(preview, /kept only if exactly the same finding appears/);
    await p.waitForTimeout(300);
    assert.equal(await p.locator("#ia-reselect").count(), 0); assert.equal(await p.locator("#ia-reselect-why").count(), 0);
    assert.match(await p.locator("#ia-retired").innerText(), /saved wording no longer matches the replayed evidence/);
  } finally { await p.close(); }
  const q = await page();
  try {
    await q.locator(p3Stat).check();
    const before = await savedCase(q);
    // The fork's run is cancelled; a later run of the same context is not the live fork.
    const gate = await gateInvestigation(q, "run");
    await q.locator("#ia-map-session").selectOption("2024");
    await q.locator("#ia-context-apply-btn").click(); await q.locator("#ia-preview-confirm").click();
    await gate.received; await q.locator("#ia-cancel").click(); gate.open();
    await p3Advanced(q); await q.locator("#ia-apply").click(); await requestDone(q);
    await q.waitForTimeout(300);
    assert.equal(await q.locator("#ia-reselect").count(), 0);
    // An old case file whose 2024 context presents the 2026 references: exact replay retires them; nothing is offered.
    const old = JSON.parse(JSON.stringify(before));
    const ctx = JSON.parse(JSON.stringify(old.branches[0])); ctx.branch_id = "0f0e0d0c-0b0a-4908-8706-050403020100"; ctx.plan.map_session = 2024; ctx.selected_action_ref = null;
    old.branches.push(ctx); old.active_branch_id = ctx.branch_id;
    await chooseCase(q, old); await replayCase(q);
    assert.match(await q.locator("#ia-retired").innerText(), /saved wording no longer matches the replayed evidence/);
    assert.equal(await q.locator("#ia-reselect").count(), 0);
    assert.equal((await p3Tray(q)).count, "No findings selected yet.");
    // Restoring the original context replays its own exact identities.
    await q.locator("#ia-restore-0").click(); await requestDone(q);
    assert.equal((await p3Tray(q)).count, "1 finding selected · no agency action.");
    assert.equal(await q.locator("#ia-reselect").count(), 0);
    await proof(q, "phase3-6-not-offered", {});
  } finally { await q.close(); }
});

test("Phase 3 #6 an unapplied draft edit hides Select again", { timeout: 45000 }, async () => {
  const p = await page();
  try {
    await p.locator(p3Stat).check();
    await p3MapChange(p, 2024);
    assert.equal(await p.locator("#ia-reselect-btn").count(), 1);
    await p.locator("#ia-service").selectOption("oahu");
    assert.equal(await p.locator("#ia-reselect-btn").count(), 0);
    assert.equal((await p3Tray(p)).count, "No findings selected yet.");
  } finally { await p.close(); }
});

test("Phase 3 #11 each comparison operand states its own margin: controlled, mixed and numeric pairs", { timeout: 60000 }, async () => {
  const p = await page();
  try {
    const details = async (cmpLabel) => {
      const node = p.locator("#ia-evidence .ia-claim", { has: p.locator(`input[aria-label^="Select for brief: ${cmpLabel}"]`) });
      await node.locator("details").first().evaluate(d => { d.open = true; });
      return node.innerText();
    };
    // Numeric pair (House 028 default): unchanged wording.
    let text = await details("Poverty rate, age 65 and over, House 028 vs");
    assert.match(text, /House District 028 \(2024 district boundaries\): 29\.0% \(margin of error ±4\.3\)/);
    assert.match(text, /State of Hawaiʻi: 9\.2% \(margin of error ±0\.5\)/);
    // Controlled pair: Senate 008 total population with the State.
    await p.locator("#ia-district").selectOption("senate:008"); await p.locator("#ia-issue").selectOption("custom");
    await p3Scope(p, "s2");
    await p.locator('input[id^="ia-s2-metrics-"][value="total_population"]').check();
    await p.locator('input[id^="ia-s2-metrics-"][value="poverty_rate_65_plus"]').uncheck();
    await p3Apply(p);
    text = await details("Total population, Senate 008 vs");
    assert.match(text, /Senate District 008 \(2024 district boundaries\): 73,731 \(Controlled estimate; no numeric margin of error published\)/);
    assert.match(text, /State of Hawaiʻi: 1,445,235 \(Controlled estimate; no numeric margin of error published\)/);
    assert.doesNotMatch(text.split(/Depends on/)[0].replace(/^[\s\S]*?Definition, margin of error and method/, ""), /\*{5}/, "no raw marker in the app's own rows");
    // Mixed pair: House 001 age 65 and over with Honolulu County.
    await p.locator("#ia-district").selectOption("house:001");
    await p3Scope(p, "s2");
    await p.locator('input[id^="ia-s2-metrics-"][value="population_65_plus"]').check();
    await p.locator('input[id^="ia-s2-metrics-"][value="total_population"]').uncheck();
    await p.locator("#ia-s2-geo").selectOption("HI-COUNTY-003-2024");
    await p3Apply(p);
    text = await details("Population age 65 and over, House 001 vs");
    assert.match(text, /House District 001 \(2024 district boundaries\): [\d,]+ \(90% margin of error ±[\d,]+\)/);
    assert.match(text, /Honolulu County: [\d,]+ \(Controlled estimate; no numeric margin of error published\)/);
    await proof(p, "phase3-11-margins", {});
  } finally { await p.close(); }
});

// SNAP participation gap: the server's typed, value-free offer on an unsupported question (shape as emitted by
// districtbrief/ia_language.py snap_gap_offer). Offline fake Ask transport in this page only: no provider.
const GAP_COLD = "How many House District 28 residents qualify for SNAP but aren’t enrolled? Give me something I can take into a meeting.";
async function gapPage(withOffer) {
  const p = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  const language = [];
  await p.route("**/*", async route => {
    const u = new URL(route.request().url());
    if (!["127.0.0.1", "localhost", "[::1]"].includes(u.hostname)) return route.abort();
    if (u.pathname === "/api/catalog") { const r = await route.fetch(), j = await r.json(); j.language = { enabled: true, schema_version: "ia-language/1", message: "fixture", limits: { deadline_seconds: 25 } }; return route.fulfill({ response: r, json: j }); }
    if (!u.pathname.startsWith("/api/language/")) return route.continue();
    const action = u.pathname.split("/").pop(), body = route.request().postDataJSON(); language.push(action);
    if (action === "cancel") return route.fulfill({ json: { status: "cancelled" } });
    if (action === "start") {
      const c = body.context, rel = await route.request().frame().page().evaluate(async () => (await (await fetch("/api/catalog")).json()).investigation.release_id || "");
      p.gapEnv = { request_id: body.request_id, context: c, context_digest: "sha256:" + "d".repeat(64), tokens: { schema_version: "ia-language/1", release_id: rel, ...Object.fromEntries(["case_id", "branch_id", "revision", "snapshot_id", "operation_version", "recipe_version"].map(k => [k, c[k]])) } };
      return route.fulfill({ status: 202, json: { ...p.gapEnv, status: "pending" } });
    }
    const reply = { ...p.gapEnv, status: "unsupported", intent: "none", message: "This request is outside the admitted evidence or operations. Use guided controls.", reason_code: "unavailable_evidence",
      normalized_plan: null, typed_diff: [], inherited_fields: [], source_inspection_refs: [], choices: [], clarify_field: "", model_calls: 1 };
    if (withOffer) reply.participation_gap = { kind: "snap_participation_gap", program_id: "snap_hi", issue_id: "food_assistance_outreach", district: { state_fips: "15", chamber: "house", code: "028", boundary_session: 2024 } };
    return route.fulfill({ json: reply });
  });
  await p.goto(base.href);
  await p.waitForFunction(() => !document.querySelector("#ia-recommend").hidden && document.querySelector("#ia-cancel").hidden);
  p.language = language;
  return p;
}
async function gapAsk(p, text = GAP_COLD) {
  await p.locator("#ia-question-text").fill(text);
  await p.locator("#ia-question-submit").click();
  await p.locator("#ia-question-result .ia-alternatives").waitFor();
}

test("SNAP gap: opening outreach waits for an incomplete staff date on pointer activation", { timeout: 30000 }, async () => {
  const p = await gapPage(true);
  try {
    const calls = investigationCalls(p), outreach = p.locator("#ia-gap-open");
    await gapAsk(p);
    const date = await startIncompleteTrackingDate(p);
    await outreach.click();
    assert.deepEqual(calls, []);
    assert.match(await p.locator("#ia-status").textContent(), /Finish or clear the staff date/);
    await assertIncompleteTrackingDateKept(date);
    await date.fill("");
    await outreach.click();
    await p.locator("#ia-answer-h").waitFor();
    assert.deepEqual(calls.map(c => c.mode), ["run"]);
    assert.deepEqual(p.language, ["start", "status"]);
  } finally { await p.close(); }
});

test("SNAP gap: the cold question gets a plain no-count answer and opens SNAP outreach and its brief without another question", { timeout: 60000 }, async () => {
  const p = await gapPage(true);
  try {
    const calls = investigationCalls(p);
    await gapAsk(p);
    const box = await p.locator("#ia-question-result").textContent();
    assert.match(box, /No SNAP enrollment or eligible-population count is available for House 028 or a matching area\. The app has state and county enrollment totals\./);
    assert.doesNotMatch(box, /Social Security|Kūpuna|older-adult|Measures already run/i, "no unrelated examples or default-context findings");
    assert.doesNotMatch(box.replace(/House 028/g, ""), /\d/, "no figure is presented");
    assert.equal(await p.locator("#ia-alt-s1").count(), 0);
    assert.equal(await p.locator("#ia-gap-open").textContent(), "Open SNAP outreach for House 028");
    assert.deepEqual(calls, [], "nothing ran before the staff choice");
    await p.locator("#ia-gap-open").click();
    await p.locator("#ia-answer-h").waitFor();
    await p.waitForFunction(() => document.querySelector("#ia-cancel").hidden);
    assert.equal(calls.length, 1);
    assert.equal(calls[0].mode, "run");
    assert.equal(calls[0].plan.issue_id, "food_assistance_outreach");
    assert.deepEqual(calls[0].plan.steps.map(s => s.operation), ["profile", "program_evidence", "outreach_lead"]);
    assert.equal(calls[0].plan.district.code, "028");
    assert.equal(await p.locator("#ia-answer-h").textContent(), "SNAP outreach · House 028");
    assert.equal((await focus(p)).id, "ia-evidence-h", "the ordinary run focus rule is unchanged");
    const CHECK = "Ask DHS BESSD for SNAP enrollment and eligible-population data for House 028 or a matching area.";
    const answer = await p.locator("#ia-answer").textContent();
    assert.match(answer, /No count: the app has no SNAP enrollment or eligible-population data for House 028\./);
    assert.match(await p.locator("#ia-status").textContent(), /SNAP outreach opened for House 028\. It does not answer how many residents qualify but are not enrolled/);
    // The staff action comes before the brief action, is named plainly and is added only on request.
    const order = await p.locator("#ia-answer").evaluate(a => [...a.querySelectorAll("#ia-gap-check-add, #ia-outreach-brief")].map(x => x.id));
    assert.deepEqual(order, ["ia-gap-check-add", "ia-outreach-brief"]);
    assert.equal(await p.locator("#ia-gap-check-add").textContent(), "Add DHS data check to brief");
    assert.equal(await p.locator("#ia-gap-check-what").textContent(), "Staff action for the brief: “" + CHECK + "” Adding it also selects the SNAP outreach findings and agency action, and it prints in the brief after the normal staff review. Nothing is added unless you choose it.");
    assert.equal(await p.locator("#ia-chk-custom1-text").count(), 0, "no staff text is added automatically");
    await p.locator("#ia-gap-check-add").click();
    assert.equal(await p.locator("#ia-chk-custom1-text").inputValue(), CHECK);
    assert.equal(await p.locator("#ia-preview").isVisible(), false, "no context review: the action was chosen before the staff item");
    assert.equal(calls.length, 1, "selecting and adding sends nothing");
    assert.equal(await p.locator("#ia-gap-check-add").count(), 0, "added once");
    assert.match(await p.locator("#ia-gap-check-what").textContent(), /It is in the checklist and prints in the brief after the normal staff review\./);
    // The normal staff review gates printing; after it, the brief carries the pinned SNAP action and the staff check.
    await p.locator("#ia-outreach-brief").click();
    assert.equal(calls.filter(c => c.mode === "brief").length, 0, "staff content is not printed before review");
    await p.locator("#ia-review-btn").click();
    await p.locator("#ia-outreach-brief").click();
    await p.waitForFunction(() => !document.querySelector("#ia-print-btn").disabled);
    const brief = calls.at(-1);
    assert.equal(brief.mode, "brief");
    assert.equal(brief.selected_action_ref.action_id, "snap_food_outreach_verify/1");
    assert.deepEqual(brief.checklist_edits, [{ item_id: "custom1", text: CHECK }]);
    const printed = await p.locator("#ia-brief").textContent();
    assert.ok(printed.includes(CHECK), "the DHS data check prints in the brief");
    assert.doesNotMatch(printed, /158,135|78,231/, "no caseload figure is presented as a district count");
    assert.deepEqual(p.language, ["start", "status"], "no further question was sent");
    await proof(p, "snap-gap-cold", {});
  } finally { await p.close(); }
});

test("SNAP gap: an unrelated unsupported reply keeps the generic fallback and offers no outreach", { timeout: 30000 }, async () => {
  const p = await gapPage(false);
  try {
    await gapAsk(p, "Forecast senior population in House 28.");
    assert.equal(await p.locator("#ia-gap-open").count(), 0);
    assert.match(await p.locator("#ia-question-result").textContent(), /Ask does not have what the question asks for/);
    assert.equal(await p.locator("#ia-alt-advanced").count(), 1);
  } finally { await p.close(); }
});

test("SNAP gap: adding the DHS check cannot discard plan edits or replace a context review", { timeout: 30000 }, async () => {
  const p = await gapPage(true);
  try {
    await gapAsk(p); await p.locator("#ia-gap-open").click();
    const add = p.locator("#ia-gap-check-add");
    await add.waitFor();
    await observeCase(p); await p.locator("#ia-download-staff").check();
    const snapshot = () => p.evaluate(() => window.dateRaceCase);
    const before = await snapshot(), calls = investigationCalls(p);
    await p.locator("#ia-map-session").selectOption("2024");
    assert.equal(await add.isDisabled(), true);
    assert.match(await p.locator("#ia-gap-check-what").innerText(), /Apply or discard the plan edits/);
    // Even a click event already delivered to the control must check the live draft.
    await add.dispatchEvent("click");
    assert.equal(await p.locator("#ia-map-session").inputValue(), "2024");
    assert.deepEqual(await snapshot(), before);
    await p.locator("#ia-context-apply-btn").click();
    const preview = p.locator("#ia-preview"), review = await preview.innerText();
    await add.dispatchEvent("click");
    assert.equal(await preview.innerText(), review);
    assert.equal(await p.locator("#ia-map-session").inputValue(), "2024");
    assert.deepEqual(await snapshot(), before);
    assert.deepEqual(calls, []);
    await p.locator("#ia-preview-cancel").click();
    await p.locator("#ia-discard").click();
    assert.equal(await add.isEnabled(), true);
  } finally { await p.close(); }
});

test("SNAP gap: adding the DHS check validates a focused date and keeps a focused staff title", { timeout: 30000 }, async () => {
  const p = await gapPage(true);
  try {
    await gapAsk(p); await p.locator("#ia-gap-open").click();
    const add = p.locator("#ia-gap-check-add");
    await add.waitFor();
    await observeCase(p); await p.locator("#ia-download-staff").check();
    const snapshot = () => p.evaluate(() => window.dateRaceCase);
    const before = await snapshot(), calls = investigationCalls(p);
    if (await p.locator("#ia-tracking").getAttribute("open") === null) await p.locator("#ia-tracking-summary").click();
    const date = p.locator("#ia-track-date");
    await date.focus();
    await p.keyboard.type("1116");
    assert.equal(await date.evaluate(el => el.value === "" && el.validity.badInput), true);
    await add.evaluate(el => el.click());
    assert.equal((await focus(p)).id, "ia-track-date");
    assert.match(await p.locator("#ia-status").innerText(), /Finish or clear the staff date/);
    assert.deepEqual(await snapshot(), before);
    await p.keyboard.type("2");
    assert.equal(await date.inputValue(), "0002-11-16", "the next key continues the held native date");
    await add.evaluate(el => el.click());
    assert.equal((await focus(p)).id, "ia-alert");
    assert.match(await p.locator("#ia-alert").innerText(), /real YYYY-MM-DD date/);
    assert.deepEqual(await snapshot(), before);
    await date.focus();
    await p.keyboard.type("1116");
    assert.equal(await date.evaluate(el => el.validity.badInput), true);
    await add.click();
    assert.equal((await focus(p)).id, "ia-track-date");
    assert.equal(await date.evaluate(el => el.validity.badInput), true, "pointer activation keeps the incomplete date after blur");
    assert.deepEqual(await snapshot(), before);
    await date.fill("");
    await p.locator("#ia-title").fill("Staff title before adding DHS check");
    await add.evaluate(el => el.click());
    const held = await snapshot(), active = activeBranch(held);
    assert.equal(held.branches.length, before.branches.length);
    assert.equal(active.staff_edits.title, "Staff title before adding DHS check");
    assert.equal(active.selected_action_ref, null);
    assert.deepEqual(active.checklist_edits, []);
    assert.match(await p.locator("#ia-preview").innerText(), /staff note or checklist entry goes to review/);
    assert.equal(await add.isDisabled(), true);
    assert.match(await p.locator("#ia-gap-check-what").innerText(), /Finish or cancel the context review/);
    assert.deepEqual(calls, []);
  } finally { await p.close(); }
});

test("SNAP gap: brief selections and a changed context are protected before outreach opens", { timeout: 60000 }, async () => {
  const p = await gapPage(true);
  try {
    await recommend(p);
    const before = await p.locator("#ia-tray-count").textContent();
    const calls = investigationCalls(p);
    await gapAsk(p);
    await p.locator("#ia-gap-open").click();
    assert.match(await p.locator("#ia-gap").textContent(), /Check this before it opens.*brief selections/);
    assert.equal((await focus(p)).id, "ia-gap-open");
    assert.deepEqual(calls, [], "the first choice only lists what is affected");
    await p.locator("#ia-gap-open").click();
    await p.locator("#ia-preview").waitFor({ state: "visible" });
    assert.deepEqual(calls, [], "a new context still shows its context review first");
    assert.equal(await p.locator("#ia-tray-count").textContent(), before, "earlier selections are unchanged");
    // A changed plan after the reply withdraws the offer instead of running it against another context.
    const q = await gapPage(true);
    try {
      const qcalls = investigationCalls(q);
      await gapAsk(q);
      await q.locator("#ia-issue").selectOption("custom");
      assert.equal(await q.locator("#ia-gap-open").count(), 0, "the offer belongs to the question's context only");
      assert.match(await q.locator("#ia-question-result").textContent(), /question scope or plan changed/);
      assert.deepEqual(qcalls, [], "nothing ran");
    } finally { await q.close(); }
  } finally { await p.close(); }
});

test("Ask count comparisons use the printed limitation without changing the finding or sources", { timeout: 40000 }, async () => {
  const p = await page(base, { mockAsk: true });
  try {
    const plan = structuredClone(activeBranch(await savedCase(p)).plan);
    plan.district = { ...plan.district, chamber: "senate", code: "008" };
    plan.issue_id = "custom";
    plan.steps = [{ step_id: "s2", operation: "compare", args: { metric_ids: ["total_population"], comparison_geography: "HI-STATE-2024" } }];
    const run = p3Response(p, "run", plan.map_session);
    await p3Ask(p, "Compare total population in Senate 8 with the State.", plan, []);
    const response = await (await run).json();
    const claim = response.claims.find(c => c.kind === "comparison");
    const internal = "the fixture has no published rate for this measure.";
    const displayed = "the data has no published rate for this measure.";
    assert.ok(claim.not_differenced_reason.includes(internal));
    assert.ok(claim.limitations.some(x => x.includes(internal)));
    assert.equal(claim.difference, null);
    const answer = await p.locator("#ia-answer").innerText();
    assert.ok(answer.includes(displayed), answer);
    assert.ok(!answer.includes(internal));
    const finding = p.locator("#ia-evidence .ia-claim").first();
    await finding.locator("summary").click();
    assert.ok((await finding.innerText()).includes(displayed));
    assert.ok(!(await finding.innerText()).includes(internal));
    assert.deepEqual(await finding.locator(".source-btn").evaluateAll(nodes => nodes.map(el => [el.dataset.sourceId, el.dataset.findingId])),
      claim.source_inspection_refs.map(r => [r.source_id, r.finding_id]));
    await finding.locator(".ia-select input").check();
    const saved = await savedCase(p);
    assert.deepEqual(activeBranch(saved).selected_claim_refs, [claim.claim_ref]);
    const brief = await p3Brief(p, plan.map_session);
    assert.ok(brief.html.includes(displayed));
    assert.ok(!brief.html.includes(internal));
    await chooseCase(p, saved); await replayCase(p);
    assert.deepEqual(activeBranch(await savedCase(p)).selected_claim_refs, [claim.claim_ref]);
    await proof(p, "ask-count-wording", { answer, claimRef: claim.claim_ref });
  } finally { await p.close(); }
});

test("Ask labels earlier findings while reading and running a question, then removes the label", { timeout: 40000 }, async () => {
  const p = await page(base, { mockAsk: true });
  let release;
  try {
    const plan = structuredClone(activeBranch(await savedCase(p)).plan);
    const ask = async (question, result) => {
      let received;
      const ready = new Promise(resolve => { received = resolve; });
      const gate = new Promise(resolve => { release = resolve; });
      await mockAskStatus(p, async () => { received(); await gate; return result(); });
      await p.locator("#ia-question-text").fill(question);
      await p.locator("#ia-question-submit").click();
      await ready;
    };
    const earlierAnswer = p.locator("#ia-earlier-answer"), earlierFindings = p.locator("#ia-earlier-findings");
    await ask("Could you show the findings?", () => ({ status: "clarify", message: "Choose a program.", choices: [] }));
    assert.equal(await earlierFindings.isVisible(), true, "existing plan findings are labelled even before the first accepted answer");
    assert.equal(await earlierAnswer.isVisible(), false);
    await p.locator("#ia-question-cancel").click(); release();
    assert.equal(await earlierFindings.isVisible(), false);
    const withMaui = structuredClone(plan);
    withMaui.steps[1].args.comparison_geography = "HI-COUNTY-009-2024";
    await p3Ask(p, "Compare senior poverty with Maui County.", withMaui, [{ field: "steps", change: "changed", step_id: "s2",
      before: plan.steps[1], after: withMaui.steps[1] }]);
    const question = "Show the Maui County comparison first.";
    const current = structuredClone(activeBranch(await savedCase(p)).plan);
    // A reorder runs in the same context, so its earlier findings stay on screen while the request is held.
    current.steps.unshift(...current.steps.splice(1, 1));
    for (const outcome of ["cancel", "error", "run"]) {
      const heldRun = outcome === "run" ? await gateInvestigation(p, "run") : null;
      await ask(question, () => outcome === "error" ? null : ({ status: "propose", intent: "replace_plan", normalized_plan: current, typed_diff: [] }));
      assert.equal(await earlierFindings.isVisible(), true);
      assert.equal(await earlierAnswer.isVisible(), true);
      assert.match(await earlierFindings.innerText(), /Earlier findings.*new question is still in progress/);
      assert.match(await p.locator("#ia-answer .ia-answer-q").innerText(), /Maui County/);
      assert.equal(await p.locator("#ia-evidence .ia-claim input").first().isEnabled(), true);
      await p.locator("#ia-title").focus();
      if (outcome === "cancel") await p.locator("#ia-question-cancel").evaluate(el => el.click());
      release();
      if (heldRun) {
        await heldRun.received;
        assert.equal(await earlierFindings.isVisible(), true, "findings remain labelled during the dispatched run");
        await earlierFindings.scrollIntoViewIfNeeded();
        await proof(p, "ask-earlier-findings", { text: await earlierFindings.innerText() });
        heldRun.open();
      }
      await requestDone(p);
      await p.locator("#ia-question-cancel").waitFor({ state: "hidden" });
      assert.equal(await earlierFindings.isVisible(), false);
      assert.equal(await earlierAnswer.isVisible(), false);
      assert.equal((await focus(p)).id, "ia-title");
      assert.match(await p.locator("#ia-answer .ia-answer-q").innerText(), outcome === "run" ? /Show the Maui County comparison first/ : /Compare senior poverty with Maui County/);
    }
  } finally { if (release) release(); await p.close(); }
});

const PRES_RATE = "What is the poverty rate for people 65 and over in Senate district 7, compared with Maui County?";
const PRES_COUNT = "How many people age 65 and over are living in poverty in Senate District 7, compared with Maui County?";

test("Ask keeps one visible confirmation for the senior-poverty rate and replays the old district", { timeout: 30000 }, async () => {
  const p = await page(base, { viewport: { width: 320, height: 568 }, mockAsk: true });
  try {
    const before = await savedCase(p), calls = investigationCalls(p);
    const district = { ...activeBranch(before).plan.district, chamber: "senate", code: "007" };
    const step = { step_id: "s5", operation: "compare", args: { metric_ids: ["poverty_rate_65_plus"], comparison_geography: "HI-COUNTY-009-2024" } };
    const plan = { ...activeBranch(before).plan, district, issue_id: "custom", steps: [step] };
    const diff = [{ field: "steps", change: "added", step_id: step.step_id, before: null, after: step }];
    await offerAskProposal(p, PRES_RATE.replace("district 7,", "district 7 or 9,"), plan, diff);
    await assertDistrictClarification(p, PRES_RATE.replace("district 7,", "district 7 or 9,"));
    const language = await offerAskProposal(p, PRES_RATE, plan, diff);
    assert.equal(await p.locator("#ia-proposal-run").textContent(), "Switch to Senate 007 and run");
    assert.deepEqual(calls, []);
    await p.keyboard.press("Tab");
    assert.equal((await focus(p)).id, "ia-proposal-run");
    await p.keyboard.press("Enter");
    const answer = p.locator("#ia-answer-h");
    await answer.waitFor();
    assert.equal((await focus(p)).id, "ia-answer-h");
    assert.equal(await answer.evaluate(el => { const r = el.getBoundingClientRect(); return r.top >= 0 && r.bottom <= innerHeight; }), true);
    assert.equal(await p.locator("#ia-preview").isVisible(), false);
    await p.waitForFunction(() => /Senate 007 · 2026 map display/.test(document.querySelector("#ia-map-summary").textContent));
    assert.equal(await p.locator("#ia-mapbox").evaluate(d => d.open), false, "a narrow screen keeps the compact closed map");
    assert.equal((await focus(p)).id, "ia-answer-h");
    assert.deepEqual(calls.map(c => c.mode), ["run"]);
    assert.deepEqual(language, ["start", "status"]);
    const after = await savedCase(p);
    assert.equal(after.branches.length, 2);
    assert.deepEqual(after.branches.find(b => b.branch_id === before.active_branch_id), activeBranch(before));
    await p.locator("#ia-restore-0").click();
    await requestDone(p);
    assert.equal((await savedCase(p)).active_branch_id, before.active_branch_id);
    assert.equal(calls[1].snapshot_id, activeBranch(before).snapshot_id);
    assert.deepEqual(calls[1].plan, activeBranch(before).plan);
  } finally { await p.close(); }
});

test("Ask comparison answer: two labelled sides with their own sources, the desktop map once, and a led brief", { timeout: 60000 }, async () => {
  const p = await page(base, { viewport: { width: 1440, height: 732 }, mockAsk: true });
  try {
    const before = await savedCase(p), calls = investigationCalls(p);
    const district = { ...activeBranch(before).plan.district, chamber: "senate", code: "007" };
    const step = { step_id: "s5", operation: "compare", args: { metric_ids: ["poverty_rate_65_plus"], comparison_geography: "HI-COUNTY-009-2024" } };
    const plan = { ...activeBranch(before).plan, district, issue_id: "custom", steps: [step] };
    const diff = [{ field: "steps", change: "added", step_id: step.step_id, before: null, after: step }];
    const run = p3Response(p, "run", plan.map_session);
    await p3Ask(p, PRES_RATE, plan, diff);
    const claim = (await (await run).json()).claims.find(c => c.kind === "comparison");
    assert.deepEqual(calls.map(c => c.mode), ["run"]);
    assert.equal(claim.left.estimate_display, "10.3%"); assert.equal(claim.right.estimate_display, "8.7%");
    const item = p.locator("#ia-answer .ia-answer-compare"), sides = item.locator(".ia-answer-side");
    assert.equal(await sides.count(), 2);
    const shown = await sides.evaluateAll(n => n.map(x => [x.getAttribute("aria-label"), x.innerText.replace(/\s+/g, " ").trim()]));
    assert.equal(shown[0][0], "District: Senate 007"); assert.equal(shown[1][0], "Compared with: Maui County");
    assert.match(shown[0][1], /^District Senate 007 10\.3% 90% margin of error ±2\.3 percentage points Inspect source: .+ — Senate 007$/i);
    assert.match(shown[1][1], /^Compared with Maui County 8\.7% 90% margin of error ±1\.3 percentage points Inspect source: .+ — Maui County$/i);
    const text = await item.innerText();
    assert.match(text, /Point difference \+1\.6 percentage points\. No statistical significance test is performed\./);
    assert.match(text, /Period: ACS 2020–2024 5-year · Universe: People age 65 years and over for whom poverty status is determined/);
    assert.doesNotMatch(text, /overlap|significant(ly)? (higher|lower|different)|boundary session/i);
    // Each side opens its own source: the Senate workbook and the county workbook, each at its own cells.
    const buttons = sides.locator(".source-btn");
    assert.deepEqual(await buttons.evaluateAll(n => n.map(b => b.dataset.findingId)), [claim.left.finding_id, claim.right.finding_id]);
    assert.deepEqual(await buttons.evaluateAll(n => n.map(b => b.dataset.sourceId)), [claim.left.source.source_id, claim.right.source.source_id]);
    assert.notEqual(claim.left.source.source_id, claim.right.source.source_id);
    for (const [i, cells] of [[0, /AB145[\s\S]*AC145|AC145[\s\S]*AB145/], [1, /T145[\s\S]*U145|U145[\s\S]*T145/]]) {
      await buttons.nth(i).click();
      await p.locator("#source-dialog[open]").waitFor();
      await p.waitForFunction(() => /DP03/.test(document.querySelector("#source-body").textContent));
      assert.match(await p.locator("#source-body").innerText(), cells);
      await p.locator("#close-source").click();
      assert.equal(await buttons.nth(i).evaluate(b => b === document.activeElement), true, "focus returns to the side's own source button");
    }
    // The confirmed district's map opens on a wide screen once drawn; its shading names all ages and both years.
    await p.locator("#ia-mapbox[open]").waitFor();
    assert.match(await p.locator("#ia-map-summary").textContent(), /^Senate 007 · 2026 map display \(statistics use 2024 district boundaries\) · 3 parts · shading: poverty rate for all ages \(not the 65 and over rate\)/);
    assert.match(await p.locator("#ia-indicator-text").textContent(), /^Shading: poverty rate for all ages \(all people\), [\d.]+%.*This is not the age 65 and over poverty rate shown in older-adult findings or answers\.$/);
    assert.equal(await p.locator("#ia-map").evaluate(m => { const f = m.querySelector("#ia-indicator-text"), svg = m.querySelector("svg"); return !!(f && svg && (f.compareDocumentPosition(svg) & Node.DOCUMENT_POSITION_FOLLOWING)); }), true, "the shading population sits just before the drawing");
    assert.deepEqual(await p.locator("#ia-map-part option").allTextContents(), ["Part 1 of 3", "Part 2 of 3", "Part 3 of 3"]);
    assert.match(await p.locator("#ia-map-text").textContent(), /Statistics boundary2024 district boundaries.*Map boundary shown2026 boundaries \(display only\).*Map shadingPoverty rate for all ages \(all people\), not the age 65 and over rate/);
    assert.match(await p.locator("#ia-context-summary").innerText(), /Senate 007 · Your question/);
    // A staff collapse is kept when a later answer for the same district is shown.
    await p.locator("#ia-mapbox > summary").click();
    assert.equal(await p.locator("#ia-mapbox").evaluate(d => d.open), false);
    await p3Ask(p, "Show the Senate 7 and Maui County comparison again.", plan, []);
    await p.waitForTimeout(200);
    assert.equal(await p.locator("#ia-mapbox").evaluate(d => d.open), false, "a manual collapse is not overridden");
    // The answer's brief leads with what the comparison shows and states that no agency action is selected.
    const brief = p3Response(p, "brief", plan.map_session);
    await p.locator("#ia-answer-brief").click();
    await requestDone(p);
    await p.waitForFunction(() => !document.querySelector("#ia-print-btn").disabled);
    const html = (await (await brief).json()).brief.html, out = await p.locator("#ia-brief-out").innerText();
    assert.match(html, /<section class="brief-takeaway"><p><strong>What this shows:<\/strong> Poverty rate, age 65 and over: Senate District 007 10\.3% and Maui County 8\.7%, a point difference of \+1\.6 percentage points between published estimates \(no significance implied\)\. <a class="cite" href="#cite-1">\[1\]<\/a><a class="cite" href="#cite-2">\[2\]<\/a><\/p><p><strong>Agency action:<\/strong> None selected\. These published figures do not identify an agency action\. Staff decide any follow-up\.<\/p><\/section>/);
    assert.match(out, /District brief: Senate District 007 \(2024 district boundaries\)/);
    assert.match(out, /Senate District 007 · Issue: Custom investigation · Statistics use 2024 district boundaries · Map display: 2026 boundaries/);
    assert.match(out, /10\.3% \(±2\.3\) vs Maui County 8\.7% \(±1\.3\); point difference \+1\.6 percentage points \(no significance implied\)/);
    assert.match(out, /No statistical difference test was performed\./);
    assert.doesNotMatch(out, /staff-composed|boundary session|Next step|Recorded next step/);
    assert.deepEqual(activeBranch(await savedCase(p)).selected_claim_refs, [claim.claim_ref], "the brief uses the exact answer finding");
    await proof(p, "comparison-answer-map-brief", { sides: shown });
  } finally { await p.close(); }
});

const rateChoices = [
  { alias: "d_s007", field: "district", value: { chamber: "senate", code: "007" }, label: "Senate 7" },
  { alias: "m_poverty_rate_65_plus", field: "metric", value: "poverty_rate_65_plus", label: "Poverty rate, age 65 and over" },
  { alias: "g_HI-COUNTY-009-2024", field: "comparator", value: "HI-COUNTY-009-2024", label: "Maui County" },
];
async function offerCountRefusal(p, choices = rateChoices, envelope = {}) {
  const language = await mockAskStatus(p, () => ({
    status: "unsupported", intent: "none", reason_code: "unavailable_evidence", normalized_plan: null,
    clarify_field: "", choices, ...envelope,
  }));
  await p.locator("#ia-question-text").fill(PRES_COUNT);
  await p.locator("#ia-question-submit").click();
  await p.locator("#ia-alt-lookup").waitFor();
  return language;
}

test("Ask offers the separately chosen rate only through guided lookup", { timeout: 30000 }, async () => {
  const p = await page(base, { mockAsk: true });
  try {
    await recommend(p);
    await p.locator("#ia-title").fill("House 028 staff notes");
    await p.locator("#ia-download-staff").check();
    const before = await savedCase(p), calls = investigationCalls(p);
    const language = await offerCountRefusal(p);
    const result = p.locator("#ia-question-result");
    assert.match(await result.innerText(), /a rate is never shown in place of a count/);
    assert.match(await result.innerText(), /Senate 007 and Maui County.*separate comparison/);
    assert.match(await result.innerText(), /Findings already run for House 028/);
    assert.equal(await p.locator("#ia-answer-h").isVisible(), false);
    assert.equal(await p.locator("#ia-proposal-run").count(), 0);
    assert.deepEqual(calls, []);
    const resolutions = [];
    p.on("request", req => {
      if (new URL(req.url()).pathname === "/api/resolve") resolutions.push(req.postDataJSON());
    });
    await p.locator("#ia-alt-lookup").click();
    assert.equal(await p.locator("#tab-btn-workflow").getAttribute("aria-selected"), "true");
    assert.equal((await focus(p)).id, "run-btn");
    assert.deepEqual(resolutions, []);
    assert.deepEqual(await Promise.all(["chamber", "code", "metric", "geo"].map(k => p.locator("#ctl-" + k).inputValue())),
      ["senate", "007", "poverty_rate_65_plus", "HI-COUNTY-009-2024"]);
    await p.keyboard.press("Enter");
    await p.waitForFunction(() => /10\.3%/.test(document.querySelector("#result").innerText));
    assert.match(await p.locator("#result").innerText(), /8\.7%/);
    assert.equal(resolutions.length, 1);
    assert.equal(resolutions[0].input_mode, "guided");
    await p.locator("#tab-btn-investigation").click();
    assert.deepEqual(await savedCase(p), before);
    assert.deepEqual(calls, []);
    assert.deepEqual(language, ["start", "status"]);
  } finally { await p.close(); }
});

test("Ask opens unfilled guided selectors for absent, malformed or stale recovery", { timeout: 30000 }, async () => {
  for (const [choices, envelope] of [
    [[], {}],
    [[...rateChoices.slice(0, 2), { ...rateChoices[2], value: "HI-COUNTY-999-2024" }], {}],
    [rateChoices, { context_digest: "sha256:" + "a".repeat(64) }],
  ]) {
    const p = await page(base, { mockAsk: true });
    try {
      await p.locator("#tab-btn-workflow").click();
      assert.equal(await p.locator("#ctl-code").inputValue(), "028");
      await p.locator("#tab-btn-investigation").click();
      const calls = investigationCalls(p);
      await offerCountRefusal(p, choices, envelope);
      assert.equal(await p.locator("#ia-alt-lookup").textContent(), "Choose measures and geography in Single lookup");
      await p.locator("#ia-alt-lookup").click();
      assert.equal((await focus(p)).id, "ctl-chamber");
      assert.equal(await p.locator("#ctl-chamber").inputValue(), "");
      assert.equal(await p.locator("#ctl-code").inputValue(), "");
      assert.equal(await p.locator("#ctl-geo").inputValue(), "");
      assert.deepEqual(calls, []);
    } finally { await p.close(); }
  }
});
