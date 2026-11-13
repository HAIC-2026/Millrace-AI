/* Reducer checks for static/case_state.js. Run: node --test tests/test_case_state.cjs
   Fixtures are case files exported from a real run of this candidate's handler (House 028 default
   recipe); replies below come from a small stand-in that assigns claim identities from the plan
   context the way the contract describes. These tests cover browser case logic only. They do not
   cover the DOM, real network transport, or native print. */
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const C = require("../static/case_state.js");

const sha = (v) => "sha256:" + crypto.createHash("sha256").update(typeof v === "string" ? v : JSON.stringify(v), "utf8").digest("hex");
const PRIVATE_TEXT = fs.readFileSync(path.join(__dirname, "fixtures/private_case.json"), "utf8");
const PUBLIC_TEXT = fs.readFileSync(path.join(__dirname, "fixtures/public_case.json"), "utf8");
const FIXTURE = JSON.parse(PRIVATE_TEXT).branches[0];
const RUNTIME = { snapshot_id: FIXTURE.snapshot_id, release_id: FIXTURE.release_id, operation_version: "ia-core/1", schema_version: "haic-investigation/1", recipe_versions: ["aging_at_home/1", "custom/1"] };
let counter = 0;
const ids = { uuid: () => { counter += 1; const hex = crypto.createHash("sha256").update("id" + counter).digest("hex"); return hex.slice(0, 8) + "-" + hex.slice(8, 12) + "-4" + hex.slice(13, 16) + "-a" + hex.slice(17, 20) + "-" + hex.slice(20, 32); } };
const ok = (r) => { assert.equal(r.error, undefined, r.error && r.error.code + ": " + r.error.message); return r.state; };
const clone = (v) => JSON.parse(JSON.stringify(v));

// Stand-in server: a claim identity depends on district plus the exact operation scope, never on a label.
function claimsFor(plan) {
  const d = plan.district.chamber + plan.district.code, steps = [], claims = new Map(), responses = [];
  const add = (fid, binding, extra) => { const ref = { snapshot_id: RUNTIME.snapshot_id, finding_id: fid, semantic_hash: sha([fid, binding]) }; claims.set(fid, Object.assign({ claim_ref: ref, kind: "statistic", text: fid, binding: {}, dependencies: [] }, extra)); return ref; };
  const programs = [], hyps = {};
  plan.steps.forEach((s) => {
    const refs = [];
    if (s.operation === "profile") (s.args.metric_ids || C.AGING_METRICS).forEach((m) => refs.push(add("stat:" + d + ":" + m, [d, m])));
    if (s.operation === "compare") s.args.metric_ids.forEach((m) => { add("stat:" + d + ":" + m, [d, m]); refs.push(add("cmp:" + d + ":" + m + ":" + s.args.comparison_geography, [d, m, s.args.comparison_geography], { kind: "comparison" })); });
    if (s.operation === "program_evidence") s.args.program_ids.forEach((p) => { refs.push(add("prog:" + d + ":" + p, [d, p], { kind: "program_relevance" })); if (!programs.includes(p)) programs.push(p); });
    if (s.operation === "outreach_lead") { const p = s.args.program_id; hyps[p] = add("hyp:" + d + ":" + p, [d, p, "state"], { kind: "outreach_hypothesis" }); refs.push(hyps[p]); add("prog:" + d + ":" + p, [d, p], { kind: "program_relevance" }); if (!programs.includes(p)) programs.push(p); }
    steps.push({ step_id: s.step_id, operation: s.operation, status: "ok", claim_refs: refs, reason_code: null, message: null, next_actions: [] });
  });
  const actionIds = { kupuna_care_hi: "kupuna_verify/1", snap_hi: "snap_verify/1" };
  programs.forEach((p) => responses.push({ program_id: p, tier: actionIds[p] ? "verification_action" : "reference", program_claim_ref: claims.get("prog:" + d + ":" + p).claim_ref, hypothesis_claim_ref: hyps[p] || null,
    action_ref: actionIds[p] ? { action_id: actionIds[p], semantic_hash: sha([d, p, plan.service_area_id, hyps[p] || null]) } : null, support_claim_refs: [], jurisdiction: { state: "unknown" }, access: { recorded_status: "reference_checked", current_availability: "unverified", cost: "unverified" },
    weakening_facts: [], facts_to_verify: [], template_checklist: C.TEMPLATE_CHECK_IDS.map((id) => ({ item_id: id, text: "Template " + id })) }));
  return { steps, claims: Array.from(claims.values()), responses };
}
function reply(request, patch) {
  const built = claimsFor(request.plan), known = new Map(built.claims.map((c) => [C.refKey(c.claim_ref), c]));
  const tokens = {}; C.TOKEN_KEYS.forEach((k) => { tokens[k] = request[k]; });
  return Object.assign({ status: "ok", tokens, model_calls: 0, data_snapshot_id: sha("data"), metadata_snapshot_id: sha("meta"), normalized_plan: clone(request.plan),
    interpretation: { matched_fields: [], inherited_fields: [], choices: [], reason: null }, steps: built.steps, claims: built.claims, responses: built.responses,
    selection_review: (request.selected_claim_refs || []).map((r) => ({ claim_ref: r, state: known.has(C.refKey(r)) ? "retained" : "retired", reason_code: known.has(C.refKey(r)) ? "exact_canonical_identity" : "claim_no_longer_in_plan" })),
    action_review: request.selected_action_ref ? { action_ref: request.selected_action_ref, state: built.responses.some((c) => c.action_ref && C.actionKey(c.action_ref) === C.actionKey(request.selected_action_ref)) ? "retained" : "retired", reason_code: "x" } : null,
    brief: request.mode === "brief" ? { html: "<article class=\"brief-doc\"></article>", print_units: 100 } : null, limitations: [] }, patch || {});
}
// As in the browser: the plan identity is computed client-side from the reply's normalized plan and passed alongside it.
const meta = (request) => ({ http_status: 200, plan_hash: sha(C.planCanonical(request.plan)) });
function run(state) { const b = C.beginRun(state, ids); assert.equal(b.error, undefined); const r = C.applyResponse(b.state, reply(b.request), meta(b.request)); assert.equal(r.outcome, "committed"); return r.state; }
function change(state, proposal) { const p = C.proposeChange(state, proposal); const c = C.confirmChange(state, p, ids); assert.equal(c.error, undefined, c.error && c.error.message); return { state: run(c.state), proposal: p, forked: c.forked }; }
const claim = (state, prefix) => C.currentResults(state).claims.find((c) => c.claim_ref.finding_id.startsWith(prefix)).claim_ref;

// A House 028 case with three selections, one response, and every kind of staff work.
function worked() {
  let s = run(C.createState(RUNTIME, ids));
  ["stat:house028:population_65_plus", "stat:house028:poverty_rate_65_plus", "cmp:house028"].forEach((p) => { s = ok(C.toggleClaim(s, claim(s, p), true)); });
  s = ok(C.confirmChange(s, C.chooseAction(s, C.availableActions(s)[0]).proposal, ids));
  s = ok(C.setStaffText(s, "title", "PRIVATE-TITLE route check"));
  s = ok(C.setStaffText(s, "note", "PRIVATE-NOTE <img src=x onerror=alert(1)>"));
  s = ok(C.setStaffText(s, "next_steps", "PRIVATE-NEXT call the office"));
  s = ok(C.setFindingNote(s, claim(s, "stat:house028:population_65_plus").semantic_hash, "PRIVATE-FNOTE on an unchanged fact"));
  s = ok(C.setFindingNote(s, claim(s, "cmp:house028").semantic_hash, "PRIVATE-CNOTE on the comparison"));
  s = ok(C.setChecklist(s, "agency_route", { owner_role: "PRIVATE-ROLE", due_date: "2026-11-20", completed: true }));
  s = ok(C.setChecklist(s, "custom1", { text: "PRIVATE-CUSTOM item" }));
  s = ok(C.setTracking(s, { label: "PRIVATE-TRACK sessions", baseline: 3, as_of: "2026-11-01" }));
  return s;
}
const PRIVATE_MARKS = ["PRIVATE-TITLE", "PRIVATE-NOTE", "PRIVATE-NEXT", "PRIVATE-FNOTE", "PRIVATE-CNOTE", "PRIVATE-ROLE", "PRIVATE-CUSTOM", "PRIVATE-TRACK", "2026-11-20", "2026-11-01"];

test("district change opens a new branch, carries no fact or staff work, and leaves the original intact", () => {
  const s0 = worked(), origin = clone(C.active(s0));
  const { state: s, proposal, forked } = change(s0, { plan: C.setContext(s0.draft, { district: { chamber: "house", code: "013" } }).plan });
  assert.deepEqual(proposal.kinds, ["district"]);
  assert.ok(forked && proposal.clears_selections);
  assert.deepEqual(C.branchOf(s, origin.branch_id), origin, "original branch must be byte-for-byte preserved");
  const b = C.active(s);
  assert.equal(b.plan.district.code, "013");
  assert.deepEqual([b.selected_claim_refs, b.selected_action_ref, b.staff_edits, b.checklist_edits, b.tracking], [[], null, {}, [], null]);
  assert.equal(b.review_state, "staff_review_required");
  assert.equal(C.pendingReview(s).length, 8, "all eight staff entries wait for review");
  assert.ok(!JSON.stringify(C.currentResults(s).claims).includes("house028"), "no House 028 fact in the new results");
  // The finding notes cannot be copied: their claims do not exist in this district.
  assert.equal(C.copyParked(s, "finding_note:" + origin.selected_claim_refs[0].semantic_hash).error.code, "not_applicable");
  // A clean brief is still possible; staff content is not sent.
  let t = ok(C.toggleClaim(s, claim(s, "stat:house013"), true));
  const clean = C.beginBrief(t, { clean: true }, ids);
  assert.deepEqual([clean.request.staff_edits, clean.request.checklist_edits, clean.request.tracking, clean.request.edits_reviewed_for], [{}, [], null, null]);
  assert.ok(!PRIVATE_MARKS.some((m) => JSON.stringify(clean.request).includes(m)));
});

test("issue change clears selections and the response; the old case stays restorable", () => {
  const s0 = worked();
  const { state: s, proposal } = change(s0, { plan: C.setContext(s0.draft, { issue_id: "custom" }).plan });
  assert.deepEqual(proposal.kinds, ["issue"]);
  assert.equal(C.active(s).recipe_version, "custom/1");
  assert.equal(C.active(s).selected_claim_refs.length, 0);
  assert.equal(C.active(s).selected_action_ref, null);
  assert.equal(s.case.branches.length, 2);
  // An identical fact may be reselected explicitly, by its current identity.
  ok(C.toggleClaim(s, claim(s, "stat:house028:population_65_plus"), true));
});

test("comparator change retires the changed comparison, keeps exact independent facts, and parks all staff work", () => {
  const s0 = worked(), o = C.active(s0);
  const { state: s, proposal } = change(s0, { plan: C.rescopeStep(s0.draft, "s2", { metric_ids: ["poverty_rate_65_plus"], comparison_geography: "HI-COUNTY-009-2024" }).plan });
  assert.deepEqual(proposal.kinds, ["comparator"]);
  const b = C.active(s);
  assert.deepEqual(b.selected_claim_refs.map((r) => r.finding_id), ["stat:house028:population_65_plus", "stat:house028:poverty_rate_65_plus"]);
  assert.equal(s.retired[b.branch_id].length, 1);
  assert.match(s.retired[b.branch_id][0].claim_ref.finding_id, /HI-STATE-2024$/);
  assert.equal(C.actionKey(b.selected_action_ref), C.actionKey(o.selected_action_ref), "state-referenced response keeps its exact identity");
  // Notes on unchanged facts are parked too, not silently active.
  assert.deepEqual(b.staff_edits, {});
  assert.deepEqual(b.checklist_edits, []);
  assert.equal(C.activeStaff(s).empty, true);
  const keep = "finding_note:" + b.selected_claim_refs[0].semantic_hash, gone = "finding_note:" + s.retired[b.branch_id][0].claim_ref.semantic_hash;
  assert.equal(C.copyParked(s, gone).error.code, "not_applicable", "a note on the retired comparison cannot be re-attached");
  assert.equal(C.markReviewed(s).error.code, "staff_review_required");
  let t = ok(C.copyParked(s, keep));
  assert.equal(C.active(t).staff_edits.finding_notes[b.selected_claim_refs[0].semantic_hash], "PRIVATE-FNOTE on an unchanged fact");
  assert.deepEqual(t.copied[b.branch_id][0], { key: keep, origin_branch_id: o.branch_id, origin_revision: o.last_ready_revision, scope_kinds: ["comparator"], completion_copied: false });
  // Same response identity: a done mark may be copied only with an explicit choice.
  assert.equal(C.copyParked(t, "checklist:agency_route").completion_copied, false);
  const withDone = C.copyParked(t, "checklist:agency_route", { include_completion: true });
  assert.equal(withDone.completion_copied, true);
  C.pendingReview(withDone.state).forEach((i) => { t = ok(C.leaveParked(t, i.key)); });
});

test("program change clears the response and a new agency never inherits a completed call", () => {
  const s0 = worked();
  let plan = C.removeStep(C.removeStep(s0.draft, "s3").plan, "s4").plan;
  plan = C.addStep(plan, "outreach_lead", { program_id: "snap_hi" }).plan;
  const { state: s0b, proposal } = change(s0, { plan });
  assert.deepEqual(proposal.kinds, ["program"]);
  assert.equal(C.active(s0b).selected_action_ref, null, "old response is cleared, not relabeled");
  const act = C.chooseAction(s0b, C.availableActions(s0b)[0]);
  assert.equal(act.proposal.fork, false, "no staff content yet in this branch");
  const s = ok(C.confirmChange(s0b, act.proposal, ids));
  assert.equal(C.active(s).selected_action_ref.action_id, "snap_verify/1");
  const copied = C.copyParked(s, "checklist:agency_route", { include_completion: true });
  assert.equal(copied.completion_copied, false);
  const item = C.active(copied.state).checklist_edits.find((c) => c.item_id === "agency_route");
  assert.deepEqual(item, { item_id: "agency_route", owner_role: "PRIVATE-ROLE", due_date: "2026-11-20" });
});

test("changing the selected response with staff work parks everything in a new branch", () => {
  const s0 = worked();
  const none = C.chooseAction(s0, null);
  assert.ok(none.proposal.fork && none.proposal.kinds.includes("response") && none.proposal.parked.length === 8);
  const c = ok(C.confirmChange(s0, none.proposal, ids));
  assert.equal(C.active(c).selected_action_ref, null);
  assert.equal(C.hasStaffContent(C.active(c)), false);
  assert.equal(C.hasStaffContent(C.branchOf(c, s0.case.active_branch_id)), true);
  assert.equal(C.chooseAction(s0, { action_id: "hcv_verify/1", semantic_hash: sha("not offered") }).error.code, "stale_ref");
});

test("step edits: reorder is not material; remove and re-scope are; hypothesis basis cannot be subset", () => {
  const s0 = worked(), before = clone(C.active(s0));
  const moved = C.moveStep(s0.draft, "s3", -1).plan;
  const p = C.proposeChange(s0, { plan: moved });
  assert.deepEqual([p.material, p.reorder_only, p.fork], [false, true, false]);
  const s = run(ok(C.confirmChange(s0, p, ids)));
  assert.equal(s.case.branches.length, 1);
  assert.deepEqual(C.active(s).staff_edits, before.staff_edits);
  assert.deepEqual(C.active(s).selected_claim_refs, before.selected_claim_refs);
  // The earlier review was for another revision and plan; it does not silently cover this one.
  assert.equal(C.reviewCurrent(s), false);
  assert.equal(C.beginBrief(s, {}, ids).error.code, "staff_review_required");
  assert.deepEqual(C.proposeChange(s0, { plan: C.removeStep(s0.draft, "s2").plan }).kinds, ["step_scope"]);
  const narrowed = C.proposeChange(s0, { plan: C.rescopeStep(s0.draft, "s1", { metric_ids: ["population_65_plus"] }).plan });
  assert.ok(narrowed.material && narrowed.fork);
  const after = change(s0, { plan: narrowed.plan }).state;
  assert.deepEqual(C.active(after).selected_claim_refs.map((r) => r.finding_id).sort(), ["cmp:house028:poverty_rate_65_plus:HI-STATE-2024", "stat:house028:population_65_plus", "stat:house028:poverty_rate_65_plus"].sort(), "poverty stays only because the comparison step still returns that exact claim");
  assert.equal(C.rescopeStep(s0.draft, "s4", { program_id: "kupuna_care_hi", metric_ids: ["population_65_plus"] }).error.code, "reviewed_basis_required");
  assert.equal(C.rescopeStep(s0.draft, "s4", { program_id: "kupuna_care_hi", comparison_geography: "HI-COUNTY-009-2024" }).error.code, "reviewed_basis_required");
  assert.equal(C.addStep(s0.draft, "compare", { metric_ids: ["poverty_rate_65_plus"], comparison_geography: "HI-HOUSE-028-2024" }).error.code, "self_comparison");
  assert.equal(C.addStep(s0.draft, "rank_by_need", {}).error.code, "unsupported_step");
  let full = s0.draft;
  for (let i = 0; i < 4; i += 1) full = C.addStep(full, "profile", { metric_ids: null }).plan;
  assert.equal(full.steps.length, 8);
  assert.equal(new Set(full.steps.map((x) => x.step_id)).size, 8);
  assert.equal(C.addStep(full, "profile", { metric_ids: null }).error.code, "plan_full");
  assert.equal(C.setContext(C.rescopeStep(s0.draft, "s2", { metric_ids: ["poverty_rate_65_plus"], comparison_geography: "HI-HOUSE-013-2024" }).plan, { district: { chamber: "house", code: "013" } }).clarification.code, "self_comparison");
});

test("retention needs the server's review and an exact identity in the results, not a matching number or ID", () => {
  const s0 = worked(), b = C.beginRun(s0, ids), base = reply(b.request);
  const target = b.request.selected_claim_refs[0];
  // Same finding ID and text, different semantic identity; the review still (wrongly) says retained.
  const forged = clone(base);
  forged.claims.find((c) => c.claim_ref.finding_id === target.finding_id).claim_ref.semantic_hash = sha("other binding");
  let r = C.applyResponse(b.state, forged);
  assert.ok(!C.active(r.state).selected_claim_refs.some((x) => x.finding_id === target.finding_id));
  assert.equal(r.retired.length, 1);
  assert.ok(C.pendingReview(r.state).some((i) => i.key === "finding_note:" + target.semantic_hash), "its note is parked as an orphan, not deleted or re-keyed");
  // A missing review entry fails closed, and other states are never treated as retained.
  r = C.applyResponse(b.state, Object.assign(clone(base), { selection_review: [] }));
  assert.equal(C.active(r.state).selected_claim_refs.length, 0);
  for (const state of ["foreign_context", "stale_snapshot", "version_mismatch", "retired"]) {
    const mixed = clone(base); mixed.selection_review[1].state = state;
    r = C.applyResponse(b.state, mixed);
    assert.deepEqual(r.retired.map((x) => x.state), [state]);
    assert.equal(C.active(r.state).selected_claim_refs.length, 2);
  }
  // A stale or foreign reference cannot be selected at all.
  assert.equal(C.toggleClaim(s0, { snapshot_id: RUNTIME.snapshot_id, finding_id: "stat:house013:population_65_plus", semantic_hash: sha("x") }, true).error.code, "stale_ref");
  assert.equal(C.setFindingNote(s0, sha("unselected"), "x").error.code, "stale_ref");
});

test("default download excludes every private field; staff work is opt-in and previewed", () => {
  let s = worked();
  const i = C.beginInterpret(s, "PRIVATE-PROMPT add snap", ids);
  s = C.applyResponse(i.state, reply(i.request, { status: "ok" })).state;
  const pub = C.exportCase(s), text = JSON.stringify(pub);
  for (const m of PRIVATE_MARKS.concat(["PRIVATE-PROMPT", "completed", "owner_role", "due_date"])) assert.ok(!text.includes(m), m + " leaked into the default download");
  assert.equal(pub.staff_work_included, false);
  for (const b of pub.branches) assert.deepEqual([b.staff_edits, b.checklist_edits, b.tracking, b.review_state], [{}, [], null, "clean"]);
  assert.equal(pub.branches[0].selected_claim_refs.length, 3);
  assert.deepEqual(Object.keys(pub.branches[0].selected_claim_refs[0]).sort(), ["finding_id", "semantic_hash", "snapshot_id"]);
  const priv = JSON.stringify(C.exportCase(s, { include_staff_work: true }));
  for (const m of PRIVATE_MARKS) assert.ok(priv.includes(m), m + " missing from the opt-in download");
  assert.ok(!priv.includes("PRIVATE-PROMPT"), "the typed prompt is never part of a case file");
  assert.ok(!JSON.stringify(s).includes("PRIVATE-PROMPT"), "the typed prompt is not retained in case state");
  const preview = C.staffExportPreview(s);
  assert.equal(preview.length, 1);
  assert.equal(preview[0].items.length, 8, "the preview lists every staff entry the file would contain");
  // Both exports re-open under the strict parser.
  assert.ok(C.parseCaseFile(text, RUNTIME).ok && C.parseCaseFile(priv, RUNTIME).ok);
});

test("real fixtures: public file has no staff work; import sends only typed plan and references", () => {
  const pub = C.parseCaseFile(PUBLIC_TEXT, RUNTIME), priv = C.parseCaseFile(PRIVATE_TEXT, RUNTIME);
  assert.ok(pub.ok && priv.ok);
  assert.equal(pub.preview.staff_items, 0);
  assert.equal(priv.preview.staff_items, 6);
  assert.ok(pub.preview.runtime_match);
  for (const m of [FIXTURE.staff_edits.title, FIXTURE.staff_edits.note, "Office manager", "2026-11-20", "referral sessions"]) assert.ok(!PUBLIC_TEXT.includes(m));
  const current = worked(), before = JSON.stringify(current.case);
  for (const accept of [false, true]) {
    const b = C.beginImport(current, priv, { accept_staff_work: accept }, ids);
    assert.deepEqual(Object.keys(b.request).sort(), ["branch_id", "case_id", "mode", "operation_version", "plan", "recipe_version", "request_id", "revision", "schema_version", "selected_action_ref", "selected_claim_refs", "snapshot_id"]);
    assert.ok(!JSON.stringify(b.request).includes("Office"), "staff text is never sent on import");
    assert.equal(JSON.stringify(b.state.case), before, "current case is untouched while the replay is pending");
    // Replay failure leaves the current case as it was.
    const failed = C.applyResponse(b.state, { status: "error", code: "invalid_request", message: "no", issues: [], retry_action: "correct_fields", model_calls: 0 });
    assert.equal(JSON.stringify(failed.state.case), before);
    // Real identities are unknown to the stand-in, so every saved selection is retired rather than trusted.
    const done = C.applyResponse(b.state, reply(b.request));
    assert.equal(done.outcome, "imported");
    assert.equal(done.state.case.case_id, priv.preview.case_id);
    assert.equal(C.active(done.state).selected_claim_refs.length, 0);
    assert.equal(done.retired.length, 4);
    assert.equal(C.hasStaffContent(C.active(done.state)) || C.pendingReview(done.state).length > 0, accept);
    if (accept) assert.equal(C.active(done.state).review_state, "staff_review_required", "imported staff text needs review before any brief");
  }
});

test("import bounds and strict schema; nothing in a file is trusted or merged", () => {
  const base = JSON.parse(PRIVATE_TEXT), current = worked();
  const bad = (mutate, code) => { const f = clone(base); mutate(f); const r = C.parseCaseFile(JSON.stringify(f), RUNTIME); assert.equal(r.ok, false); if (code) assert.equal(r.issues[0].code, code); return r; };
  assert.equal(C.parseCaseFile("{\"case_schema\":", RUNTIME).issues[0].code, "invalid_json");
  assert.equal(C.parseCaseFile("", RUNTIME).issues[0].code, "empty");
  assert.equal(C.parseCaseFile(JSON.stringify(Object.assign(clone(base), { pad: "x".repeat(262144) })), RUNTIME).issues[0].code, "too_large");
  // Multi-byte text counts in UTF-8 bytes, not characters.
  assert.equal(C.parseCaseFile("\"" + "ʻ".repeat(140000) + "\"", RUNTIME).issues[0].code, "too_large");
  let deep = "x"; for (let i = 0; i < 20; i += 1) deep = [deep];
  bad((f) => { f.extra = deep; }, "too_deep");
  bad((f) => { f.case_schema = "haic-case/2"; }, "unsupported_version");
  bad((f) => { f.summary_html = "<b>29.0%</b>"; }, "unknown_field");
  bad((f) => { f.branches[0].facts = [{ text: "29.0%" }]; }, "unknown_field");
  bad((f) => { f.branches[0].plan.formula = "a/b"; });
  bad((f) => { f.branches[0].plan.steps[0].subject = "house013"; });
  bad((f) => { f.branches[0].plan.steps[3].args.metric_ids = ["population_65_plus"]; });
  bad((f) => { f.branches[0].plan.steps.push(f.branches[0].plan.steps[0]); });
  bad((f) => { for (let i = 5; i < 11; i += 1) f.branches[0].plan.steps.push({ step_id: "s" + i, operation: "profile", args: { metric_ids: null } }); });
  bad((f) => { f.branches = [1, 2, 3, 4, 5].map((n) => Object.assign(clone(f.branches[0]), { branch_id: ids.uuid() })); });
  bad((f) => { f.branches[0].branch_id = f.branches[0].branch_id.toUpperCase(); });
  bad((f) => { f.branches[0].selected_claim_refs[0].semantic_hash = "sha256:abc"; });
  bad((f) => { f.branches[0].selected_claim_refs.push(f.branches[0].selected_claim_refs[0]); });
  bad((f) => { f.branches[0].selected_action_ref.action_id = "wic_verify/1"; });
  bad((f) => { f.branches[0].staff_edits.note = "n".repeat(401); });
  bad((f) => { f.branches[0].staff_edits.finding_notes = { [sha("not selected")]: "orphan" }; });
  bad((f) => { f.branches[0].checklist_edits[0].completed = "yes"; });
  bad((f) => { f.branches[0].checklist_edits[0].due_date = "11/20/2026"; });
  bad((f) => { f.branches[0].tracking.baseline = 1.5; });
  bad((f) => { f.branches[0].plan.district.code = "052"; });
  bad((f) => { f.active_branch_id = ids.uuid(); });
  const proto = C.parseCaseFile(PRIVATE_TEXT.replace("\"case_schema\"", "\"__proto__\":{\"polluted\":true},\"case_schema\""), RUNTIME);
  assert.equal(proto.ok, false);
  assert.equal({}.polluted, undefined);
  // Markup in staff text stays literal data; rendering must escape it (investigation.js uses text nodes).
  const marked = clone(base); marked.branches[0].staff_edits.note = "<script>alert(1)</script>";
  assert.equal(C.parseCaseFile(JSON.stringify(marked), RUNTIME).incoming.case.branches[0].staff_edits.note, "<script>alert(1)</script>");
  const ui = fs.readFileSync(path.join(__dirname, "../static/investigation.js"), "utf8");
  assert.deepEqual(ui.match(/\.innerHTML\s*=[^;]*;/g), [".innerHTML = brief.brief.html;"], "only the token-matched server brief may be inserted as markup");
  assert.ok(!/localStorage|sessionStorage|indexedDB|document\.cookie|location\.(hash|search)|history\.(push|replace)State/.test(ui + fs.readFileSync(path.join(__dirname, "../static/case_state.js"), "utf8")), "no storage or URL carries a case");
  // Another snapshot: nothing is dispatched, the current case is unchanged, and the file is only previewed as unverified.
  const other = clone(base); other.branches[0].snapshot_id = sha("another release");
  const parsed = C.parseCaseFile(JSON.stringify(other), RUNTIME);
  assert.ok(parsed.ok && parsed.preview.runtime_match === false);
  const refused = C.beginImport(current, parsed, {}, ids);
  assert.equal(refused.error.code, "snapshot_unavailable");
  assert.equal(refused.state, undefined);
});

test("late or mismatched replies never replace a newer context", () => {
  const s0 = worked();
  const a = C.beginRun(s0, ids), replyA = reply(a.request);
  const cancelled = C.cancelPending(a.state);
  assert.equal(C.applyResponse(cancelled, replyA).outcome, "discarded");
  const b = C.beginRun(cancelled, ids);
  assert.ok(b.request.revision > a.request.revision && b.request.request_id !== a.request.request_id);
  const late = C.applyResponse(b.state, replyA);
  assert.equal(late.outcome, "discarded");
  assert.equal(late.state, b.state, "state object is unchanged and the newer request is still pending");
  for (const k of C.TOKEN_KEYS) {
    const wrong = reply(b.request); wrong.tokens[k] = k === "revision" ? b.request.revision - 1 : k.endsWith("_id") && k !== "snapshot_id" ? ids.uuid() : "other";
    assert.equal(C.applyResponse(b.state, wrong).outcome, "discarded", k);
  }
  const extra = reply(b.request); extra.tokens.note = "x";
  assert.equal(C.applyResponse(b.state, extra).outcome, "discarded");
  const lateError = { status: "error", code: "invalid_request", message: "old", issues: [], retry_action: "x", model_calls: 0, tokens: replyA.tokens };
  assert.equal(C.applyResponse(b.state, lateError).outcome, "discarded");
  assert.equal(C.applyResponse(b.state, reply(b.request, { model_calls: 1 })).outcome, "error");
  const done = C.applyResponse(b.state, reply(b.request));
  assert.equal(done.outcome, "committed");
  assert.equal(C.currentResults(done.state).revision, b.request.revision);
  assert.equal(C.beginRun(b.state, ids).error.code, "busy");
  // A failed run keeps the last committed results under their own revision.
  const c = C.beginRun(done.state, ids);
  for (const kind of ["network", "session"]) {
    const f = C.applyTransportFailure(c.state, c.request.request_id, kind);
    assert.equal(f.error.code, kind === "network" ? "network_unavailable" : "session_restarted");
    assert.equal(C.currentResults(f.state).revision, b.request.revision);
    assert.deepEqual(C.active(f.state).staff_edits, C.active(s0).staff_edits);
    assert.equal(f.state.pending, null);
  }
  assert.equal(C.applyTransportFailure(c.state, a.request.request_id, "network").outcome, "discarded");
  // A run whose steps all failed is a result with per-step status, not a transport error.
  const allFailed = reply(c.request, { status: "unsupported" }); allFailed.steps.forEach((x) => { x.status = "unsupported"; x.claim_refs = []; }); allFailed.claims = [];
  assert.equal(C.applyResponse(c.state, allFailed).outcome, "committed");
});

test("a brief is printable only for the exact selections, staff content and revision it was made for", () => {
  let s = ok(C.markReviewed(worked()));
  assert.equal(C.printStatus(s).code, "no_brief");
  const b = C.beginBrief(s, {}, ids);
  assert.deepEqual(b.request.edits_reviewed_for, { branch_id: C.active(s).branch_id, revision: C.active(s).last_ready_revision, plan_hash: sha(C.planCanonical(C.active(s).plan)) });
  assert.equal(b.request.revision, C.active(s).last_ready_revision);
  assert.deepEqual(Object.keys(b.request.staff_edits.finding_notes).sort(), C.active(s).selected_claim_refs.filter((r) => !r.finding_id.includes("poverty_rate_65_plus") || r.finding_id.startsWith("cmp")).map((r) => r.semantic_hash).sort());
  s = C.applyResponse(b.state, reply(b.request)).state;
  assert.equal(C.printStatus(s).ok, true);
  const edited = ok(C.setStaffText(s, "note", "changed after the brief"));
  assert.equal(C.printStatus(edited).code, "brief_stale");
  assert.equal(C.beginBrief(edited, {}, ids).error.code, "staff_review_required");
  assert.equal(C.printStatus(ok(C.toggleClaim(s, C.active(s).selected_claim_refs[1], false))).code, "brief_stale");
  const drafted = Object.assign({}, s, { draft: C.removeStep(s.draft, "s2").plan });
  assert.equal(C.printStatus(drafted).code, "unapplied_changes");
  assert.equal(C.beginBrief(drafted, {}, ids).error.code, "unapplied_changes");
  assert.equal(C.printStatus(run(s)).code, "no_brief", "a new revision needs a new brief");
  const empty = run(C.createState(RUNTIME, ids));
  assert.equal(C.beginBrief(empty, {}, ids).error.code, "no_selection");
});

test("branch restore replays first and returns staff work only to its original context", () => {
  const s0 = worked(), h028 = s0.case.active_branch_id, original = clone(C.active(s0));
  let s = change(s0, { plan: C.setContext(s0.draft, { district: { chamber: "senate", code: "025" } }).plan }).state;
  const s025 = s.case.active_branch_id;
  s = ok(C.toggleClaim(s, claim(s, "stat:senate025"), true));
  s = ok(C.setStaffText(s, "title", "Senate 025 title"));
  const r = C.beginRestore(s, h028, ids);
  assert.equal(r.state.case.active_branch_id, s025, "nothing switches before the replay returns");
  assert.equal(r.request.branch_id, h028);
  assert.deepEqual(r.request.selected_claim_refs, original.selected_claim_refs);
  const stray = C.beginRun(C.cancelPending(r.state), ids);
  assert.equal(C.applyResponse(r.state, reply(stray.request)).outcome, "discarded");
  const done = C.applyResponse(r.state, reply(r.request));
  assert.equal(done.outcome, "restored");
  const b = C.active(done.state);
  assert.equal(b.branch_id, h028);
  assert.deepEqual([b.staff_edits, b.checklist_edits, b.tracking, b.selected_claim_refs], [original.staff_edits, original.checklist_edits, original.tracking, original.selected_claim_refs]);
  assert.equal(C.branchOf(done.state, s025).staff_edits.title, "Senate 025 title");
  assert.deepEqual(done.state.draft, b.plan);
  assert.equal(C.reviewCurrent(done.state), false, "restored staff content still needs an explicit review for the new revision");
  // A branch saved against another snapshot or version is kept but never replayed or printed here.
  for (const patch of [{ snapshot_id: sha("older evidence") }, { operation_version: "ia-core/0" }]) {
    const old = clone(done.state); Object.assign(C.branchOf(old, s025), patch);
    const blocked = C.beginRestore(old, s025, ids);
    assert.equal(blocked.error.code, "snapshot_unavailable");
    assert.equal(blocked.state.pending, null);
    assert.equal(C.branchOf(blocked.state, s025).review_state, "replay_blocked");
    assert.equal(C.branchOf(blocked.state, s025).staff_edits.title, "Senate 025 title");
    const activeOld = clone(old); activeOld.case.active_branch_id = s025;
    assert.equal(C.printStatus(activeOld).code, "replay_blocked");
    assert.equal(C.beginBrief(activeOld, { clean: true }, ids).error.code, "snapshot_unavailable");
  }
  // The server's own 409 also blocks the branch without touching its content.
  const run2 = C.beginRun(done.state, ids);
  const refused = C.applyResponse(run2.state, { status: "error", code: "snapshot_unavailable", message: "This case needs an evidence snapshot not admitted by this release.", issues: [], retry_action: "open_matching_release_or_keep_saved_case", model_calls: 0 }, { http_status: 409 });
  assert.equal(C.active(refused.state).review_state, "replay_blocked");
  assert.deepEqual(C.active(refused.state).staff_edits, original.staff_edits);
});

test("fifth branch is refused until one is removed after an explicit local save", () => {
  let s = worked();
  for (const code of ["013", "009", "001"]) {
    s = change(s, { plan: C.setContext(s.draft, { district: { chamber: "house", code } }).plan }).state;
    s = ok(C.toggleClaim(s, claim(s, "stat:house" + code), true));
  }
  assert.equal(s.case.branches.length, 4);
  const p = C.proposeChange(s, { plan: C.setContext(s.draft, { district: { chamber: "senate", code: "025" } }).plan });
  assert.equal(p.branch_limit, true);
  assert.equal(C.confirmChange(s, p, ids).error.code, "branch_limit");
  const first = s.case.branches[0].branch_id;
  assert.equal(C.removeBranch(s, first, { saved_locally: false }).error.code, "save_required");
  assert.equal(C.removeBranch(s, s.case.active_branch_id, { saved_locally: true }).error.code, "active_branch");
  const removed = ok(C.removeBranch(s, first, { saved_locally: true }));
  assert.equal(removed.case.branches.length, 3);
  assert.equal(C.confirmChange(removed, C.proposeChange(removed, { plan: p.plan }), ids).forked, true);
  // The earlier preview is re-derived against the current case, so it is no longer refused.
  assert.equal(C.confirmChange(removed, p, ids).error, undefined);
});

test("overflow keeps every edit and offers exact leave-out choices instead of cropping", () => {
  let s = worked();
  s = ok(C.setStaffText(s, "note", "N".repeat(400)));
  s = ok(C.markReviewed(s));
  const b = C.beginBrief(s, {}, ids);
  const tokens = reply(b.request).tokens;
  const over = C.applyResponse(b.state, { status: "error", code: "brief_overflow", message: "This brief is too long for one printed page.", tokens, model_calls: 0, retry_action: "shorten_brief",
    issues: [{ path: "staff_edits", code: "brief_overflow", message: "too long" }, { path: "brief", code: "brief_overflow", message: "print_units=7421; print_budget=7000" }] }, { http_status: 409 });
  assert.equal(over.error.code, "brief_overflow");
  assert.deepEqual([over.error.detail.estimated_units, over.error.detail.budget_units], [7421, 7000]);
  s = over.state;
  assert.equal(C.active(s).staff_edits.note.length, 400);
  assert.equal(C.active(s).selected_claim_refs.length, 3);
  assert.equal(C.active(s).review_state, "clean", "overflow is not a replay block");
  const choices = C.shorteningChoices(s);
  assert.deepEqual(choices.map((c) => c.kind).sort().filter((k, i, a) => a.indexOf(k) === i), ["deselect_finding", "leave_out_staff"]);
  assert.equal(choices.find((c) => c.key === "note").size, 400);
  s = ok(C.setExclusion(s, "note", true));
  assert.equal(C.active(s).staff_edits.note.length, 400, "left-out text stays in the editor");
  assert.equal(C.beginBrief(s, {}, ids).error.code, "staff_review_required", "changed brief content needs a fresh review");
  s = ok(C.markReviewed(s));
  const retry = C.beginBrief(s, {}, ids);
  assert.equal("note" in retry.request.staff_edits, false);
  assert.equal(retry.request.staff_edits.title, "PRIVATE-TITLE route check");
  assert.equal(retry.request.staff_edits.next_steps, "PRIVATE-NEXT call the office", "other fields are sent whole, never truncated");
  s = ok(C.setExclusion(C.cancelPending(retry.state), "note", false));
  assert.equal(C.activeStaff(s).staff_edits.note.length, 400);
  // Over-limit entries are refused whole rather than cut.
  assert.equal(C.setStaffText(s, "title", "t".repeat(91)).error.code, "too_long");
  assert.equal(C.setStaffText(s, "title", "ʻ".repeat(90)).error, undefined);
  assert.equal(C.setChecklist(s, "custom2", { text: "c".repeat(121) }).error.code, "invalid_field");
  assert.equal(C.setChecklist(s, "custom4", { text: "x" }).error.code, "invalid_field");
  assert.equal(C.setTracking(s, { label: "x", baseline: -1, as_of: null }).error.code, "invalid_field");
  let full = s;
  C.currentResults(s).claims.forEach((c) => { const r = C.toggleClaim(full, c.claim_ref, true); if (!r.error) full = r.state; });
  assert.ok(C.active(full).selected_claim_refs.length <= 8);
});

test("requests carry exactly the contract fields for each mode", () => {
  const s = worked(), common = ["branch_id", "case_id", "mode", "operation_version", "plan", "recipe_version", "request_id", "revision", "schema_version", "snapshot_id"];
  const i = C.beginInterpret(s, "add snap", ids);
  assert.deepEqual(Object.keys(i.request).sort(), common.concat(["utterance"]).sort());
  assert.ok(!PRIVATE_MARKS.some((m) => JSON.stringify(i.request).includes(m)));
  const r = C.beginRun(s, ids);
  assert.deepEqual(Object.keys(r.request).sort(), common.concat(["selected_action_ref", "selected_claim_refs"]).sort());
  assert.ok(!PRIVATE_MARKS.some((m) => JSON.stringify(r.request).includes(m)), "no staff text in a run request");
  assert.match(r.request.request_id, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
  assert.equal(r.request.recipe_version, r.request.plan.issue_id + "/1");
  const b = C.beginBrief(ok(C.markReviewed(s)), {}, ids);
  assert.deepEqual(Object.keys(b.request).sort(), common.concat(["checklist_edits", "edits_reviewed_for", "selected_action_ref", "selected_claim_refs", "staff_edits", "tracking"]).sort());
  assert.equal(C.beginInterpret(s, "   ", ids).error.code, "empty");
  assert.equal(C.beginInterpret(s, "x".repeat(501), ids).error.code, "too_long");
  // Plan identity text matches the server's canonical JSON for the contract's default recipe.
  // (Value computed by the candidate's own claim_binding.plan_hash for that recipe.)
  assert.equal(sha(C.planCanonical(C.defaultPlan())), "sha256:8a7cf535614fcfc3671c440f0fc135be1996b5d95cec9a2bc075e0c7c503cd16");
  // NFC normalization and key order follow the server rule; array order is kept.
  assert.equal(C.planCanonical({ b: "u\u0304", a: [2, 1], "\u00e9": null }), "{\"a\":[2,1],\"b\":\"\u016b\",\"\u00e9\":null}");
  assert.equal(C.planCanonical({ "e\u0301": 1 }), C.planCanonical({ "\u00e9": 1 }));
  // The envelope has no plan-hash field. A value placed in a reply is never used as the review identity.
  const fresh = C.beginRun(s, ids), forged = reply(fresh.request, { plan_hash: sha("forged") });
  forged.interpretation.plan_hash = sha("forged");
  const nohash = C.applyResponse(fresh.state, forged).state;
  assert.equal(C.currentResults(nohash).plan_hash, null);
  assert.equal(C.applyResponse(fresh.state, forged, { plan_hash: "sha256:short" }).state.results[s.case.active_branch_id].plan_hash, null);
  // Without a plan identity staff content cannot be attached, but a clean brief still can.
  assert.equal(C.markReviewed(nohash).error.code, "plan_hash_unavailable");
  assert.equal(C.beginBrief(nohash, {}, ids).error.code, "staff_review_required");
  assert.equal(C.beginBrief(nohash, { clean: true }, ids).error, undefined);
});

test("interpretation highlights use Unicode character offsets and never apply on their own", () => {
  const text = "😀 use house 13 for kūpuna";
  const segs = C.interpretationSegments(text, [{ field: "district", value: {}, span: [2, 14] }, { field: "bad", span: [40, 50] }, { field: "overlap", span: [5, 9] }]);
  assert.deepEqual(segs, [{ text: "😀 ", field: null }, { text: "use house 13", field: "district" }, { text: " for kūpuna", field: null }]);
  const s = worked(), i = C.beginInterpret(s, "use house 13", ids);
  const plan = C.setContext(s.draft, { district: { chamber: "house", code: "013" } }).plan;
  const done = C.applyResponse(i.state, reply(i.request, { normalized_plan: plan, steps: [], claims: [], responses: [] }));
  assert.equal(done.outcome, "interpreted");
  assert.equal(done.interpretation.proposed_plan.district.code, "013");
  assert.equal(C.active(done.state).plan.district.code, "028", "nothing changes until Apply");
  assert.deepEqual(done.state.draft, s.draft);
  const unclear = C.applyResponse(i.state, reply(i.request, { status: "clarification", normalized_plan: plan }));
  assert.equal(unclear.interpretation.proposed_plan, null);
  const invalid = C.applyResponse(i.state, reply(i.request, { normalized_plan: Object.assign(clone(plan), { extra: 1 }) }));
  assert.equal(invalid.interpretation.proposed_plan, null);
});

test("plan edits made while a run is pending survive its reply", () => {
  const s0 = worked();
  const b = C.beginRun(s0, ids);
  // Staff keep editing after the request left: another district and one step fewer.
  const newer = C.removeStep(C.setContext(b.state.draft, { district: { chamber: "house", code: "013" } }).plan, "s2").plan;
  const editing = Object.assign({}, b.state, { draft: newer });
  const r = C.applyResponse(editing, reply(b.request), meta(b.request));
  assert.equal(r.outcome, "committed");
  assert.equal(r.draft_kept, true);
  assert.deepEqual(r.state.draft, newer, "the newer draft is not reset to the replied plan");
  assert.equal(C.active(r.state).plan.district.code, "028", "results and committed plan stay with the context that was run");
  assert.equal(C.currentResults(r.state).plan.district.code, "028");
  assert.equal(C.currentResults(r.state).revision, b.request.revision);
  assert.deepEqual(C.active(r.state).staff_edits, C.active(s0).staff_edits);
  assert.equal(C.printStatus(r.state).code, "no_brief");
  assert.equal(C.beginBrief(r.state, { clean: true }, ids).error.code, "unapplied_changes", "no brief while the draft differs");
  // The kept draft is still a material change that goes through the preview and a new branch.
  const p = C.proposeChange(r.state, { plan: r.state.draft });
  assert.deepEqual(p.kinds.sort(), ["district", "step_scope"]);
  const after = change(r.state, { plan: r.state.draft });
  assert.ok(after.forked);
  assert.equal(C.active(after.state).plan.district.code, "013");
  assert.equal(C.active(after.state).plan.steps.length, 3);
  // Without newer edits the draft follows the server's normalized plan as before.
  const plain = C.applyResponse(b.state, reply(b.request), meta(b.request));
  assert.equal(plain.draft_kept, false);
  assert.deepEqual(plain.state.draft, C.active(plain.state).plan);
  // Restoring or opening a file would replace the draft, so both refuse while edits are unapplied.
  const two = change(s0, { plan: C.setContext(s0.draft, { district: { chamber: "house", code: "009" } }).plan }).state;
  const dirty = Object.assign({}, two, { draft: C.removeStep(two.draft, "s1").plan });
  const refused = C.beginRestore(dirty, s0.case.active_branch_id, ids);
  assert.equal(refused.error.code, "unapplied_changes");
  assert.equal(refused.state, undefined);
  assert.equal(C.beginImport(dirty, C.parseCaseFile(PUBLIC_TEXT, RUNTIME), {}, ids).error.code, "unapplied_changes");
  assert.equal(C.beginRestore(two, s0.case.active_branch_id, ids).error, undefined);
});

test("dates must be real calendar dates, in edits and in imported files", () => {
  const s = worked();
  for (const d of ["2026-02-31", "2026-04-31", "2027-02-29", "2026-13-01", "2026-00-10", "26-11-20", "2026-11-20T00:00"]) {
    assert.equal(C.setChecklist(s, "next_check", { due_date: d }).error.code, "invalid_field", d);
    assert.equal(C.setTracking(s, { label: "x", baseline: null, as_of: d }).error.code, "invalid_field", d);
  }
  assert.equal(C.setChecklist(s, "next_check", { due_date: "2028-02-29" }).error, undefined, "leap day is real");
  assert.equal(C.setTracking(s, { label: "x", baseline: 0, as_of: "2026-12-31" }).error, undefined);
  const file = JSON.parse(PRIVATE_TEXT);
  file.branches[0].checklist_edits[0].due_date = "2026-02-31";
  const before = JSON.stringify(s.case), parsed = C.parseCaseFile(JSON.stringify(file), RUNTIME);
  assert.equal(parsed.ok, false);
  assert.match(parsed.issues[0].path, /checklist_edits$/);
  assert.equal(JSON.stringify(s.case), before);
  file.branches[0].checklist_edits[0].due_date = "2026-11-20"; file.branches[0].tracking.as_of = "2026-06-31";
  assert.equal(C.parseCaseFile(JSON.stringify(file), RUNTIME).ok, false);
});

test("findings ticked or unticked while a run is pending are not silently lost when its reply commits", () => {
  const s0 = worked(), sentRefs = clone(C.active(s0).selected_claim_refs);
  const b = C.beginRun(s0, ids);
  // While the request is out: tick two more findings, untick one that was sent, and add a note to a new one.
  const female = claim(b.state, "stat:house028:female_householder"), male = claim(b.state, "stat:house028:male_householder");
  let live = ok(C.toggleClaim(b.state, female, true));
  live = ok(C.toggleClaim(live, male, true));
  live = ok(C.toggleClaim(live, sentRefs[1], false));
  live = ok(C.setFindingNote(live, female.semantic_hash, "added while pending"));
  assert.deepEqual(b.request.selected_claim_refs, sentRefs, "the request carried only what was selected when it left");
  // The real matching reply reviews only what was sent.
  const matching = reply(b.request);
  assert.equal(matching.selection_review.length, 3);
  const r = C.applyResponse(live, matching, meta(b.request));
  assert.equal(r.outcome, "committed");
  assert.deepEqual(C.active(r.state).selected_claim_refs.map((x) => x.finding_id), [sentRefs[0].finding_id, sentRefs[2].finding_id, female.finding_id, male.finding_id], "newer ticks kept in order; the unticked finding stays out");
  assert.deepEqual(r.retired, []);
  assert.equal(C.active(r.state).staff_edits.finding_notes[female.semantic_hash], "added while pending");
  assert.equal(C.currentResults(r.state).revision, b.request.revision);
  // The next request submits the kept selections for the server's own review.
  const next = C.beginRun(r.state, ids);
  assert.equal(next.request.selected_claim_refs.length, 4);
  assert.ok(reply(next.request).selection_review.every((x) => x.state === "retained"));
  // A newer tick is kept only for an exact identity in these results: same ID with another identity is retired, its note parked.
  const changed = reply(b.request);
  changed.claims.find((c) => c.claim_ref.finding_id === female.finding_id).claim_ref.semantic_hash = sha("rebound");
  const dropped = C.applyResponse(live, changed, meta(b.request));
  assert.deepEqual(dropped.retired.map((x) => [x.claim_ref.finding_id, x.reason_code]), [[female.finding_id, "not_in_current_results"]]);
  assert.ok(C.pendingReview(dropped.state).some((i) => i.key === "finding_note:" + female.semantic_hash));
  assert.equal(C.active(dropped.state).selected_claim_refs.length, 3);
  // Sent selections still need the server's "retained": identity presence alone is not enough for them.
  const unreviewed = C.applyResponse(live, Object.assign(reply(b.request), { selection_review: [] }), meta(b.request));
  assert.deepEqual(C.active(unreviewed.state).selected_claim_refs.map((x) => x.finding_id), [female.finding_id, male.finding_id]);
  // A server verdict on a newer tick, if one ever arrives, is still honored.
  const judged = reply(b.request); judged.selection_review.push({ claim_ref: female, state: "foreign_context", reason_code: "foreign_primary_district" });
  assert.ok(!C.active(C.applyResponse(live, judged, meta(b.request)).state).selected_claim_refs.some((x) => x.finding_id === female.finding_id));
  // A response chosen while pending is judged by its own identity, not by the review of the response that was sent.
  const none = run(C.createState(RUNTIME, ids));
  const pb = C.beginRun(none, ids);
  const picked = ok(C.confirmChange(pb.state, C.chooseAction(pb.state, C.availableActions(pb.state)[0]).proposal, ids));
  const after = C.applyResponse(picked, reply(pb.request), meta(pb.request));
  assert.equal(after.outcome, "committed");
  assert.equal(C.active(after.state).selected_action_ref.action_id, "kupuna_verify/1");
  // Restore keeps its strict rule: every saved selection needs the server's review.
  const two = change(s0, { plan: C.setContext(s0.draft, { district: { chamber: "house", code: "009" } }).plan }).state;
  const rs = C.beginRestore(two, s0.case.active_branch_id, ids);
  const strict = C.applyResponse(rs.state, Object.assign(reply(rs.request), { selection_review: [] }), meta(rs.request));
  assert.equal(C.active(strict.state).selected_claim_refs.length, 0);
});

test("a late reply to a cancelled request cannot end or alter the newer pending request", () => {
  const s0 = worked();
  const first = C.beginRun(s0, ids);
  const second = C.beginRun(C.cancelPending(first.state), ids);
  const editing = Object.assign({}, second.state, { draft: C.removeStep(second.state.draft, "s2").plan });
  const origin = { http_status: 500, request_id: first.request.request_id };
  const late = [
    ["tokenless safe 500", { status: "error", code: "internal_error", message: "Unexpected error.", issues: [], retry_action: "retry", model_calls: 0 }, origin],
    ["unreadable 502 body", null, { http_status: 502, request_id: first.request.request_id }],
    ["valid reply to the old request", reply(first.request), Object.assign(meta(first.request), { request_id: first.request.request_id })],
    ["old reply claiming model calls", reply(first.request, { model_calls: 1 }), origin],
    ["old brief_overflow with matching-looking shape", { status: "error", code: "brief_overflow", message: "x", issues: [], retry_action: "shorten_brief", model_calls: 0 }, origin],
  ];
  for (const [name, body, m] of late) {
    const r = C.applyResponse(editing, body, m);
    assert.equal(r.outcome, "discarded", name);
    assert.equal(r.state, editing, name + ": state object untouched");
    assert.equal(r.state.pending.tokens.request_id, second.request.request_id, name + ": request 2 still pending");
    assert.equal(r.state.last_error, null, name);
    assert.equal(r.state.draft.steps.length, 3, name + ": newer draft kept");
  }
  // Request 2's own reply still commits, with the draft edit preserved.
  const own = Object.assign(meta(second.request), { request_id: second.request.request_id });
  const done = C.applyResponse(editing, reply(second.request), own);
  assert.equal(done.outcome, "committed");
  assert.equal(done.draft_kept, true);
  // Request 2's own errors still end it and stay recoverable.
  for (const [body, status, code] of [[{ status: "error", code: "internal_error", message: "Unexpected error.", issues: [], retry_action: "retry", model_calls: 0 }, 500, "internal_error"], [null, 502, "unreadable_response"]]) {
    const f = C.applyResponse(editing, body, { http_status: status, request_id: second.request.request_id });
    assert.equal(f.outcome, "error");
    assert.equal(f.error.code, code);
    assert.equal(f.state.pending, null);
    assert.equal(f.state.draft.steps.length, 3);
    assert.deepEqual(C.active(f.state).staff_edits, C.active(s0).staff_edits);
    assert.equal(C.currentResults(f.state).revision, C.active(s0).last_ready_revision, "last committed results remain");
    assert.equal(C.beginRun(f.state, ids).error, undefined, "retry starts a fresh request");
  }
  // The browser passes the originating request ID on every reply.
  const ui = fs.readFileSync(path.join(__dirname, "../static/investigation.js"), "utf8");
  assert.equal((ui.match(/C\.applyResponse\(/g) || []).length, 1);
  assert.match(ui, /C\.applyResponse\(state, body, \{[^}]*request_id: request\.request_id \}\)/);
});
