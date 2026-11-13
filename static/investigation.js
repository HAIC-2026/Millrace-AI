/* IA-1 investigation workspace. Collects controls, calls /api/investigation and renders typed
   server results. It computes no factual value. Text from the server and from case files is
   inserted as text; only brief.html from a matching brief reply is inserted as trusted markup.
   Case state lives in memory only: no storage, URL, query or fragment carries a case. */
(function () {
  "use strict";
  const C = window.IACase;
  const $ = (sel, root) => (root || document).querySelector(sel);
  const ids = { uuid: () => crypto.randomUUID() };
  let state = null, catalog = null, boot = null;
  let interp = null;            // last interpretation for the typed draft
  let preview = null;           // pending context-change preview
  let importing = null;         // parsed case file awaiting an explicit choice
  let mapHandle = null, mapKey = null, savedDigest = null, showStaffPreview = false;
  let notice = "";              // polite status line

  function h(tag, attrs) {
    const n = document.createElement(tag);
    Object.keys(attrs || {}).forEach((k) => {
      const v = attrs[k];
      if (v === null || v === undefined || v === false) return;
      if (k === "text") n.textContent = v;
      else if (k === "on") Object.keys(v).forEach((e) => n.addEventListener(e, v[e]));
      else if (k === "checked" || k === "disabled" || k === "selected" || k === "value" || k === "hidden" || k === "multiple") n[k] = v;
      else n.setAttribute(k, v === true ? "" : String(v));
    });
    for (let i = 2; i < arguments.length; i += 1) {
      const c = arguments[i];
      if (c === null || c === undefined || c === false) continue;
      (Array.isArray(c) ? c : [c]).forEach((x) => { if (x !== null && x !== undefined && x !== false) n.append(x.nodeType ? x : document.createTextNode(String(x))); });
    }
    return n;
  }
  const btn = (label, onClick, attrs) => h("button", Object.assign({ type: "button", class: "btn", text: label, on: { click: onClick } }, attrs || {}));
  const fill = (el, nodes) => { el.replaceChildren.apply(el, [].concat(nodes).filter(Boolean)); };

  // ------------------------------------------------------------------ labels
  const OP_LABEL = { profile: "Profile measures", compare: "Compare with a geography", program_evidence: "Program reference", outreach_lead: "Reviewed outreach hypothesis", administrative_evidence: "Administrative records" };
  const ISSUE_LABEL = { aging_at_home: "Older-adult support at home", custom: "Custom (staff-composed steps)" };
  const AREA_LABEL = { statewide: "Statewide", oahu: "Oʻahu", hawaii_island: "Hawaiʻi Island", maui: "Maui", molokai: "Molokaʻi", lanai: "Lānaʻi", kauai: "Kauaʻi", kalawao: "Kalawao" };
  const TIER_LABEL = { reference: "Dated program reference", hypothesis: "Reviewed outreach hypothesis", verification_action: "Staff verification action" };
  const KIND_LABEL = { statistic: "Statistic", comparison: "Comparison", program_relevance: "Program reference", outreach_hypothesis: "Outreach hypothesis", administrative_context: "Administrative record (not district data)" };
  const CHANGE_LABEL = { district: "district", map_session: "map session", issue: "issue", service_area: "service area", comparator: "comparison geography", program: "program", step_scope: "step scope", response: "selected response" };
  const STAFF_LABEL = { title: "Title", note: "Staff note", next_steps: "Next steps", finding_note: "Finding note", checklist: "Checklist entry", tracking: "Office tracking entry" };
  const districtLabel = (d) => (d.chamber === "house" ? "House " : "Senate ") + d.code;
  const short = (hash) => (typeof hash === "string" ? hash.slice(0, 15) + "…" : "");
  const metricLabel = (id) => ((catalog.metrics || []).find((m) => m.metric_id === id) || {}).label || id;
  const programLabel = (id) => ((catalog.programs || []).find((p) => p.program_id === id) || {}).name || id;
  function geoLabel(id) {
    const g = (catalog.geographies || []).concat(catalog.unavailable_geographies || []).find((x) => x.geography_id === id);
    return g ? g.label : id;
  }
  const adminRows = () => catalog.administrative_rows || catalog.participation || [];
  function adminLabel(id) {
    const r = adminRows().find((x) => x.observation_id === id);
    return r ? [r.series_label || r.label || r.program_id, r.period, id].filter(Boolean).join(" · ") : id;
  }
  function stepScope(s) {
    const a = s.args;
    if (s.operation === "profile") return a.metric_ids === null ? "All 20 measures" : a.metric_ids.map(metricLabel).join("; ");
    if (s.operation === "compare") return a.metric_ids.map(metricLabel).join("; ") + " — comparison: " + geoLabel(a.comparison_geography);
    if (s.operation === "program_evidence") return a.program_ids.map(programLabel).join("; ");
    if (s.operation === "outreach_lead") return programLabel(a.program_id) + " — complete reviewed measure set; hypothesis reference: State";
    return a.observation_ids.map(adminLabel).join("; ");
  }
  function plain(v, depth) {
    if (v === null || v === undefined || v === "") return "—";
    if (typeof v !== "object") return String(v);
    if ((depth || 0) > 2) return "…";
    if (Array.isArray(v)) return v.map((x) => plain(x, (depth || 0) + 1)).join("; ");
    return Object.keys(v).filter((k) => v[k] !== null && v[k] !== "").map((k) => k.replace(/_/g, " ") + ": " + plain(v[k], (depth || 0) + 1)).join(", ");
  }

  // ------------------------------------------------------------------ state plumbing
  function set(result, okMessage) {
    if (result.error) { if (result.state) state = result.state; alertUser(result.error.message); render(); return false; }
    if (result.state) state = result.state;
    if (okMessage) notice = okMessage;
    render();
    return true;
  }
  function alertUser(message) {
    const a = $("#ia-alert");
    fill(a, [h("p", { text: message })]);
    a.hidden = false;
    a.focus();
  }
  function clearAlert() { const a = $("#ia-alert"); a.hidden = true; fill(a, []); }

  async function sha256Hex(text) {
    if (!(crypto.subtle && crypto.subtle.digest)) return null;
    const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
    return "sha256:" + Array.from(new Uint8Array(buf), (b) => b.toString(16).padStart(2, "0")).join("");
  }

  async function send(request) {
    render();
    let resp, body = null;
    try {
      resp = await fetch("/api/investigation", { method: "POST", headers: { "Content-Type": "application/json" }, credentials: "same-origin", body: JSON.stringify(request) });
    } catch (e) {
      return finish(C.applyTransportFailure(state, request.request_id, "network"));
    }
    try { body = await resp.json(); } catch (e) { body = null; }
    if (resp.status === 403) {
      // Session or origin check failed: renew the session cookie, keep all local work, ask for a retry.
      try { await fetch("/api/health", { credentials: "same-origin" }); } catch (e) { /* retry stays available */ }
      return finish(C.applyTransportFailure(state, request.request_id, "session"));
    }
    let planHash = null;
    if (body && Array.isArray(body.steps) && body.normalized_plan && request.mode === "run") {
      // Client-internal plan identity for the staff-review token: SHA-256 of the canonical typed Plan.
      // The server recomputes and checks it; the reply itself is left exactly as received.
      try { planHash = await sha256Hex(C.planCanonical(body.normalized_plan)); } catch (e) { planHash = null; }
    }
    // request_id is the originating request, checked against the pending one after all async work above.
    finish(C.applyResponse(state, body, { http_status: resp.status, plan_hash: planHash, request_id: request.request_id }));
  }

  function finish(result) {
    state = result.state;
    flushActive();
    if (result.outcome === "discarded") { notice = "A late reply for an earlier request was ignored. The current context is unchanged."; render(); return; }
    if (result.outcome === "error") { render(); const e = $("#ia-error"); if (e) e.focus(); return; }
    if (result.outcome === "interpreted") { interp = Object.assign({ status: result.status, utterance: interp ? interp.utterance : "" }, result.interpretation); notice = result.status === "ok" ? "Interpretation ready. Review it, then choose Apply interpretation." : "The request needs a choice or is not supported. Nothing was run."; render(); const t = $("#ia-interpretation"); t.focus(); return; }
    if (result.outcome === "brief") { notice = "Brief created for the current results."; render(); const out = $("#ia-brief"); out.focus(); return; }
    if (result.outcome === "imported") { importing = null; notice = "Case file replayed against this release's evidence and opened."; }
    else if (result.outcome === "restored") notice = "Branch restored after an exact replay. Its notes and progress are shown as staff contributions from that context.";
    else notice = (result.draft_kept ? "Results updated for the plan you applied earlier. Your newer plan edits are kept as a draft; choose Apply plan to run them. " : "") + "Results updated (" + result.status + ")." + (result.retired && result.retired.length ? " " + result.retired.length + " earlier selection" + (result.retired.length === 1 ? " was" : "s were") + " not carried into this context." : "");
    render();
    syncMap(true);
  }

  function runActive() {
    const r = C.beginRun(state, ids);
    if (r.error) { if (r.state) state = r.state; alertUser(r.error.message); render(); return; }
    state = r.state; clearAlert(); notice = "Running the plan…";
    syncMap(false);
    send(r.request);
  }

  // ------------------------------------------------------------------ plan editing
  function editDraft(result, message) {
    if (state.pending && state.pending.kind !== "run" && state.pending.kind !== "brief" && state.pending.kind !== "interpret") { alertUser("A saved context is being replayed. Wait for it to finish, or cancel the request, before editing the plan."); render(); return; }
    if (result.error) { alertUser(result.error.message); return; }
    state = Object.assign({}, state, { draft: result.plan });
    clearAlert();
    notice = result.clarification ? result.clarification.message : (message || "Plan edited. Choose Apply plan to run it.");
    render();
  }

  function applyPlan() {
    const p = C.proposeChange(state, { plan: state.draft });
    const res = C.currentResults(state);
    // "Run again" replays the unchanged plan at a new revision; nothing is forked or parked.
    if (p.noop && res) { preview = null; runActive(); return; }
    if (!p.material || !p.fork) return commit(p);
    preview = p; render(); $("#ia-preview").focus();
  }

  function commit(p) {
    const r = C.confirmChange(state, p, ids);
    preview = null;
    if (r.error) { alertUser(r.error.message); render(); return; }
    state = r.state;
    runActive();
  }

  function defaultArgs(op) {
    const metrics = catalog.metrics || [], programs = catalog.programs || [];
    if (op === "profile") return { metric_ids: null };
    if (op === "compare") return { metric_ids: [metrics.some((m) => m.metric_id === "poverty_rate_65_plus") ? "poverty_rate_65_plus" : (metrics[0] || {}).metric_id], comparison_geography: "HI-STATE-2024" };
    if (op === "program_evidence") return { program_ids: [(programs[0] || {}).program_id] };
    if (op === "outreach_lead") return { program_id: (programs[0] || {}).program_id };
    return { observation_ids: [(adminRows()[0] || {}).observation_id] };
  }

  function multi(id, label, options, chosen, max, onChange, help) {
    const sel = h("select", { id: id, multiple: true, size: Math.min(6, Math.max(3, options.length)), "aria-describedby": id + "-help" });
    options.forEach((o) => sel.append(h("option", { value: o[0], text: o[1], selected: chosen.includes(o[0]) })));
    sel.addEventListener("change", () => {
      const v = Array.from(sel.selectedOptions, (o) => o.value);
      if (!v.length || v.length > max) { alertUser("Choose between 1 and " + max + " for this step. The step was not changed."); render(); return; }
      onChange(v);
    });
    return h("div", { class: "field" }, h("label", { for: id, text: label }), sel, h("p", { class: "fine", id: id + "-help", text: (help || "") + " Hold Command or Control to choose several (1–" + max + ")." }));
  }
  function single(id, label, options, value, onChange) {
    const sel = h("select", { id: id });
    options.forEach((o) => sel.append(h("option", { value: o[0], text: o[1], selected: o[0] === value })));
    sel.addEventListener("change", () => onChange(sel.value));
    return h("div", { class: "field" }, h("label", { for: id, text: label }), sel);
  }

  function stepEditor(s) {
    const a = s.args, id = "ia-" + s.step_id, re = (args) => editDraft(C.rescopeStep(state.draft, s.step_id, args));
    const metrics = (catalog.metrics || []).map((m) => [m.metric_id, m.label]);
    if (s.operation === "profile") {
      const all = h("input", { type: "checkbox", id: id + "-all", checked: a.metric_ids === null, on: { change: (e) => re({ metric_ids: e.target.checked ? null : C.AGING_METRICS.filter((m) => metrics.some((x) => x[0] === m)) }) } });
      return [h("label", { class: "ia-check", for: id + "-all" }, all, " All 20 measures"),
        a.metric_ids === null ? null : multi(id + "-metrics", "Measures shown", metrics, a.metric_ids, 20, (v) => re({ metric_ids: v }))];
    }
    if (s.operation === "compare") {
      const geos = (catalog.geographies || []).map((g) => [g.geography_id, g.label]).concat((catalog.unavailable_geographies || []).map((g) => [g.geography_id, g.label + " (not normalized in this snapshot)"]));
      return [multi(id + "-metrics", "Measures compared", metrics, a.metric_ids, 4, (v) => re({ metric_ids: v, comparison_geography: a.comparison_geography })),
        single(id + "-geo", "Comparison geography", geos, a.comparison_geography, (v) => re({ metric_ids: a.metric_ids, comparison_geography: v })),
        h("p", { class: "fine", text: "A separate comparison never changes a hypothesis's own State reference. No statistical difference test is performed." })];
    }
    const programs = (catalog.programs || []).map((p) => [p.program_id, p.name]);
    if (s.operation === "program_evidence") return [multi(id + "-programs", "Programs", programs, a.program_ids, 5, (v) => re({ program_ids: v }), "A program reference is dated information, not an eligibility or need finding.")];
    if (s.operation === "outreach_lead") return [single(id + "-program", "Program", programs, a.program_id, (v) => re({ program_id: v })),
      h("p", { class: "fine", text: "Uses the program's complete reviewed measure set and State references. A subset or another comparator is not supported; remove this step to keep only the general reference." })];
    return [multi(id + "-rows", "Recorded rows", adminRows().map((r) => [r.observation_id, adminLabel(r.observation_id)]), a.observation_ids, 8, (v) => re({ observation_ids: v }), "State, county or island records; never district counts.")];
  }

  // ------------------------------------------------------------------ render
  function render() {
    if (!state) return;
    const keep = document.activeElement && document.activeElement.id;
    // Opened detail panels stay open across re-renders.
    const opened = Array.from(document.querySelectorAll("#ia-workspace details[open]"), (d) => d.id).filter(Boolean);
    const b = C.active(state), res = C.currentResults(state), busy = !!state.pending;
    const dirty = !C.proposeChange(state, { plan: state.draft }).noop;
    $("#ia-status").textContent = busy ? "Working: " + state.pending.kind + " request in progress…" : notice;
    $("#ia-cancel").hidden = !busy;

    // context bar
    const d = state.draft.district;
    $("#ia-chamber").value = d.chamber;
    const codeSel = $("#ia-code");
    if (codeSel.dataset.chamber !== d.chamber) {
      const rows = (catalog.districts || []).filter((x) => x.chamber === d.chamber && x.boundary_session === 2024);
      const n = d.chamber === "house" ? 51 : 25;
      fill(codeSel, Array.from({ length: n }, (_, i) => {
        const code = String(i + 1).padStart(3, "0"), row = rows.find((x) => x.code === code);
        return h("option", { value: code, text: code + (row && row.name ? " — " + row.name : "") });
      }));
      codeSel.dataset.chamber = d.chamber;
    }
    codeSel.value = d.code;
    $("#ia-issue").value = state.draft.issue_id;
    $("#ia-service").value = state.draft.service_area_id || "";
    $("#ia-map-session").value = String(state.draft.map_session);
    fill($("#ia-context-summary"), [
      h("strong", { text: districtLabel(b.plan.district) }), " · " + ISSUE_LABEL[b.plan.issue_id] + " · inquiry area: " + (b.plan.service_area_id ? AREA_LABEL[b.plan.service_area_id] + " (staff-chosen, not a finding)" : "none chosen") +
      " · statistics on 2024 boundaries · map session " + b.plan.map_session + " · ",
      res ? "results at revision " + res.revision + " (" + res.status + ")" : "not run yet",
      dirty ? h("span", { class: "badge badge-warn", text: "Unapplied plan edits" }) : null,
      b.review_state !== "clean" ? h("span", { class: "badge badge-note", text: b.review_state === "replay_blocked" ? "Replay blocked" : "Staff review required" }) : null,
    ]);

    renderInterpretation();
    renderSteps(dirty, busy);
    renderPreview();
    renderError();
    renderEvidence(res, dirty);
    renderResponses(res);
    renderTray(b, res, busy, dirty);
    renderBrief(b);
    renderCase(b, busy);
    syncMapText(b);
    opened.forEach((id) => { const d = document.getElementById(id); if (d) d.open = true; });
    if (keep) { const el = document.getElementById(keep); if (el && el !== document.activeElement) el.focus(); }
  }

  // A reply can arrive while staff are typing. Commit the focused field first so the re-render keeps it.
  function flushActive() {
    const el = document.activeElement;
    if (!el || !el.closest || !el.closest(".ia-tray") || el.id === "ia-chk-new") return;
    if (el.tagName === "TEXTAREA" || (el.tagName === "INPUT" && ["text", "number", "date"].includes(el.type))) el.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function renderInterpretation() {
    const box = $("#ia-interpretation");
    if (!interp) { fill(box, [h("p", { class: "fine", text: "Supported phrases include “aging at home in house 28”, “use house 13”, “compare senior poverty with maui county”, “add snap”, “remove step s3” and “show the full profile”. Other text is not interpreted." })]); return; }
    const segs = C.interpretationSegments(interp.utterance, interp.matched_fields);
    const nodes = [h("h4", { text: interp.status === "pending" ? "Interpreting…" : interp.status === "ok" ? "Proposed interpretation (not applied)" : interp.status === "clarification" ? "A choice is needed" : "Not supported" }),
      h("p", { class: "ia-utterance" }, segs.map((s) => (s.field ? h("mark", { title: "Matched: " + s.field, text: s.text }) : s.text)))];
    if (interp.reason) nodes.push(h("p", { text: interp.reason }));
    const list = (title, items) => items.length ? h("div", {}, h("h5", { text: title }), h("ul", { class: "ia-fields" }, items.map((m) => h("li", {}, h("strong", { text: String(m.field).replace(/_/g, " ") + ": " }), plain(m.value))))) : null;
    nodes.push(list("Matched in your text", interp.matched_fields), list("Inherited from the current plan", interp.inherited_fields));
    if (interp.choices.length) nodes.push(h("ul", { class: "ia-choices" }, interp.choices.map((c) => {
      const label = String(c.label || plain(c.value));
      const usable = c && c.field === "district" && c.value && (c.value.chamber === "house" || c.value.chamber === "senate") && typeof c.value.code === "string";
      return h("li", {}, usable ? btn("Use " + label, () => { interp = null; editDraft(C.setContext(state.draft, { district: c.value }), label + " placed in the plan. Choose Apply plan to run it."); }) : label);
    })));
    if (interp.proposed_plan) nodes.push(h("div", { class: "btn-row" },
      btn("Apply interpretation", () => { const p = interp.proposed_plan; interp = null; state = Object.assign({}, state, { draft: p }); applyPlan(); }, { class: "btn btn-primary", id: "ia-apply-interp" }),
      btn("Discard", () => { interp = null; notice = "Interpretation discarded. The plan is unchanged."; render(); })));
    fill(box, nodes);
  }

  function renderSteps(dirty, busy) {
    const plan = state.draft;
    fill($("#ia-steps"), plan.steps.length ? plan.steps.map((s, i) => h("li", { class: "ia-step", id: "ia-step-" + s.step_id },
      h("div", { class: "ia-step-head" }, h("span", { class: "ia-step-id", text: s.step_id }), h("strong", { text: OP_LABEL[s.operation] }),
        h("span", { class: "ia-step-tools" },
          btn("Up", () => editDraft(C.moveStep(plan, s.step_id, -1), "Step moved. Order does not change any fact."), { class: "btn-link", id: "ia-up-" + s.step_id, disabled: i === 0, "aria-label": "Move step " + s.step_id + " up" }),
          btn("Down", () => editDraft(C.moveStep(plan, s.step_id, 1), "Step moved. Order does not change any fact."), { class: "btn-link", id: "ia-down-" + s.step_id, disabled: i === plan.steps.length - 1, "aria-label": "Move step " + s.step_id + " down" }),
          btn("Remove", () => editDraft(C.removeStep(plan, s.step_id), "Step " + s.step_id + " removed from the draft. Choose Apply plan to run it."), { class: "btn-link", id: "ia-rm-" + s.step_id, "aria-label": "Remove step " + s.step_id }))),
      h("p", { class: "ia-step-scope", text: stepScope(s) }),
      h("details", { id: "ia-scope-" + s.step_id }, h("summary", { text: "Change scope" }), stepEditor(s))))
      : [h("li", { class: "muted", text: "No steps. An empty plan can be edited but has no results or printable brief. Add a step below." })]);
    $("#ia-step-count").textContent = plan.steps.length + " of 8 steps";
    $("#ia-add-btn").disabled = plan.steps.length >= 8;
    $("#ia-apply").disabled = busy;
    $("#ia-apply").textContent = dirty ? "Apply plan" : "Run again";
    $("#ia-discard").hidden = !dirty;
  }

  function renderPreview() {
    const box = $("#ia-preview");
    box.hidden = !preview;
    if (!preview) { fill(box, []); return; }
    const p = preview, kinds = p.kinds.map((k) => CHANGE_LABEL[k] || k).join(", ");
    fill(box, [h("h3", { text: "Review this context change" }),
      h("p", { text: "This changes the " + kinds + ". The current branch stays saved exactly as it is, and a new branch opens for the changed context." }),
      h("ul", {},
        h("li", { text: p.clears_selections ? "Selected findings and the selected response are not carried over. No fact from the earlier context enters the new brief." : p.provisional_selections + " selected finding(s) are kept only if the server confirms the exact same claim identity in the new results." }),
        h("li", { text: p.parked.length ? p.parked.length + " staff entr" + (p.parked.length === 1 ? "y goes" : "ies go") + " to review, including notes on unchanged facts and checklist progress. Nothing is copied unless you choose it." : "There is no staff text or checklist progress to review." }),
        p.kinds.includes("program") || p.kinds.includes("response") ? h("li", { text: "A different agency or response never inherits a completed call or its text." }) : null),
      p.branch_limit ? h("p", { class: "alert", text: "This case already holds four branches. Download the case, then remove a branch under Case file and branches before applying." }) : null,
      h("div", { class: "btn-row" },
        btn("Apply change and run", () => commit(p), { class: "btn btn-primary", id: "ia-preview-confirm", disabled: p.branch_limit }),
        btn("Keep current context", () => { preview = null; notice = "No change applied. Your edits remain in the draft plan."; render(); $("#ia-apply").focus(); }, { id: "ia-preview-cancel" }))]);
  }

  function renderError() {
    const box = $("#ia-error"), e = state.last_error;
    box.hidden = !e;
    if (!e) { fill(box, []); return; }
    const nodes = [h("h3", { text: e.code === "brief_overflow" ? "The brief is too long for one page" : e.code === "session_restarted" || e.code === "network_unavailable" ? "Connection problem — your work is kept" : "The request was not completed" }), h("p", { text: e.message })];
    if (e.issues && e.issues.length) nodes.push(h("ul", {}, e.issues.map((i) => h("li", { text: (i.path ? i.path + ": " : "") + i.message }))));
    if (e.code === "brief_overflow") {
      const dt = e.detail || {};
      if (dt.estimated_units !== null && dt.budget_units !== null) nodes.push(h("p", { text: "Estimated " + dt.estimated_units + " print units against a budget of " + dt.budget_units + ". The estimate guides shortening; it does not prove a one-page print." }));
      nodes.push(h("p", { text: "Nothing was cropped or shrunk. Choose exactly what to leave out; your text stays in the editor and can be included again." }));
      nodes.push(h("ul", { class: "ia-choices" }, C.shorteningChoices(state).map((c, i) => h("li", {}, c.kind === "leave_out_staff"
        ? btn("Leave out " + staffKeyLabel(c.key) + " (" + c.size + " characters)", () => set(C.setExclusion(state, c.key, true), "Left out of the next brief. The text is kept."), { id: "ia-short-" + i })
        : btn("Deselect finding " + claimTitle(c.claim_ref), () => set(C.toggleClaim(state, c.claim_ref, false), "Finding deselected. It can be selected again from the evidence."), { id: "ia-short-" + i })))));
    } else if (e.code === "snapshot_unavailable" || e.code === "version_mismatch") {
      nodes.push(h("p", { text: "The saved case and this branch are unchanged. A verified brief or print needs the matching release. You can keep working in another branch or start a new plan." }));
    } else if (e.code === "foreign_context" || e.code === "selection_conflict" || e.code === "action_conflict") {
      nodes.push(h("p", { text: "Remove the named selection, or restore the branch it came from under Case file and branches. No mixed brief was created." }));
    }
    const retry = e.kind === "run" || e.kind === "restore" ? btn("Retry", () => { state = Object.assign({}, state, { last_error: null }); runActive(); }, { class: "btn btn-primary", id: "ia-retry" }) : null;
    nodes.push(h("div", { class: "btn-row" }, e.code === "session_restarted" || e.code === "network_unavailable" || e.code === "unreadable_response" ? retry : null,
      btn("Dismiss", () => { state = Object.assign({}, state, { last_error: null }); render(); }, { id: "ia-dismiss" }),
      btn("Use guided single-operation view", () => $("#tab-btn-workflow").click(), { id: "ia-recover-guided" })));
    fill(box, nodes);
  }

  const claimMap = (res) => new Map((res ? res.claims : []).map((c) => [C.refKey(c.claim_ref), c]));
  function claimTitle(ref) {
    const c = claimMap(C.currentResults(state)).get(C.refKey(ref));
    return c && typeof c.text === "string" ? (c.text.length > 90 ? c.text.slice(0, 88) + "…" : c.text) : ref.finding_id;
  }
  // The whole server statement of a dependency (estimate, margin, universe, period), never a shortened label.
  function claimFull(ref) {
    const c = claimMap(C.currentResults(state)).get(C.refKey(ref));
    return c && typeof c.text === "string" ? c.text : ref.finding_id;
  }
  function staffKeyLabel(key) {
    const kind = key.split(":")[0];
    return key.startsWith("finding_note:") ? "finding note" : key.startsWith("checklist:") ? "checklist entry " + key.slice(10) : (STAFF_LABEL[kind] || kind).toLowerCase();
  }

  // Every value below is a trusted field of the server's canonical claim, shown as text. Nothing is recomputed.
  function claimRows(c) {
    const m = c.metric || {}, g = c.geography || {}, src = c.source || {};
    const side = (x) => (x && x.geography ? x.geography.label + ": " + x.estimate_display + " (margin of error " + x.moe_display + ")" : null);
    return [
      ["Label", c.label],
      ["Universe", c.universe], ["Unit", c.unit], ["Period", c.period ? [c.period.label, c.period.product, c.period.dollar_year ? c.period.dollar_year + " dollars" : null].filter(Boolean).join(" · ") : null],
      ["Geography", g.label ? [g.label, g.geoid ? "GEOID " + g.geoid : null, g.summary_level ? "summary level " + g.summary_level : null, g.source_name].filter(Boolean).join(" · ") : null],
      ["Published value and margin", c.estimate_display !== undefined ? c.estimate_display + " · margin of error " + c.moe_display + " · published confidence level " + c.moe_confidence_level : null],
      ["Annotation", c.annotation_meaning || c.annotation || c.moe_annotation],
      ["District side", side(c.left)], ["Comparison side", side(c.right)],
      ["Point difference", c.kind === "comparison" ? (c.difference ? plain(c.difference) : "Not differenced: " + plain(c.not_differenced_reason)) : null],
      ["Compatibility checks", c.compatibility],
      ["Method", c.transformation],
      ["Table and variable", m.table_id ? [m.table_id, m.variable_id, m.margin_of_error_variable_id].filter(Boolean).join(" · ") : null], ["Official variable label", m.official_variable_label],
      ["Agency", c.program && c.program.agency], ["Program jurisdiction", c.program && c.program.jurisdiction], ["Recorded status", c.status_notes], ["Effective period", c.effective_text],
      ["Reviewed measures", Array.isArray(c.observed_need) ? c.observed_need.map((o) => o.label + ": " + o.estimate_display + " (margin of error " + o.moe_display + "; " + o.universe + "; " + o.period_label + ")" + (o.state_reference ? " — State reference: " + plain(o.state_reference) : "")) : null],
      ["Program connection", c.program_connection && c.program_connection.text], ["Not known from this evidence", c.unknowns], ["Reviewed next step", c.next_step],
      ["Source", src.source_id ? [src.publisher, src.url, src.retrieved_at_utc ? "retrieved " + src.retrieved_at_utc : null, src.sha256 ? "SHA-256 " + src.sha256 : null, src.locator ? "locator: " + plain(src.locator) : null].filter(Boolean).join(" · ") : null],
      ["Finding ID", c.claim_ref.finding_id], ["Claim identity", c.claim_ref.semantic_hash],
    ].filter((r) => r[1] !== null && r[1] !== undefined && r[1] !== "" && !(Array.isArray(r[1]) && !r[1].length));
  }

  function claimNode(c, selected, prefix) {
    const key = C.refKey(c.claim_ref);
    const id = prefix + c.claim_ref.semantic_hash.slice(7, 19);
    const seen = new Set(), sources = (Array.isArray(c.source_inspection_refs) ? c.source_inspection_refs : []).filter((r) => r && typeof r.source_id === "string" && !seen.has(r.source_id + "|" + r.finding_id) && seen.add(r.source_id + "|" + r.finding_id));
    const cb = h("input", { type: "checkbox", id: id + "-sel", checked: selected.has(key), on: { change: (e) => set(C.toggleClaim(state, c.claim_ref, e.target.checked), e.target.checked ? "Finding selected for the brief." : "Finding removed from the brief selection.") } });
    return h("li", { class: "ia-claim" + (selected.has(key) ? " is-selected" : ""), id: id, tabindex: "-1" },
      h("div", { class: "ia-claim-head" }, h("span", { class: "badge", text: KIND_LABEL[c.kind] || c.kind || "Finding" }),
        selected.has(key) ? h("span", { class: "badge badge-info", text: "In brief" }) : null,
        h("label", { class: "ia-check", for: id + "-sel" }, cb, " Select for brief")),
      h("p", { class: "ia-claim-text", text: typeof c.text === "string" ? c.text : c.claim_ref.finding_id }),
      h("details", { id: id + "-more" }, h("summary", { text: "Definition, margin, geography and source" }),
        h("dl", { class: "kv" }, claimRows(c).map((r) => h("div", {}, h("dt", { text: r[0] }), h("dd", {}, Array.isArray(r[1]) ? h("ul", {}, r[1].map((x) => h("li", { text: plain(x) }))) : plain(r[1]))))),
        Array.isArray(c.dependencies) && c.dependencies.length ? h("div", {}, h("h5", { text: c.kind === "outreach_hypothesis" ? "Complete reviewed basis (shown in full whatever the profile displays)" : "Depends on" }),
          h("ul", {}, c.dependencies.map((r) => h("li", { text: claimFull(r) })))) : null,
        Array.isArray(c.limitations) && c.limitations.length ? h("div", {}, h("h5", { text: "Limits of this finding" }), h("ul", {}, c.limitations.map((l) => h("li", { text: plain(l) })))) : null,
        sources.length ? h("p", { class: "fine" }, sources.map((r) => h("button", { type: "button", class: "btn-link source-btn", "data-source-id": r.source_id, "data-finding-id": typeof r.finding_id === "string" ? r.finding_id : c.claim_ref.finding_id, text: "Inspect source " + r.source_id + (r.finding_id && r.finding_id !== c.claim_ref.finding_id ? " (" + r.finding_id + ")" : "") }))) : null));
  }

  function renderEvidence(res, dirty) {
    const box = $("#ia-evidence");
    if (!res) { fill(box, [h("p", { class: "muted", text: state.pending ? "Running the plan…" : "No results for this branch yet. Choose Apply plan to run it." })]); return; }
    const claims = claimMap(res), selected = new Set(C.active(state).selected_claim_refs.map(C.refKey));
    const nodes = [h("p", { class: "fine", text: "Results for " + districtLabel(res.plan.district) + " at revision " + res.revision + (dirty ? ". The draft plan has unapplied edits; these results describe the last applied plan." : ".") + " Model calls: 0." })];
    res.steps.forEach((s) => {
      const refs = Array.isArray(s.claim_refs) ? s.claim_refs : [];
      nodes.push(h("section", { class: "ia-step-result status-" + s.status, "aria-labelledby": "ia-res-h-" + s.step_id },
        h("h4", { id: "ia-res-h-" + s.step_id }, s.step_id + " · " + (OP_LABEL[s.operation] || s.operation) + " ", h("span", { class: "badge" + (s.status === "ok" ? "" : " badge-warn"), text: s.status === "ok" ? refs.length + " finding" + (refs.length === 1 ? "" : "s") : s.status })),
        s.status !== "ok" ? h("div", { class: "notice notice-unsupported" }, h("p", { text: (s.message || "This step did not produce a result.") + (s.reason_code ? " (" + s.reason_code + ")" : "") }),
          h("p", { class: "fine", text: "No substitute answer was used. Other steps are unaffected." }),
          (Array.isArray(s.next_actions) ? s.next_actions : []).map((a, i) => {
            // Typed comparator choices only: either {kind:"choose_comparator",values} or {label,request:{comparison_geography}}.
            const geos = a && a.kind === "choose_comparator" && Array.isArray(a.values) ? a.values : a && a.request && typeof a.request.comparison_geography === "string" ? [a.request.comparison_geography] : [];
            const usable = s.operation === "compare" ? geos.filter((g) => typeof g === "string") : [];
            return usable.length ? h("div", { class: "btn-row" }, usable.map((g, j) => btn("Compare with " + geoLabel(g) + " instead", () => {
              const st = state.draft.steps.find((x) => x.step_id === s.step_id);
              if (st) editDraft(C.rescopeStep(state.draft, s.step_id, { metric_ids: st.args.metric_ids, comparison_geography: g }), "Comparison geography changed in the draft. Choose Apply plan to run it.");
            }, { id: "ia-next-" + s.step_id + "-" + i + "-" + j })))
              : h("p", { class: "fine", text: plain(a && (a.label || a)) });
          })) : null,
        h("ul", { class: "ia-claims" }, refs.map((r) => claims.get(C.refKey(r))).filter(Boolean).map((c) => claimNode(c, selected, "ia-c-" + s.step_id + "-")))));
    });
    if (res.limitations.length) nodes.push(h("section", { class: "limitations" }, h("h4", { text: "Limits of these results" }), h("ul", {}, res.limitations.map((l) => h("li", { text: plain(l) })))));
    fill(box, nodes);
  }

  function renderResponses(res) {
    const box = $("#ia-responses"), b = C.active(state);
    if (!res || !res.responses.length) { fill(box, [h("p", { class: "muted", text: res ? "No program step is in this plan, so there is no response to choose. A brief without a response is valid." : "Responses appear after the plan runs." })]); return; }
    const pick = (ref) => {
      const r = C.chooseAction(state, ref);
      if (r.error) return alertUser(r.error.message);
      if (r.proposal.noop) return;
      if (r.proposal.fork) { preview = r.proposal; render(); $("#ia-preview").focus(); } else commitAction(r.proposal);
    };
    const nodes = res.responses.map((card, i) => {
      const j = card.jurisdiction || {}, a = card.access || {}, on = card.action_ref && C.actionKey(card.action_ref) === C.actionKey(b.selected_action_ref);
      const list = (title, items) => (Array.isArray(items) && items.length ? h("div", {}, h("h5", { text: title }), h("ul", {}, items.map((x) => h("li", { text: plain(x) })))) : null);
      return h("article", { class: "card ia-response" + (on ? " is-selected" : ""), id: "ia-resp-" + i },
        h("header", {}, h("h4", { text: programLabel(card.program_id) }), h("span", { class: "badge badge-info", text: TIER_LABEL[card.tier] || card.tier })),
        h("dl", { class: "kv" },
          h("div", {}, h("dt", { text: "Jurisdiction" }), h("dd", { text: (j.state || "unknown") + " · " + String(j.scope_kind || "").replace(/_/g, " ") + (Array.isArray(j.area_ids) && j.area_ids.length ? " · " + j.area_ids.join(", ") : "") })),
          h("div", {}, h("dt", { text: "Recorded status" }), h("dd", { text: String(a.recorded_status || "unknown").replace(/_/g, " ") + (a.checked_at ? " · checked " + a.checked_at : " · no check date recorded") })),
          h("div", {}, h("dt", { text: "Effective period" }), h("dd", { text: plain(a.effective_period) })),
          h("div", {}, h("dt", { text: "Availability now" }), h("dd", { text: (a.current_availability || "unverified") + " · cost " + (a.cost || "unverified") + " — a checked reference does not mean access is open" })),
          card.eligibility_area !== undefined && card.eligibility_area !== null ? h("div", {}, h("dt", { text: "Eligibility area" }), h("dd", { text: plain(card.eligibility_area) })) : null),
        list("Jurisdiction limits", j.limitations), list("What weakens this lead", card.weakening_facts), list("Facts staff must verify", card.facts_to_verify),
        card.tier === "reference" ? h("p", { class: "fine", text: "General reference only. It is not promoted to a hypothesis or action because it was requested, and it does not substitute for another program." }) : null,
        Array.isArray(card.support_claim_refs) && card.support_claim_refs.length ? h("p", { class: "fine", text: "Reviewed basis: " + card.support_claim_refs.map(claimTitle).join(" | ") }) : null,
        card.action_ref ? h("label", { class: "ia-check", for: "ia-act-" + i }, h("input", { type: "radio", name: "ia-action", id: "ia-act-" + i, checked: on, on: { change: () => pick(card.action_ref) } }), " Use this verification step in the brief") : h("p", { class: "fine", text: "No reviewed staff action is attached to this program." }));
    });
    nodes.push(h("label", { class: "ia-check", for: "ia-act-none" }, h("input", { type: "radio", name: "ia-action", id: "ia-act-none", checked: b.selected_action_ref === null, on: { change: () => pick(null) } }), " No response in the brief"));
    fill(box, nodes);
  }

  function commitAction(p) {
    const r = C.confirmChange(state, p, ids);
    if (r.error) return alertUser(r.error.message);
    state = r.state; notice = p.action ? "Response selected. Its checklist is in the brief panel." : "No response selected.";
    // A response change that opened a new branch always recomputes the plan for that branch.
    if (r.forked) { runActive(); return; }
    render();
  }

  function textField(id, label, value, max, onCommit, area) {
    const el = h(area ? "textarea" : "input", Object.assign({ id: id, maxlength: max }, area ? { rows: 3 } : { type: "text" }));
    el.value = value || "";
    el.addEventListener("change", () => onCommit(el.value));
    return h("div", { class: "field" }, h("label", { for: id }, label + " ", h("span", { class: "req", text: "(staff contribution, up to " + max + ")" })), el);
  }

  function renderTray(b, res, busy, dirty) {
    const claims = claimMap(res), ex = new Set(state.exclusions[b.branch_id] || []);
    const notes = (b.staff_edits.finding_notes || {});
    $("#ia-tray-count").textContent = b.selected_claim_refs.length ? b.selected_claim_refs.length + " of 8 findings selected." + (b.selected_claim_refs.length > 3 ? " Three concise findings and one response usually fit a page best." : "") : "No findings selected. Tick “Select for brief” on evidence.";
    fill($("#ia-selected"), b.selected_claim_refs.map((r, i) => {
      const c = claims.get(C.refKey(r)), sid = "ia-sel-" + r.semantic_hash.slice(7, 19);
      return h("li", { id: sid }, h("span", { class: "tray-label", text: c && typeof c.text === "string" ? c.text : r.finding_id }),
        h("span", { class: "ia-step-tools" },
          btn("Up", () => set(C.moveSelection(state, r, -1)), { class: "btn-link", id: sid + "-up", disabled: i === 0, "aria-label": "Move finding " + (i + 1) + " up" }),
          btn("Down", () => set(C.moveSelection(state, r, 1)), { class: "btn-link", id: sid + "-down", disabled: i === b.selected_claim_refs.length - 1, "aria-label": "Move finding " + (i + 1) + " down" }),
          btn("Remove", () => set(C.toggleClaim(state, r, false), "Finding removed from the brief selection."), { class: "btn-link", id: sid + "-rm", "aria-label": "Remove finding " + (i + 1) + " from brief" })),
        textField(sid + "-note", "Note on this finding", notes[r.semantic_hash], 160, (v) => set(C.setFindingNote(state, r.semantic_hash, v))));
    }));
    const retired = state.retired[b.branch_id] || [];
    fill($("#ia-retired"), retired.length ? [h("p", { class: "fine", text: "Not carried into this context (kept in their original branch):" }), h("ul", { class: "fine" }, retired.map((r) => h("li", { text: (r.claim_ref ? r.claim_ref.finding_id : "response " + r.action_ref.action_id) + " — " + String(r.state).replace(/_/g, " ") + " (" + r.reason_code + ")" })))] : []);

    // action checklist
    const card = res && b.selected_action_ref ? res.responses.find((c) => c.action_ref && C.actionKey(c.action_ref) === C.actionKey(b.selected_action_ref)) : null;
    const edits = new Map(b.checklist_edits.map((c) => [c.item_id, c]));
    const item = (idKey, templateText) => {
      const e = edits.get(idKey) || {}, pid = "ia-chk-" + idKey;
      return h("li", { class: "ia-check-item" },
        templateText ? h("p", { class: "ia-template", text: templateText }) : null,
        textField(pid + "-text", templateText ? "Staff wording (optional)" : idKey.startsWith("custom") ? "Custom item" : "Staff entry for " + idKey.replace(/_/g, " "), e.text, 120, (v) => set(C.setChecklist(state, idKey, { text: v }))),
        h("div", { class: "ia-inline" },
          textField(pid + "-owner", "Staff role", e.owner_role, 80, (v) => set(C.setChecklist(state, idKey, { owner_role: v }))),
          h("div", { class: "field" }, h("label", { for: pid + "-due", text: "Date" }), h("input", { type: "date", id: pid + "-due", value: e.due_date || "", on: { change: (ev) => set(C.setChecklist(state, idKey, { due_date: ev.target.value || null })) } }))),
        h("label", { class: "ia-check", for: pid + "-done" }, h("input", { type: "checkbox", id: pid + "-done", checked: e.completed === true, on: { change: (ev) => set(C.setChecklist(state, idKey, { completed: ev.target.checked })) } }), " Staff marked done (not a verified system fact)"),
        ex.has("checklist:" + idKey) ? h("p", { class: "fine" }, "Left out of the next brief. ", btn("Include again", () => set(C.setExclusion(state, "checklist:" + idKey, false)), { class: "btn-link", id: pid + "-incl" })) : null);
    };
    const check = $("#ia-checklist");
    const templates = card && Array.isArray(card.template_checklist) ? card.template_checklist.filter((t) => t && C.TEMPLATE_CHECK_IDS.includes(t.item_id)) : [];
    const shown = new Set(templates.map((t) => t.item_id));
    // Staff entries stay visible and editable even with no response selected.
    const loose = C.CHECK_IDS.filter((k) => edits.has(k) && !shown.has(k)), free = C.CHECK_IDS.slice(3).find((k) => !edits.has(k));
    const add = h("input", { type: "text", id: "ia-chk-new", maxlength: 120 });
    fill(check, [card ? h("p", {}, h("strong", { text: programLabel(card.program_id) + " — verification checklist" })) : h("p", { class: "muted", text: "No response selected, so no template checklist applies. Custom items and tracking can still be added as staff contributions." }),
      templates.length || loose.length ? h("ol", { class: "ia-checklist" }, templates.map((t) => item(t.item_id, String(t.text || ""))), loose.map((k) => item(k, ""))) : null,
      free ? h("div", { class: "field" }, h("label", { for: "ia-chk-new", text: "Add a custom checklist item (up to 3)" }), add, btn("Add item", () => { if (add.value.trim()) set(C.setChecklist(state, free, { text: add.value.trim() }), "Custom item added as a staff contribution."); }, { id: "ia-chk-add" })) : null]);

    // staff text and tracking
    const t = b.tracking || { label: "", baseline: null, as_of: null };
    const track = (patch) => { const n = Object.assign({}, t, patch); set(C.setTracking(state, !n.label && n.baseline === null && !n.as_of ? null : n)); };
    const excl = (key) => (ex.has(key) ? h("p", { class: "fine" }, "Left out of the next brief. ", btn("Include again", () => set(C.setExclusion(state, key, false)), { class: "btn-link", id: "ia-incl-" + key })) : null);
    fill($("#ia-staff"), [
      textField("ia-title", "Brief title", b.staff_edits.title, 90, (v) => set(C.setStaffText(state, "title", v))), excl("title"),
      textField("ia-note", "Staff note", b.staff_edits.note, 400, (v) => set(C.setStaffText(state, "note", v)), true), excl("note"),
      textField("ia-next", "Next steps", b.staff_edits.next_steps, 300, (v) => set(C.setStaffText(state, "next_steps", v)), true), excl("next_steps"),
      h("fieldset", {}, h("legend", { text: "Office-held tracking (optional)" }),
        h("p", { class: "fine", text: "A staff record such as “agency/partner referral sessions arranged”. Baseline: " + (t.baseline === null ? "not supplied" : t.baseline + (t.as_of ? " as of " + t.as_of : "")) + ". Never a verified dataset baseline. Do not enter resident details." }),
        textField("ia-track-label", "Measure label", t.label, 80, (v) => track({ label: v })),
        h("div", { class: "ia-inline" },
          h("div", { class: "field" }, h("label", { for: "ia-track-base", text: "Office baseline" }), h("input", { type: "number", id: "ia-track-base", min: 0, max: 1000000000, step: 1, value: t.baseline === null ? "" : String(t.baseline), on: { change: (e) => track({ baseline: e.target.value === "" ? null : Number(e.target.value) }) } })),
          h("div", { class: "field" }, h("label", { for: "ia-track-date", text: "As of" }), h("input", { type: "date", id: "ia-track-date", value: t.as_of || "", on: { change: (e) => track({ as_of: e.target.value || null }) } }))), excl("tracking")),
    ]);

    // parked staff work
    const parked = C.pendingReview(state), box = state.parked[b.branch_id];
    const sameAction = box && box.origin_action_ref && C.actionKey(box.origin_action_ref) === C.actionKey(b.selected_action_ref);
    fill($("#ia-review"), parked.length ? [h("h3", { text: "Staff work waiting for review (" + parked.length + ")" }),
      h("p", { class: "fine", text: "These entries were written for an earlier context" + (box.kinds.length ? " (changed: " + box.kinds.map((k) => CHANGE_LABEL[k] || k).join(", ") + ")" : "") + ". They are excluded from this brief and stay in their original branch unless you copy them. Copies remain labeled staff contributions." }),
      h("ul", { class: "ia-parked" }, parked.map((p, i) => {
        const val = p.kind === "checklist" ? [p.item.item_id.replace(/_/g, " "), p.item.text, p.item.owner_role, p.item.due_date, p.item.completed ? "marked done in the earlier context" : null].filter(Boolean).join(" · ") : p.kind === "tracking" ? plain(p.tracking) : p.value;
        const done = p.kind === "checklist" && p.item.completed && sameAction ? h("input", { type: "checkbox", id: "ia-park-done-" + i }) : null;
        return h("li", {}, h("p", {}, h("strong", { text: (STAFF_LABEL[p.kind] || p.kind) + ": " }), val),
          p.kind === "checklist" && p.item.completed && !sameAction ? h("p", { class: "fine", text: "The done mark belongs to a different response and is not copied." }) : null,
          done ? h("label", { class: "ia-check", for: "ia-park-done-" + i }, done, " Also copy the done mark (same response identity)") : null,
          h("div", { class: "btn-row" },
            btn("Copy into this context", () => set(C.copyParked(state, p.key, { include_completion: !!(done && done.checked) }), "Copied as a staff contribution. Review staff content before creating the brief."), { id: "ia-park-copy-" + i }),
            btn("Leave in original branch", () => set(C.leaveParked(state, p.key), "Left in its original branch."), { id: "ia-park-leave-" + i })));
      }))] : []);

    // brief controls
    const staff = C.activeStaff(state), reviewed = C.reviewCurrent(state);
    $("#ia-review-state").textContent = staff.empty ? "No staff content will be sent with this brief." : reviewed ? "Staff content reviewed for this branch, revision and plan. It is sent only when you create the brief and is not stored by the app." : "Staff content changed or was not yet reviewed for this context.";
    $("#ia-review-btn").hidden = staff.empty || reviewed;
    $("#ia-review-btn").disabled = busy || parked.length > 0 || !res;
    $("#ia-brief-btn").disabled = busy || !res || dirty || !b.selected_claim_refs.length || (!staff.empty && !reviewed);
    $("#ia-clean-brief-btn").hidden = staff.empty && !parked.length;
    $("#ia-clean-brief-btn").disabled = busy || !res || dirty || !b.selected_claim_refs.length;
  }

  function renderBrief(b) {
    const brief = state.briefs[b.branch_id], status = C.printStatus(state), out = $("#ia-brief-out");
    $("#ia-brief-status").textContent = status.message;
    $("#ia-print-btn").disabled = !status.ok;
    if (!brief) { if (out.dataset.rev) { fill(out, []); delete out.dataset.rev; } out.classList.remove("is-stale"); return; }
    const tag = b.branch_id + ":" + brief.revision + ":" + brief.digest.length + ":" + (brief.brief.html || "").length;
    if (out.dataset.rev !== tag) {
      // Trusted server-rendered brief from a reply whose tokens matched this exact branch and revision.
      out.innerHTML = brief.brief.html;
      out.querySelectorAll("[id]").forEach((n) => { if (n.id === "brief-doc") n.id = "ia-brief-doc"; });
      out.dataset.rev = tag;
    }
    out.classList.toggle("is-stale", !status.ok);
  }

  function renderCase(b, busy) {
    const list = $("#ia-branches");
    fill(list, state.case.branches.map((br, i) => {
      const on = br.branch_id === b.branch_id, n = C.staffItems(br).length;
      return h("li", { class: on ? "is-selected" : "" }, h("span", { text: "Branch " + (i + 1) + ": " + districtLabel(br.plan.district) + " · " + ISSUE_LABEL[br.plan.issue_id] + " · " + br.plan.steps.length + " steps · " + br.selected_claim_refs.length + " selected · " + n + " staff entr" + (n === 1 ? "y" : "ies") + (br.review_state === "replay_blocked" ? " · replay blocked" : "") + (on ? " · current" : "") }),
        on ? null : h("span", { class: "ia-step-tools" },
          btn("Restore", () => { const r = C.beginRestore(state, br.branch_id, ids); if (r.error) { if (r.state) state = r.state; alertUser(r.error.message); render(); return; } state = r.state; notice = "Replaying that branch against its exact evidence…"; send(r.request); }, { class: "btn-link", id: "ia-restore-" + i, disabled: busy, "aria-label": "Restore branch " + (i + 1) + " by replaying its evidence" }),
          btn("Remove", () => set(C.removeBranch(state, br.branch_id, { saved_locally: savedDigest === C.canonical(C.exportCase(state, { include_staff_work: true })) }), "Branch removed after a full local download."), { class: "btn-link", id: "ia-rmbranch-" + i, disabled: busy, "aria-label": "Remove branch " + (i + 1) })));
    }));
    const staffOn = $("#ia-download-staff").checked, pv = $("#ia-staff-preview");
    pv.hidden = !staffOn;
    if (staffOn) {
      const rows = C.staffExportPreview(state);
      fill(pv, [h("p", { class: "alert", text: "This file will contain the staff text below as plain text. It is not encrypted. Anyone who can open the file can read it." }),
        rows.length ? h("ul", {}, rows.map((r) => h("li", {}, districtLabel(r.district) + ": ", h("ul", {}, r.items.map((it) => h("li", { text: (STAFF_LABEL[it.kind] || it.kind) + " — " + (it.value || plain(it.item || it.tracking)) })))))) : h("p", { text: "There is no staff text, checklist entry or tracking record in this case." })]);
    } else fill(pv, []);
    const ip = $("#ia-import-preview");
    ip.hidden = !importing;
    if (!importing) { fill(ip, []); return; }
    if (!importing.ok) { fill(ip, [h("h3", { text: "The file was not opened" }), h("ul", {}, importing.issues.map((i) => h("li", { text: (i.path ? i.path + ": " : "") + i.message }))), h("p", { text: "Your current case is unchanged." }), btn("Close", () => { importing = null; render(); $("#ia-import-file").focus(); }, { id: "ia-import-close" })]); return; }
    const p = importing.preview, accept = h("input", { type: "checkbox", id: "ia-import-staff" });
    fill(ip, [h("h3", { text: "Case file preview" + (p.runtime_match ? "" : " — unverified") }),
      h("dl", { class: "kv" },
        h("div", {}, h("dt", { text: "Active plan" }), h("dd", { text: districtLabel(p.active_plan.district) + " · " + ISSUE_LABEL[p.active_plan.issue_id] + " · " + p.active_plan.steps.map((s) => s.step_id + " " + OP_LABEL[s.operation]).join("; ") })),
        h("div", {}, h("dt", { text: "Branches" }), h("dd", { text: String(p.branch_count) })),
        h("div", {}, h("dt", { text: "Saved selections" }), h("dd", { text: p.selection_count + " finding reference(s)" + (p.has_action ? " and one response" : "") + ". Facts are regenerated by replay; saved text is not used." })),
        h("div", {}, h("dt", { text: "Evidence snapshot" }), h("dd", { text: short(p.snapshot_id) + " · " + p.operation_version + " · " + p.recipe_version + (p.runtime_match ? " — served by this release" : " — not served by this release") }))),
      p.runtime_match ? null : h("p", { class: "alert", text: "This file needs a different evidence snapshot or version. It cannot be replayed here, so no verified brief or print is available for it. The file and your current case are unchanged. For historical R2 cases, use the matching live R2 app or run the documented r2 input profile with retained original inputs." }),
      p.staff_items && p.runtime_match ? h("div", {}, h("p", { text: "The file holds " + p.staff_items + " staff entr" + (p.staff_items === 1 ? "y" : "ies") + " (unverified staff text):" }),
        h("ul", {}, p.staff_preview.flatMap((r) => r.items.map((it) => h("li", { text: (STAFF_LABEL[it.kind] || it.kind) + " — " + (it.value || plain(it.item || it.tracking)) })))),
        h("label", { class: "ia-check", for: "ia-import-staff" }, accept, " Also open this staff text (it will need review before any brief)")) : null,
      h("div", { class: "btn-row" },
        p.runtime_match ? btn("Replay and open this case", () => { const r = C.beginImport(state, importing, { accept_staff_work: accept.checked }, ids); if (r.error) return alertUser(r.error.message); state = r.state; notice = "Replaying the file's active plan. Only the typed plan and references are sent, never the file."; send(r.request); }, { class: "btn btn-primary", id: "ia-import-go", disabled: busy }) : null,
        btn("Cancel", () => { importing = null; notice = "Import cancelled. Your current case is unchanged."; render(); $("#ia-import-file").focus(); }, { id: "ia-import-cancel" }))]);
  }

  // ------------------------------------------------------------------ map
  function syncMap(force) {
    const p = C.active(state).plan, key = [state.runtime.snapshot_id, p.district.chamber, p.district.code, p.map_session].join("|");
    if (key === mapKey && !force) return;
    if (key === mapKey) return;
    mapKey = key;
    const box = $("#ia-map");
    if (!mapHandle && window.IA1Map && typeof window.IA1Map.mount === "function") mapHandle = window.IA1Map.mount(box);
    if (!mapHandle) { fill(box, [h("p", { class: "alert", text: "Boundary map unavailable in this build. The district identity below and all other evidence remain available." })]); return; }
    // The viewer replaces its own content and ignores late geometry for an earlier identity.
    mapHandle.update({ snapshot_id: state.runtime.snapshot_id, chamber: p.district.chamber, code: p.district.code, session: p.map_session });
  }
  function syncMapText(b) {
    const d = b.plan.district;
    fill($("#ia-map-text"), [h("div", {}, h("dt", { text: "District" }), h("dd", { text: districtLabel(d) + " (state 15)" })),
      h("div", {}, h("dt", { text: "Statistics boundary" }), h("dd", { text: "2024 session" })),
      h("div", {}, h("dt", { text: "Map boundary shown" }), h("dd", { text: b.plan.map_session + " session" })),
      h("div", {}, h("dt", { text: "Inquiry area" }), h("dd", { text: b.plan.service_area_id ? AREA_LABEL[b.plan.service_area_id] + " (staff-chosen scope, not a geographic finding)" : "None chosen" }))]);
  }

  // ------------------------------------------------------------------ wiring
  function wire() {
    const ctx = (patch) => editDraft(C.setContext(state.draft, patch), "Context edited. Choose Apply plan to review and run the change.");
    $("#ia-chamber").addEventListener("change", (e) => { const ch = e.target.value, code = state.draft.district.code; ctx({ district: { chamber: ch, code: ch === "senate" && Number(code) > 25 ? "025" : code } }); });
    $("#ia-code").addEventListener("change", (e) => ctx({ district: { chamber: state.draft.district.chamber, code: e.target.value } }));
    $("#ia-issue").addEventListener("change", (e) => ctx({ issue_id: e.target.value }));
    $("#ia-service").addEventListener("change", (e) => ctx({ service_area_id: e.target.value || null }));
    $("#ia-map-session").addEventListener("change", (e) => ctx({ map_session: Number(e.target.value) }));
    $("#ia-ask").addEventListener("submit", (e) => {
      e.preventDefault();
      const text = $("#ia-utterance").value;
      const r = C.beginInterpret(state, text, ids);
      if (r.error) return alertUser(r.error.message);
      state = r.state; interp = { utterance: text, matched_fields: [], inherited_fields: [], choices: [], reason: null, status: "pending" }; notice = "Interpreting. Nothing is run until you apply it.";
      send(r.request);
    });
    $("#ia-add-btn").addEventListener("click", () => {
      const op = $("#ia-add-op").value, r = C.addStep(state.draft, op, defaultArgs(op));
      editDraft(r, "Step added to the draft with a default scope. Open “Change scope” to adjust it, then Apply plan.");
      if (!r.error) { const s = r.plan.steps[r.plan.steps.length - 1], dt = $("#ia-scope-" + s.step_id); if (dt) { dt.open = true; dt.querySelector("summary").focus(); } }
    });
    $("#ia-apply").addEventListener("click", applyPlan);
    $("#ia-discard").addEventListener("click", () => { state = Object.assign({}, state, { draft: JSON.parse(JSON.stringify(C.active(state).plan)) }); preview = null; notice = "Draft edits discarded. The plan matches the last applied context."; render(); });
    $("#ia-cancel").addEventListener("click", () => { state = C.cancelPending(state); notice = "Request cancelled. Any late reply will be ignored. Earlier results are unchanged."; render(); });
    $("#ia-review-btn").addEventListener("click", () => set(C.markReviewed(state), "Staff content marked as reviewed for this context."));
    const brief = (clean) => { const r = C.beginBrief(state, { clean: clean }, ids); if (r.error) return alertUser(r.error.message); state = r.state; notice = "Creating the brief…"; send(r.request); };
    $("#ia-brief-btn").addEventListener("click", () => brief(false));
    $("#ia-clean-brief-btn").addEventListener("click", () => brief(true));
    $("#ia-print-btn").addEventListener("click", () => { if (C.printStatus(state).ok) window.print(); });
    $("#ia-download-staff").addEventListener("change", render);
    $("#ia-download").addEventListener("click", () => {
      const staff = $("#ia-download-staff").checked, data = C.exportCase(state, { include_staff_work: staff });
      const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 1)], { type: "application/json" }));
      const a = h("a", { href: url, download: "haic-case-" + districtLabel(C.active(state).plan.district).toLowerCase().replace(" ", "-") + (staff ? "-with-staff-work" : "") + ".json" });
      document.body.append(a); a.click(); a.remove(); URL.revokeObjectURL(url);
      if (staff) savedDigest = C.canonical(data);
      // The page cannot see whether the browser saved the file, so it does not claim that it did.
      notice = (staff ? "Download requested with staff work as plain, unencrypted text." : "Download requested: typed plan and references only. No prompt, title, notes, owners, dates, tracking or completion marks.") + " Check your browser's downloads to confirm the file was saved.";
      render();
    });
    $("#ia-import-file").addEventListener("change", async (e) => {
      const file = e.target.files && e.target.files[0];
      e.target.value = "";
      if (!file) return;
      if (file.size > C.LIMITS.case_bytes) importing = { ok: false, issues: [{ path: "", code: "too_large", message: "The file is larger than the 262,144-byte case limit. It was not read." }] };
      else { let text = ""; try { text = await file.text(); } catch (err) { text = ""; } importing = C.parseCaseFile(text, state.runtime); }
      render(); $("#ia-import-preview").focus();
    });
    // Only the reviewed investigation brief prints while this view is open.
    window.addEventListener("beforeprint", () => {
      if ($("#tab-investigation").hidden) return;
      const root = $("#print-root"), doc = $("#ia-brief-out .brief-doc") || $("#ia-brief-out").firstElementChild, st = C.printStatus(state);
      fill(root, st.ok && doc ? [doc.cloneNode(true)] : [h("p", { text: "No verified brief is ready to print. " + st.message })]);
    });
  }

  function unavailable(message) {
    fill($("#ia-boot"), [h("section", { class: "notice notice-error", role: "alert" }, h("h3", { text: "Investigation is not available" }), h("p", { text: message }),
      btn("Open the guided single-operation view", () => $("#tab-btn-workflow").click(), { id: "ia-boot-guided" }), " ", btn("Try again", () => start(), { id: "ia-boot-retry" }))]);
    $("#ia-boot").hidden = false; $("#ia-workspace").hidden = true;
  }

  async function start() {
    if (!C) return unavailable("The case module did not load.");
    let cat;
    try { const r = await fetch("/api/catalog", { credentials: "same-origin" }); cat = await r.json(); } catch (e) { return unavailable("The server did not respond. Nothing was lost; try again."); }
    boot = cat && cat.investigation;
    if (!boot || typeof boot.snapshot_id !== "string" || boot.schema_version !== C.SCHEMA_VERSION) return unavailable("This release does not expose the investigation runtime identities. The guided view still works.");
    catalog = cat;
    const runtime = { snapshot_id: boot.snapshot_id, release_id: boot.release_id || "", operation_version: boot.operation_version, schema_version: boot.schema_version, recipe_versions: boot.recipe_versions || ["aging_at_home/1", "custom/1"] };
    const issues = [], plan = boot.default_plan && C.validPlan(boot.default_plan, "plan", issues) ? boot.default_plan : C.defaultPlan();
    const first = !state;
    state = C.createState(runtime, ids, plan);
    $("#ia-runtime").textContent = "Evidence " + short(boot.snapshot_id) + " · data " + short(boot.data_snapshot_id) + " · sources " + short(boot.metadata_snapshot_id) + " · " + boot.operation_version;
    $("#ia-runtime").title = boot.snapshot_id;
    $("#ia-boot").hidden = true; $("#ia-workspace").hidden = false;
    if (first) wire();
    render(); syncMap(false);
    runActive();
  }

  document.addEventListener("DOMContentLoaded", start);
})();
