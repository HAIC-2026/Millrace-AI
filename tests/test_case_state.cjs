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

// Event regression: the literal typed-request "Put in draft plan" control only installs the
// proposal as the draft. Running stays behind the separate Apply plan / Run again action. The real UI
// functions are evaluated with an inert renderer and a recording send stub (no network).
test("a literal proposal changes only the draft; a separate plan action makes the single run request", () => {
  const vm = require("node:vm");
  const ui = fs.readFileSync(path.join(__dirname, "../static/investigation.js"), "utf8");
  const part = (a, b) => { const i = ui.indexOf(a); assert.ok(i >= 0, a); return ui.slice(i, ui.indexOf(b, i)); };
  const code = part("  function runActive() {", "  // Optional language") + part("  function applyPlan() {", "  function defaultArgs") +
    part("  function renderInterpretation() {", "  function renderSteps");
  function harness(proposed) {
    const buttons = [], requests = [];
    const ctx = { C, ids, state: run(C.createState(RUNTIME, ids)), notice: "", preview: null,
      interp: { status: "ok", utterance: "use house 13", matched_fields: [], inherited_fields: [], choices: [], reason: null, proposed_plan: null },
      h: (...a) => a, $: () => ({ focus() {} }), fill() {}, btn: (label, fn) => { buttons.push({ label, fn }); return {}; },
      fieldLabel: (x) => x, valueText: (f, v) => String(v), plain: (x) => x, clearAlert() {}, alertUser(m) { throw new Error(m); },
      render() {}, syncMap() {}, holdFocus() {}, send: (r) => requests.push(r) };
    ctx.interp.proposed_plan = proposed(ctx.state);
    vm.createContext(ctx); vm.runInContext(code, ctx); vm.runInContext("renderInterpretation()", ctx);
    return { ctx, buttons, requests };
  }
  // 1. Proposal equal to the confirmed plan (no-op).
  let t = harness((s) => clone(C.active(s).plan));
  t.buttons.find((b) => /^Put in draft plan$/.test(b.label)).fn();
  assert.equal(t.requests.length, 0, "no run on the literal action");
  assert.match(t.ctx.notice, /nothing has run/i); assert.doesNotMatch(t.ctx.notice, /Apply plan/, "unchanged proposal: the shown control is Run again");
  assert.equal(t.ctx.state.pending, null);
  vm.runInContext("applyPlan()", t.ctx);   // explicit Run again
  assert.equal(t.requests.length, 1); assert.equal(t.requests[0].mode, "run");
  // 2. Changed proposal (another district) with fewer than four contexts.
  t = harness((s) => { const p = clone(C.active(s).plan); p.district = Object.assign({}, p.district, { code: "013" }); return p; });
  assert.ok(t.ctx.state.case.branches.length < 4);
  t.buttons.find((b) => /^Put in draft plan$/.test(b.label)).fn();
  assert.equal(t.requests.length, 0, "no run on the literal action");
  assert.equal(t.ctx.state.draft.district.code, "013");
  assert.match(t.ctx.notice, /Nothing has run/); assert.match(t.ctx.notice, /choose Apply plan/);
  assert.equal(C.active(t.ctx.state).plan.district.code, "028", "confirmed results unchanged");
  vm.runInContext("applyPlan()", t.ctx);   // explicit Apply plan opens the context review only
  assert.equal(t.requests.length, 0);
  assert.ok(t.ctx.preview && t.ctx.preview.fork);
  vm.runInContext("commit(preview)", t.ctx); // explicit Apply change and run
  assert.equal(t.requests.length, 1); assert.equal(t.requests[0].mode, "run"); assert.equal(t.requests[0].plan.district.code, "013");
});


// Presentation regression (R4): a failed attempt to create a NEW brief is attributed to that attempt, and a
// previous brief that still matches the context is named as the previous one and stays printable. With no
// valid previous brief the existing messages and print block are unchanged. Real UI functions, inert DOM.
function uiHarness(state, fit) {
  const vm = require("node:vm");
  const ui = fs.readFileSync(path.join(__dirname, "../static/investigation.js"), "utf8");
  const part = (a, b) => { const i = ui.indexOf(a); assert.ok(i >= 0, a); return ui.slice(i, ui.indexOf(b, i)); };
  const code = part("  // ------------------------------------------------------------------ labels", "  // ------------------------------------------------------------------ state plumbing") +
    part("  function finish(result) {", "  // Keyboard focus never falls") + part("  function renderError() {", "  const claimMap") +
    part("  function renderBrief(b) {", "  // Whether the current brief passed") +
    part(ui.includes("  // Name a staff group in the reopen preview") ? "  // Name a staff group in the reopen preview" : "  function renderCase(b, busy) {", "  // ------------------------------------------------------------------ map") +
    part("  // One staff contribution as a labelled sentence", "  // One-page check on the real layout") +
    (ui.includes("  // Staff-note review chip") ? part("  // Staff-note review chip", "  // One compact selector")
      // Earlier versions computed the chip inline in render(); evaluate that exact expression for comparison.
      : (/\n\s*(b\.review_state !== "clean" \? h\([^\n]*\) : null),\n/.exec(ui) ? "function reviewChip(b) { return " + /\n\s*(b\.review_state !== "clean" \? h\([^\n]*\) : null),\n/.exec(ui)[1] + "; }" : ""));
  const nodes = new Map();
  const $ = (sel) => { if (!nodes.has(sel)) nodes.set(sel, { sel, textContent: "", hidden: false, disabled: false, dataset: {}, children: [], classList: { remove() {}, toggle() {} }, querySelectorAll() { return []; }, querySelector() { return null; }, focus() {} }); return nodes.get(sel); };
  const catalog = { metrics: [{ metric_id: "poverty_rate_65_plus", label: "Poverty rate, age 65 and over" }, { metric_id: "population_65_plus", label: "Population age 65 and over" }],
    geographies: [{ geography_id: "HI-STATE-2024", label: "State of Hawaiʻi" }], unavailable_geographies: [], programs: [{ program_id: "kupuna_care_hi", name: "Kūpuna Care" }] };
  const ctx = { C, ids, state, catalog, notice: "", interp: null, importing: null, $,
    h: (tag, attrs, ...kids) => ({ tag, attrs, kids }), btn: (label) => ({ button: label }), fill: (n, c) => { n.children = c; },
    measureBrief: () => fit || { ok: true, over: 0 }, briefFits: () => !fit || fit.ok, render() {}, flushActive() {}, syncMap() {}, focusResults() {}, replayHelp: () => null, choiceList: () => null, claimMap: () => new Map(), savedDigest: null, ids, bootRun: false };
  vm.createContext(ctx); vm.runInContext(code, ctx);
  return { ctx, $, run: (expr) => vm.runInContext(expr, ctx) };
}
function briefState() {
  let s = run(C.createState(RUNTIME, ids));
  s = ok(C.toggleClaim(s, claim(s, "stat:house028:population_65_plus"), true));
  const b = C.beginBrief(s, {}, ids);
  return C.applyResponse(b.state, reply(b.request)).state;
}
function failBrief(s) { const b = C.beginBrief(s, {}, ids); assert.equal(b.error, undefined); return C.applyTransportFailure(b.state, b.request.request_id, "network"); }

test("a failed new brief attempt names the retained previous brief; printability follows the measured page check; otherwise existing blocks apply", () => {
  // 1. Valid previous brief, then a failed recreation in the same context.
  const prior = briefState();
  assert.equal(C.printStatus(prior).ok, true);
  let f = failBrief(prior), u = uiHarness(f.state);
  u.ctx.__r = f; u.run("finish(__r)");
  assert.match(u.ctx.notice, /^The new brief was not created\./); assert.match(u.ctx.notice, /previous brief is kept unchanged/); assert.doesNotMatch(u.ctx.notice, /printable/);
  u.run("renderBrief(C.active(state))");
  assert.match(u.$("#ia-brief-status").textContent, /^Ready to print the previous brief/); assert.equal(u.$("#ia-print-btn").disabled, false, "retained brief stays printable");
  assert.deepEqual(f.state.briefs[C.active(f.state).branch_id], prior.briefs[C.active(prior).branch_id], "previous brief retained unchanged");
  u.run("renderError()");
  assert.match(JSON.stringify(u.$("#ia-error").children), /previous brief is kept unchanged/); assert.doesNotMatch(JSON.stringify(u.$("#ia-error").children), /printable/);
  assert.match(JSON.stringify(u.$("#ia-error").children), /Create the brief again/, "operation recovery kept");

  // 1b. Same retained current brief, but the measured page layout does not fit: retention is acknowledged,
  // nothing claims it is printable, and the measured too-long status with disabled Print remains.
  f = failBrief(prior); u = uiHarness(f.state, { ok: false, over: 2, tag: "x" });
  u.ctx.__r = f; u.run("finish(__r)");
  assert.match(u.ctx.notice, /^The new brief was not created\./); assert.match(u.ctx.notice, /previous brief is kept unchanged/); assert.doesNotMatch(u.ctx.notice, /printable|Ready/);
  u.run("renderBrief(C.active(state))");
  assert.match(u.$("#ia-brief-status").textContent, /^Not ready to print: .*about 2% longer than one page/); assert.equal(u.$("#ia-print-btn").disabled, true);
  u.run("renderError()");
  assert.doesNotMatch(JSON.stringify(u.$("#ia-error").children), /printable/);
  assert.doesNotMatch(fs.readFileSync(path.join(__dirname, "../static/investigation.js"), "utf8"), /still current and printable/, "no panel copy asserts printability from case state alone");

  // 2. No previous brief: unchanged wording and print stays blocked.
  let s = run(C.createState(RUNTIME, ids)); s = ok(C.toggleClaim(s, claim(s, "stat:house028:population_65_plus"), true));
  f = failBrief(s); u = uiHarness(f.state); u.ctx.__r = f; u.run("finish(__r)");
  assert.equal(u.ctx.notice, "The brief was not created. Your work is kept.");
  u.run("renderBrief(C.active(state))");
  assert.equal(u.$("#ia-print-btn").disabled, true); assert.doesNotMatch(u.$("#ia-brief-status").textContent, /previous/);

  // 3. Stale previous brief (selection changed): not offered as printable, no "previous brief" claim.
  s = ok(C.toggleClaim(briefState(), claim(briefState(), "stat:house028:poverty_rate_65_plus"), true));
  assert.equal(C.printStatus(s).code, "brief_stale");
  f = failBrief(s); u = uiHarness(f.state); u.ctx.__r = f; u.run("finish(__r)");
  assert.equal(u.ctx.notice, "The brief was not created. Your work is kept.");
  u.run("renderBrief(C.active(state))");
  assert.equal(u.$("#ia-print-btn").disabled, true); assert.equal(u.$("#ia-brief-status").textContent, C.printStatus(f.state).message);

  // 4. Normal success wording.
  const b = C.beginBrief(prior, {}, ids), done = C.applyResponse(b.state, reply(b.request));
  u = uiHarness(b.state); u.ctx.__r = done; u.run("finish(__r)");
  assert.equal(u.ctx.notice, "Brief created for the current results.");
  u.run("renderBrief(C.active(state))");
  assert.equal(u.$("#ia-brief-status").textContent, C.printStatus(done.state).message);
});

test("typed-request fields show plan wording: inherited steps as the plan cards word them, no raw ids", () => {
  const s = run(C.createState(RUNTIME, ids)), u = uiHarness(s);
  const steps = C.active(s).plan.steps;
  u.ctx.__steps = steps;
  const text = u.run("valueText('steps', __steps)");
  assert.doesNotMatch(text, /operation|args|HI-STATE|metric_ids|step_id/i);
  steps.forEach((st, i) => assert.ok(text.includes((i + 1) + ". " + u.run("OP_LABEL")[st.operation] + " — " + u.run("stepScope(__steps[" + i + "])")), st.step_id));
  assert.match(text, /comparison: State of Hawaiʻi/);
  assert.match(u.run("valueText('removed_step_id', 's3')"), /^Step 3 · Program reference \(typed-request name s3\)$/);
  assert.equal(u.run("valueText('metric_ids', null)"), "All 20 measures");
  assert.equal(u.run("fieldLabel('removed_step_id')"), "Remove step");
});


// Presentation regression (R6): the reopen preview names each staff group by its own context, using the
// actual parser output (preview rows carry branch_id and items only) joined to the parsed file's branches.
test("reopen preview groups staff notes under each context's own district, from real parser output", () => {
  const vm = require("node:vm");
  let s = run(C.createState(RUNTIME, ids));
  s = ok(C.setStaffText(s, "title", "NOTE-A"));
  const toDistrict = (st, code, chamber) => { const p = clone(C.active(st).plan); p.district = { state_fips: "15", chamber, code, boundary_session: 2024 }; return change(st, { plan: p }).state; };
  s = toDistrict(s, "013", "house"); s = ok(C.setStaffText(s, "note", "NOTE-B"));
  s = toDistrict(s, "025", "senate"); s = ok(C.setStaffText(s, "next_steps", "NOTE-C"));
  const parsed = C.parseCaseFile(JSON.stringify(C.exportCase(s, { include_staff_work: true })), RUNTIME);
  assert.ok(parsed.ok && parsed.preview.runtime_match);
  assert.ok(parsed.preview.staff_preview.every((r) => Object.keys(r).sort().join() === "branch_id,items"), "actual preview shape has no district");
  const u = uiHarness(C.createState(RUNTIME, ids));
  u.ctx.importing = parsed;
  u.run("renderCase(C.active(state), false)");
  const groups = (u.$("#ia-import-preview").children.find((n) => n && n.tag === "div" && n.kids && JSON.stringify(n.kids).includes("ia-staff-list")) || {}).kids;
  const list = groups.find((k) => k && k.tag === "ul");
  const heads = list.kids[0].map((li) => li.kids[0].attrs.text);
  assert.deepEqual(heads, ["Context 1: House 028 · Older-adult support at home · compared with State of Hawaiʻi", "Context 2: House 013 · Older-adult support at home · compared with State of Hawaiʻi", "Context 3: Senate 025 · Older-adult support at home · compared with State of Hawaiʻi"]);
  const own = list.kids[0].map((li) => JSON.stringify(li.kids[1]));
  assert.match(own[0], /NOTE-A/); assert.doesNotMatch(own[0], /NOTE-B|NOTE-C/);
  assert.match(own[1], /NOTE-B/); assert.doesNotMatch(own[1], /NOTE-A|NOTE-C/);
  assert.match(own[2], /NOTE-C/); assert.doesNotMatch(own[2], /NOTE-A|NOTE-B/);
});


// Presentation regression (R7): the staff-note review chip follows the current review checks (parked items,
// active staff notes, the review token), not the historical branch flag. Real export/parse/import replay.
test("review chip agrees with the current staff review after an imported case is reviewed, edited, parked or blocked", () => {
  const chip = (st) => { const u = uiHarness(st); assert.equal(typeof u.ctx.reviewChip, "function", "reviewChip derives the chip"); const n = u.run("reviewChip(C.active(state))"); return n ? n.attrs.text : null; };
  // Actual staff import replay.
  const parsed = C.parseCaseFile(JSON.stringify(C.exportCase(worked(), { include_staff_work: true })), RUNTIME);
  const imp = C.beginImport(run(C.createState(RUNTIME, ids)), parsed, { accept_staff_work: true }, ids);
  const done = C.applyResponse(imp.state, reply(imp.request), meta(imp.request));
  assert.equal(done.outcome, "imported");
  let s = done.state;
  assert.equal(C.active(s).review_state, "staff_review_required");
  assert.equal(C.reviewCurrent(s), false);
  assert.equal(chip(s), "Staff review required");
  // Review: the gate passes and the chip agrees, although the historical branch flag is unchanged.
  s = ok(C.markReviewed(s));
  assert.equal(C.reviewCurrent(s), true); assert.equal(C.active(s).review_state, "staff_review_required");
  assert.equal(chip(s), "Staff notes reviewed");
  // An edit invalidates the review.
  s = ok(C.setStaffText(s, "note", "changed after review"));
  assert.equal(C.reviewCurrent(s), false); assert.equal(chip(s), "Staff review required");
  // No staff notes: no chip.
  assert.equal(chip(run(C.createState(RUNTIME, ids))), null);
  // Parked contributions from an earlier context still require review.
  const p = clone(C.active(worked()).plan); p.district = Object.assign({}, p.district, { code: "013" });
  const moved = change(worked(), { plan: p }).state;
  assert.ok(C.pendingReview(moved).length > 0); assert.equal(chip(moved), "Staff review required");
  // Replay blocked (actual reducer path: a run against another evidence version) keeps priority.
  const other = Object.assign({}, s, { runtime: Object.assign({}, s.runtime, { snapshot_id: sha("another release") }) });
  const blocked = C.beginRun(other, ids);
  assert.ok(blocked.error && blocked.state); assert.equal(C.active(blocked.state).review_state, "replay_blocked");
  assert.equal(chip(blocked.state), "Replay blocked");
});

// Recovery and replay presentation (real reducer and actual investigation.js functions, inert DOM).
function recoveryHarness(state) {
  const vm = require("node:vm");
  const ui = fs.readFileSync(path.join(__dirname, "../static/investigation.js"), "utf8");
  const part = (a, b) => { const i = ui.indexOf(a); assert.ok(i >= 0, a); return ui.slice(i, ui.indexOf(b, i)); };
  const code = part("  // ------------------------------------------------------------------ labels", "  // ------------------------------------------------------------------ state plumbing") +
    part("  function finish(result) {", "  function runActive() {") + part("  function renderError() {", "  // A saved finding named") +
    part("  // A saved finding named", "  function claimTitle(ref) {");
  const nodes = new Map(), buttons = [], sent = [], focused = [];
  const $ = (sel) => { if (!nodes.has(sel)) nodes.set(sel, { sel, textContent: "", hidden: false, disabled: false, children: [], focus() { focused.push(sel); } }); return nodes.get(sel); };
  const ctx = { C, ids, state, notice: "", interp: null, importing: null, preview: null, bootRun: false, $, catalog: { metrics: [{ metric_id: "population_65_plus", label: "Population age 65 and over" }], geographies: [{ geography_id: "HI-STATE-2024", label: "State of Hawaiʻi" }, { geography_id: "HI-COUNTY-009-2024", label: "Maui County" }], unavailable_geographies: [], programs: [] },
    h: (tag, attrs, ...kids) => ({ tag, attrs, kids }), btn: (label, fn, attrs) => { buttons.push({ label, fn, attrs }); return { button: label }; }, fill: (n, c) => { n.children = c; },
    render() {}, flushActive() {}, syncMap() {}, replayHelp: () => null, briefFits: () => true, measureBrief: () => ({ ok: true }), alertUser(m) { throw new Error(m); }, clearAlert() {},
    send: (r) => { sent.push(r); }, document: { activeElement: null, body: {} } };
  vm.createContext(ctx); vm.runInContext(code, ctx);
  return { ctx, buttons, sent, focused, run: (x) => vm.runInContext(x, ctx) };
}

test("a failed restore names the context, keeps the current one, and its retry restores the same target", () => {
  const s0 = run(C.createState(RUNTIME, ids)), p = clone(C.active(s0).plan); p.district = Object.assign({}, p.district, { code: "013" });
  const s1 = change(s0, { plan: p }).state, target = s1.case.branches[0].branch_id;
  assert.equal(C.active(s1).plan.district.code, "013");
  const u = recoveryHarness(s1);
  u.ctx.__t = target; u.run("restoreContext(__t)");
  assert.equal(u.sent.length, 1); assert.equal(u.sent[0].branch_id, target);
  const f = C.applyTransportFailure(u.ctx.state, u.sent[0].request_id, "network");
  u.ctx.__r = f; u.run("finish(__r)");
  assert.match(u.ctx.notice, /^Context 1 \(House 028 · Older-adult support at home · compared with State of Hawaiʻi\) was not restored\. You are still on Context 2 \(House 013 · Older-adult support at home · compared with State of Hawaiʻi\)\./);
  assert.equal(C.active(u.ctx.state).plan.district.code, "013", "current context unchanged");
  u.run("renderError()");
  const retry = u.buttons.find((b) => /^Restore Context 1 again$/.test(b.label));
  assert.ok(retry, "retry names the same restore target"); assert.ok(!u.buttons.some((b) => b.label === "Run the plan again"));
  retry.fn();
  assert.equal(u.sent.length, 2); assert.equal(u.sent[1].branch_id, target, "retry restores the same context"); assert.equal(u.sent[1].plan.district.code, "028");
});

test("a replayed selection whose saved wording no longer matches is named, explained and counted", () => {
  let s = run(C.createState(RUNTIME, ids));
  s = ok(C.toggleClaim(s, claim(s, "stat:house028:population_65_plus"), true)); s = ok(C.toggleClaim(s, claim(s, "stat:house028:poverty_rate_65_plus"), true));
  const file = C.exportCase(s, { include_staff_work: false });
  const changed = file.branches[0].selected_claim_refs.find((r) => r.finding_id === "stat:house028:population_65_plus");
  changed.semantic_hash = sha("not the replayed wording");
  const imp = C.beginImport(run(C.createState(RUNTIME, ids)), C.parseCaseFile(JSON.stringify(file), RUNTIME), {}, ids);
  const done = C.applyResponse(imp.state, reply(imp.request), meta(imp.request));
  assert.equal(done.outcome, "imported"); assert.equal(C.active(done.state).selected_claim_refs.length, 1);
  const u = recoveryHarness(done.state); u.ctx.__r = done; u.run("finish(__r)");
  assert.match(u.ctx.notice, /1 saved selection was not reselected/);
  const r = done.state.retired[C.active(done.state).branch_id].find((x) => x.claim_ref);
  u.ctx.__ref = r.claim_ref; u.ctx.__r2 = r;
  assert.match(u.run("savedFindingName(__ref)"), /^Population age 65 and over/);
  assert.match(u.run("droppedReason(__r2, C.currentResults(state))"), /saved wording no longer matches the replayed evidence, so it was not reselected/);
  assert.doesNotMatch(u.run("droppedReason(__r2, C.currentResults(state))"), /another|original context/);
});

test("the automatic first run keeps the page's starting focus; later runs move focus to the findings", () => {
  const b = C.beginRun(C.createState(RUNTIME, ids), ids), r = C.applyResponse(b.state, reply(b.request), meta(b.request));
  const u = recoveryHarness(b.state); u.ctx.bootRun = true; u.ctx.__r = r;
  u.run("finish(__r)"); assert.deepEqual(u.focused, [], "no focus move after the automatic first run"); assert.equal(u.ctx.bootRun, false);
  const b2 = C.beginRun(r.state, ids), r2 = C.applyResponse(b2.state, reply(b2.request), meta(b2.request));
  u.ctx.state = b2.state; u.ctx.__r = r2; u.run("finish(__r)");
  assert.deepEqual(u.focused, ["#ia-evidence-h"]);
});

// Source dialog: only the reply for the latest open request, while the dialog is still open, fills it or
// moves focus; closing returns focus to the opener. Actual app.js functions with deferred replies.
function sourceHarness() {
  const vm = require("node:vm");
  const app = fs.readFileSync(path.join(__dirname, "../static/app.js"), "utf8");
  const part = (a, b) => { const i = app.indexOf(a); assert.ok(i >= 0, a); return app.slice(i, app.indexOf(b, i)); };
  const code = part("  let sourceOpener = null;", "  // ------------------------------------------------------------ tabs") +
    (app.includes("  function sourceDialogClosed() {") ? part("  function sourceDialogClosed() {", "  // ------------------------------------------------------------ boot")
      : "function sourceDialogClosed() { const back = sourceOpener; sourceOpener = null; if (back && back.isConnected && typeof back.focus === 'function') back.focus(); }");
  const focus = [], pending = [];
  const el = (name) => ({ name, isConnected: true, focus() { focus.push(name); } });
  const body = { innerHTML: "" }, close = el("close");
  const dlg = { open: false, showModal() { this.open = true; }, close() { this.open = false; ctx.sourceDialogClosed(); } };
  const nodes = { "#source-body": body, "#source-dialog": dlg, "#close-source": close };
  const ctx = { $: (s) => nodes[s], document: { activeElement: null }, logEvent() {}, escapeText: (x) => String(x),
    api: () => new Promise((resolve) => pending.push(resolve)) };
  vm.createContext(ctx); vm.runInContext(code, ctx);
  return { ctx, body, dlg, focus, pending, el };
}

test("an older source reply never replaces the newer source or moves focus after close", async () => {
  // Close A while loading, open B, B replies first, then A replies late.
  let h = sourceHarness();
  const openerA = h.el("openerA"), openerB = h.el("openerB");
  const a = h.ctx.openSource("srcA", "f1", openerA);
  h.dlg.close();
  assert.deepEqual(h.focus, ["openerA"], "closing returns focus to the opener");
  const b = h.ctx.openSource("srcB", "f2", openerB);
  h.pending[1]({ html: "<p>SOURCE B</p>" }); await b;
  assert.equal(h.body.innerHTML, "<p>SOURCE B</p>"); assert.deepEqual(h.focus, ["openerA", "close"]);
  h.pending[0]({ html: "<p>SOURCE A</p>" }); await a;
  assert.equal(h.body.innerHTML, "<p>SOURCE B</p>", "late reply for A is ignored"); assert.deepEqual(h.focus, ["openerA", "close"], "no focus move for the stale reply");
  // A late error after a newer open is ignored too.
  h = sourceHarness();
  const a2 = h.ctx.openSource("srcA", "f1", h.el("x")); const b2 = h.ctx.openSource("srcB", "f2", h.el("y"));
  h.pending[1]({ html: "<p>B</p>" }); await b2;
  h.pending[0]({ status: "error", reason: "late failure" }); await a2;
  assert.equal(h.body.innerHTML, "<p>B</p>");
  // A reply for a dialog closed while loading changes nothing and moves no focus.
  h = sourceHarness();
  const c = h.ctx.openSource("srcA", "f1", h.el("opener")); h.dlg.close();
  const before = h.body.innerHTML; h.pending[0]({ html: "<p>A</p>" }); await c;
  assert.equal(h.body.innerHTML, before); assert.deepEqual(h.focus, ["opener"]);
});

test("saved contexts that differ only in comparison scope have distinct names", () => {
  const s0 = run(C.createState(RUNTIME, ids)), p = clone(C.active(s0).plan);
  const cmp = p.steps.find((s) => s.operation === "compare"); cmp.args.comparison_geography = "HI-COUNTY-009-2024";
  const s1 = change(s0, { plan: p }).state;
  const [b1, b2] = s1.case.branches.map((b) => b.branch_id);
  const u = recoveryHarness(s1);
  u.ctx.__a = b1; u.ctx.__b = b2;
  const n1 = u.run("contextName(__a)"), n2 = u.run("contextName(__b)");
  assert.equal(n1, "Context 1 (House 028 · Older-adult support at home · compared with State of Hawaiʻi)");
  assert.equal(n2, "Context 2 (House 028 · Older-adult support at home · compared with Maui County)");
  const unknown = clone(p); unknown.steps.find((s) => s.operation === "compare").args.comparison_geography = "HI-COUNTY-999-2024";
  u.ctx.__p = unknown; assert.match(u.run("planLabel(__p)"), /compared with an unlisted geography$/);
});

// ------------------------------------------------------------------ recommended brief selector
// Real handler results projected in tests/fixtures/recommended-brief-results.json (drift-checked by test_recommended_brief.py).
const RB_CASES = JSON.parse(fs.readFileSync(path.join(__dirname, "fixtures/recommended-brief-results.json"), "utf8")).cases;
const recIds = (rec) => rec.claims.map((c) => c.claim_ref.finding_id);

test("care recipe: one comparison with both numbers plus the Kūpuna Care verification step, no program tile", () => {
  for (const [key, district] of [["house-013-aging_at_home", "HI-HOUSE-013-2024"], ["house-028-aging_at_home", "HI-HOUSE-028-2024"], ["senate-025-aging_at_home", "HI-SENATE-025-2024"]]) {
    const rec = C.recommendedBrief(RB_CASES[key]);
    assert.deepEqual(recIds(rec), ["cmp:" + district + "~HI-STATE-2024:poverty_rate_65_plus"], key);
    assert.equal(rec.card.tier, "verification_action"); assert.equal(rec.card.program_id, "kupuna_care_hi");
    assert.deepEqual(rec.action, rec.card.action_ref);
    assert.ok(!rec.claims.some((c) => c.kind === "program_relevance" || c.kind === "outreach_hypothesis"));
  }
});

test("SNAP recipe: two short district measures plus the SNAP verification step; supporting comparisons are not selectable", () => {
  for (const [key, district] of [["senate-006-food_assistance_outreach", "HI-SENATE-006-2024"], ["house-028-food_assistance_outreach", "HI-HOUSE-028-2024"]]) {
    const rec = C.recommendedBrief(RB_CASES[key]);
    assert.deepEqual(recIds(rec), ["stat:" + district + ":poverty_rate_all_people", "stat:" + district + ":median_household_income"], key);
    assert.equal(rec.card.program_id, "snap_hi"); assert.equal(rec.card.tier, "verification_action");
  }
});

test("a plan without a program step recommends measures only and no agency step", () => {
  const rec = C.recommendedBrief(RB_CASES["house-028-custom"]);
  assert.deepEqual(recIds(rec), ["stat:HI-HOUSE-028-2024:population_65_plus", "stat:HI-HOUSE-028-2024:total_households"]);
  assert.equal(rec.action, null);
});

test("every recommended finding is listed by a successful step, and the program reference stays selectable", () => {
  for (const [key, res] of Object.entries(RB_CASES)) {
    const listed = new Set(res.steps.filter((s) => s.status === "ok").flatMap((s) => s.claim_refs.map(C.refKey)));
    const rec = C.recommendedBrief(res);
    assert.ok(rec.claims.every((c) => listed.has(C.refKey(c.claim_ref))), key);
    const program = res.claims.find((c) => c.kind === "program_relevance");
    if (program) assert.ok(listed.has(C.refKey(program.claim_ref)), key + ": program reference remains available for manual selection");
  }
  assert.deepEqual(C.recommendedBrief(null), { claims: [], action: null, card: null });
});

// ---- Language question scope (repair-1 v4): the real UI state shapes the language context is built from.
test("language context: boot default House 028 plan, edited draft, conflict basis, step focus and inspected finding", () => {
  const L = require("../static/language_state.js");
  let s = run(C.createState(RUNTIME, ids));
  const b = C.active(s), stamp = (st) => JSON.stringify(st.case.branches.map((x) => [x.plan, x.selected_claim_refs])) + JSON.stringify(st.draft);
  const before = stamp(s);
  // Boot: confirmed = draft = default plan, no focus, brief selections (none).
  let c = L.context(s, C.active);
  assert.deepEqual([c.confirmed_plan.district.code, c.draft_plan.district.code, c.focused_step_id, c.selected_claim_refs], ["028", "028", null, []]);
  // Explicit step focus is kept only for a step of the held plan; an unknown or removed step is dropped.
  assert.equal(L.context(s, C.active, { focus: "s2" }).focused_step_id, "s2");
  assert.equal(L.context(s, C.active, { focus: "s9" }).focused_step_id, null);
  // Inspected finding: the only selected reference while it belongs to the current revision; brief selections stay.
  const ref = claim(s, "cmp:house028");
  const src = { claim_ref: ref, branch_id: b.branch_id, revision: b.last_ready_revision };
  assert.deepEqual(L.context(s, C.active, { source: src }).selected_claim_refs, [ref]);
  assert.deepEqual(L.context(s, C.active, { source: Object.assign({}, src, { revision: b.last_ready_revision + 1 }) }).selected_claim_refs, []);
  assert.deepEqual(C.active(s).selected_claim_refs, []);
  // Unapplied draft edit: a conflict. Basis 'draft' asks about the draft alone; basis 'confirmed' about the confirmed plan.
  const confirmedBefore = JSON.stringify(C.active(s).plan);
  s = Object.assign({}, s, { draft: C.removeStep(s.draft, "s4").plan });
  c = L.context(s, C.active);
  assert.notDeepEqual(c.confirmed_plan, c.draft_plan);
  const asDraft = L.context(s, C.active, { basis: L.makeBasis(s, C.active, "draft"), source: src, focus: "s2" });
  assert.deepEqual([asDraft.confirmed_plan, asDraft.draft_plan.steps.length, asDraft.selected_claim_refs, asDraft.focused_step_id], [null, 3, [], "s2"]);
  const asConfirmed = L.context(s, C.active, { basis: L.makeBasis(s, C.active, "confirmed"), focus: "s4" });
  assert.deepEqual(asConfirmed.draft_plan, asConfirmed.confirmed_plan);
  assert.equal(asConfirmed.focused_step_id, "s4");  // s4 exists in the confirmed plan the question uses
  assert.equal(L.context(s, C.active, { basis: L.makeBasis(s, C.active, "draft"), focus: "s4" }).focused_step_id, null);
  // A basis chosen before a later edit is stale and ignored (no silent reuse of an old choice).
  const old = L.makeBasis(s, C.active, "draft");
  const s2 = Object.assign({}, s, { draft: C.removeStep(s.draft, "s3").plan });
  assert.notEqual(L.context(s2, C.active, { basis: old }).confirmed_plan, null);
  // Building contexts never mutates the confirmed plan, its selections or the draft.
  assert.equal(JSON.stringify(C.active(s).plan), confirmedBefore);
  assert.equal(s.draft.steps.length, 3);
  assert.deepEqual(C.active(s).selected_claim_refs, []);
  assert.ok(before.length > 0);
});

test("language clarification choice becomes a canonical visible question prefix, replacing an earlier one", () => {
  const L = require("../static/language_state.js");
  const q = "Switch to district 13 and show senior poverty.";
  assert.equal(L.withChoice(q, { field: "district", value: { chamber: "house", code: "013" } }), "House 13: " + q);
  assert.equal(L.withChoice("House 13: " + q, { field: "district", value: { chamber: "senate", code: "013" } }), "Senate 13: " + q);
  assert.equal(L.withChoice("I want the rate for the district I represent.", { field: "chamber", value: "senate" }), "In the Senate: I want the rate for the district I represent.");
  assert.equal(L.withChoice("In the Senate: x", { field: "district", value: { chamber: "senate", code: "005" } }), "Senate 5: x");
  assert.equal(L.withChoice(q, { field: "control_conflict", value: "draft" }), q);
  assert.equal(L.withChoice(q, { field: "district", value: { chamber: "county", code: "013" } }), q);
});

test("language replies for an old question scope never match after focus or source scope changes", () => {
  const L = require("../static/language_state.js");
  const s = run(C.createState(RUNTIME, ids)), b = C.active(s);
  const job = { request_id: "r1", context: L.context(s, C.active, { focus: "s2" }), context_digest: "sha256:" + "a".repeat(64) };
  const reply = { request_id: "r1", context: JSON.parse(JSON.stringify(job.context)), context_digest: job.context_digest,
    tokens: { schema_version: "ia-language/1", release_id: RUNTIME.release_id, case_id: job.context.case_id, branch_id: job.context.branch_id,
      revision: job.context.revision, snapshot_id: job.context.snapshot_id, operation_version: job.context.operation_version, recipe_version: job.context.recipe_version } };
  assert.equal(L.matches(reply, job, L.context(s, C.active, { focus: "s2" }), RUNTIME.release_id), true);
  assert.equal(L.matches(reply, job, L.context(s, C.active), RUNTIME.release_id), false);  // focus cleared
  const src = { claim_ref: claim(s, "cmp:house028"), branch_id: b.branch_id, revision: b.last_ready_revision };
  assert.equal(L.matches(reply, job, L.context(s, C.active, { focus: "s2", source: src }), RUNTIME.release_id), false);  // new finding scope
});

// Answer-focused brief selection: only the requested step's listed findings, the recommended agency action,
// and the selection survives case export, parsing and the replay request exactly (no new case fields).
test("a focused brief selection uses the requested step and replays from a case file unchanged", () => {
  let s = run(C.createState(RUNTIME, ids));
  const res = C.currentResults(s), legacy = C.recommendedBrief(res);
  const profile = C.focusedBrief(res, ["s1"]), compare = C.focusedBrief(res, ["s2"]);
  assert.equal(C.focusedBrief(res, []), null); assert.equal(C.focusedBrief(res, ["nope"]), null);
  assert.equal(profile.requested, C.AGING_METRICS.length);
  assert.deepEqual(profile.claims.map((c) => c.claim_ref.finding_id), C.AGING_METRICS.slice(0, 2).map((m) => "stat:house028:" + m));
  assert.deepEqual(compare.claims.map((c) => c.kind), ["comparison"]);
  assert.deepEqual(profile.action, legacy.action); assert.ok(profile.action);
  for (const c of profile.claims) s = ok(C.toggleClaim(s, c.claim_ref, true));
  const pick = C.chooseAction(s, profile.action); assert.equal(pick.error, undefined);
  s = ok(C.confirmChange(s, pick.proposal, ids));
  const file = JSON.stringify(C.exportCase(s, { include_staff_work: false }));
  const parsed = C.parseCaseFile(file, RUNTIME); assert.ok(parsed.ok);
  const b = C.beginImport(C.createState(RUNTIME, ids), parsed, { accept_staff_work: false }, ids);
  assert.equal(b.error, undefined);
  assert.deepEqual(b.request.selected_claim_refs, profile.claims.map((c) => c.claim_ref));
  assert.deepEqual(b.request.selected_action_ref, profile.action);
});

// Brief actions and the answer they focus on, through the actual investigation.js functions (inert DOM, stand-in server).
function briefActionHarness(state, extra) {
  const vm = require("node:vm");
  const ui = fs.readFileSync(path.join(__dirname, "../static/investigation.js"), "utf8");
  const part = (a, b) => { const i = ui.indexOf(a); assert.ok(i >= 0, a); return ui.slice(i, ui.indexOf(b, i)); };
  const code = part("  // Selects the recommended findings and agency action.", "  function renderTray(") +
    part("  function answerAfterRun(result) {", "  function finish(result) {") + part("  function settleAnswer() {", "  function focusAnswer()");
  const briefs = [], runs = [];
  const ctx = Object.assign({ C, ids, state, notice: "", preview: null, pendingAnswer: null, answerBasis: null, briefFocus: null,
    currentRecommendation: (res) => ctx.briefFocus || C.recommendedBrief(res), briefBlock: () => null, createBrief: () => briefs.push(clone(ctx.state)),
    render() {}, runActive() { runs.push(1); }, alertUser(m) { throw new Error(m); }, focusAnswer() {}, districtLabel: (d) => d.chamber + d.code,
    plural: (n, a, b) => n + " " + (n === 1 ? a : b), document: { activeElement: null, body: {} }, $: () => ({ focus() {} }) }, extra || {});
  vm.createContext(ctx); vm.runInContext(code, ctx);
  return { ctx, briefs, runs, run: (x) => vm.runInContext(x, ctx) };
}

test("a brief action with unapplied plan edits asks to apply or discard and changes nothing", () => {
  let s = run(C.createState(RUNTIME, ids));
  const draft = clone(C.active(s).plan); draft.steps[0].args.metric_ids = ["median_age"];
  s = Object.assign({}, s, { draft });
  const before = C.canonical(s);
  const t = briefActionHarness(s);
  t.run("createRecommended()");
  assert.equal(C.canonical(t.ctx.state), before, "state, including the draft edits, is byte-identical");
  assert.equal(t.briefs.length, 0, "no brief request"); assert.equal(t.runs.length, 0);
  assert.match(t.ctx.notice, /Apply or discard the plan edits first/);
});

test("an answer-focused brief keeps its focus through an action-only context fork", () => {
  let s = run(C.createState(RUNTIME, ids));
  s = ok(C.setStaffText(s, "title", "Synthetic staff title"));   // staff content makes the action change open a new context
  const b0 = C.active(s), res = C.currentResults(s);
  const answer = { kind: "answer", question: "How many older adults?", plan: clone(b0.plan), step_ids: ["s1"], only: {}, branch_id: b0.branch_id };
  const focus = C.focusedBrief(res, ["s1"], {});
  const t = briefActionHarness(s, { answerBasis: answer, briefFocus: focus });
  t.run("createRecommended()");
  assert.ok(t.ctx.preview && t.ctx.preview.fork, "the action change is reviewed first");
  assert.deepEqual(t.ctx.preview.kinds, ["response"]);
  assert.equal(t.briefs.length, 0);
  assert.ok(t.ctx.pendingAnswer && t.ctx.pendingAnswer.rebind, "the answer is carried to the new context");
  assert.match(t.ctx.notice, /Create brief from this answer/);
  // Staff confirms the context review; the new context replays the same plan.
  const forked = C.confirmChange(t.ctx.state, t.ctx.preview, ids); assert.equal(forked.error, undefined); assert.ok(forked.forked);
  const bb = C.beginRun(forked.state, ids);
  const result = C.applyResponse(bb.state, reply(bb.request), meta(bb.request));
  assert.equal(result.outcome, "committed");
  t.ctx.state = result.state;
  t.run("answerAfterRun(" + JSON.stringify({ outcome: result.outcome, status: "ok" }) + ")");
  const b1 = C.active(t.ctx.state);
  assert.notEqual(b1.branch_id, b0.branch_id);
  assert.ok(t.ctx.answerBasis && t.ctx.answerBasis.branch_id === b1.branch_id, "answer rebound to the new context");
  assert.deepEqual(t.ctx.answerBasis.step_ids, ["s1"]);
  const again = C.focusedBrief(C.currentResults(t.ctx.state), t.ctx.answerBasis.step_ids, t.ctx.answerBasis.only);
  assert.deepEqual(again.claims.map((c) => c.claim_ref.finding_id), focus.claims.map((c) => c.claim_ref.finding_id), "same focused findings, not the generic comparison");
  assert.deepEqual(C.active(t.ctx.state).selected_claim_refs.map((r) => r.finding_id), focus.claims.map((c) => c.claim_ref.finding_id), "carried selection kept");
  assert.equal(C.pendingReview(t.ctx.state).length, 1, "the staff title waits for review in the new context");
});

test("a focused brief narrows to the measures or program asked for and pairs the agency action with that program", () => {
  const ref = (fid) => ({ snapshot_id: RUNTIME.snapshot_id, finding_id: fid, semantic_hash: sha(fid) });
  const stat = (m) => ({ kind: "statistic", claim_ref: ref("stat:" + m), metric: { metric_id: m }, geography: { geography_id: "HI-HOUSE-028-2024" } });
  const progc = (p) => ({ kind: "program_relevance", claim_ref: ref("prog:" + p), program: { program_id: p } });
  const claims = ["population_65_plus", "male_householder_65_plus_living_alone", "median_age"].map(stat).concat([progc("kupuna_care_hi"), progc("snap_hi")]);
  const card = (p, a) => ({ program_id: p, tier: "verification_action", action_ref: { action_id: a, semantic_hash: sha(a) } });
  const res = { plan: { district: { chamber: "house", code: "028" } }, claims,
    steps: [{ step_id: "s1", status: "ok", claim_refs: claims.slice(0, 3).map((c) => c.claim_ref) }, { step_id: "s3", status: "ok", claim_refs: claims.slice(3).map((c) => c.claim_ref) }],
    responses: [card("kupuna_care_hi", "kupuna_verify/1"), card("snap_hi", "snap_verify/1")] };
  const age = C.focusedBrief(res, ["s1"], { s1: { metric_ids: ["median_age"] } });
  assert.deepEqual(age.claims.map((c) => c.claim_ref.finding_id), ["stat:median_age"]); assert.equal(age.requested, 1);
  const snap = C.focusedBrief(res, ["s3"], { s3: { program_ids: ["snap_hi"] } });
  assert.deepEqual(snap.claims.map((c) => c.claim_ref.finding_id), ["prog:snap_hi"]);
  assert.equal(snap.action.action_id, "snap_verify/1", "the SNAP answer gets the SNAP action, not the plan's Kupuna Care");
  const both = C.focusedBrief(res, ["s3"], {});
  assert.equal(both.action, null); assert.equal(both.action_note, "no_matching_action", "two programs: no action is guessed");
  assert.equal(C.focusedBrief(res, ["s1"], { s1: { metric_ids: ["not_in_results"] } }), null);
});

function programCaseState(withStaff) {
  const plan = { district: { state_fips: "15", chamber: "house", code: "028", boundary_session: 2024 }, map_session: 2026, issue_id: "custom", service_area_id: null,
    steps: [{ step_id: "s1", operation: "program_evidence", args: { program_ids: ["kupuna_care_hi", "snap_hi"] } }] };
  let s = run(C.createState(RUNTIME, ids, plan));
  const snap = C.currentResults(s).responses.find((r) => r.program_id === "snap_hi").action_ref;
  s = ok(C.confirmChange(s, C.chooseAction(s, snap).proposal, ids));   // staff chose the SNAP action by hand
  if (withStaff) s = ok(C.setStaffText(s, "title", "Synthetic staff title"));
  return s;
}

test("a recommendation with no agency action replaces an earlier, unrelated action through the ordinary action change", () => {
  // Answer about a program step listing two programs: no single matching action, so the focused brief has none.
  let s = programCaseState(false);
  const res = C.currentResults(s), kupuna = res.claims.find((c) => c.kind === "program_relevance" && /kupuna/.test(c.claim_ref.finding_id));
  const focus = { claims: [kupuna], action: null, card: null, requested: 2, action_note: "no_matching_action" };
  let t = briefActionHarness(s, { briefFocus: focus });
  t.run("createRecommended()");
  assert.equal(t.briefs.length, 1, "brief created after the action change");
  assert.equal(t.briefs[0].case.branches.find((b) => b.branch_id === t.briefs[0].case.active_branch_id).selected_action_ref, null, "SNAP action not kept for a Kupuna-only brief");
  assert.equal(C.beginBrief(t.briefs[0], { clean: false }, ids).request.selected_action_ref, null);
  // With staff content the same change opens a new context, so it is reviewed first and nothing is sent yet.
  s = programCaseState(true);
  t = briefActionHarness(s, { briefFocus: focus });
  t.run("createRecommended()");
  assert.equal(t.briefs.length, 0);
  assert.ok(t.ctx.preview && t.ctx.preview.fork && t.ctx.preview.action_changed && t.ctx.preview.action === null, "the action removal is shown for review");
  assert.equal(C.actionKey(C.active(t.ctx.state).selected_action_ref), C.actionKey(C.active(s).selected_action_ref), "nothing changed before confirmation");
});

function previewHarness(state, extra) {
  const vm = require("node:vm");
  const ui = fs.readFileSync(path.join(__dirname, "../static/investigation.js"), "utf8");
  const part = (a, b) => { const i = ui.indexOf(a); assert.ok(i >= 0, a); return ui.slice(i, ui.indexOf(b, i)); };
  const code = part("  function editDraft(result, message) {", "  function applyPlan() {") + part("  function renderPreview() {", "  // Exact evidence identities");
  const buttons = {}, commits = [];
  const ctx = Object.assign({ C, ids, state, notice: "", preview: null, pendingAnswer: null, CHANGE_LABEL: {}, commits,
    $: () => ({ focus() {}, hidden: false }), h: () => ({}), fill() {}, btn: (label, fn, attrs) => { if (attrs && attrs.id) buttons[attrs.id] = fn; return {}; },
    plural: (n, a, b) => n + " " + (n === 1 ? a : b), render() {}, clearAlert() {}, alertUser(m) { throw new Error(m); }, commit: (p) => commits.push(p) }, extra || {});
  vm.createContext(ctx); vm.runInContext(code, ctx);
  return { ctx, buttons, run: (x) => vm.runInContext(x, ctx) };
}

test("a context review never overwrites plan edits made after it opened", () => {
  const s0 = run(C.createState(RUNTIME, ids));
  const original = clone(C.active(s0).plan), proposed = clone(original); proposed.map_session = 2024;
  const revised = clone(proposed); revised.service_area_id = "oahu";
  const open = () => {
    const s = Object.assign({}, s0, { draft: clone(proposed) });
    const t = previewHarness(s, { preview: C.proposeChange(s, { plan: proposed }), pendingAnswer: { plan: clone(proposed), prev_draft: clone(original) } });
    t.run("renderPreview()");
    return t;
  };
  // Keep current context with no later edit: the plan from before the question returns.
  let t = open(); t.buttons["ia-preview-cancel"]();
  assert.deepEqual(t.ctx.state.draft, original);
  // Keep current context after a later Advanced edit: the newer edit stays.
  t = open(); t.ctx.change = { plan: clone(revised) }; t.run("editDraft(change, 'Edited after the review opened')"); t.buttons["ia-preview-cancel"]();
  assert.deepEqual(t.ctx.state.draft, revised);
  assert.equal(t.ctx.preview, null);
  // Apply change and run after a later edit: nothing stale is applied, the newer edit stays, and nothing runs.
  t = open(); t.ctx.change = { plan: clone(revised) }; t.run("editDraft(change, 'Edited after the review opened')"); t.buttons["ia-preview-confirm"]();
  assert.equal(t.ctx.commits.length, 0); assert.deepEqual(t.ctx.state.draft, revised); assert.equal(t.ctx.preview, null);
  assert.match(t.ctx.notice, /edited after this review opened/);
  // Apply change and run with the draft unchanged: the reviewed change is committed.
  t = open(); t.buttons["ia-preview-confirm"]();
  assert.equal(t.ctx.commits.length, 1);
});

// The agency-action radio, through the actual renderResponses change handler (inert DOM, stand-in server).
function responsesHarness(state) {
  const vm = require("node:vm");
  const ui = fs.readFileSync(path.join(__dirname, "../static/investigation.js"), "utf8");
  const part = (a, b) => { const i = ui.indexOf(a); assert.ok(i >= 0, a); return ui.slice(i, ui.indexOf(b, i)); };
  const code = part("  function renderResponses(res) {", "  function textField(");
  const handlers = {}, runs = [], alerts = [];
  const h = (tag, attrs, ...kids) => { if (attrs && attrs.id && attrs.on) handlers[attrs.id] = attrs.on; return { tag, attrs, kids }; };
  const ctx = { C, ids, state, notice: "", preview: null, h, fill() {}, $: () => ({ focus() {} }), render() {}, runActive() { runs.push(1); },
    alertUser(m) { alerts.push(m); }, claimMap: (res) => new Map(res.claims.map((c) => [C.refKey(c.claim_ref), c])), programLabel: (x) => x,
    plain: (x) => String(x), humanWords: (x) => String(x), humanDate: (x) => String(x), hawaiiDisplay: (x) => x, AREA_LABEL: {}, TIER_LABEL: {},
    officialNextStep: () => null, claimTitle: () => "", btn: () => ({}) };
  vm.createContext(ctx); vm.runInContext(code, ctx);
  return { ctx, handlers, runs, alerts, render: () => vm.runInContext("renderResponses(C.currentResults(state))", ctx) };
}

test("choosing an agency action by hand never discards unapplied plan edits", () => {
  const s0 = run(C.createState(RUNTIME, ids));
  // Unapplied Advanced edit, no staff content (the action change would otherwise apply at once).
  const draft = clone(C.active(s0).plan); draft.service_area_id = "oahu";
  const dirty = Object.assign({}, s0, { draft });
  const before = C.canonical(dirty);
  let t = responsesHarness(dirty); t.render();
  const radio = Object.keys(t.handlers).find((k) => /^ia-act-\d+$/.test(k));
  assert.ok(radio, "an agency action radio is rendered");
  t.handlers[radio].change();
  assert.equal(C.canonical(t.ctx.state), before, "plan, draft, action and selections are byte-identical");
  assert.equal(t.runs.length, 0); assert.equal(t.ctx.preview, null);
  assert.ok(t.alerts.some((m) => /Apply or discard the plan edits first/.test(m)), "the reason is shown");
  // "No agency action" is guarded the same way.
  const withAction = ok(C.confirmChange(s0, C.chooseAction(s0, C.currentResults(s0).responses.find((r) => r.action_ref).action_ref).proposal, ids));
  const dirty2 = Object.assign({}, withAction, { draft });
  const before2 = C.canonical(dirty2);
  t = responsesHarness(dirty2); t.render(); t.handlers["ia-act-none"].change();
  assert.equal(C.canonical(t.ctx.state), before2);
  // With the draft clean, choosing an action still works as before.
  t = responsesHarness(s0); t.render(); t.handlers[radio].change();
  assert.ok(C.active(t.ctx.state).selected_action_ref, "action selected on a clean draft");
  assert.equal(t.alerts.length, 0);
});

// Finding notes and the one-action brief: a shortcut never moves a staff note out of every case file.
function annotatedState(note) {
  let s = run(C.createState(RUNTIME, ids));
  const pop = C.currentResults(s).claims.find((c) => /population_65_plus/.test(c.claim_ref.finding_id) && c.kind === "statistic");
  s = ok(C.toggleClaim(s, pop.claim_ref, true));
  s = ok(C.setFindingNote(s, pop.claim_ref.semantic_hash, note));
  return { s, pop };
}

test("a recommended brief that would leave out an annotated finding is held, and the note stays in the case", () => {
  const { s, pop } = annotatedState("Synthetic note to keep");
  const before = C.canonical(s);
  const t = briefActionHarness(s);
  t.run("createRecommended()");
  assert.equal(C.canonical(t.ctx.state), before, "selection, note and plan unchanged");
  assert.equal(t.briefs.length, 0, "no brief request");
  assert.match(t.ctx.notice, /staff note/i);
  const file = JSON.stringify(C.exportCase(t.ctx.state, { include_staff_work: true }));
  assert.ok(file.includes("Synthetic note to keep"), "the downloaded case still holds the note");
  const reopened = C.parseCaseFile(file, RUNTIME); assert.ok(reopened.ok);
  assert.ok(JSON.stringify(reopened.preview.staff_preview).includes("Synthetic note to keep"), "reopening the file offers the note");
  // A recommendation that keeps the annotated finding is not held.
  const t2 = briefActionHarness(s, { briefFocus: { claims: [pop], action: null, card: null, requested: 1, action_note: null } });
  t2.run("createRecommended()");
  assert.equal(t2.briefs.length, 1);
  assert.ok(JSON.stringify(C.activeStaff(t2.briefs[0])).includes("Synthetic note to keep"), "the note goes into the brief");
});

test("a note waiting for review after a manual deselection blocks the brief and the staff download until resolved", () => {
  const { s, pop } = annotatedState("Synthetic note to keep");
  let d = ok(C.toggleClaim(s, pop.claim_ref, false));            // staff remove the finding by hand
  const cmp = C.currentResults(d).claims.find((c) => c.kind === "comparison");
  d = ok(C.toggleClaim(d, cmp.claim_ref, true));
  assert.equal(C.pendingReview(d).length, 1, "the note waits for review");
  const t = waitingNotesHarness(d);
  assert.match(t.run("briefBlock(C.active(state), C.currentResults(state), false, false, C.activeStaff(state), C.reviewCurrent(state), C.pendingReview(state))") || "", /waiting for review/);
  assert.equal(t.run("staffDownloadBlock()") !== null, true, "a download with staff notes would omit the waiting note");
  // Selecting the finding again and copying the note back (or leaving it) is the explicit resolution.
  const copied = ok(C.copyParked(ok(C.toggleClaim(d, pop.claim_ref, true)), C.pendingReview(d)[0].key, {}));
  assert.ok(JSON.stringify(C.exportCase(copied, { include_staff_work: true })).includes("Synthetic note to keep"), "copied back, the note is in the case file");
  const t2 = waitingNotesHarness(copied);
  assert.equal(t2.run("staffDownloadBlock()"), null);
  const left = ok(C.leaveParked(d, C.pendingReview(d)[0].key));
  assert.equal(waitingNotesHarness(left).run("staffDownloadBlock()"), null, "leaving it is an intentional choice");
  // Other staff work is not affected by the guard.
  const titled = ok(C.setStaffText(s, "title", "Synthetic title"));
  assert.equal(waitingNotesHarness(titled).run("staffDownloadBlock()"), null);
});

function waitingNotesHarness(state) {
  const vm = require("node:vm");
  const ui = fs.readFileSync(path.join(__dirname, "../static/investigation.js"), "utf8");
  const part = (a, b) => { const i = ui.indexOf(a); assert.ok(i >= 0, a); return ui.slice(i, ui.indexOf(b, i)); };
  const ctx = { C, state, addDrafts: new Map(), $: () => null };
  vm.createContext(ctx); vm.runInContext(part("  function briefBlock(", "  function recommendedBrief(res)") + part("  // A note on a removed finding waits for review in this page only:", "  function renderCase(b, busy) {"), ctx);
  return { ctx, run: (x) => vm.runInContext(x, ctx) };
}

// Staff text still being typed when a language question finishes, through the actual pollLanguage, flushActive and
// focus functions: the text is committed before anything renders or runs, and focus stays where staff left it.
function languageCompletionHarness(state, reply, opts) {
  const vm = require("node:vm");
  const ui = fs.readFileSync(path.join(__dirname, "../static/investigation.js"), "utf8");
  const part = (a, b) => { const i = ui.indexOf(a); assert.ok(i >= 0, a); return ui.slice(i, ui.indexOf(b, i)); };
  const code = part("  function focusQuestionResult()", "  // ------------------------------------------------------------------ One Ask") +
    part("  function flushActive() {", "  async function askLanguage(text) {") + part("  // True while keyboard focus is still in the question area", "  function finish(result) {");
  const log = [], focused = [];
  // A Summary field in the Brief panel holding unfinished text (its change handler is the field's commit).
  const input = { tagName: "TEXTAREA", id: "ia-note", isConnected: true, value: "Unfinished staff summary",
    closest: (sel) => (sel === ".ia-tray" ? {} : null),
    dispatchEvent: (e) => { if (e.type === "change") ctx.state = ok(C.setStaffText(ctx.state, "note", input.value)); } };
  const ctx = { C, state, languageJob: null, languageResult: null, Date, Event: class { constructor(t) { this.type = t; } },
    document: { activeElement: input, body: {} }, $: (sel) => ({ hidden: false, focus() { focused.push(sel); } }),
    deadlineMs: () => 25000, currentLanguage: () => true, setTimeout: () => 0, clearTimeout() {},
    languagePost: async () => { if (opts && opts.fail) throw new Error("network"); return { http: 200, data: reply }; },
    askOnce: () => { log.push({ step: "askOnce", note: C.active(ctx.state).staff_edits.note || "" }); return !!(opts && opts.autorun); },
    cancelLanguage: (m) => { ctx.languageJob = null; ctx.languageResult = { status: "notice", message: m }; },
    render: () => log.push({ step: "render", note: C.active(ctx.state).staff_edits.note || "" }) };
  vm.createContext(ctx); vm.runInContext(code, ctx);
  const job = { request_id: "r", pending: true, cancelled: false, started: opts && opts.timedOut ? 0 : Date.now(), timer: null, polls: 0, deadlineTimer: 0 };
  ctx.languageJob = job;
  return { ctx, log, focused, input, poll: () => vm.runInContext("pollLanguage(languageJob)", ctx) };
}

test("staff text being typed survives a finished, refused, failed or timed-out question and keeps its focus", async () => {
  const s = run(C.createState(RUNTIME, ids));
  for (const [name, reply, opts] of [["auto-run answer", { status: "propose" }, { autorun: true }], ["refusal", { status: "unsupported" }, {}],
    ["poll failure", null, { fail: true }], ["timeout", null, { timedOut: true }]]) {
    const t = languageCompletionHarness(s, reply, opts);
    await t.poll();
    assert.equal(C.active(t.ctx.state).staff_edits.note, "Unfinished staff summary", name + ": typed text kept in the case state");
    assert.ok(t.log.length && t.log.every((x) => x.note === "Unfinished staff summary"), name + ": committed before any render or auto-run");
    assert.ok(JSON.stringify(C.exportCase(t.ctx.state, { include_staff_work: true })).includes("Unfinished staff summary"), name + ": in a staff-inclusive case file");
    assert.equal(t.focused.length, 0, name + ": focus is not taken from the staff field");
  }
});

// An accepted whole-plan proposal that singles out no step, through the actual renderAnswer and answerItem functions:
// related findings (not an answer) with sources and selection controls in plan order, no answer-focused brief, and
// the user's own selection leads to a brief. A single-step answer is still a focused answer.
function answerRegionHarness(state, basis) {
  const vm = require("node:vm");
  const ui = fs.readFileSync(path.join(__dirname, "../static/investigation.js"), "utf8");
  const part = (a, b) => { const i = ui.indexOf(a); assert.ok(i >= 0, a); return ui.slice(i, ui.indexOf(b, i)); };
  const code = part("  // The finding(s) the latest executed question asked for", "  // ------------------------------------------------------------------ plan editing");
  const box = { hidden: false, children: [] }, briefs = [];
  const nodes = (n, out) => { if (Array.isArray(n)) n.forEach((x) => nodes(x, out)); else if (n && typeof n === "object") { out.push(n); nodes(n.kids || [], out); } return out; };
  const ctx = { C, state, answerBasis: basis, briefFocus: null, languageResult: null, lastQuestion: basis.question, notice: "", questionSource: null, OP_LABEL: {},
    $: (sel) => (sel === "#ia-answer" ? box : { focus() {} }), fill: (el, kids) => { el.children = kids; },
    h: (tag, attrs, ...kids) => ({ tag, attrs: attrs || {}, kids, text: (attrs && attrs.text) || "" }),
    btn: (label, fn, attrs) => ({ tag: "button", attrs: Object.assign({}, attrs || {}), kids: [], text: label, fn }),
    answerCurrent: () => basis, claimMap: (res) => new Map(res.claims.map((c) => [C.refKey(c.claim_ref), c])), districtLabel: (d) => d.chamber + d.code,
    plural: (n, a, b) => n + " " + (n === 1 ? a : b), shortGeo: (x) => String(x || ""), valueWithUnit: (v) => String(v), moeWithUnit: (m) => String(m), periodText: () => null,
    plain: (x) => String(x), claimShortName: (c) => c.claim_ref.finding_id, srcLabel: (x) => x, humanWords: (x) => String(x), stepScope: () => "", render() {}, renderLanguage() {},
    set: (r) => { assert.equal(r.error, undefined); ctx.state = r.state; }, briefBlock: () => null, createBrief: () => briefs.push(clone(ctx.state)), document: { getElementById: () => null } };
  vm.createContext(ctx); vm.runInContext(code, ctx);
  vm.runInContext("renderAnswer(C.currentResults(state))", ctx);
  const all = nodes(box.children, []);
  return { ctx, box, briefs, all, text: all.map((n) => n.text).join(" | "), inputs: all.filter((n) => n.tag === "input" && n.attrs.type === "checkbox"), button: (id) => all.find((n) => n.attrs && n.attrs.id === id) };
}

test("an accepted whole-plan proposal shows related findings to choose from, never a false answer or answer brief", () => {
  const s = run(C.createState(RUNTIME, ids)), b = C.active(s), res = C.currentResults(s);
  const t = answerRegionHarness(s, { kind: "answer", question: "How many adults 65 and older live in House 28?", plan: clone(b.plan), step_ids: [], only: {}, branch_id: b.branch_id });
  assert.match(t.text, /Related findings · house028/); assert.doesNotMatch(t.text, /Answer · /);
  assert.match(t.text, /Not a completed answer/);
  const listed = res.plan.steps.flatMap((ps) => res.steps.find((x) => x.step_id === ps.step_id).claim_refs.map((r) => r.finding_id));
  assert.equal(t.inputs.length, Math.min(7, listed.length), "each related finding (up to seven before Show more) has a selection control");
  assert.equal(t.button("ia-answer-brief"), undefined, "no Create brief from this answer");
  const own = t.button("ia-answer-own-brief"); assert.ok(own && own.attrs.disabled, "brief from the user's selection, disabled until something is selected");
  // Selecting the population finding there, then creating the brief from that selection.
  const popId = "stat:house028:population_65_plus";
  const input = t.inputs.find((n) => /population_65_plus/.test(n.attrs["aria-label"] || "") || /population_65_plus/.test(n.attrs.id || ""))
    || t.inputs[listed.filter((f) => /^stat:/.test(f)).indexOf(popId)];
  input.attrs.on.change({ target: { checked: true } });
  assert.deepEqual(C.active(t.ctx.state).selected_claim_refs.map((r) => r.finding_id), [popId]);
  own.fn();
  assert.equal(t.briefs.length, 1);
  assert.deepEqual(C.active(t.briefs[0]).selected_claim_refs.map((r) => r.finding_id), [popId]);
  // A step with several findings (here four measures) is related findings even when the diff names the step ...
  const g = answerRegionHarness(s, { kind: "answer", question: "q", plan: clone(b.plan), step_ids: ["s1"], only: {}, branch_id: b.branch_id });
  assert.match(g.text, /Related findings · house028/); assert.equal(g.button("ia-answer-brief"), undefined);
  // ... and a step that resolves to one finding stays a focused answer.
  const one = clone(b.plan); one.steps = [{ step_id: "s1", operation: "profile", args: { metric_ids: ["population_65_plus"] } }];
  const s1 = run(C.createState(RUNTIME, ids, one)), b1 = C.active(s1);
  const f = answerRegionHarness(s1, { kind: "answer", question: "q", plan: clone(b1.plan), step_ids: ["s1"], only: {}, branch_id: b1.branch_id });
  assert.match(f.text, /Answer · house028/); assert.equal(f.inputs.length, 0); assert.equal(f.button("ia-answer-own-brief"), undefined);
});

// Staff text being typed when a restore reply arrives, through the actual send and flushActive functions: it is
// committed to the context it was typed in, before the reply switches the active context.
function sendHarness(state, fetchImpl, typed) {
  const vm = require("node:vm");
  const ui = fs.readFileSync(path.join(__dirname, "../static/investigation.js"), "utf8");
  const part = (a, b) => { const i = ui.indexOf(a); assert.ok(i >= 0, a); return ui.slice(i, ui.indexOf(b, i)); };
  const code = part("  async function send(request) {", "  // A run started by a question") + part("  // A reply can arrive while staff are typing.", "  async function askLanguage(text) {");
  const input = { tagName: "INPUT", type: "text", id: "ia-title", value: typed, closest: (sel) => (sel === ".ia-tray" ? {} : null),
    dispatchEvent: (e) => { if (e.type === "change") ctx.state = ok(C.setStaffText(ctx.state, "title", input.value)); } };
  const ctx = { C, state, Event: class { constructor(t) { this.type = t; } }, document: { activeElement: input }, render() {}, sha256Hex: async () => null,
    fetch: fetchImpl, finish: (result) => { ctx.state = result.state; ctx.outcome = result.outcome; }, answerAfterRun() {} };
  vm.createContext(ctx); vm.runInContext(code, ctx);
  return { ctx, send: (request) => vm.runInContext("send", ctx)(request) };
}

test("typing in one context while another is being restored keeps each title in its own context", async () => {
  // Context A (House 028) with a saved title; context B (House 013) open with its own saved title.
  let s = run(C.createState(RUNTIME, ids));
  s = ok(C.setStaffText(s, "title", "Saved House 28 title"));
  const a = C.active(s).branch_id;
  const p = C.proposeChange(s, { plan: C.setContext(s.draft, { district: { chamber: "house", code: "013" } }).plan });
  s = run(ok(C.confirmChange(s, p, ids)));
  s = ok(C.setStaffText(s, "title", "Saved House 13 title"));
  const b = C.active(s).branch_id;
  const titleOf = (st, id) => (st.case.branches.find((x) => x.branch_id === id).staff_edits || {}).title;
  for (const fail of [false, true]) {
    const r = C.beginRestore(s, a, ids); assert.equal(r.error, undefined);
    const fetchImpl = fail ? async () => { throw new Error("offline"); } : async (url, opts) => ({ status: 200, json: async () => reply(JSON.parse(opts.body)) });
    const t = sendHarness(r.state, fetchImpl, "Unblurred House 13 title");
    await t.send(r.request);
    assert.equal(titleOf(t.ctx.state, b), "Unblurred House 13 title", (fail ? "failed" : "successful") + " restore: the typed text stays with House 13");
    assert.equal(titleOf(t.ctx.state, a), "Saved House 28 title", (fail ? "failed" : "successful") + " restore: House 28 keeps its own title");
    assert.equal(C.active(t.ctx.state).branch_id, fail ? b : a);
  }
});

test("a fallback step with several findings is related findings to choose from; with one finding it is the answer", () => {
  const s = run(C.createState(RUNTIME, ids)), b = C.active(s), res = C.currentResults(s);
  // The kept or only step lists four measures and the diff names none: no single answer.
  const t = answerRegionHarness(s, { kind: "answer", question: "What is the poverty rate for adults 65+ in House 28?", plan: clone(b.plan), step_ids: ["s1"], only: {}, fallback: true, branch_id: b.branch_id });
  assert.match(t.text, /Related findings · house028/); assert.match(t.text, /did not single out which one answers it/);
  const stepFindings = res.steps.find((x) => x.step_id === "s1").claim_refs.map((r) => r.finding_id);
  assert.equal(t.inputs.length, stepFindings.length, "every finding of that step has a selection control");
  assert.equal(t.button("ia-answer-brief"), undefined, "no focused brief");
  // The poverty measure can be selected from there, then the brief is created from that selection.
  const povIndex = stepFindings.indexOf("stat:house028:poverty_rate_65_plus");
  t.inputs[povIndex].attrs.on.change({ target: { checked: true } });
  t.button("ia-answer-own-brief").fn();
  assert.deepEqual(C.active(t.briefs[0]).selected_claim_refs.map((r) => r.finding_id), ["stat:house028:poverty_rate_65_plus"]);
  // A fallback step with exactly one finding is the answer.
  const single = clone(b.plan); single.steps = [{ step_id: "s1", operation: "profile", args: { metric_ids: ["poverty_rate_65_plus"] } }];
  const s1 = run(C.createState(RUNTIME, ids, single)), b1 = C.active(s1);
  const f = answerRegionHarness(s1, { kind: "answer", question: "q", plan: clone(b1.plan), step_ids: ["s1"], only: {}, fallback: true, branch_id: b1.branch_id });
  assert.match(f.text, /Answer · house028/); assert.equal(f.inputs.length, 0);
});

// Staff text typed while a chosen case file is being read, through the actual file-input callback and flushActive:
// it is committed before the reopen preview renders (also when the read fails).
test("a title typed while a case file is being read is kept when the reopen preview opens", async () => {
  const vm = require("node:vm");
  const ui = fs.readFileSync(path.join(__dirname, "../static/investigation.js"), "utf8");
  const part = (a, b) => { const i = ui.indexOf(a); assert.ok(i >= 0, a); return ui.slice(i, ui.indexOf(b, i)); };
  const code = part("  // A reply can arrive while staff are typing.", "  async function askLanguage(text) {") +
    part('    $("#ia-import-file").addEventListener("change", async (e) => {', "    // Only the reviewed investigation brief prints");
  for (const failRead of [false, true]) {
    const s0 = ok(C.setStaffText(run(C.createState(RUNTIME, ids)), "title", "Saved title"));
    const handlers = {}, renders = [];
    const input = { tagName: "INPUT", type: "text", id: "ia-title", value: "Saved title", closest: (sel) => (sel === ".ia-tray" ? {} : null),
      dispatchEvent: (e) => { if (e.type === "change") ctx.state = ok(C.setStaffText(ctx.state, "title", input.value)); } };
    const ctx = { C, state: s0, importing: null, Event: class { constructor(t) { this.type = t; } }, document: { activeElement: input },
      $: (sel) => (sel === "#ia-import-file" ? { addEventListener: (ev, fn) => { handlers[ev] = fn; } } : { focus() {} }),
      render: () => renders.push(C.active(ctx.state).staff_edits.title) };
    vm.createContext(ctx); vm.runInContext(code, ctx);
    let release;
    const text = JSON.stringify(C.exportCase(s0, { include_staff_work: true }));
    const file = { size: text.length, text: () => new Promise((res, rej) => { release = () => (failRead ? rej(new Error("read")) : res(text)); }) };
    const pending = handlers.change({ target: { files: [file], value: "x" } });
    input.value = "Typed while the file is read";   // unblurred edit during the read
    release(); await pending;
    assert.equal(C.active(ctx.state).staff_edits.title, "Typed while the file is read", (failRead ? "failed read" : "preview") + ": typed title kept");
    assert.ok(renders.length && renders.every((t) => t === "Typed while the file is read"), "committed before the preview renders");
    assert.ok(ctx.importing, "the preview (or its error) opens");
  }
});

// Unfinished add-checklist-item text through the actual renderTray add-item code: it stays with the case and context it
// was typed in, comes back there, is added only there, survives a failed Add, and never appears in another case.
test("unfinished custom checklist text belongs to the context it was typed in", () => {
  const vm = require("node:vm");
  const ui = fs.readFileSync(path.join(__dirname, "../static/investigation.js"), "utf8");
  const start = ui.indexOf("    // Unfinished text in the add-item box"), end = ui.indexOf("    // staff notes and tracking", start);
  assert.ok(start > 0 && end > start);
  const nodes = new Map(), buttons = new Map(), alerts = [];
  const ctx = { C, state: run(C.createState(RUNTIME, ids)), addDrafts: new Map(), programLabel: (x) => x, $: (sel) => nodes.get(sel),
    h: (tag, attrs, ...kids) => { const n = { tag, attrs, kids, value: "" }; if (attrs && attrs.id) nodes.set("#" + attrs.id, n); return n; },
    btn: (label, fn, attrs) => { buttons.set(attrs.id, fn); return { label }; }, fill: (el, kids) => { el.kids = kids; },
    set: (r) => { if (r.error) { alerts.push(r.error.message); ctx.render(); return false; } ctx.state = r.state; ctx.render(); return true; } };
  vm.createContext(ctx);
  vm.runInContext("function renderCustom(){const b=C.active(state),card=null,check={},templates=[],loose=[],free=C.CHECK_IDS.slice(3).find(k=>!b.checklist_edits.some(e=>e.item_id===k));" + ui.slice(start, end) + "}" +
    ui.slice(ui.indexOf("  // A note on a removed finding waits for review in this page only:"), ui.indexOf("  function renderCase(b, busy) {")), ctx);
  const held = () => vm.runInContext("staffDownloadBlock()", ctx);
  ctx.render = () => vm.runInContext("renderCustom()", ctx);
  ctx.render();
  const h28 = C.active(ctx.state).branch_id;
  nodes.get("#ia-chk-new").value = "Call the House 28 partner";        // typed, not added
  assert.match(held() || "", /unfinished custom checklist item/, "a staff download (and context removal) is held while unfinished text is in no case file");
  const p = C.setContext(ctx.state.draft, { district: { chamber: "house", code: "013" } }).plan;
  ctx.state = run(ok(C.confirmChange(ctx.state, C.proposeChange(ctx.state, { plan: p }), ids)));
  ctx.render();
  const h13 = C.active(ctx.state).branch_id;
  assert.equal(nodes.get("#ia-chk-new").value, "", "House 013 does not show House 028's unfinished text");
  buttons.get("ia-chk-add")();                                          // empty box: nothing is added
  assert.deepEqual(C.active(ctx.state).checklist_edits, []);
  // Back in House 028 the unfinished text returns; a failed Add keeps it; a successful Add stores it only there.
  ctx.state = Object.assign({}, ctx.state, { case: Object.assign({}, ctx.state.case, { active_branch_id: h28 }) });
  ctx.render();
  assert.equal(nodes.get("#ia-chk-new").value, "Call the House 28 partner");
  const tooLong = "x".repeat(400);
  nodes.get("#ia-chk-new").value = tooLong; buttons.get("ia-chk-add")();
  assert.equal(alerts.length, 1, "the overlong item is refused");
  assert.equal(nodes.get("#ia-chk-new").value, tooLong, "a refused Add keeps the typed text");
  nodes.get("#ia-chk-new").value = "Call the House 28 partner"; buttons.get("ia-chk-add")();
  const items = (id) => ctx.state.case.branches.find((x) => x.branch_id === id).checklist_edits.map((c) => c.text);
  assert.deepEqual(items(h28), ["Call the House 28 partner"]); assert.deepEqual(items(h13), []);
  assert.equal(nodes.get("#ia-chk-new").value, "", "the box is empty after the item is added");
  assert.equal(held(), null, "once added, nothing is held");
  // A different case never inherits unfinished text.
  nodes.get("#ia-chk-new").value = "Unfinished in the first case"; ctx.render();
  ctx.state = run(C.createState(RUNTIME, ids)); ctx.render();
  assert.equal(nodes.get("#ia-chk-new").value, "");
});

// While a confirmed case-file import replays, the actual render code makes the outgoing case's controls inert, keeps
// Cancel request outside them, and re-enables them once nothing is pending (opened, failed or cancelled).
test("editing the outgoing case is paused only while a confirmed case-file import replays", () => {
  const vm = require("node:vm");
  const ui = fs.readFileSync(path.join(__dirname, "../static/investigation.js"), "utf8"), html = fs.readFileSync(path.join(__dirname, "../static/index.html"), "utf8");
  const a = ui.indexOf("    const importPaused = "), code = ui.slice(a, ui.indexOf("\n", ui.indexOf("forEach((sel)", a)) + 1);
  const regions = { "#ia-question": {}, ".ia-grid": {}, "#ia-brief": {} };
  Object.values(regions).forEach((el) => { el.attrs = {}; el.setAttribute = (k, v) => { el.attrs[k] = v; }; el.removeAttribute = (k) => { delete el.attrs[k]; }; });
  const pause = (pending) => { const ctx = { state: { pending }, document: { querySelector: (sel) => regions[sel] } }; vm.createContext(ctx); vm.runInContext(code, ctx); };
  pause({ kind: "import" });
  Object.entries(regions).forEach(([sel, el]) => { assert.equal(el.inert, true, sel + " inert during the import replay"); assert.equal(el.attrs["aria-busy"], "true"); });
  for (const pending of [null, { kind: "run" }, { kind: "restore" }, { kind: "brief" }]) {
    pause(pending);
    Object.entries(regions).forEach(([sel, el]) => { assert.equal(el.inert, false, sel + " editable when " + (pending ? pending.kind : "nothing") + " is pending"); assert.equal(el.attrs["aria-busy"], undefined); });
  }
  // Cancel request lives in the context bar, outside every paused region.
  const grid = html.indexOf('<div class="ia-grid">'), cancel = html.indexOf('id="ia-cancel"'), brief = html.indexOf('id="ia-brief"'), q0 = html.indexOf('id="ia-question"'), q1 = html.indexOf("</section>", html.indexOf('id="ia-answer"'));
  assert.ok(cancel > 0 && cancel < grid && !(cancel > q0 && cancel < q1) && cancel < brief, "Cancel request stays usable");
});

test("a newly added step with several findings is related findings, so the asked measure can be chosen", () => {
  const p = { district: { state_fips: "15", chamber: "house", code: "028", boundary_session: 2024 }, map_session: 2026, issue_id: "custom", service_area_id: null,
    steps: [{ step_id: "s1", operation: "profile", args: { metric_ids: ["population_65_plus", "poverty_rate_65_plus", "median_age"] } }] };
  const s = run(C.createState(RUNTIME, ids, p)), b = C.active(s);
  // The diff names the added step but not which of its three measures answers the question.
  const t = answerRegionHarness(s, { kind: "answer", question: "What is the poverty rate for adults 65+?", plan: clone(b.plan), step_ids: ["s1"], only: {}, branch_id: b.branch_id });
  assert.match(t.text, /Related findings · house028/); assert.equal(t.button("ia-answer-brief"), undefined, "no brief claiming to be the answer");
  assert.equal(t.inputs.length, 3, "all three measures with selection controls");
  t.inputs[1].attrs.on.change({ target: { checked: true } });
  t.button("ia-answer-own-brief").fn();
  assert.deepEqual(C.active(t.briefs[0]).selected_claim_refs.map((r) => r.finding_id), ["stat:house028:poverty_rate_65_plus"]);
});

// The reopen preview's Cancel, through the actual renderCase callback: after Replay and open it cancels the pending
// import like Cancel request, so the case and its staff work stay, editing returns and the late reply is ignored.
test("Cancel in the reopen preview also cancels a confirmed import that is still replaying", () => {
  const vm = require("node:vm");
  const ui = fs.readFileSync(path.join(__dirname, "../static/investigation.js"), "utf8");
  const part = (a, b) => { const i = ui.indexOf(a); assert.ok(i >= 0, a); return ui.slice(i, ui.indexOf(b, i)); };
  const code = part("  // Name a staff group in the reopen preview", "  // ------------------------------------------------------------------ map");
  const a = ui.indexOf("    const importPaused = "), pauseCode = ui.slice(a, ui.indexOf("\n", ui.indexOf("forEach((sel)", a)) + 1);
  const harness = (state, importing) => {
    const buttons = {}, el = () => ({ hidden: false, checked: false, focus() {} });
    const els = { "#ia-download-staff": el(), "#ia-staff-preview": el(), "#ia-import-preview": el(), "#ia-download": el(), "#ia-branches": el(), "#ia-import-file": el(), "#ia-chk-new": null };
    const ctx = { C, state, importing, notice: "", savedDigest: null, addDrafts: new Map(), $: (sel) => els[sel] !== undefined ? els[sel] : el(),
      h: (tag, attrs, ...kids) => ({ tag, attrs, kids }), fill() {}, btn: (label, fn, attrs) => { if (attrs && attrs.id) buttons[attrs.id] = fn; return {}; },
      render() {}, contextName: () => "Context", planLabel: () => "plan", replayHelp: () => null, staffLine: () => [], OP_LABEL: {}, plural: (n, x, y) => n + " " + (n === 1 ? x : y) };
    vm.createContext(ctx); vm.runInContext(code, ctx);
    vm.runInContext("renderCase(C.active(state), !!state.pending)", ctx);
    return { ctx, buttons };
  };
  const s0 = ok(C.setStaffText(run(C.createState(RUNTIME, ids)), "title", "Outgoing title"));
  const parsed = C.parseCaseFile(PUBLIC_TEXT, RUNTIME); assert.ok(parsed.ok);
  // Replay and open was chosen: the import is pending.
  const begun = C.beginImport(s0, parsed, { accept_staff_work: false }, ids); assert.equal(begun.error, undefined);
  assert.equal(begun.state.pending.kind, "import");
  let t = harness(begun.state, parsed);
  t.buttons["ia-import-cancel"]();
  assert.equal(t.ctx.state.pending, null, "the replay is cancelled");
  assert.equal(t.ctx.state.case.case_id, s0.case.case_id, "the current case is kept");
  assert.equal(C.active(t.ctx.state).staff_edits.title, "Outgoing title");
  assert.equal(t.ctx.importing, null); assert.match(t.ctx.notice, /current case is kept/);
  const regions = { "#ia-question": {}, ".ia-grid": {}, "#ia-brief": {} };
  Object.values(regions).forEach((r) => { r.inert = true; r.setAttribute = () => {}; r.removeAttribute = () => {}; });
  const pctx = { state: t.ctx.state, document: { querySelector: (sel) => regions[sel] } }; vm.createContext(pctx); vm.runInContext(pauseCode, pctx);
  Object.values(regions).forEach((r) => assert.equal(r.inert, false, "editing is back on after the render"));
  const late = C.applyResponse(t.ctx.state, reply(begun.request), meta(begun.request));
  assert.equal(late.outcome, "discarded", "the matching late reply is ignored");
  // Cancel before Replay and open only closes the preview.
  t = harness(s0, parsed);
  t.buttons["ia-import-cancel"]();
  assert.equal(t.ctx.state, s0, "nothing else changes"); assert.equal(t.ctx.importing, null); assert.match(t.ctx.notice, /current case is unchanged/);
  // Cancel request (main) still uses the same reducer: the late reply is ignored there too.
  assert.equal(C.applyResponse(C.cancelPending(begun.state), reply(begun.request), meta(begun.request)).outcome, "discarded");
});

// A question being asked cannot be edited, so typing can no longer cancel a request that may already be charged. Real
// cancelLanguage/askLanguage/pollLanguage/lockQuestion and the real question "input" listener, stand-in language server.
function pendingQuestionHarness(state, startReply, statusReply) {
  const vm = require("node:vm");
  const ui = fs.readFileSync(path.join(__dirname, "../static/investigation.js"), "utf8");
  const part = (a, b) => { const i = ui.indexOf(a); assert.ok(i >= 0, a); return ui.slice(i, ui.indexOf(b, i)); };
  const listener = part('$("#ia-question-text").addEventListener("input", ', "\n");
  const code = part("  function cancelLanguage(message, recover) {", "  // ------------------------------------------------------------------ One Ask") +
    "\n  var onQuestionInput = null; const $real = $; " + listener.replace('$("#ia-question-text").addEventListener("input", ', "onQuestionInput = (").replace(/\);\s*$/, ");");
  const text = { id: "ia-question-text", readOnly: false, value: "How many adults 65 and older live in House 28?" };
  const posts = [], renders = [], timers = [];
  const ctx = { C, state, languageJob: null, languageResult: null, lastQuestion: "", notice: "", Date, Error,
    catalog: { language: { enabled: true } }, window: { IALanguage: { matches: () => true } }, ids: { uuid: () => "q-1" },
    document: { activeElement: text }, $: (sel) => (sel === "#ia-question-text" ? text : { hidden: true, focus() {} }),
    languageContext: () => ({}), deadlineMs: () => 25000, languagePolicy: () => "", alertUser: (m) => { throw new Error("alert " + m); },
    userInComposer: () => false, askOnce: () => false,
    setTimeout: (fn) => { timers.push(fn); return timers.length; }, clearTimeout() {},
    render: () => renders.push({ readOnly: text.readOnly, value: text.value, pending: !!(ctx.languageJob && ctx.languageJob.pending) }),
    languagePost: async (action, body) => { posts.push(action); if (action === "start") return startReply(); if (action === "status") return statusReply(body); return { http: 200, data: {} }; } };
  vm.createContext(ctx); vm.runInContext(code, ctx);
  return { ctx, text, posts, renders, timers, input: () => vm.runInContext("onQuestionInput()", ctx),
    ask: () => vm.runInContext("askLanguage", ctx)(text.value), poll: () => vm.runInContext("pollLanguage(languageJob)", ctx) };
}

test("a pending question is read-only, typing never cancels it, and every finish/error/cancel path unlocks it with the question kept", async () => {
  const s = run(C.createState(RUNTIME, ids));
  const accepted = () => ({ http: 202, data: { request_id: "q-1", status: "pending" } });
  const question = "How many adults 65 and older live in House 28?";
  // 1. Pending: read-only from the first render, text kept; an input event does not cancel or change the job.
  let t = pendingQuestionHarness(s, accepted, () => ({ http: 200, data: { request_id: "q-1", status: "unsupported" } }));
  await t.ask();
  assert.deepEqual(t.renders[0], { readOnly: true, value: question, pending: true }, "locked while the question is being read");
  assert.equal(t.text.readOnly, true);
  const job = t.ctx.languageJob; t.input();
  assert.equal(t.ctx.languageJob, job, "typing during a pending question keeps the same request");
  assert.equal(job.pending, true); assert.deepEqual(t.posts, ["start"], "no cancel was sent for a possibly charged request");
  // 2. Finished answer: unlocked, question kept, still no cancel; editing afterwards only clears the shown answer (as before).
  await t.poll();
  assert.equal(t.text.readOnly, false, "unlocked when the answer arrives"); assert.equal(t.text.value, question);
  assert.deepEqual(t.posts, ["start", "status"]);
  t.input(); assert.equal(t.ctx.languageJob, null); assert.deepEqual(t.posts, ["start", "status"], "clearing a finished answer sends nothing");
  // 3. Poll failure: unlocked, question kept.
  t = pendingQuestionHarness(s, accepted, () => { throw new Error("network"); });
  await t.ask(); assert.equal(t.text.readOnly, true); await t.poll();
  assert.equal(t.text.readOnly, false, "unlocked after a failed status check"); assert.equal(t.text.value, question);
  assert.equal(t.ctx.languageResult.status, "error");
  // 4. Refused start (shared limit): unlocked, question kept.
  t = pendingQuestionHarness(s, () => ({ http: 429, data: { code: "shared_demonstration_rate_limit", message: "limit" } }), () => null);
  await t.ask();
  assert.equal(t.text.readOnly, false, "unlocked after a refused start"); assert.equal(t.text.value, question); assert.deepEqual(t.posts, ["start"]);
  // 5. Explicit Cancel keeps its behavior (it may still be charged) and unlocks.
  t = pendingQuestionHarness(s, accepted, () => null);
  await t.ask(); vm_cancel(t);
  assert.equal(t.text.readOnly, false, "unlocked after Cancel"); assert.deepEqual(t.posts, ["start", "cancel"]); assert.equal(t.text.value, question);
  // 6. Time-out: unlocked.
  t = pendingQuestionHarness(s, accepted, () => null);
  await t.ask(); t.timers[0]();
  assert.equal(t.text.readOnly, false, "unlocked after the time-out"); assert.equal(t.ctx.languageJob, null);
  function vm_cancel(h) { require("node:vm").runInContext("cancelLanguage('Question cancelled. Your work is unchanged.'); render();", h.ctx); }
});
