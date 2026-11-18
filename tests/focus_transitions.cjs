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
      assert.match(text, /staff entr[^.]+Context 1, Context 2/i);
      assert.match(text, /selected finding[^.]+Context 1, Context 2/i);
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
