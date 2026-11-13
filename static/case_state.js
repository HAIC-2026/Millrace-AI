/* IA-1 browser case state. Pure functions only: no DOM, network, storage or clock.
   Loaded as a plain script (window.IACase) and by Node tests (module.exports).
   It computes no factual value and never trusts factual text, hashes or HTML from a case file.
   Retention of a selection is decided by the server's selection_review plus an exact
   claim identity match in the returned claims, never by numeric or label equality. */
(function (root, factory) {
  "use strict";
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.IACase = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const SCHEMA_VERSION = "haic-investigation/1";
  const OPERATION_VERSION = "ia-core/1";
  const CASE_SCHEMA = "haic-case/1";
  const RECIPES = ["aging_at_home/1", "custom/1"];
  const ISSUES = ["aging_at_home", "custom"];
  const OPERATIONS = ["profile", "compare", "program_evidence", "outreach_lead", "administrative_evidence"];
  const SERVICE_AREAS = ["statewide", "oahu", "hawaii_island", "maui", "molokai", "lanai", "kauai", "kalawao"];
  const ACTION_IDS = ["kupuna_verify/1", "snap_verify/1", "medquest_verify/1", "hcv_verify/1"];
  const CHECK_IDS = ["agency_route", "partner_plan", "next_check", "custom1", "custom2", "custom3"];
  const TEMPLATE_CHECK_IDS = CHECK_IDS.slice(0, 3);
  const TOKEN_KEYS = ["request_id", "case_id", "branch_id", "revision", "snapshot_id", "schema_version", "operation_version", "recipe_version"];
  const LIMITS = {
    steps: 8, selections: 8, branches: 4, title: 90, note: 400, next_steps: 300, finding_note: 160,
    checklist_text: 120, owner_role: 80, tracking_label: 80, baseline: 1000000000, utterance: 500,
    case_bytes: 262144, case_depth: 16, revision: 2147483647,
  };
  const HASH = /^sha256:[0-9a-f]{64}$/;
  const UUID4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
  const STEP_ID = /^s[0-9]{1,3}$/;
  const ID_TEXT = /^[A-Za-z0-9_.\/-]{1,120}$/;
  const GEO_ID = /^HI-(?:STATE|COUNTY-[0-9]{3}|HOUSE-[0-9]{3}|SENATE-[0-9]{3})-2024$/;
  const ISO_DATE = /^[0-9]{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01])$/;
  const AGING_METRICS = ["population_65_plus", "male_householder_65_plus_living_alone", "female_householder_65_plus_living_alone", "poverty_rate_65_plus"];

  const clone = (v) => (v === undefined ? undefined : JSON.parse(JSON.stringify(v)));
  const isObj = (v) => v !== null && typeof v === "object" && !Array.isArray(v);
  const same = (a, b) => canonical(a) === canonical(b);

  // Stable serialization for local equality only. It is not the server's claim canonicalization.
  function canonical(v) {
    if (Array.isArray(v)) return "[" + v.map(canonical).join(",") + "]";
    if (isObj(v)) return "{" + Object.keys(v).sort().map((k) => JSON.stringify(k) + ":" + canonical(v[k])).join(",") + "}";
    return JSON.stringify(v === undefined ? null : v);
  }

  // The typed Plan's identity text for edits_reviewed_for: NFC strings and keys, recursively sorted keys,
  // compact separators, literal Unicode, array order kept. The caller hashes it (SHA-256, "sha256:" prefix).
  // This identifies the staff-typed plan only; it never stands in for a factual claim binding.
  function planCanonical(v) {
    if (typeof v === "string") return JSON.stringify(v.normalize("NFC"));
    if (Array.isArray(v)) return "[" + v.map(planCanonical).join(",") + "]";
    if (isObj(v)) return "{" + Object.keys(v).map((k) => [k.normalize("NFC"), v[k]]).sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0)).map((e) => JSON.stringify(e[0]) + ":" + planCanonical(e[1])).join(",") + "}";
    return JSON.stringify(v === undefined ? null : v);
  }

  // A real calendar date in YYYY-MM-DD form (2026-02-31 is refused).
  function validDate(v) {
    if (typeof v !== "string" || !ISO_DATE.test(v)) return false;
    const y = Number(v.slice(0, 4)), m = Number(v.slice(5, 7)), d = Number(v.slice(8, 10)), t = new Date(Date.UTC(y, m - 1, d));
    return t.getUTCFullYear() === y && t.getUTCMonth() === m - 1 && t.getUTCDate() === d;
  }

  function utf8Length(s) {
    let n = 0;
    for (let i = 0; i < s.length; i += 1) {
      const c = s.charCodeAt(i);
      if (c < 0x80) n += 1;
      else if (c < 0x800) n += 2;
      else if (c >= 0xd800 && c <= 0xdbff && i + 1 < s.length) { n += 4; i += 1; }
      else n += 3;
    }
    return n;
  }

  function depthOf(v) {
    let max = 0;
    const stack = [[v, 1]];
    while (stack.length) {
      const [x, d] = stack.pop();
      if (x !== null && typeof x === "object") {
        if (d > max) max = d;
        if (max > 64) return max;
        (Array.isArray(x) ? x : Object.values(x)).forEach((c) => stack.push([c, d + 1]));
      }
    }
    return max;
  }

  const refKey = (r) => r.snapshot_id + "|" + r.finding_id + "|" + r.semantic_hash;
  const actionKey = (a) => (a ? a.action_id + "|" + a.semantic_hash : "");
  const districtKey = (d) => d.chamber + "-" + d.code + "-" + d.boundary_session;

  // ------------------------------------------------------------------ plan
  function defaultPlan(district) {
    const d = district || { chamber: "house", code: "028" };
    return {
      district: { state_fips: "15", chamber: d.chamber, code: d.code, boundary_session: 2024 },
      map_session: 2026, issue_id: "aging_at_home", service_area_id: null,
      steps: [
        { step_id: "s1", operation: "profile", args: { metric_ids: AGING_METRICS.slice() } },
        { step_id: "s2", operation: "compare", args: { metric_ids: ["poverty_rate_65_plus"], comparison_geography: "HI-STATE-2024" } },
        { step_id: "s3", operation: "program_evidence", args: { program_ids: ["kupuna_care_hi"] } },
        { step_id: "s4", operation: "outreach_lead", args: { program_id: "kupuna_care_hi" } },
      ],
    };
  }

  function validPlan(plan, path, issues) {
    const p = path || "plan";
    const bad = (where, message) => { issues.push({ path: where, code: "invalid", message: message }); return false; };
    if (!exactKeys(plan, ["district", "map_session", "issue_id", "service_area_id", "steps"])) return bad(p, "A plan needs exactly district, map_session, issue_id, service_area_id and steps.");
    const d = plan.district;
    if (!exactKeys(d, ["state_fips", "chamber", "code", "boundary_session"]) || d.state_fips !== "15" ||
        (d.chamber !== "house" && d.chamber !== "senate") || typeof d.code !== "string" || !/^[0-9]{3}$/.test(d.code) ||
        Number(d.code) < 1 || Number(d.code) > (d.chamber === "house" ? 51 : 25) || d.boundary_session !== 2024) return bad(p + ".district", "Only an admitted 2024 Hawaiʻi House or Senate district is supported.");
    if (plan.map_session !== 2024 && plan.map_session !== 2026) return bad(p + ".map_session", "Map session must be 2024 or 2026.");
    if (!ISSUES.includes(plan.issue_id)) return bad(p + ".issue_id", "Issue must be aging_at_home or custom.");
    if (plan.service_area_id !== null && !SERVICE_AREAS.includes(plan.service_area_id)) return bad(p + ".service_area_id", "Unknown service-area choice.");
    if (!Array.isArray(plan.steps) || plan.steps.length > LIMITS.steps) return bad(p + ".steps", "A plan holds at most eight steps.");
    const seen = new Set();
    for (let i = 0; i < plan.steps.length; i += 1) {
      const s = plan.steps[i], sp = p + ".steps[" + i + "]";
      if (!exactKeys(s, ["step_id", "operation", "args"]) || typeof s.step_id !== "string" || !STEP_ID.test(s.step_id) || seen.has(s.step_id)) return bad(sp, "Each step needs a unique s-number identifier, an operation and args.");
      seen.add(s.step_id);
      if (!validArgs(s.operation, s.args)) return bad(sp + ".args", s.operation === "outreach_lead" ? "reviewed_basis_required: an outreach hypothesis takes only its program; its reviewed measure set and State references are fixed." : "Arguments do not match the supported operation.");
    }
    return true;
  }

  function idList(v, min, max, pattern) {
    return Array.isArray(v) && v.length >= min && v.length <= max && v.every((x) => typeof x === "string" && (pattern || ID_TEXT).test(x)) && new Set(v).size === v.length;
  }

  function validArgs(operation, a) {
    if (!isObj(a)) return false;
    if (operation === "profile") return exactKeys(a, ["metric_ids"]) && (a.metric_ids === null || idList(a.metric_ids, 1, 20));
    if (operation === "compare") return exactKeys(a, ["metric_ids", "comparison_geography"]) && idList(a.metric_ids, 1, 4) && typeof a.comparison_geography === "string" && GEO_ID.test(a.comparison_geography);
    if (operation === "program_evidence") return exactKeys(a, ["program_ids"]) && idList(a.program_ids, 1, 5);
    if (operation === "outreach_lead") return exactKeys(a, ["program_id"]) && typeof a.program_id === "string" && ID_TEXT.test(a.program_id);
    if (operation === "administrative_evidence") return exactKeys(a, ["observation_ids"]) && idList(a.observation_ids, 1, 8);
    return false;
  }

  function exactKeys(o, keys, optional) {
    if (!isObj(o)) return false;
    const have = Object.keys(o), opt = optional || [];
    return keys.every((k) => have.includes(k)) && have.every((k) => keys.includes(k) || opt.includes(k));
  }

  function nextStepId(plan) {
    const used = new Set(plan.steps.map((s) => s.step_id));
    for (let n = 1; n <= 999; n += 1) if (!used.has("s" + n)) return "s" + n;
    return null;
  }

  // Each plan edit returns { plan } or { error: { code, message } } and never mutates its input.
  function addStep(plan, operation, args) {
    if (plan.steps.length >= LIMITS.steps) return err("plan_full", "A plan holds at most eight steps. Remove a step before adding another.");
    if (!OPERATIONS.includes(operation)) return err("unsupported_step", "That operation is not one of the five supported steps.");
    if (!validArgs(operation, args)) return err(operation === "outreach_lead" ? "reviewed_basis_required" : "invalid_args", operation === "outreach_lead" ? "An outreach hypothesis uses its complete reviewed measure set and State references. Choose only the program." : "Complete this step's scope before adding it.");
    if (operation === "compare" && args.comparison_geography === geographyIdOf(plan.district)) return err("self_comparison", "A district cannot be compared with itself. Choose another geography.");
    const out = clone(plan);
    out.steps.push({ step_id: nextStepId(plan), operation: operation, args: clone(args) });
    return { plan: out };
  }

  function removeStep(plan, stepId) {
    if (!plan.steps.some((s) => s.step_id === stepId)) return err("unknown_step", "That step is not in the plan.");
    const out = clone(plan);
    out.steps = out.steps.filter((s) => s.step_id !== stepId);
    return { plan: out };
  }

  function moveStep(plan, stepId, delta) {
    const i = plan.steps.findIndex((s) => s.step_id === stepId), j = i + delta;
    if (i < 0) return err("unknown_step", "That step is not in the plan.");
    if (j < 0 || j >= plan.steps.length) return { plan: plan };
    const out = clone(plan);
    const [s] = out.steps.splice(i, 1);
    out.steps.splice(j, 0, s);
    return { plan: out };
  }

  function rescopeStep(plan, stepId, args) {
    const i = plan.steps.findIndex((s) => s.step_id === stepId);
    if (i < 0) return err("unknown_step", "That step is not in the plan.");
    const op = plan.steps[i].operation;
    if (!validArgs(op, args)) return err(op === "outreach_lead" ? "reviewed_basis_required" : "invalid_args", op === "outreach_lead" ? "This hypothesis keeps its complete reviewed basis and State references. Restore the full basis, remove the hypothesis, or keep only the general program reference." : "That scope is not supported for this step.");
    if (op === "compare" && args.comparison_geography === geographyIdOf(plan.district)) return err("self_comparison", "A district cannot be compared with itself. Choose another geography.");
    const out = clone(plan);
    out.steps[i].args = clone(args);
    return { plan: out };
  }

  function geographyIdOf(d) { return "HI-" + d.chamber.toUpperCase() + "-" + d.code + "-2024"; }

  function setContext(plan, patch) {
    const out = clone(plan);
    if (patch.district) out.district = { state_fips: "15", chamber: patch.district.chamber, code: patch.district.code, boundary_session: 2024 };
    if ("map_session" in patch) out.map_session = patch.map_session;
    if ("service_area_id" in patch) out.service_area_id = patch.service_area_id;
    if ("issue_id" in patch && patch.issue_id !== plan.issue_id) {
      out.issue_id = patch.issue_id;
      // A new issue brings its recipe; Custom keeps the visible steps for staff to edit.
      if (patch.issue_id === "aging_at_home") out.steps = defaultPlan(out.district).steps;
    }
    const issues = [];
    if (!validPlan(out, "plan", issues)) return err("invalid_context", issues[0].message);
    const self = out.steps.find((s) => s.operation === "compare" && s.args.comparison_geography === geographyIdOf(out.district));
    if (self) return { plan: out, clarification: { code: "self_comparison", step_id: self.step_id, message: "Step " + self.step_id + " would compare this district with itself. Choose another comparison geography or remove that step." } };
    return { plan: out };
  }

  function err(code, message) { return { error: { code: code, message: message } }; }

  // What changed between the committed plan and a proposal. Pure reorder and no-op are not material.
  function classifyChange(a, b) {
    const kinds = new Set();
    if (districtKey(a.district) !== districtKey(b.district)) kinds.add("district");
    if (a.map_session !== b.map_session) kinds.add("map_session");
    if (a.issue_id !== b.issue_id) kinds.add("issue");
    if (a.service_area_id !== b.service_area_id) kinds.add("service_area");
    const before = new Map(a.steps.map((s) => [s.step_id, s])), after = new Map(b.steps.map((s) => [s.step_id, s]));
    const programOp = (s) => s.operation === "program_evidence" || s.operation === "outreach_lead";
    before.forEach((s, id) => {
      const t = after.get(id);
      if (!t) kinds.add(programOp(s) ? "program" : "step_scope");
      else if (s.operation !== t.operation) kinds.add(programOp(s) || programOp(t) ? "program" : "step_scope");
      else if (!same(s.args, t.args)) {
        if (programOp(s)) kinds.add("program");
        else if (s.operation === "compare" && s.args.comparison_geography !== t.args.comparison_geography) {
          kinds.add("comparator");
          if (!same(s.args.metric_ids, t.args.metric_ids)) kinds.add("step_scope");
        } else kinds.add("step_scope");
      }
    });
    after.forEach((t, id) => { if (!before.has(id)) kinds.add(programOp(t) ? "program" : "step_scope"); });
    const order = a.steps.map((s) => s.step_id).join(",") !== b.steps.map((s) => s.step_id).join(",");
    return { material: kinds.size > 0, kinds: Array.from(kinds), reorder_only: kinds.size === 0 && order, noop: kinds.size === 0 && !order };
  }

  // ------------------------------------------------------------------ case
  function emptyBranch(runtime, branchId, plan) {
    return {
      branch_id: branchId, release_id: runtime.release_id, snapshot_id: runtime.snapshot_id,
      operation_version: runtime.operation_version, recipe_version: plan.issue_id + "/1", plan: clone(plan),
      selected_claim_refs: [], selected_action_ref: null, staff_edits: {}, checklist_edits: [], tracking: null,
      review_state: "clean", last_ready_revision: null,
    };
  }

  // runtime: { snapshot_id, release_id, operation_version, schema_version, recipe_versions } from the server catalog.
  // ids: { uuid() } supplied by the caller (crypto.randomUUID in the browser).
  function createState(runtime, ids, plan) {
    const branchId = ids.uuid();
    const p = plan || defaultPlan();
    return {
      runtime: clone(runtime),
      case: { case_schema: CASE_SCHEMA, case_id: ids.uuid(), active_branch_id: branchId, next_revision: 1, branches: [emptyBranch(runtime, branchId, p)] },
      draft: clone(p), pending: null, results: {}, parked: {}, reviewed: {}, exclusions: {}, briefs: {}, retired: {}, copied: {}, last_error: null,
    };
  }

  const branchOf = (state, id) => state.case.branches.find((b) => b.branch_id === (id || state.case.active_branch_id)) || null;
  const active = (state) => branchOf(state);

  function staffItems(branch) {
    const items = [], e = branch.staff_edits || {};
    ["title", "note", "next_steps"].forEach((k) => { if (typeof e[k] === "string" && e[k] !== "") items.push({ key: k, kind: k, value: e[k] }); });
    Object.keys(e.finding_notes || {}).forEach((h) => { if (e.finding_notes[h]) items.push({ key: "finding_note:" + h, kind: "finding_note", semantic_hash: h, value: e.finding_notes[h] }); });
    (branch.checklist_edits || []).forEach((c) => {
      if (Object.keys(c).length > 1) items.push({ key: "checklist:" + c.item_id, kind: "checklist", item: clone(c) });
    });
    if (branch.tracking) items.push({ key: "tracking", kind: "tracking", tracking: clone(branch.tracking) });
    return items;
  }
  const hasStaffContent = (branch) => staffItems(branch).length > 0;

  function runtimeMatches(state, branch) {
    const r = state.runtime;
    return branch.snapshot_id === r.snapshot_id && branch.operation_version === r.operation_version &&
      (r.recipe_versions || RECIPES).includes(branch.recipe_version);
  }

  // Preview of a proposed plan and/or selected-response change. Nothing is changed here.
  function proposeChange(state, proposal) {
    const b = active(state);
    const plan = proposal.plan || b.plan;
    const change = classifyChange(b.plan, plan);
    const kinds = change.kinds.slice();
    const actionChanged = "action" in proposal && actionKey(proposal.action) !== actionKey(b.selected_action_ref);
    if (actionChanged) kinds.push("response");
    const material = kinds.length > 0;
    const worth = b.last_ready_revision !== null || hasStaffContent(b) || b.selected_claim_refs.length > 0 || b.selected_action_ref !== null;
    // A first response choice on a branch without staff content parks nothing and needs no new branch.
    const actionOnly = actionChanged && change.kinds.length === 0;
    const fork = material && worth && !(actionOnly && !hasStaffContent(b));
    const clearsSelections = kinds.includes("district") || kinds.includes("issue");
    const clearsAction = clearsSelections || kinds.includes("program");
    return {
      plan: clone(plan), action: actionChanged ? clone(proposal.action) : undefined, action_changed: actionChanged,
      material: material, kinds: kinds, reorder_only: change.reorder_only, noop: change.noop && !actionChanged, fork: fork,
      branch_limit: fork && state.case.branches.length >= LIMITS.branches,
      clears_selections: clearsSelections, clears_action: clearsAction && !actionChanged,
      parked: fork ? staffItems(b).map((i) => i.key) : [],
      provisional_selections: clearsSelections ? 0 : b.selected_claim_refs.length,
      origin_branch_id: b.branch_id,
    };
  }

  // Commit a previewed change. Material changes on a branch with work open a new branch; the
  // original branch, its selections, notes and checklist progress stay exactly as they were.
  function confirmChange(state, proposal, ids) {
    const origin = active(state);
    if (!proposal || proposal.origin_branch_id !== origin.branch_id) return err("stale_preview", "The case changed after this preview. Review the change again.");
    const issues = [];
    if (!validPlan(proposal.plan, "plan", issues)) return err("invalid_plan", issues[0].message);
    // The preview is re-derived from the current case, so a preview shown earlier cannot carry stale effects.
    proposal = proposeChange(state, proposal.action_changed ? { plan: proposal.plan, action: proposal.action } : { plan: proposal.plan });
    if (proposal.branch_limit) return err("branch_limit", "This case already holds four branches. Download the case, then remove one branch before applying this change.");
    const out = clone(state);
    out.last_error = null;
    if (!proposal.fork) {
      const b = active(out);
      b.plan = clone(proposal.plan);
      b.recipe_version = proposal.plan.issue_id + "/1";
      if (proposal.clears_selections) b.selected_claim_refs = [];
      if (proposal.clears_action) b.selected_action_ref = null;
      if (proposal.action_changed) b.selected_action_ref = clone(proposal.action);
      out.draft = clone(proposal.plan);
      return { state: out, forked: false };
    }
    const b = emptyBranch(out.runtime, ids.uuid(), proposal.plan);
    b.selected_claim_refs = proposal.clears_selections ? [] : clone(origin.selected_claim_refs);
    b.selected_action_ref = proposal.action_changed ? clone(proposal.action) : (proposal.clears_action ? null : clone(origin.selected_action_ref));
    const items = staffItems(origin);
    if (items.length) {
      b.review_state = "staff_review_required";
      out.parked[b.branch_id] = {
        origin_branch_id: origin.branch_id, origin_revision: origin.last_ready_revision, kinds: proposal.kinds.slice(),
        origin_action_ref: clone(origin.selected_action_ref), items: items.map((i) => Object.assign({ resolved: null }, i)),
      };
    }
    out.case.branches.push(b);
    out.case.active_branch_id = b.branch_id;
    out.draft = clone(proposal.plan);
    return { state: out, forked: true };
  }

  function removeBranch(state, branchId, confirmation) {
    if (!confirmation || confirmation.saved_locally !== true) return err("save_required", "Download the case before removing a branch. Nothing was removed.");
    if (branchId === state.case.active_branch_id) return err("active_branch", "Open another branch before removing this one.");
    if (!branchOf(state, branchId)) return err("unknown_branch", "That branch is not in this case.");
    if (state.pending) return err("busy", "Wait for the current request to finish or cancel it.");
    const out = clone(state);
    out.case.branches = out.case.branches.filter((b) => b.branch_id !== branchId);
    ["results", "parked", "reviewed", "exclusions", "briefs", "retired", "copied"].forEach((k) => { delete out[k][branchId]; });
    return { state: out };
  }

  // ------------------------------------------------------------------ selections and staff work
  function currentResults(state, branchId) {
    const b = branchOf(state, branchId), r = b && state.results[b.branch_id];
    return r && r.revision === b.last_ready_revision ? r : null;
  }

  function toggleClaim(state, claimRef, on) {
    const b = active(state), res = currentResults(state);
    const key = refKey(claimRef);
    const out = clone(state), ob = active(out);
    if (!on) {
      ob.selected_claim_refs = ob.selected_claim_refs.filter((r) => refKey(r) !== key);
      parkOrphanNotes(out, ob, "deselected");
      return { state: out };
    }
    if (!res || !res.claims.some((c) => c.claim_ref && refKey(c.claim_ref) === key)) return err("stale_ref", "That finding is not part of the current results for this branch. Run the plan and select it again.");
    if (b.selected_claim_refs.some((r) => refKey(r) === key)) return { state: state };
    if (b.selected_claim_refs.length >= LIMITS.selections) return err("selection_full", "A one-page brief holds at most eight findings. Remove one before adding another.");
    ob.selected_claim_refs.push({ snapshot_id: claimRef.snapshot_id, finding_id: claimRef.finding_id, semantic_hash: claimRef.semantic_hash });
    return { state: out };
  }

  function moveSelection(state, claimRef, delta) {
    const out = clone(state), list = active(out).selected_claim_refs;
    const i = list.findIndex((r) => refKey(r) === refKey(claimRef)), j = i + delta;
    if (i < 0 || j < 0 || j >= list.length) return { state: state };
    const [r] = list.splice(i, 1); list.splice(j, 0, r);
    return { state: out };
  }

  // Notes whose claim is no longer selected are parked for review, never deleted or re-keyed.
  function parkOrphanNotes(out, branch, reason) {
    const notes = (branch.staff_edits && branch.staff_edits.finding_notes) || {};
    const selected = new Set(branch.selected_claim_refs.map((r) => r.semantic_hash));
    Object.keys(notes).forEach((h) => {
      if (selected.has(h)) return;
      const box = out.parked[branch.branch_id] || (out.parked[branch.branch_id] = { origin_branch_id: branch.branch_id, origin_revision: branch.last_ready_revision, kinds: [], origin_action_ref: clone(branch.selected_action_ref), items: [] });
      box.items.push({ key: "finding_note:" + h, kind: "finding_note", semantic_hash: h, value: notes[h], resolved: null, orphan_reason: reason });
      delete notes[h];
      branch.review_state = "staff_review_required";
    });
    if (branch.staff_edits && branch.staff_edits.finding_notes && !Object.keys(notes).length) delete branch.staff_edits.finding_notes;
  }

  function availableActions(state) {
    const res = currentResults(state);
    return res ? res.responses.filter((c) => c.action_ref).map((c) => c.action_ref) : [];
  }

  function chooseAction(state, actionRef) {
    if (actionRef !== null && !availableActions(state).some((a) => actionKey(a) === actionKey(actionRef))) return err("stale_ref", "That response is not part of the current results for this branch.");
    return { proposal: proposeChange(state, { action: actionRef }) };
  }

  function setStaffText(state, field, value) {
    const limit = { title: LIMITS.title, note: LIMITS.note, next_steps: LIMITS.next_steps }[field];
    if (!limit || typeof value !== "string") return err("invalid_field", "Unknown staff text field.");
    if (Array.from(value).length > limit) return err("too_long", "This field holds at most " + limit + " characters. Your text was not changed.");
    const out = clone(state), b = active(out);
    if (value === "") delete b.staff_edits[field]; else b.staff_edits[field] = value;
    return { state: out };
  }

  function setFindingNote(state, semanticHash, value) {
    const b = active(state);
    if (typeof value !== "string" || !b.selected_claim_refs.some((r) => r.semantic_hash === semanticHash)) return err("stale_ref", "Notes attach only to a currently selected finding.");
    if (Array.from(value).length > LIMITS.finding_note) return err("too_long", "A finding note holds at most 160 characters. Your text was not changed.");
    const out = clone(state), ob = active(out);
    const notes = ob.staff_edits.finding_notes || {};
    if (value === "") delete notes[semanticHash]; else notes[semanticHash] = value;
    if (Object.keys(notes).length) ob.staff_edits.finding_notes = notes; else delete ob.staff_edits.finding_notes;
    return { state: out };
  }

  function validChecklistItem(c) {
    return exactKeys(c, ["item_id"], ["text", "owner_role", "due_date", "completed"]) && CHECK_IDS.includes(c.item_id) &&
      (!("text" in c) || (typeof c.text === "string" && Array.from(c.text).length <= LIMITS.checklist_text)) &&
      (!("owner_role" in c) || (typeof c.owner_role === "string" && Array.from(c.owner_role).length <= LIMITS.owner_role)) &&
      (!("due_date" in c) || c.due_date === null || validDate(c.due_date)) &&
      (!("completed" in c) || typeof c.completed === "boolean");
  }

  // patch keys set to undefined/"" remove that staff value; completion is always a staff contribution.
  function setChecklist(state, itemId, patch) {
    if (!CHECK_IDS.includes(itemId)) return err("invalid_field", "Unknown checklist item.");
    const out = clone(state), b = active(out);
    let item = b.checklist_edits.find((c) => c.item_id === itemId);
    if (!item) { item = { item_id: itemId }; b.checklist_edits.push(item); }
    Object.keys(patch).forEach((k) => {
      const v = patch[k];
      if (v === undefined || v === "" || (k === "completed" && v === false) || (k === "due_date" && v === null)) delete item[k]; else item[k] = v;
    });
    if (!validChecklistItem(item)) return err("invalid_field", "Checklist text holds 120 characters, role 80, and the date must be a real YYYY-MM-DD date. Your entry was not changed.");
    if (itemId.startsWith("custom") && !item.text) b.checklist_edits = b.checklist_edits.filter((c) => c.item_id !== itemId);
    else if (Object.keys(item).length === 1) b.checklist_edits = b.checklist_edits.filter((c) => c.item_id !== itemId);
    b.checklist_edits.sort((x, y) => CHECK_IDS.indexOf(x.item_id) - CHECK_IDS.indexOf(y.item_id));
    return { state: out };
  }

  function validTracking(t) {
    return t === null || (exactKeys(t, ["label", "baseline", "as_of"]) && typeof t.label === "string" && Array.from(t.label).length <= LIMITS.tracking_label &&
      (t.baseline === null || (Number.isInteger(t.baseline) && t.baseline >= 0 && t.baseline <= LIMITS.baseline)) &&
      (t.as_of === null || validDate(t.as_of)));
  }

  function setTracking(state, tracking) {
    if (!validTracking(tracking)) return err("invalid_field", "Tracking needs a label of at most 80 characters, a whole-number baseline or none, and a real YYYY-MM-DD date or none.");
    const out = clone(state);
    active(out).tracking = clone(tracking);
    return { state: out };
  }

  // Explicit, per-item reuse of parked staff work. The copy stays labeled staff content and records
  // its origin. Completion is never carried to a different response identity.
  function copyParked(state, key, options) {
    const box = state.parked[state.case.active_branch_id];
    const item = box && box.items.find((i) => i.key === key && i.resolved === null);
    if (!item) return err("unknown_item", "That parked item is no longer waiting for review.");
    let r, completionCopied = false;
    if (item.kind === "finding_note") r = setFindingNote(state, item.semantic_hash, item.value);
    else if (item.kind === "checklist") {
      const patch = clone(item.item); delete patch.item_id;
      const sameAction = box.origin_action_ref && actionKey(box.origin_action_ref) === actionKey(active(state).selected_action_ref);
      completionCopied = !!(patch.completed && options && options.include_completion === true && sameAction);
      if (!completionCopied) delete patch.completed;
      r = setChecklist(state, item.item.item_id, patch);
    } else if (item.kind === "tracking") r = setTracking(state, item.tracking);
    else r = setStaffText(state, item.kind, item.value);
    if (r.error) return r.error.code === "stale_ref" ? err("not_applicable", "This note belongs to a finding that is not selected in the current context. It stays in its original branch.") : r;
    const out = r.state, b = active(out);
    out.parked[b.branch_id].items.find((i) => i.key === key).resolved = "copied";
    (out.copied[b.branch_id] || (out.copied[b.branch_id] = [])).push({ key: key, origin_branch_id: box.origin_branch_id, origin_revision: box.origin_revision, scope_kinds: box.kinds.slice(), completion_copied: completionCopied });
    return { state: settleReview(out), completion_copied: completionCopied };
  }

  function leaveParked(state, key) {
    const out = clone(state), box = out.parked[out.case.active_branch_id];
    const item = box && box.items.find((i) => i.key === key && i.resolved === null);
    if (!item) return err("unknown_item", "That parked item is no longer waiting for review.");
    item.resolved = "left";
    return { state: settleReview(out) };
  }

  function settleReview(out) {
    const b = active(out), box = out.parked[b.branch_id];
    if (b.review_state === "staff_review_required" && (!box || box.items.every((i) => i.resolved !== null))) b.review_state = "clean";
    return out;
  }

  const pendingReview = (state) => ((state.parked[state.case.active_branch_id] || {}).items || []).filter((i) => i.resolved === null);

  function briefKeys(branch) { return staffItems(branch).map((i) => i.key); }

  function setExclusion(state, key, excluded) {
    const out = clone(state), id = out.case.active_branch_id;
    const set = new Set(out.exclusions[id] || []);
    if (excluded) set.add(key); else set.delete(key);
    out.exclusions[id] = Array.from(set).sort();
    return { state: out };
  }

  // The staff content a brief request would carry right now, after explicit "leave out" choices.
  function activeStaff(state) {
    const b = active(state), ex = new Set(state.exclusions[b.branch_id] || []), e = b.staff_edits;
    const staff = {};
    ["title", "note", "next_steps"].forEach((k) => { if (e[k] && !ex.has(k)) staff[k] = e[k]; });
    const selected = new Set(b.selected_claim_refs.map((r) => r.semantic_hash)), notes = {};
    Object.keys(e.finding_notes || {}).forEach((h) => { if (selected.has(h) && !ex.has("finding_note:" + h)) notes[h] = e.finding_notes[h]; });
    if (Object.keys(notes).length) staff.finding_notes = notes;
    const checklist = b.checklist_edits.filter((c) => !ex.has("checklist:" + c.item_id) && Object.keys(c).length > 1).map(clone);
    const tracking = b.tracking && !ex.has("tracking") ? clone(b.tracking) : null;
    return { staff_edits: staff, checklist_edits: checklist, tracking: tracking, empty: !Object.keys(staff).length && !checklist.length && tracking === null };
  }

  function staffDigest(state) {
    const b = active(state), s = activeStaff(state);
    return canonical([s.staff_edits, s.checklist_edits, s.tracking, b.selected_claim_refs, b.selected_action_ref]);
  }

  // The browser's explicit review action for exactly this branch, revision, plan and content.
  function markReviewed(state) {
    const b = active(state), res = currentResults(state);
    if (!res) return err("not_ready", "Run the plan before reviewing staff content.");
    if (pendingReview(state).length) return err("staff_review_required", "Decide each parked item first: copy it into this context or leave it in its original branch.");
    if (!res.plan_hash) return err("plan_hash_unavailable", "This browser could not compute the plan identity (it needs a secure connection), so staff content cannot be attached. A clean brief without staff content is still available.");
    const out = clone(state);
    out.reviewed[b.branch_id] = { branch_id: b.branch_id, revision: b.last_ready_revision, plan_hash: res.plan_hash, digest: staffDigest(state) };
    return { state: out };
  }

  function reviewCurrent(state) {
    const b = active(state), rv = state.reviewed[b.branch_id], res = currentResults(state);
    return !!(rv && res && rv.revision === b.last_ready_revision && rv.plan_hash === res.plan_hash && rv.digest === staffDigest(state));
  }

  // ------------------------------------------------------------------ requests
  function tokensFor(state, branch, revision, ids) {
    return {
      schema_version: SCHEMA_VERSION, operation_version: branch.operation_version, recipe_version: branch.recipe_version,
      snapshot_id: branch.snapshot_id, request_id: ids.uuid(), case_id: state.case.case_id, branch_id: branch.branch_id, revision: revision,
    };
  }

  function blockIfMismatch(state, branch) {
    if (runtimeMatches(state, branch)) return null;
    return err("snapshot_unavailable", "This branch was built on evidence snapshot or versions that this release does not serve. It is kept unchanged. Open the matching release to replay or print it.");
  }

  function begin(state, kind, branch, body, revision, ids, extra) {
    if (state.pending) return err("busy", "A request is already in progress. Wait for it or cancel it.");
    const tokens = tokensFor(state, branch, revision, ids);
    const out = clone(state);
    out.last_error = null;
    // What was sent is kept so that choices made after the request left can be told apart from it.
    out.pending = Object.assign({ kind: kind, tokens: pick(tokens, TOKEN_KEYS), plan: clone(body.plan), selected: clone(body.selected_claim_refs || []), action: clone(body.selected_action_ref || null) }, extra || {});
    return { state: out, request: Object.assign({}, tokens, body) };
  }

  function pick(o, keys) { const out = {}; keys.forEach((k) => { out[k] = o[k]; }); return out; }

  function beginInterpret(state, utterance, ids) {
    const b = active(state);
    if (typeof utterance !== "string" || !utterance.trim()) return err("empty", "Type a request first, for example “add snap” or “use house 13”.");
    if (Array.from(utterance).length > LIMITS.utterance) return err("too_long", "A typed request holds at most 500 characters.");
    const block = blockIfMismatch(state, b); if (block) return block;
    return begin(state, "interpret", b, { mode: "interpret", plan: clone(state.draft), utterance: utterance }, b.last_ready_revision === null ? 0 : b.last_ready_revision, ids);
  }

  function nextRevision(out) {
    const r = out.case.next_revision;
    if (r > LIMITS.revision) return null;
    out.case.next_revision = r + 1;
    return r;
  }

  // Run the active branch's committed plan (after confirmChange). Each run takes a new revision.
  function beginRun(state, ids) {
    const b = active(state);
    const block = blockIfMismatch(state, b);
    if (block) { const s = clone(state); active(s).review_state = "replay_blocked"; return Object.assign(block, { state: s }); }
    const staged = clone(state), revision = nextRevision(staged);
    if (revision === null) return err("revision_limit", "This case reached its revision limit. Download it and start a new case.");
    return begin(staged, "run", b, { mode: "run", plan: clone(b.plan), selected_claim_refs: clone(b.selected_claim_refs), selected_action_ref: clone(b.selected_action_ref) }, revision, ids);
  }

  // Restore replays the saved branch against its exact snapshot and versions before it becomes active.
  function beginRestore(state, branchId, ids) {
    const b = branchOf(state, branchId);
    if (!b) return err("unknown_branch", "That branch is not in this case.");
    if (!same(active(state).plan, state.draft)) return err("unapplied_changes", "The plan has unapplied edits. Apply or discard them before restoring another branch.");
    const block = blockIfMismatch(state, b);
    if (block) { const s = clone(state); branchOf(s, branchId).review_state = "replay_blocked"; return Object.assign(block, { state: s }); }
    const staged = clone(state), revision = nextRevision(staged);
    if (revision === null) return err("revision_limit", "This case reached its revision limit.");
    return begin(staged, "restore", b, { mode: "run", plan: clone(b.plan), selected_claim_refs: clone(b.selected_claim_refs), selected_action_ref: clone(b.selected_action_ref) }, revision, ids);
  }

  function beginBrief(state, options, ids) {
    const b = active(state), res = currentResults(state);
    const block = blockIfMismatch(state, b); if (block) return block;
    if (!res) return err("not_ready", "Run the plan before creating a brief.");
    if (same(b.plan, state.draft) === false) return err("unapplied_changes", "The plan has unapplied edits. Apply or discard them before creating a brief.");
    if (!b.selected_claim_refs.length) return err("no_selection", "Select at least one finding for the brief.");
    const staff = activeStaff(state), clean = !!(options && options.clean);
    let body;
    if (clean || staff.empty) body = { staff_edits: {}, checklist_edits: [], tracking: null, edits_reviewed_for: null };
    else {
      if (pendingReview(state).length || !reviewCurrent(state)) return err("staff_review_required", "Staff text or checklist entries changed since they were last reviewed for this context. Review them, or create a clean brief without staff content.");
      const rv = state.reviewed[b.branch_id];
      body = { staff_edits: staff.staff_edits, checklist_edits: staff.checklist_edits, tracking: staff.tracking, edits_reviewed_for: { branch_id: rv.branch_id, revision: rv.revision, plan_hash: rv.plan_hash } };
    }
    return begin(state, "brief", b, Object.assign({ mode: "brief", plan: clone(b.plan), selected_claim_refs: clone(b.selected_claim_refs), selected_action_ref: clone(b.selected_action_ref) }, body),
      b.last_ready_revision, ids, { digest: staffDigest(state), clean: clean || staff.empty });
  }

  function cancelPending(state) {
    if (!state.pending) return state;
    const out = clone(state);
    out.pending = null;
    return out;
  }

  function tokensMatch(pending, tokens) {
    return !!pending && isObj(tokens) && TOKEN_KEYS.every((k) => tokens[k] === pending.tokens[k]) && Object.keys(tokens).length === TOKEN_KEYS.length;
  }

  function validRef(r) {
    return exactKeys(r, ["snapshot_id", "finding_id", "semantic_hash"]) && typeof r.snapshot_id === "string" && HASH.test(r.snapshot_id) &&
      typeof r.semantic_hash === "string" && HASH.test(r.semantic_hash) && typeof r.finding_id === "string" && r.finding_id.length >= 1 && r.finding_id.length <= 500;
  }
  function validAction(a) {
    return a === null || (exactKeys(a, ["action_id", "semantic_hash"]) && ACTION_IDS.includes(a.action_id) && typeof a.semantic_hash === "string" && HASH.test(a.semantic_hash));
  }

  // Apply a server reply. Only the exact pending case/branch/revision/snapshot/version is accepted;
  // anything else is discarded and the last committed results stay under their own heading.
  // meta: { http_status, plan_hash }. plan_hash is the browser's own SHA-256 of planCanonical(normalized_plan);
  // the server envelope has no such field and none is read from it. Returns { state, outcome, ... }.
  function applyResponse(state, response, meta) {
    const pending = state.pending, http = (meta && meta.http_status) || 200;
    if (!pending) return { state: state, outcome: "discarded", reason: "no_pending_request" };
    // The caller names the request this reply answers. A reply to any other request (cancelled or superseded)
    // is dropped here, before its body is looked at, so a late tokenless error or unreadable body can never
    // end the request that is pending now.
    if (meta && meta.request_id !== undefined && meta.request_id !== pending.tokens.request_id) return { state: state, outcome: "discarded", reason: "not_the_pending_request" };
    if (!isObj(response)) return fail(state, { code: "unreadable_response", message: "The server reply could not be read. Your work is unchanged; try again.", retry_action: "retry" });
    // An error envelope carries a code and no step results. A run whose steps all failed is still a result.
    if (response.status === "error" && !Array.isArray(response.steps)) {
      if (response.tokens && !tokensMatch(pending, response.tokens)) return { state: state, outcome: "discarded", reason: "token_mismatch" };
      const blocked = response.code === "snapshot_unavailable" || response.code === "version_mismatch";
      const out = fail(state, {
        code: typeof response.code === "string" ? response.code : "error", http_status: http,
        message: typeof response.message === "string" ? response.message : "The request could not be completed.",
        issues: Array.isArray(response.issues) ? response.issues.filter(isObj).slice(0, 20).map((i) => ({ path: String(i.path || ""), code: String(i.code || ""), message: String(i.message || "") })) : [],
        retry_action: typeof response.retry_action === "string" ? response.retry_action : "retry",
        detail: response.code === "brief_overflow" ? overflowDetail(response) : null,
      });
      if (blocked && pending.kind !== "import") { const b = branchOf(out.state, pending.tokens.branch_id); if (b) b.review_state = "replay_blocked"; }
      return out;
    }
    if (!tokensMatch(pending, response.tokens)) return { state: state, outcome: "discarded", reason: "token_mismatch" };
    if (response.model_calls !== 0) return fail(state, { code: "unexpected_model_calls", message: "The reply did not confirm zero model calls, so it was not used.", retry_action: "retry" });
    const out = clone(state);
    out.pending = null;
    if (pending.kind === "interpret") {
      const i = isObj(response.interpretation) ? response.interpretation : {};
      const proposed = response.normalized_plan, issues = [];
      return { state: out, outcome: "interpreted", status: response.status, interpretation: {
        matched_fields: Array.isArray(i.matched_fields) ? i.matched_fields : [], inherited_fields: Array.isArray(i.inherited_fields) ? i.inherited_fields : [],
        choices: Array.isArray(i.choices) ? i.choices : [], reason: typeof i.reason === "string" ? i.reason : null,
        proposed_plan: response.status === "ok" && proposed && validPlan(proposed, "plan", issues) ? clone(proposed) : null,
      } };
    }
    if (pending.kind === "brief") {
      if (!isObj(response.brief) || typeof response.brief.html !== "string") return fail(state, { code: "brief_unavailable", message: "The server did not return a brief. Your selections and staff text are unchanged.", retry_action: "retry" });
      out.briefs[pending.tokens.branch_id] = { revision: pending.tokens.revision, digest: pending.digest, clean: pending.clean, brief: response.brief, limitations: response.limitations || [] };
      return { state: out, outcome: "brief" };
    }
    // run, restore and import all commit a whole-plan result for exactly the pending branch.
    if (pending.kind === "import") {
      out.case = clone(pending.incoming.case);
      out.results = {}; out.parked = {}; out.reviewed = {}; out.exclusions = {}; out.briefs = {}; out.retired = {}; out.copied = {};
    }
    const b = branchOf(out, pending.tokens.branch_id);
    if (!b) return { state: state, outcome: "discarded", reason: "branch_removed" };
    const claims = Array.isArray(response.claims) ? response.claims.filter((c) => isObj(c) && validRef(c.claim_ref)) : [];
    const known = new Set(claims.map((c) => refKey(c.claim_ref)));
    const review = new Map((Array.isArray(response.selection_review) ? response.selection_review : []).filter((r) => isObj(r) && validRef(r.claim_ref)).map((r) => [refKey(r.claim_ref), r]));
    // Selections that were sent need the server's "retained" review. A finding ticked after the request
    // left has no review entry yet: it is kept only when its exact identity is in these results, and the
    // server reviews it on the next run or brief. A finding unticked meanwhile stays unticked.
    const sent = pending.kind === "run" && Array.isArray(pending.selected) ? new Set(pending.selected.map(refKey)) : null;
    const kept = [], retired = [];
    b.selected_claim_refs.forEach((r) => {
      const rv = review.get(refKey(r)), newer = sent !== null && !sent.has(refKey(r));
      if (known.has(refKey(r)) && (newer ? !rv || rv.state === "retained" : rv && rv.state === "retained")) kept.push(r);
      else retired.push({ claim_ref: r, state: rv && rv.state !== "retained" ? String(rv.state) : "retired", reason_code: rv && rv.reason_code ? String(rv.reason_code) : "not_in_current_results" });
    });
    b.selected_claim_refs = kept;
    const responses = Array.isArray(response.responses) ? response.responses.filter(isObj) : [];
    // The action review speaks only for the response that was sent; a newer choice is checked by identity alone.
    const ar = sent !== null && actionKey(pending.action) !== actionKey(b.selected_action_ref) ? null : response.action_review;
    if (b.selected_action_ref && (!responses.some((c) => validAction(c.action_ref) && c.action_ref && actionKey(c.action_ref) === actionKey(b.selected_action_ref)) || (isObj(ar) && typeof ar.state === "string" && ar.state !== "retained"))) {
      retired.push({ action_ref: b.selected_action_ref, state: isObj(ar) && ar.state ? String(ar.state) : "retired", reason_code: isObj(ar) && ar.reason_code ? String(ar.reason_code) : "not_in_current_results" });
      b.selected_action_ref = null;
    }
    const issues = [];
    if (response.normalized_plan && validPlan(response.normalized_plan, "plan", issues)) b.plan = clone(response.normalized_plan);
    b.last_ready_revision = pending.tokens.revision;
    out.results[b.branch_id] = {
      revision: pending.tokens.revision, status: response.status, plan: clone(b.plan),
      plan_hash: meta && typeof meta.plan_hash === "string" && HASH.test(meta.plan_hash) ? meta.plan_hash : null, steps: Array.isArray(response.steps) ? response.steps.filter(isObj) : [], claims: claims, responses: responses,
      limitations: Array.isArray(response.limitations) ? response.limitations : [],
      data_snapshot_id: response.data_snapshot_id || null, metadata_snapshot_id: response.metadata_snapshot_id || null,
    };
    out.retired[b.branch_id] = retired;
    delete out.briefs[b.branch_id];
    delete out.reviewed[b.branch_id];
    parkOrphanNotes(out, b, "retired");
    if (b.review_state === "replay_blocked") b.review_state = "clean";
    if (pendingReviewOf(out, b.branch_id).length) b.review_state = "staff_review_required";
    if (pending.kind === "import" && hasStaffContent(b)) b.review_state = "staff_review_required";
    let draftKept = false;
    if (pending.kind !== "run") { out.case.active_branch_id = b.branch_id; out.draft = clone(b.plan); }
    else if (out.case.active_branch_id === b.branch_id) {
      // Plan edits made after this request was sent are newer than its reply: keep them as the draft.
      if (same(state.draft, pending.plan)) out.draft = clone(b.plan); else draftKept = true;
    }
    return { state: out, outcome: pending.kind === "run" ? "committed" : pending.kind === "restore" ? "restored" : "imported", status: response.status, retired: retired, draft_kept: draftKept };
  }

  const pendingReviewOf = (state, id) => ((state.parked[id] || {}).items || []).filter((i) => i.resolved === null);

  function overflowDetail(response) {
    const num = (v) => (Number.isFinite(v) ? v : null);
    const src = isObj(response.overflow) ? response.overflow : response;
    // The server states its estimate in a safe issue message when no typed fields are present.
    const stated = (Array.isArray(response.issues) ? response.issues : []).map((i) => /print_units=([0-9]+); print_budget=([0-9]+)/.exec(String((i || {}).message || ""))).find(Boolean);
    return {
      estimated_units: num(src.estimated_units) !== null ? num(src.estimated_units) : (stated ? Number(stated[1]) : null),
      budget_units: num(src.budget_units !== undefined ? src.budget_units : src.budget) !== null ? num(src.budget_units !== undefined ? src.budget_units : src.budget) : (stated ? Number(stated[2]) : null),
      choices: (Array.isArray(src.choices) ? src.choices : Array.isArray(src.shortening_choices) ? src.shortening_choices : []).filter(isObj).slice(0, 24),
    };
  }

  function fail(state, error) {
    const out = clone(state);
    out.pending = null;
    out.last_error = Object.assign({ kind: state.pending ? state.pending.kind : null, issues: [], detail: null }, error);
    return { state: out, outcome: "error", error: out.last_error };
  }

  // Transport failure (network down, timeout, session restart). Nothing committed changes.
  function applyTransportFailure(state, requestId, kind) {
    if (!state.pending || state.pending.tokens.request_id !== requestId) return { state: state, outcome: "discarded", reason: "token_mismatch" };
    const session = kind === "session";
    return fail(state, {
      code: session ? "session_restarted" : "network_unavailable", retry_action: "retry",
      message: session ? "Your session was restarted. Your case, selections and staff text are kept in this page. Retry to continue." : "The server did not respond. Your case, selections and staff text are kept in this page. Retry when the connection is back.",
    });
  }

  // Exact local shortening choices for an over-budget brief. Each keeps the staff text in the
  // editor; "leave out" only excludes it from the next brief request. Nothing is cropped.
  function shorteningChoices(state) {
    const b = active(state), ex = new Set(state.exclusions[b.branch_id] || []), out = [];
    staffItems(b).forEach((i) => { if (!ex.has(i.key)) out.push({ kind: "leave_out_staff", key: i.key, size: Array.from(i.value || (i.item && i.item.text) || (i.tracking && i.tracking.label) || "").length }); });
    b.selected_claim_refs.forEach((r) => out.push({ kind: "deselect_finding", claim_ref: clone(r) }));
    return out;
  }

  // ------------------------------------------------------------------ print gate
  function printStatus(state) {
    const b = active(state), brief = state.briefs[b.branch_id];
    if (!runtimeMatches(state, b) || b.review_state === "replay_blocked") return { ok: false, code: "replay_blocked", message: "This branch needs a matching evidence snapshot and version before a verified brief can be printed." };
    if (state.pending) return { ok: false, code: "busy", message: "Wait for the current request to finish." };
    if (!brief || brief.revision !== b.last_ready_revision) return { ok: false, code: "no_brief", message: "Create the brief for the current results first." };
    if (!same(b.plan, state.draft)) return { ok: false, code: "unapplied_changes", message: "The plan has unapplied edits. Apply or discard them, then create the brief again." };
    if (brief.digest !== staffDigest(state)) return { ok: false, code: "brief_stale", message: "Selections or staff content changed after this brief was created. Create it again before printing." };
    return { ok: true, code: "ready", message: brief.clean ? "Ready to print. This brief contains no staff text." : "Ready to print. Staff text is labeled as staff contribution." };
  }

  // ------------------------------------------------------------------ export and import
  function exportCase(state, options) {
    const staff = !!(options && options.include_staff_work);
    const c = state.case;
    return {
      case_schema: CASE_SCHEMA, case_id: c.case_id, active_branch_id: c.active_branch_id, next_revision: c.next_revision,
      staff_work_included: staff,
      branches: c.branches.map((b) => ({
        branch_id: b.branch_id, release_id: b.release_id, snapshot_id: b.snapshot_id, operation_version: b.operation_version, recipe_version: b.recipe_version,
        plan: clone(b.plan), selected_claim_refs: clone(b.selected_claim_refs), selected_action_ref: clone(b.selected_action_ref),
        staff_edits: staff ? clone(b.staff_edits) : {}, checklist_edits: staff ? clone(b.checklist_edits) : [], tracking: staff ? clone(b.tracking) : null,
        review_state: staff && b.review_state === "staff_review_required" ? "staff_review_required" : "clean", last_ready_revision: b.last_ready_revision,
      })),
    };
  }

  // Every staff value the opt-in download would write, for an explicit preview before saving.
  function staffExportPreview(state) {
    return state.case.branches.map((b) => ({ branch_id: b.branch_id, district: b.plan.district, items: staffItems(b) })).filter((x) => x.items.length);
  }

  function validStaffEdits(e, refs) {
    if (!exactKeys(e, [], ["title", "note", "next_steps", "finding_notes"])) return false;
    const lim = { title: LIMITS.title, note: LIMITS.note, next_steps: LIMITS.next_steps };
    for (const k of Object.keys(lim)) if (k in e && (typeof e[k] !== "string" || Array.from(e[k]).length > lim[k])) return false;
    if ("finding_notes" in e) {
      const n = e.finding_notes, hashes = new Set(refs.map((r) => r.semantic_hash));
      if (!isObj(n) || Object.keys(n).length > 8) return false;
      for (const h of Object.keys(n)) if (!HASH.test(h) || !hashes.has(h) || typeof n[h] !== "string" || Array.from(n[h]).length > LIMITS.finding_note) return false;
    }
    return true;
  }

  // Bounded local parse: size, native JSON.parse, depth, then strict schema. The file is never uploaded
  // and none of its text is treated as evidence. Returns { ok, incoming, preview } or { ok:false, issues }.
  function parseCaseFile(text, runtime) {
    const no = (code, message, path) => ({ ok: false, issues: [{ path: path || "", code: code, message: message }] });
    if (typeof text !== "string" || !text.length) return no("empty", "The file is empty.");
    if (text.length > LIMITS.case_bytes || utf8Length(text) > LIMITS.case_bytes) return no("too_large", "The file is larger than the 262,144-byte case limit. It was not opened.");
    let raw;
    try { raw = JSON.parse(text); } catch (e) { return no("invalid_json", "The file is not valid JSON. It was not opened."); }
    if (depthOf(raw) > LIMITS.case_depth) return no("too_deep", "The file is nested more deeply than a case file allows. It was not opened.");
    if (!isObj(raw) || raw.case_schema !== CASE_SCHEMA) return no("unsupported_version", "This is not a haic-case/1 file. It was not opened.", "case_schema");
    if (!exactKeys(raw, ["case_schema", "case_id", "active_branch_id", "next_revision", "branches"], ["staff_work_included"])) return no("unknown_field", "The file has missing or unknown top-level fields.");
    if (!UUID4.test(String(raw.case_id)) || typeof raw.case_id !== "string") return no("invalid", "The case identifier is not a canonical UUIDv4.", "case_id");
    if (!Number.isInteger(raw.next_revision) || raw.next_revision < 0 || raw.next_revision > LIMITS.revision) return no("invalid", "The revision counter is out of range.", "next_revision");
    if ("staff_work_included" in raw && typeof raw.staff_work_included !== "boolean") return no("invalid", "staff_work_included must be true or false.", "staff_work_included");
    if (!Array.isArray(raw.branches) || raw.branches.length < 1 || raw.branches.length > LIMITS.branches) return no("invalid", "A case holds one to four branches.", "branches");
    const ids = new Set();
    const keys = ["branch_id", "release_id", "snapshot_id", "operation_version", "recipe_version", "plan", "selected_claim_refs", "selected_action_ref", "staff_edits", "checklist_edits", "tracking", "review_state", "last_ready_revision"];
    for (let i = 0; i < raw.branches.length; i += 1) {
      const b = raw.branches[i], p = "branches[" + i + "]";
      if (!exactKeys(b, keys)) return no("unknown_field", "A branch has missing or unknown fields.", p);
      if (typeof b.branch_id !== "string" || !UUID4.test(b.branch_id) || ids.has(b.branch_id)) return no("invalid", "Branch identifiers must be unique canonical UUIDv4 values.", p + ".branch_id");
      ids.add(b.branch_id);
      if (typeof b.release_id !== "string" || b.release_id.length > 200) return no("invalid", "The release identity is not valid.", p + ".release_id");
      if (typeof b.snapshot_id !== "string" || !HASH.test(b.snapshot_id)) return no("invalid", "The snapshot identity is not a full SHA-256 value.", p + ".snapshot_id");
      if (typeof b.operation_version !== "string" || b.operation_version.length > 40 || typeof b.recipe_version !== "string" || b.recipe_version.length > 40) return no("invalid", "Version identifiers are not valid.", p);
      const issues = [];
      if (!validPlan(b.plan, p + ".plan", issues)) return { ok: false, issues: issues };
      if (b.recipe_version !== b.plan.issue_id + "/1") return no("invalid", "The recipe version does not match the branch issue.", p + ".recipe_version");
      if (!Array.isArray(b.selected_claim_refs) || b.selected_claim_refs.length > LIMITS.selections || !b.selected_claim_refs.every(validRef) || new Set(b.selected_claim_refs.map(refKey)).size !== b.selected_claim_refs.length) return no("invalid", "Selections must be at most eight unique full claim references.", p + ".selected_claim_refs");
      if (!validAction(b.selected_action_ref)) return no("invalid", "The selected response identity is not valid.", p + ".selected_action_ref");
      if (!validStaffEdits(b.staff_edits, b.selected_claim_refs)) return no("invalid", "Staff text is over its limit or attached to an unselected finding.", p + ".staff_edits");
      if (!Array.isArray(b.checklist_edits) || b.checklist_edits.length > 6 || !b.checklist_edits.every(validChecklistItem) || new Set(b.checklist_edits.map((c) => c.item_id)).size !== b.checklist_edits.length) return no("invalid", "Checklist entries are not valid.", p + ".checklist_edits");
      if (!validTracking(b.tracking)) return no("invalid", "The tracking entry is not valid.", p + ".tracking");
      if (!["clean", "staff_review_required", "replay_blocked"].includes(b.review_state)) return no("invalid", "The review state is not valid.", p + ".review_state");
      if (b.last_ready_revision !== null && (!Number.isInteger(b.last_ready_revision) || b.last_ready_revision < 0 || b.last_ready_revision > LIMITS.revision)) return no("invalid", "The ready revision is out of range.", p + ".last_ready_revision");
    }
    if (typeof raw.active_branch_id !== "string" || !ids.has(raw.active_branch_id)) return no("invalid", "The active branch is not one of the file's branches.", "active_branch_id");
    const incoming = { case: { case_schema: CASE_SCHEMA, case_id: raw.case_id, active_branch_id: raw.active_branch_id, next_revision: raw.next_revision, branches: clone(raw.branches) } };
    const a = incoming.case.branches.find((b) => b.branch_id === raw.active_branch_id);
    const match = !!runtime && a.snapshot_id === runtime.snapshot_id && a.operation_version === runtime.operation_version && (runtime.recipe_versions || RECIPES).includes(a.recipe_version);
    return { ok: true, incoming: incoming, preview: {
      case_id: raw.case_id, branch_count: raw.branches.length, active_plan: clone(a.plan), selection_count: a.selected_claim_refs.length,
      has_action: a.selected_action_ref !== null, runtime_match: match, snapshot_id: a.snapshot_id, operation_version: a.operation_version, recipe_version: a.recipe_version,
      staff_items: incoming.case.branches.reduce((n, b) => n + staffItems(b).length, 0),
      staff_preview: incoming.case.branches.map((b) => ({ branch_id: b.branch_id, items: staffItems(b) })).filter((x) => x.items.length),
    } };
  }

  // Import replays only the active plan against the exact trusted snapshot. The current case is
  // replaced only when that replay succeeds; the request carries the typed plan and references, never the file.
  function beginImport(state, parsed, options, ids) {
    if (!parsed || !parsed.ok) return err("invalid_file", "That file was not accepted.");
    if (!same(active(state).plan, state.draft)) return err("unapplied_changes", "The plan has unapplied edits. Apply or discard them before opening a case file.");
    if (!parsed.preview.runtime_match) return err("snapshot_unavailable", "This file needs an evidence snapshot or version that this release does not serve. The file and your current case are unchanged; verified brief and print stay disabled for it. Open the matching release to replay it.");
    const incoming = clone(parsed.incoming), staff = !!(options && options.accept_staff_work);
    incoming.case.branches.forEach((b) => {
      if (!staff) { b.staff_edits = {}; b.checklist_edits = []; b.tracking = null; }
      b.review_state = hasStaffContent(b) ? "staff_review_required" : "clean";
      b.last_ready_revision = null;
    });
    const b = incoming.case.branches.find((x) => x.branch_id === incoming.case.active_branch_id);
    const revision = incoming.case.next_revision;
    if (revision > LIMITS.revision) return err("revision_limit", "That case reached its revision limit.");
    incoming.case.next_revision = revision + 1;
    const shell = { case: incoming.case };
    if (state.pending) return err("busy", "A request is already in progress. Wait for it or cancel it.");
    const tokens = tokensFor(shell, b, revision, ids);
    const out = clone(state);
    out.last_error = null;
    out.pending = { kind: "import", tokens: pick(tokens, TOKEN_KEYS), plan: clone(b.plan), incoming: incoming };
    return { state: out, request: Object.assign({}, tokens, { mode: "run", plan: clone(b.plan), selected_claim_refs: clone(b.selected_claim_refs), selected_action_ref: clone(b.selected_action_ref) }) };
  }

  // Matched spans are Unicode code point offsets into the original text.
  function interpretationSegments(utterance, matched) {
    const cps = Array.from(utterance);
    const spans = (matched || []).filter((m) => isObj(m) && Array.isArray(m.span) && m.span.length === 2 && Number.isInteger(m.span[0]) && Number.isInteger(m.span[1]) && m.span[0] >= 0 && m.span[1] > m.span[0] && m.span[1] <= cps.length)
      .map((m) => ({ start: m.span[0], end: m.span[1], field: String(m.field) })).sort((a, b) => a.start - b.start);
    const out = []; let at = 0;
    spans.forEach((s) => {
      if (s.start < at) return;
      if (s.start > at) out.push({ text: cps.slice(at, s.start).join(""), field: null });
      out.push({ text: cps.slice(s.start, s.end).join(""), field: s.field });
      at = s.end;
    });
    if (at < cps.length) out.push({ text: cps.slice(at).join(""), field: null });
    return out;
  }

  return {
    SCHEMA_VERSION, OPERATION_VERSION, CASE_SCHEMA, OPERATIONS, SERVICE_AREAS, ISSUES, CHECK_IDS, TEMPLATE_CHECK_IDS, TOKEN_KEYS, LIMITS, AGING_METRICS,
    canonical, planCanonical, validDate, utf8Length, refKey, actionKey, geographyIdOf,
    defaultPlan, validPlan, validArgs, addStep, removeStep, moveStep, rescopeStep, setContext, classifyChange,
    createState, active, branchOf, staffItems, hasStaffContent, runtimeMatches, proposeChange, confirmChange, removeBranch,
    currentResults, toggleClaim, moveSelection, availableActions, chooseAction, setStaffText, setFindingNote, setChecklist, setTracking,
    copyParked, leaveParked, pendingReview, setExclusion, activeStaff, staffDigest, markReviewed, reviewCurrent,
    beginInterpret, beginRun, beginRestore, beginBrief, cancelPending, applyResponse, applyTransportFailure, shorteningChoices, printStatus,
    exportCase, staffExportPreview, parseCaseFile, beginImport, interpretationSegments,
  };
});
