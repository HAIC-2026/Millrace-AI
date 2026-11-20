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
  // A fresh desktop answer opens the map once its confirmed district is drawn, unless staff collapsed the map.
  let mapReadyKey = null, mapWanted = null, mapCollapsedByUser = false;
  let languageJob = null, languageResult = null;
  // Ephemeral question scope (never saved in the case): conflict basis, explicit step focus, last inspected finding.
  let questionBasis = null, questionFocus = null, questionSource = null, lastQuestion = '';
  // The executed question whose findings lead the page (never saved in the case). It is shown only while the
  // current results are exactly the plan the question produced, in the context where it ran.
  let answerBasis = null, pendingAnswer = null, gapReview = null;
  // A map-only fork observed on this page, tied to its first run. Dropped on cancel, replay, another change or rerun.
  let mapFork = null;
  let notice = "";
  let pointerDown = false, textRenderPending = false;
  let bootRun = false;          // the automatic first run after loading: focus stays where the page starts              // polite status line

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
  // The brief recommendation focused on the current question's answer (C.focusedBrief), set on every render;
  // null when no answer singles out findings, and the investigation's recommended brief applies instead.
  let briefFocus = null;
  // Unfinished add-checklist-item text per "case_id|branch_id" (page memory only; never in a case file).
  const addDrafts = new Map();
  const OP_LABEL = { profile: "Profile measures", compare: "Compare with a geography", program_evidence: "Program reference", outreach_lead: "Reviewed outreach hypothesis", administrative_evidence: "Administrative records" };
  const ISSUE_LABEL = { aging_at_home: "Older-adult support at home", food_assistance_outreach: "SNAP outreach", custom: "Custom investigation" };
  const AREA_LABEL = { statewide: "Statewide", oahu: "Oʻahu", hawaii_island: "Hawaiʻi Island", maui: "Maui", molokai: "Molokaʻi", lanai: "Lānaʻi", kauai: "Kauaʻi", kalawao: "Kalawao" };
  const TIER_LABEL = { reference: "Dated program reference", hypothesis: "Reviewed outreach hypothesis", verification_action: "Agency action (staff verification)" };
  const KIND_LABEL = { statistic: "Statistic", comparison: "Comparison", program_relevance: "Program reference", outreach_hypothesis: "Outreach hypothesis", administrative_context: "Administrative record (not district data)" };
  const CHANGE_LABEL = { district: "district", map_session: "map session", issue: "issue", service_area: "service area", comparator: "comparison geography", program: "program", step_scope: "step scope", response: "agency action" };
  const STAFF_LABEL = { title: "Title", note: "Staff note", next_steps: "Next steps", finding_note: "Finding note", checklist: "Checklist entry", tracking: "Office tracking entry" };
  const districtLabel = (d) => (d.chamber === "house" ? "House " : "Senate ") + d.code;
  // Human wording only: machine identities stay in the case file, the API reply and diagnostics.
  let sourceLabels = {};
  const srcLabel = (id) => sourceLabels[id] || "Recorded source";
  const humanWords = (v) => { const t = String(v == null ? "" : v).replace(/_/g, " ").trim(); return t ? t.charAt(0).toUpperCase() + t.slice(1) : "Not recorded"; };
  const humanDate = (v) => (typeof v === "string" && /^\d{4}-\d{2}-\d{2}/.test(v) ? v.slice(0, 10) : v ? String(v) : "not recorded");
  const PENDING_LABEL = { run: "Running the plan…", brief: "Creating the brief…", interpret: "Reading your typed request…", restore: "Replaying the saved context…", import: "Replaying the case file… Editing is paused until it opens (this case is then replaced) or you cancel the request." };
  const COUNT_COMPARISON_LIMIT = "Counts for geographies of different size are shown side by side without a difference; the fixture has no published rate for this measure.";
  // Use the same wording as the printed brief for this exact canonical reason.
  const limitText = (limit) => limit === COUNT_COMPARISON_LIMIT ? limit.replace("the fixture has", "the data has") : plain(limit);
  const CHECK_LABEL = { agency_route: "Agency route", partner_plan: "Partner plan", next_check: "Next check" };
  const checkLabel = (id) => CHECK_LABEL[id] || (/^custom/.test(id) ? "Custom item" : humanWords(id));
  const FIELD_LABEL = { district: "District", issue_id: "Issue", issue: "Issue", service_area_id: "Area for program questions", map_session: "Map boundary", metric_ids: "Measures", comparison_geography: "Comparison geography", program_ids: "Programs", program_id: "Program", steps: "Steps", removed_step_id: "Remove step", focus: "Focused step" };
  const fieldLabel = (f) => FIELD_LABEL[f] || humanWords(f);
  // Typed values shown with the same wording as the selectors (no raw ids).
  function valueText(field, v) {
    if (v === null || v === undefined || v === "") return field === "service_area_id" ? "None chosen" : field === "metric_ids" ? "All 20 measures" : "—";
    if (field === "issue_id" || field === "issue") return ISSUE_LABEL[v] || humanWords(v);
    if (field === "service_area_id") return AREA_LABEL[v] || humanWords(v);
    if (field === "map_session") return v + " session";
    if (field === "district" && v.chamber) return districtLabel(v);
    if (field === "comparison_geography") return geoLabel(v);
    if (field === "metric_ids" && Array.isArray(v)) return v.map(metricLabel).join("; ");
    if (field === "steps" && Array.isArray(v)) return v.map((st, i) => (i + 1) + ". " + (OP_LABEL[st.operation] || humanWords(st.operation)) + " — " + stepScope(st)).join("; ");
    if (field === "removed_step_id") {
      const steps = (state && state.draft ? state.draft.steps : []), i = steps.findIndex((st) => st.step_id === v);
      return i >= 0 ? "Step " + (i + 1) + " · " + (OP_LABEL[steps[i].operation] || humanWords(steps[i].operation)) + " (typed-request name " + v + ")" : "Step with typed-request name " + v;
    }
    if ((field === "program_ids" || field === "program_id")) return [].concat(v).map(programLabel).join("; ");
    return plain(v);
  }
  // True when the last brief attempt failed and the previous brief still matches this context. This states
  // retention only: whether that brief fits one printed page is reported by the measured One-page brief status.
  const previousBriefKept = () => !!(state.last_error && state.last_error.kind === "brief" && C.printStatus(state).ok);
  const PREVIOUS_BRIEF = "The previous brief is kept unchanged; the failed attempt did not replace it. Its print status is shown under One-page brief.";
  // Display form for agency/publisher/jurisdiction names recorded as "Hawaii <body>"; stored data is unchanged.
  const hawaiiDisplay = (t) => String(t == null ? "" : t).replace(/\bHawaii (?=(DBEDT|DOH|DHS|Legislature|Office of Elections|Public Housing Authority|statewide)\b)/g, "Hawaiʻi ");
  const plural = (n, one, many) => n + " " + (n === 1 ? one : many);
  // Display spelling for place names recorded without diacritics in geography labels ("Hawaii County" shows as
  // "Hawaiʻi County"). Geography labels only: identifiers, source titles, publishers and claim text are unchanged.
  const PLACE = { Hawaii: "Hawaiʻi", Kauai: "Kauaʻi", Oahu: "Oʻahu", Molokai: "Molokaʻi", Lanai: "Lānaʻi" };
  // Display only: the canonical geography label (part of each claim identity) keeps its recorded wording.
  const placeDisplay = (t) => String(t == null ? "" : t).replace(/\b(Hawaii|Kauai|Oahu|Molokai|Lanai)\b/g, (m) => PLACE[m]).replace(/ \(boundary session (\d{4})\)/g, " ($1 district boundaries)");
  // The scope that tells saved contexts of one district and issue apart: each comparison geography in the
  // plan's steps and the staff-chosen program area. A geography not in the catalog is named as unlisted.
  function planScope(p) {
    const bits = [];
    (p && Array.isArray(p.steps) ? p.steps : []).forEach((st) => {
      const g = st && st.operation === "compare" && st.args ? st.args.comparison_geography : null;
      if (typeof g === "string") {
        const known = (catalog.geographies || []).concat(catalog.unavailable_geographies || []).find((x) => x.geography_id === g);
        bits.push("compared with " + (known ? placeDisplay(known.label) : "an unlisted geography"));
      }
    });
    if (p && p.service_area_id) bits.push("program area " + (AREA_LABEL[p.service_area_id] || "not listed"));
    return Array.from(new Set(bits)).join(", ");
  }
  // The map year is the plan's display choice only; every statistic uses the 2024 district boundaries (the plan is unchanged).
  const mapYearLabel = (p) => p.map_session + " map display, 2024 district statistics";
  const planLabel = (p) => districtLabel(p.district) + " · " + (ISSUE_LABEL[p.issue_id] || humanWords(p.issue_id)) + (planScope(p) ? " · " + planScope(p) : "") + " · " + mapYearLabel(p);

  const metricLabel = (id) => ((catalog.metrics || []).find((m) => m.metric_id === id) || {}).label || id;
  const programLabel = (id) => ((catalog.programs || []).find((p) => p.program_id === id) || {}).name || id;
  function geoLabel(id) {
    const g = (catalog.geographies || []).concat(catalog.unavailable_geographies || []).find((x) => x.geography_id === id);
    return g ? placeDisplay(g.label) : id;
  }
  const adminRows = () => catalog.administrative_rows || catalog.participation || [];
  function adminLabel(id) {
    const r = adminRows().find((x) => x.observation_id === id);
    return r ? [r.series_label || r.label || r.program_id, placeDisplay(typeof r.geography === "object" && r.geography ? (r.geography.label || r.geography.name) : r.geography) || null, r.period].filter(Boolean).join(" · ") : "Recorded administrative row";
  }
  function stepScope(s) {
    const a = s.args;
    if (s.operation === "profile") return a.metric_ids === null ? "All 20 measures" : a.metric_ids.map(metricLabel).join("; ");
    if (s.operation === "compare") return a.metric_ids.map(metricLabel).join("; ") + " — comparison: " + geoLabel(a.comparison_geography);
    if (s.operation === "program_evidence") return a.program_ids.map(programLabel).join("; ");
    if (s.operation === "outreach_lead") return programLabel(a.program_id) + " — complete reviewed measure set; hypothesis reference: State";
    return a.observation_ids.map(adminLabel).join("; ");
  }
  // Staff-facing wording for recorded values: known issue, operation and geography identifiers and plan
  // fields use the selector labels; anything else is shown as recorded. Identifiers stay in the data.
  // Ordinary text for the publisher's controlled-estimate marker; the marker itself stays in the data and source inspection.
  const MOE_NOT_PUBLISHED = "Controlled estimate; no numeric margin of error published";
  const VERIFIED_LABEL = { true: "matches the retained cell", false: "not checked against a retained cell", null: "original cell not reread" };
  function plain(v, depth) {
    if (v === null || v === undefined || v === "") return "—";
    if (typeof v === "string") {
      if (ISSUE_LABEL[v]) return ISSUE_LABEL[v];
      if (OP_LABEL[v]) return OP_LABEL[v];
      if (/^HI-[A-Z]+-/.test(v) && catalog) { const g = geoLabel(v); if (g !== v) return g; }
      return v;
    }
    if (typeof v !== "object") return String(v);
    if ((depth || 0) > 2) return "…";
    if (Array.isArray(v)) return v.map((x) => plain(x, (depth || 0) + 1)).join("; ");
    if (v.chamber && v.code) return districtLabel(v);
    if (typeof v.operation === "string" && v.args && typeof v.args === "object") {
      let scope = null;
      try { scope = stepScope(v); } catch (e) { scope = null; }
      return (OP_LABEL[v.operation] || humanWords(v.operation)) + (scope ? " — " + scope : "");
    }
    return Object.keys(v).filter((k) => v[k] !== null && v[k] !== "" && !/(^|_)(id|ids|hash|sha256|digest|path)$/.test(k) || FIELD_LABEL[k]).map((k) =>
      k === "cell_verified" ? "Recorded value " + (VERIFIED_LABEL[String(v[k])] || plain(v[k], (depth || 0) + 1)) :
      k === "args" && v[k] && typeof v[k] === "object" ? plain(v[k], (depth || 0) + 1) :
      FIELD_LABEL[k] ? fieldLabel(k) + ": " + valueText(k, v[k]) : humanWords(k) + ": " + plain(v[k], (depth || 0) + 1)).join(", ");
  }

  // ------------------------------------------------------------------ state plumbing
  function renderAfterTextCommit() {
    textRenderPending = true;
    setTimeout(() => {
      if (!textRenderPending || pointerDown) return;
      flushActive(false); // retain text in the next field; a focused native date is still being edited
      if (textRenderPending) render();
    }, 0);
  }
  function set(result, okMessage, deferRender) {
    if (result.error) { if (result.state) state = result.state; alertUser(result.error.message); render(); return false; }
    if (result.state) state = result.state;
    if (okMessage) notice = okMessage;
    if (deferRender) renderAfterTextCommit(); else render();
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
      flushActive(false);
      return finish(C.applyTransportFailure(state, request.request_id, "network"));
    }
    try { body = await resp.json(); } catch (e) { body = null; }
    if (resp.status === 403) {
      // Session or origin check failed: renew the session cookie, keep all local work, ask for a retry.
      try { await fetch("/api/health", { credentials: "same-origin" }); } catch (e) { /* retry stays available */ }
      flushActive(false);
      return finish(C.applyTransportFailure(state, request.request_id, "session"));
    }
    let planHash = null;
    if (body && Array.isArray(body.steps) && body.normalized_plan && request.mode === "run") {
      // Client-internal plan identity for the staff-review token: SHA-256 of the canonical typed Plan.
      // The server recomputes and checks it; the reply itself is left exactly as received.
      try { planHash = await sha256Hex(C.planCanonical(body.normalized_plan)); } catch (e) { planHash = null; }
    }
    // Staff text still being typed belongs to the context on screen now, so it is committed there before the reply
    // is applied (a restore or import may switch the active context). request_id is the originating request, checked
    // against the pending one after all async work above.
    flushActive(false);
    const result = C.applyResponse(state, body, { http_status: resp.status, plan_hash: planHash, request_id: request.request_id });
    const returnToAsk = pendingAnswer && pendingAnswer.district_review && userInComposer();
    finish(result);
    answerAfterRun(result, returnToAsk);
  }
  // A run started by a question: when it commits the question's exact plan in the active context, its requested
  // findings lead the page. Any other completed reply drops the pending question.
  function answerAfterRun(result, returnToAsk) {
    if (!pendingAnswer || result.outcome === "error" || result.outcome === "discarded") return;
    if (result.outcome !== "committed") { pendingAnswer = null; return; }
    const b = C.active(state), origin = pendingAnswer.origin_branch_id, rebind = !!pendingAnswer.rebind;
    pendingAnswer.branch_id = b.branch_id;
    if (!settleAnswer()) return;
    delete answerBasis.rebind;
    if (rebind) { notice = "The agency action was chosen in a new context with the same plan and replayed findings; your answer carried over. Choose " + (answerBasis.kind === "outreach" ? "Create SNAP outreach brief" : "Create brief from this answer") + " to make the brief."; render(); return; }
    if (answerBasis.kind === "outreach") {
      notice = "SNAP outreach opened for " + districtLabel(b.plan.district) + ". It does not answer how many residents qualify but are not enrolled; no such count is available." + (result.status === "ok" ? "" : " Some steps did not produce findings.") + openedContextNote(origin);
      const inComposer = userInComposer(); render(); if (inComposer) focusAnswer(); return;
    }
    if (answerBasis.kind !== "answer") return;
    const res = C.currentResults(state), unsingled = !answerBasis.step_ids.length || C.focusedFindings(res, answerBasis.step_ids, answerBasis.only).length > 1;
    notice = "Your question ran for " + districtLabel(b.plan.district) + "." + (unsingled ? " It did not single out one finding, so related findings are shown to choose from." : " The answer is shown first; other findings follow.") + (result.status === "ok" ? "" : " Some steps did not produce findings.") + openedContextNote(origin);
    const inComposer = returnToAsk || userInComposer();
    render(); if (inComposer) focusAnswer();
    openMapForAnswer();
  }
  // Names a context a question opened and the room left, so the four-context limit is never reached silently.
  function openedContextNote(originBranchId) {
    const b = C.active(state), n = state.case.branches.length, i = state.case.branches.findIndex((x) => x.branch_id === b.branch_id);
    if (!originBranchId || originBranchId === b.branch_id) return "";
    const left = C.LIMITS.branches - n;
    return " It opened as Investigation " + (i + 1) + "; your earlier context is kept under Save or reopen the case. " + (left > 0 ? plural(left, "more context", "more contexts") + " can be opened in this case." : "This case now holds the most contexts it can; a question that changes the plan will need one removed first.");
  }
  // True while keyboard focus is still in the question area (or nowhere), so a result may take focus.
  function userInComposer() {
    const a = document.activeElement;
    return !a || a === document.body || !a.isConnected || !!(a.closest && a.closest("#ia-question")) || a.id === "ia-cancel";
  }
  // A background result or preview must not finish a native staff date edit by taking focus.
  function activeDate() {
    const el = document.activeElement;
    return el && el.isConnected && el.commitDate && el.closest(".ia-tray") ? el : null;
  }
  // An incomplete native date can have an empty value even after a button has taken focus.
  function incompleteStaffDate(root = $(".ia-tray")) {
    const date = root && $('input[type="date"]:invalid', root);
    return date && date.validity.badInput ? date : null;
  }
  function focusIncompleteStaffDate() {
    const date = incompleteStaffDate();
    if (!date) return false;
    const details = date.closest("details");
    if (details) details.open = true;
    date.focus();
    return true;
  }
  function holdIncompleteStaffDate(action) {
    if (!focusIncompleteStaffDate()) return false;
    notice = "Finish or clear the staff date before " + action + ".";
    // Leave the current review in place so the same confirmation is available after clearing the field.
    $("#ia-status").textContent = notice;
    return true;
  }
  function staffDateButton(label, onClick, attrs) {
    const button = btn(label, onClick, attrs);
    // Let the click run without blurring the native editor and losing its current segment.
    button.addEventListener("mousedown", (event) => {
      if (activeDate()?.validity.badInput) event.preventDefault();
    });
    return button;
  }

  function finish(result) {
    const quiet = bootRun; bootRun = false;
    const was = state.pending;   // the request this reply concluded (null when it was already cancelled)
    // Typed staff text was committed to its own context in send(), before this reply could switch the active context.
    state = result.state;
    if (result.outcome === "discarded") { notice = "A late reply for an earlier request was ignored. The current context is unchanged."; render(); return; }
    if (result.outcome === "error") {
      if (was && was.kind === "run") mapFork = null;
      const e = state.last_error || {};
      // Only the typed-request card of this exact request stops reading; its text stays in the box for a retry.
      if (was && was.kind === "interpret" && interp && interp.status === "pending" && interp.request_id === was.tokens.request_id) interp = Object.assign({}, interp, { status: "not_read" });
      notice = previousBriefKept() ? (e.code === "brief_overflow" ? "The new brief was not created: it is too long for one page." : "The new brief was not created.") + " " + PREVIOUS_BRIEF + " Your work is kept." :
        (e.code === "brief_overflow" ? "No brief was created: it is too long for one page. Choose what to leave out." :
        e.kind === "brief" ? "The brief was not created." : e.kind === "restore" && lastRestore ? lastRestore.name + " was not restored. You are still on " + contextName(C.active(state).branch_id) + "." : e.kind === "run" || e.kind === "restore" ? "The plan did not run." :
        e.kind === "interpret" ? "The typed request was not read." : e.kind === "import" ? "The case file was not opened." : "The request did not complete.") + " Your work is kept.";
      render(); const box = $("#ia-error"); if (box && !quiet && !activeDate()) box.focus(); return;
    }
    if (result.outcome === "interpreted") { interp = Object.assign({ status: result.status, utterance: interp ? interp.utterance : "" }, result.interpretation, { origin: result.origin, request_id: result.origin.request_id }); notice = result.status === "ok" ? "Typed request read. Review the proposed change, then choose Put in draft plan." : "The typed request needs a choice or is not supported. Nothing was run."; render(); const t = $("#ia-interpretation"); if (!activeDate()) t.focus(); return; }
    if (result.outcome === "brief") {
      notice = "Brief created for the current results."; render();
      if (!briefFits()) { notice = "Brief drafted, but it is too long to print on one page. Choose what to leave out under One-page brief."; render(); }
      const out = $("#ia-brief"); if (!activeDate()) out.focus(); return;
    }
    const dropped = (result.retired || []).filter((r) => r.claim_ref).length;
    if (result.outcome === "imported") {
      // A reopened case starts with no unfinished add-item text from the page's earlier case.
      addDrafts.clear();
      const box = $("#ia-chk-new"); if (box) box.value = "";
      // Staff-notes download consent belongs to the case it was given for: every successful replay (also a file with the
      // same case ID, whose contents may differ) starts unchecked. Preview, cancel, failure and restore keep the choice.
      const consent = $("#ia-download-staff"), wasOn = !!(consent && consent.checked); if (consent) consent.checked = false;
      // A typed proposal read for the outgoing case never crosses into the reopened one (even one with the same IDs).
      if (interp && interp.origin) interp = Object.assign({}, interp, { origin: null });
      importing = null; notice = "Case file replayed against this release's evidence and opened." + (dropped ? " " + plural(dropped, "saved selection was", "saved selections were") + " not reselected; see Selected findings." : "") +
        (wasOn ? " “Include staff notes” was turned off for this case; check it again before a download should include its staff notes." : ""); }
    else if (result.outcome === "restored") notice = "Context restored after an exact replay. Its staff notes and progress are shown as staff contributions from that context.";
    else notice = (result.draft_kept ? "Results updated for the plan you applied earlier. Your newer plan edits are kept as a draft; choose Apply plan to run them. " : "") + (result.status === "ok" ? "Results updated." : "Results updated; some steps did not produce findings (see Findings and evidence).") + (result.retired && result.retired.length ? " " + result.retired.length + " earlier selection" + (result.retired.length === 1 ? " was" : "s were") + " not carried into this context." : "");
    render();
    syncMap(true);
    if (!quiet) focusResults();
  }

  // Keyboard focus never falls to the page body: while a request runs it rests on Cancel request; when a
  // run, restore or import completes it moves to the findings heading unless staff moved it elsewhere.
  function holdFocus() {
    if (bootRun) return;
    const a = document.activeElement;
    if (!a || a === document.body || !a.isConnected || a.disabled || a.closest("[hidden]")) { const c = $("#ia-cancel"); if (c && !c.hidden) c.focus(); }
  }
  function focusResults() {
    const a = document.activeElement;
    if (!a || a === document.body || !a.isConnected || a.id === "ia-cancel" || a.disabled || a.closest("[hidden]")) $("#ia-evidence-h").focus();
  }

  // Restore target kept only for presentation (the case module keeps the current context on failure).
  let lastRestore = null;
  function contextName(branchId) {
    const i = state.case.branches.findIndex((br) => br.branch_id === branchId);
    if (i < 0) return "the current context";
    const p = state.case.branches[i].plan;
    return "Investigation " + (i + 1) + " (" + planLabel(p) + ")";
  }
  function restoreContext(branchId) {
    lastRestore = { branchId: branchId, name: contextName(branchId) };
    const r = C.beginRestore(state, branchId, ids);
    if (r.error) { if (r.state) state = r.state; alertUser(r.error.message); render(); return; }
    mapFork = null;
    state = r.state; notice = "Replaying " + lastRestore.name + " against its exact evidence…"; send(r.request); holdFocus();
  }

  function runActive() {
    const r = C.beginRun(state, ids);
    if (r.error) { if (r.state) state = r.state; alertUser(r.error.message); render(); return; }
    if (mapFork) {
      if (mapFork.revision === null) mapFork.revision = r.request.revision;
      else mapFork = null;
    }
    state = r.state; clearAlert(); notice = "Running the plan…";
    syncMap(false);
    send(r.request);
    holdFocus();
  }

  // Optional language uses its own request lifecycle; it never dispatches a plan.
  function questionScope() {
    // The inspected finding counts only while it is a finding of the current confirmed results.
    const res = C.currentResults(state), b = C.active(state);
    const src = questionSource && res && claimMap(res).has(C.refKey(questionSource.claim_ref)) && questionSource.branch_id === b.branch_id && questionSource.revision === b.last_ready_revision ? questionSource : null;
    return {basis:questionBasis, focus:questionFocus, source:src};
  }
  function languageContext() { return window.IALanguage.context(state, C.active, questionScope()); }
  // Question policy as the server states it in its catalog (limits); nothing about remaining questions is invented.
  function languageLimits() { const l = catalog.language && catalog.language.limits; return l && typeof l === "object" ? l : {}; }
  const deadlineMs = () => 1000 * (Number.isInteger(languageLimits().deadline_seconds) && languageLimits().deadline_seconds > 0 ? languageLimits().deadline_seconds : 25);
  function languagePolicy() {
    const l = languageLimits();
    if (!Number.isInteger(l.site_starts_per_window) || !Number.isInteger(l.site_window_seconds) || l.site_window_seconds <= 0) return "";
    const span = l.site_window_seconds % 60 === 0 ? plural(l.site_window_seconds / 60, "minute", "minutes") : plural(l.site_window_seconds, "second", "seconds");
    return "Questions are shared across the whole site: up to " + l.site_starts_per_window + " every " + span + ".";
  }
  function languageEnabled() { return !!(window.IALanguage && catalog.language && catalog.language.enabled === true && catalog.language.schema_version === 'ia-language/1'); }
  async function languagePost(action, body) {
    const r = await fetch('/api/language/' + action, {method:'POST', credentials:'same-origin', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
    let data = null; try { data = await r.json(); } catch (_) { /* handled as unavailable */ }
    return {http:r.status, data};
  }
  function cancelLanguage(message, recover) {
    const job = languageJob;
    if (!job) return;
    languageJob = null;
    job.cancelled = true;
    clearTimeout(job.timer);
    clearTimeout(job.deadlineTimer);
    if (job.pending) languagePost('cancel', {schema_version:'ia-language/1', request_id:job.request_id}).catch(() => {});
    languageResult = message ? {status: recover ? 'error' : 'notice', message} : null;
    lockQuestion();
  }
  function currentLanguage(job, body) {
    return languageJob === job && !job.cancelled && window.IALanguage.matches(body, job, languageContext(), state.runtime.release_id);
  }
  // A reply can arrive while staff are typing. Commit the focused field first so the re-render keeps it.
  // Background replies collect text, but a native date's year segment remains provisional until exit/save.
  function flushActive(commitDates = true) {
    const el = document.activeElement;
    if (!el || !el.closest || !el.closest(".ia-tray") || el.id === "ia-chk-new") return;
    if (el.commitDate) return commitDates ? el.commitDate() : undefined;
    if (el.tagName === "TEXTAREA" || (el.tagName === "INPUT" && ["text", "number", "date"].includes(el.type))) el.dispatchEvent(new Event("change", { bubbles: true }));
  }

  // While a question is being asked its text is read-only (still readable and focusable): an edit there used to cancel a
  // request that may already be charged. Derived only from the live job, so every finish, error and cancel path unlocks it.
  function lockQuestion() {
    const q = $('#ia-question-text');
    q.readOnly = !!(languageJob && languageJob.pending);
    $('#ia-question-example').disabled = q.readOnly || !!q.value.trim();
  }
  async function askLanguage(text) {
    if (!catalog.language || catalog.language.enabled !== true || !window.IALanguage) return;
    if (!text.trim() || Array.from(text).length > 500) { alertUser('Enter a question of up to 500 characters.'); return; }
    if (state.pending) { alertUser('Wait for the current request to finish or cancel it first.'); return; }
    cancelLanguage(); lastQuestion = text; notice = '';
    const job = {request_id:ids.uuid(), context:languageContext(), context_digest:null, pending:true, cancelled:false, started:Date.now(), timer:null, polls:0};
    languageJob = job; languageResult = {status:'pending',message:'Reading your question…'}; lockQuestion();
    job.deadlineTimer = setTimeout(() => { if (languageJob === job && job.pending) { flushActive(false); cancelLanguage('The question timed out. Your work is unchanged; use an option below or Advanced investigation.', true); render(); focusQuestionResult(); } }, deadlineMs());
    render();
    const body = {schema_version:'ia-language/1',request_id:job.request_id,context:job.context,utterance:text};
    try {
      const reply = await languagePost('start',body);
      if (languageJob !== job || job.cancelled) {
        // Cancel again after a late successful start, which may have raced an earlier cancellation.
        if (reply.http === 202) languagePost('cancel',{schema_version:'ia-language/1',request_id:job.request_id}).catch(() => {});
        return;
      }
      if (reply.http !== 202 || !currentLanguage(job,reply.data)) {
        const err = new Error(reply.http === 429 && reply.data && reply.data.code === 'shared_demonstration_rate_limit' ? 'rate_limited' : 'unavailable');
        // A refused start states the server's own policy text; nothing about remaining questions is invented.
        err.serverMessage = reply.data && typeof reply.data.message === 'string' && reply.data.code ? reply.data.message : '';
        err.guidedOnly = !!(reply.data && reply.data.code === 'guided_only_measure' && reply.data.model_calls === 0);
        throw err;
      }
      job.context_digest = reply.data.context_digest;
      scheduleLanguagePoll(job);
    } catch (e) {
      if (languageJob !== job) return;
      clearTimeout(job.deadlineTimer); job.pending = false; lockQuestion(); flushActive(false);
      const limited = e && e.message === 'rate_limited', guided = !!(e && e.guidedOnly);
      languageResult = {status:'error', limited, guided_only:guided, message:(e && e.serverMessage) || (limited ? 'The shared limit of 3 language questions every 5 minutes across the site has been reached.'
          : guided ? 'Ask covers the original 20 measures. This plan or selection uses a measure that is available only in guided controls, so the question was not sent.' : 'Language question unavailable.'),
        after:limited ? 'Your question is still in the box above. Choose a task and district in Single lookup.' : guided ? guidedOnlyAfter(job.context) : 'Your question is still in the box above.'}; render(); focusQuestionResult();
    }
  }
  // The guided-only measures this question's own context holds (plan steps and selected findings), named for staff.
  function guidedOnlyAfter(ctx) {
    const guidedOnly = new Set((catalog.metrics || []).filter((m) => m.guided_only === true).map((m) => m.metric_id)), found = [];
    const add = (id) => { if (guidedOnly.has(id) && !found.includes(id)) found.push(id); };
    [ctx && ctx.confirmed_plan, ctx && ctx.draft_plan].forEach((p) => (p && Array.isArray(p.steps) ? p.steps : []).forEach((s) => {
      if ((s.operation === 'profile' || s.operation === 'compare') && s.args && Array.isArray(s.args.metric_ids)) s.args.metric_ids.forEach(add);
    }));
    ((ctx && ctx.selected_claim_refs) || []).forEach((r) => { const m = /^(?:stat|cmp):.+:([a-z0-9_]+)$/.exec((r && r.finding_id) || ''); if (m) add(m[1]); });
    return (found.length ? 'Guided-only ' + (found.length === 1 ? 'measure' : 'measures') + ' here: ' + found.map(metricLabel).join('; ') + '. ' : '') +
      'Your question is still in the box above. It was not sent to OpenAI and does not count toward the shared question limit.';
  }
  function focusQuestionResult() { if (userInComposer()) { const r = $('#ia-question-result'); if (r && !r.hidden) r.focus(); } }
  function scheduleLanguagePoll(job) {
    const delays = [500,1000,2000];
    const delay = delays[Math.min(job.polls++,delays.length-1)];
    job.timer = setTimeout(() => pollLanguage(job),delay);
  }
  async function pollLanguage(job) {
    if (languageJob !== job) return;
    if (Date.now() - job.started >= deadlineMs()) { flushActive(false); cancelLanguage('The question timed out. Your work is unchanged; use an option below or Advanced investigation.', true); render(); focusQuestionResult(); return; }
    try {
      const reply = await languagePost('status',{schema_version:'ia-language/1',request_id:job.request_id});
      if (languageJob !== job) return;
      if (reply.http !== 200 || !currentLanguage(job,reply.data)) throw new Error('unavailable');
      if (reply.data.status === 'pending') { scheduleLanguagePoll(job); return; }
      // Staff text still being typed is committed before the answer renders or runs, so it is kept and counted by the review rules.
      clearTimeout(job.deadlineTimer); job.pending = false; lockQuestion(); flushActive(false); languageResult = reply.data;
      if (askOnce(job, reply.data)) return;
      render(); focusQuestionResult();
    } catch (_) {
      if (languageJob !== job) return;
      flushActive(false); cancelLanguage('Language question unavailable. Your work is unchanged; use an option below or Advanced investigation.', true); render(); focusQuestionResult();
    }
  }

  // ------------------------------------------------------------------ One Ask
  // Why a validated proposal needs a person to check it before it runs. Empty when it can run at once.
  function reviewProposal(result, job) {
    const plan = result.normalized_plan, ctx = job.context, held = ctx.confirmed_plan || ctx.draft_plan;
    const change = C.proposeChange(state, { plan: plan }), blockers = window.IALanguage.runBlockers(lastQuestion, held, plan);
    const reasons = workReasons(change, blockers.map((x) =>
      x.code === 'own_district' ? 'The question says “my district”. The app does not know which district is yours, so check that ' + districtLabel(plan.district) + ' is the one you mean.'
      : x.code === 'primary_changed' ? 'This would change the investigation district from ' + districtLabel(x.from) + ' to ' + districtLabel(x.to) + '. To compare these districts, name both in your question.'
      : 'It compares with ' + geoLabel(x.geography) + ', but the question does not name that district with House or Senate.'), 'running this proposal', 'this proposal');
    // Only the district confirmation can be combined with the fork review. Other guards keep the separate review.
    const wording = blockers.some(x => x.code === 'primary_changed') ? window.IALanguage.switchDistrictWording(lastQuestion, plan) : 'review';
    const cleanSwitch = reasons.length === 1 && blockers.length === 1 && blockers[0].code === 'primary_changed' &&
      wording === 'single' && change.fork && !activeDate() && !preview;
    if (!cleanSwitch) return { reasons, districtChange: null, clarifyDistrict: wording === 'clarify' };
    const staff = heldWork();
    return { reasons, districtChange: staff.notes || staff.unfinished || C.pendingReview(state).length ? null : change };
  }
  // Protections for earlier work before a plan from a question runs: a request in flight, a staff date being edited,
  // unapplied draft edits it would replace, and the context limit, staff notes or brief selections a new context affects.
  function workReasons(change, blockers, doing, what) {
    const reasons = [], b = C.active(state);
    if (state.pending) reasons.push('Another request is still running.');
    const date = activeDate();
    if (incompleteStaffDate() || (date && date.dateDirty())) reasons.push('A staff date is still being edited. Finish it or clear it before ' + doing + '.');
    if (!C.proposeChange(state, { plan: state.draft }).noop) reasons.push('Your plan has unapplied edits, and ' + what + ' would replace them.');
    reasons.push(...blockers);
    if (change.branch_limit) reasons.push('This case already holds four contexts. Download the case' + (C.staffExportPreview(state).length ? ' with staff notes' : '') + ', then remove one under Save or reopen the case.');
    else if (change.fork && state.case.branches.length === C.LIMITS.branches - 1) reasons.push('This would open the last of four contexts in this case. After it, a question that changes the plan needs a context removed first.');
    else if (change.fork && change.parked.length) reasons.push('This context has staff notes or checklist entries; review how they are kept before a new context opens.');
    else if (change.fork && (b.selected_claim_refs.length || b.selected_action_ref)) reasons.push('This context has brief selections; review how they are kept before a new context opens.');
    return reasons;
  }
  // A supported, unambiguous proposal that leaves earlier work untouched runs at once through the same plan route.
  function askOnce(job, result) {
    if (!result || result.status !== 'propose' || !result.normalized_plan || (result.intent !== 'create_plan' && result.intent !== 'replace_plan')) return false;
    if (!currentLanguage(job, result)) return false;
    const issues = [];
    if (!C.validPlan(result.normalized_plan, 'plan', issues) || !(state.runtime.recipe_versions || []).includes(result.normalized_plan.issue_id + '/1')) return false;
    const review = reviewProposal(result, job);
    if (review.clarifyDistrict) {
      cancelLanguage('Which district should the investigation use? Ask again naming one district with House or Senate. To compare districts, name both with their chambers.');
      return false;
    }
    if (review.reasons.length) {
      result.review = review.reasons;
      job.offerDistrictReview = !!review.districtChange;
      return false;
    }
    runProposal(job, result, false);
    return true;
  }
  // Once the combined review is no longer accurate, keep the ordinary review route for this reply.
  function districtReviewCurrent(job, result) {
    if (!job || !job.offerDistrictReview) return null;
    const review = reviewProposal(result, job);
    if (review.districtChange) return review.districtChange;
    job.offerDistrictReview = false;
    result.review = review.reasons;
    return null;
  }

  // A held proposal opens the ordinary context review unless its context impact was already reviewed in Ask.
  function runProposal(job, result, reviewed, districtChange) {
    if (state.pending) { alertUser('Wait for the current request to finish or cancel it first.'); return; }
    const plan = JSON.parse(JSON.stringify(result.normalized_plan));
    const focus = window.IALanguage.requestedFocus(result, job.context && job.context.focused_step_id);
    pendingAnswer = { kind: 'answer', question: lastQuestion, plan: plan, step_ids: focus.step_ids, only: focus.only, fallback: !!focus.fallback, branch_id: null, district_review: !!districtChange,
      origin_branch_id: C.active(state).branch_id, prev_draft: JSON.parse(JSON.stringify(state.draft)) };
    cancelLanguage();
    clearAlert();
    if (districtChange) { commit(districtChange); return; }
    state = Object.assign({}, state, { draft: plan });
    const p = C.proposeChange(state, { plan: plan });
    if (p.noop && C.currentResults(state)) {
      pendingAnswer.branch_id = C.active(state).branch_id; settleAnswer();
      notice = 'Your question matches the plan already run, so its findings are shown without running again.'; const inComposer = userInComposer(); render(); if (inComposer) focusAnswer(); openMapForAnswer(); return;
    }
    if (reviewed) { applyPlan(); return; }
    commit(p);
  }
  // ------------------------------------------------------------------ SNAP participation gap
  // The server's typed, value-free offer on an unsupported SNAP participation-gap question naming one district. It is
  // used only while the question's context is current and the SNAP outreach recipe is admitted; it carries no figure.
  function snapGap(result) {
    const g = result && result.status === 'unsupported' ? result.participation_gap : null, d = g && g.district;
    if (!g || g.kind !== 'snap_participation_gap' || g.program_id !== 'snap_hi' || g.issue_id !== 'food_assistance_outreach' || !d) return null;
    if (d.state_fips !== '15' || d.boundary_session !== 2024 || !/^(house|senate)$/.test(d.chamber) || !/^\d{3}$/.test(d.code)) return null;
    if (!(state.runtime.recipe_versions || []).includes('food_assistance_outreach/1') || !languageJob || languageJob.pending) return null;
    return g;
  }
  // A staff checklist suggestion (a staff contribution, not agency content) for the data question the app cannot answer.
  const gapCheckText = (d) => 'Ask DHS BESSD for SNAP enrollment and eligible-population data for ' + districtLabel(d) + ' or a matching area.';
  function gapOutreach(result, gap) {
    const label = districtLabel(gap.district), review = gapReview && gapReview.request_id === languageJob.request_id ? gapReview.reasons : null;
    return h('div', { class: 'ia-alternatives', id: 'ia-gap' },
      h('h3', { class: 'ia-group-title', text: 'What you can take into a meeting' }),
      h('p', { class: 'hint', text: 'Open the checked SNAP outreach steps for ' + label + ': the all-ages poverty rate and median household income, SNAP program information and a reviewed outreach hypothesis, then create their brief. It sends no further question, and it does not count eligible or unenrolled residents.' }),
      review ? h('h4', { text: 'Check this before it opens' }) : null,
      review ? h('ul', { class: 'ia-review-reasons' }, review.map((r) => h('li', { text: r }))) : null,
      h('div', { class: 'btn-row' }, staffDateButton('Open SNAP outreach for ' + label, () => openGapOutreach(result, gap), { class: 'btn btn-primary', id: 'ia-gap-open', disabled: !!state.pending }),
        btn('Edit the plan yourself (Advanced investigation)', () => { cancelLanguage(); render(); openAdvanced(true); }, { class: 'btn-link ia-alt', id: 'ia-alt-advanced' })));
  }
  // Opens the offer through the same guarded route as a question's proposal: the question's context must still be
  // current, and earlier work (pending request, staff date, unapplied draft, context limit, notes or selections) is
  // listed for a second, explicit choice before anything runs. A new context still shows its context review.
  function openGapOutreach(result, gap) {
    const job = languageJob;
    if (!job || !currentLanguage(job, result) || snapGap(result) !== gap) { cancelLanguage('The context changed. Ask again or use guided controls.'); render(); return; }
    if (state.pending) { alertUser('Wait for the current request to finish or cancel it first.'); return; }
    if (holdIncompleteStaffDate('opening SNAP outreach')) return;
    const held = job.context.confirmed_plan || job.context.draft_plan;
    const built = held ? C.foodOutreachPlan(held, gap.district) : { error: { message: 'No plan is held for this question.' } };
    if (built.error) { cancelLanguage('SNAP outreach is unavailable for this context. Use guided controls.'); render(); return; }
    const reasons = workReasons(C.proposeChange(state, { plan: built.plan }), [], 'opening SNAP outreach', 'opening SNAP outreach');
    const reviewed = !!(gapReview && gapReview.request_id === job.request_id && reasons.every((r) => gapReview.reasons.includes(r)));
    if (reasons.length && !reviewed) { gapReview = { request_id: job.request_id, reasons: reasons }; render(); const t = $('#ia-gap-open'); if (t) t.focus(); return; }
    gapReview = null;
    pendingAnswer = { kind: 'outreach', question: lastQuestion, plan: JSON.parse(JSON.stringify(built.plan)), step_ids: [], only: {}, branch_id: null,
      district: JSON.parse(JSON.stringify(gap.district)), origin_branch_id: C.active(state).branch_id, prev_draft: JSON.parse(JSON.stringify(state.draft)) };
    cancelLanguage();
    state = Object.assign({}, state, { draft: built.plan });
    clearAlert();
    const p = C.proposeChange(state, { plan: built.plan });
    if (p.noop && C.currentResults(state)) {
      pendingAnswer.branch_id = C.active(state).branch_id; settleAnswer();
      notice = 'SNAP outreach for ' + districtLabel(gap.district) + ' is already the current plan, so its findings are shown without running again.'; const inComposer = userInComposer(); render(); if (inComposer) focusAnswer(); return;
    }
    if (reviewed) { applyPlan(); return; }
    commit(p);
  }
  function settleAnswer() {
    const b = C.active(state);
    answerBasis = pendingAnswer && pendingAnswer.branch_id === b.branch_id && C.canonical(b.plan) === C.canonical(pendingAnswer.plan) && C.currentResults(state) ? pendingAnswer : null;
    pendingAnswer = null;
    return !!answerBasis;
  }
  function answerCurrent(res) {
    const a = answerBasis, b = C.active(state);
    return a && res && a.branch_id === b.branch_id && C.canonical(b.plan) === C.canonical(a.plan) ? a : null;
  }
  function focusAnswer() { const h3 = $('#ia-answer-h'); if (h3) h3.focus(); }
  function openAdvanced(focusSummary) { const d = $('#ia-advanced'); d.open = true; if (focusSummary) d.querySelector('summary').focus(); }

  // Only the whole server-verified tuple on a matching refusal can prefill the lookup.
  function rateComparisonAlternative(job, result) {
    if (!job || !currentLanguage(job, result) || result.status !== 'unsupported' ||
        result.reason_code !== 'unavailable_evidence' || result.intent !== 'none' || result.normalized_plan !== null ||
        result.clarify_field !== '' || !Array.isArray(result.choices) || result.choices.length !== 3) return null;
    const [districtChoice, metricChoice, comparatorChoice] = result.choices;
    if (districtChoice?.field !== 'district' || metricChoice?.field !== 'metric' || comparatorChoice?.field !== 'comparator') return null;
    const d = districtChoice.value, m = metricChoice.value, g = comparatorChoice.value;
    if (m !== 'poverty_rate_65_plus' || metricChoice.alias !== 'm_' + m || !catalog.metrics.some(x => x.metric_id === m) ||
        typeof g !== 'string' || !/^HI-COUNTY-\d{3}-2024$/.test(g) || comparatorChoice.alias !== 'g_' + g ||
        !catalog.geographies.some(x => x.geography_id === g) ||
        !d || !/^(house|senate)$/.test(d.chamber) || typeof d.code !== 'string' || !/^\d{3}$/.test(d.code) ||
        districtChoice.alias !== 'd_' + d.chamber[0] + d.code ||
        !catalog.districts.some(x => x.chamber === d.chamber && x.code === d.code && x.boundary_session === 2024 && x.has_statistics)) return null;
    return { task: 'compare', district: { chamber: d.chamber, code: d.code, boundary_session: 2024 }, metric_ids: [m], comparison_geography: g };
  }
  // Guided controls are separate from findings already run for the active district.
  function guidedAlternatives(result) {
    const job = languageJob, comparison = rateComparisonAlternative(job, result);
    const res = C.currentResults(state), b = C.active(state), nodes = [];
    if (res) res.steps.filter((st) => st.status === 'ok' && Array.isArray(st.claim_refs) && st.claim_refs.length && st.operation !== 'administrative_evidence').slice(0, 4).forEach((st) => {
      const ps = res.plan.steps.find((x) => x.step_id === st.step_id);
      if (!ps) return;
      const ms = ps.operation === 'profile' ? (ps.args.metric_ids === null ? ['all 20 measures'] : ps.args.metric_ids.map(metricLabel)) : [];
      const label = ps.operation === 'profile' ? 'Measures already run for ' + districtLabel(res.plan.district) + ': ' + (ms.length > 2 ? ms.slice(0, 2).join('; ') + ' and ' + (ms.length - 2) + ' more' : ms.join('; '))
        : ps.operation === 'compare' ? 'Comparison already run: ' + ps.args.metric_ids.map(metricLabel).join('; ') + ' with ' + geoLabel(ps.args.comparison_geography)
        : ps.operation === 'program_evidence' ? 'Recorded program information: ' + ps.args.program_ids.map(programLabel).join('; ') + ' (not an eligibility finding)'
        : 'Reviewed outreach hypothesis: ' + programLabel(ps.args.program_id) + ' (not a count of eligible or unenrolled residents)';
      nodes.push(h('li', {}, btn('Show: ' + label, () => {
        answerBasis = { kind: 'related', label: label, question: lastQuestion, plan: JSON.parse(JSON.stringify(b.plan)), step_ids: [st.step_id], only: {}, branch_id: b.branch_id };
        cancelLanguage(); notice = 'Showing findings already run in this context. They do not answer the question you asked.'; render(); focusAnswer();
      }, { class: 'btn-link ia-alt', id: 'ia-alt-' + st.step_id })));
    });
    return h('div', { class: 'ia-alternatives' }, h('h3', { class: 'ia-group-title', text: 'What you can do instead' }),
      comparison ? h('p', { class: 'hint', text: 'The published poverty rate for people age 65 and over is available for ' +
        districtLabel(comparison.district) + ' and ' + geoLabel(comparison.comparison_geography) + '. Choose it as a separate comparison.' }) : null,
      h('div', { class: 'btn-row' },
        result.limited ? null : staffDateButton(comparison ? 'Open this rate comparison in Single lookup' : 'Choose measures and geography in Single lookup', () => {
          if (languageResult !== result || holdIncompleteStaffDate('opening Single lookup')) return;
          window.DBLookup.openGuided(rateComparisonAlternative(job, result));
        }, { class: 'btn', id: 'ia-alt-lookup' }),
        btn('Edit the plan yourself (Advanced investigation)', () => { cancelLanguage(); render(); openAdvanced(true); }, { class: 'btn-link ia-alt', id: 'ia-alt-advanced' })),
      nodes.length ? h('h4', { text: 'Findings already run for ' + districtLabel(b.plan.district) }) : null,
      nodes.length ? h('ul', {}, nodes) : null);
  }
  // Plain explanation of a refusal, from the server's typed reason (never from the question text).
  function refusalText(result) {
    const gap = snapGap(result);
    if (gap) return 'No SNAP enrollment or eligible-population count is available for ' + districtLabel(gap.district) + ' or a matching area. The app has state and county enrollment totals.';
    if (result.status === 'unsupported' && result.reason_code === 'unsupported_operation') return 'This app cannot do what the question asks. It shows published district estimates, comparisons with a county, the State or another district, recorded program information and reviewed outreach hypotheses. It does not determine eligibility, count residents who are eligible but not enrolled, or test whether a difference is statistically significant.';
    if (result.status === 'unsupported') {
      const guided = (catalog.metrics || []).filter((m) => m.guided_only === true).length;
      return 'Ask does not have what the question asks for among its measures and recorded program information. No substitute figure is used: a rate is never shown in place of a count, and household Social Security income is not treated as fixed-income status.' +
        (guided ? ' Single lookup also lists ' + guided + ' guided measures that Ask does not use, such as survey-reported SNAP receipt, disability and health insurance. None is an enrollment or eligibility count.' : '');
    }
    if (result.status === 'uncertain') return 'The question could not be read reliably. Try again naming the district with House or Senate and the measure you want, or use an option below.';
    return null;
  }

  // A held proposal's typed diff in staff terms. Removed and changed steps are numbered in the plan the question used (its
  // basis: the draft, or the confirmed plan when staff chose it), added steps in the proposed plan; a scope route names the
  // step's live draft position. A changed step still in the draft offers its
  // existing scope editor (focus only); removed and added steps are references only. A new order is listed once, in the
  // proposed plan's visible order. Typed-request names are not shown here.
  function proposalDiff(result, ctx) {
    const before = ctx ? (ctx.draft_plan || ctx.confirmed_plan) : null, after = result.normalized_plan, items = [];
    const what = (st) => valueText('steps', st);
    result.typed_diff.forEach((d) => {
      if (d.field === 'step_order') return;
      if (d.field !== 'steps') { items.push(h('li', { text: [humanWords(d.change), fieldLabel(d.field || ''), 'from ' + valueText(d.field || '', d.before), 'to ' + valueText(d.field || '', d.after)].join(' · ') })); return; }
      const was = stepRef(before, d.step_id), now = stepRef(after, d.step_id);
      if (d.change === 'removed') items.push(h('li', { text: 'Removed · ' + (was ? 'step ' + was.n + ' of the plan the question used' : 'a step of the plan the question used') + ' · ' + what(d.before) }));
      else if (d.change === 'added') items.push(h('li', { text: 'Added · ' + (now ? 'step ' + now.n + ' of the proposed plan' : 'a step') + ' · ' + what(d.after) }));
      else {
        const replaced = !d.before || !d.after || d.before.operation !== d.after.operation;
        const route = was && !replaced ? scopeRoute('ia-diff-scope-' + d.step_id, d.step_id, d.before) : null;
        items.push(h('li', {}, 'Changed · ' + (was ? 'step ' + was.n + ' of the plan the question used' : 'a step') + (now && (!was || now.n !== was.n) ? ' (step ' + now.n + ' of the proposed plan)' : '') +
          ' · from ' + what(d.before) + ' · to ' + what(d.after), route ? ' ' : null, route));
      }
    });
    const ids = (p) => (p && Array.isArray(p.steps) ? p.steps.map((s) => s.step_id) : []), old = ids(before), next = ids(after);
    const kept = next.filter((id) => old.includes(id));
    if (kept.join() !== old.filter((id) => kept.includes(id)).join()) {
      // A moved step that is otherwise unchanged (and has no Changed row above) offers its scope editor while the draft
      // still holds exactly that step; added, removed, changed, replaced or stale steps do not.
      const listed = new Set(result.typed_diff.filter((d) => d.field === 'steps').map((d) => d.step_id));
      const routes = next.map((id, i) => {
        const w = stepRef(before, id), was = w && before.steps[w.n - 1];
        if (!w || w.n === i + 1 || listed.has(id) || C.canonical(was) !== C.canonical(after.steps[i])) return null;
        return scopeRoute('ia-order-scope-' + id, id, was, (live) => ({ text: 'Open step ' + live.n + ' scope (step ' + (i + 1) + ' in the proposal)',
          aria: 'Open the scope editor for step ' + live.n + ' of your draft plan, step ' + (i + 1) + ' of the proposed plan: ' + what(was) }));
      }).filter(Boolean);
      items.push(h('li', {}, 'New step order · ' + next.map((id, i) => {
        const w = stepRef(before, id);
        return (i + 1) + '. ' + what(after.steps[i]) + (!w ? ' (added)' : w.n !== i + 1 ? ' (step ' + w.n + ' in the plan the question used)' : '');
      }).join('; '), ...routes.flatMap((r) => [' ', r])));
    }
    return items;
  }

  function renderQuestionScope(enabled) {
    const box = $('#ia-question-scope'), b = C.active(state), ctx = enabled ? languageContext() : null;
    if (!box) return;
    if (!ctx) { box.hidden = true; fill(box, []); return; }
    // Drop scope that no longer applies (changed plans, removed step, new revision or case).
    if (questionBasis && !window.IALanguage.same(questionBasis, window.IALanguage.makeBasis(state, C.active, questionBasis.kind))) questionBasis = null;
    if (questionFocus && ctx.focused_step_id !== questionFocus) questionFocus = null;
    const scope = questionScope(); if (questionSource && !scope.source) questionSource = null;
    const held = ctx.confirmed_plan || ctx.draft_plan, parts = [];
    parts.push(h('span',{text:'This question uses: ' + (held ? districtLabel(held.district) + ' · ' + (ctx.confirmed_plan ? (questionBasis && questionBasis.kind === 'confirmed' ? 'confirmed plan' : 'current plan') : 'unapplied draft') : 'no plan')}));
    if (questionBasis) parts.push(' ', btn('Clear', () => { questionBasis = null; render(); }, {class:'btn-link','aria-label':'Clear plan choice for questions'}));
    if (ctx.focused_step_id) {
      const i = held.steps.findIndex((s) => s.step_id === ctx.focused_step_id), st = held.steps[i];
      parts.push(h('span',{text:' · step ' + (i + 1) + ' (' + (OP_LABEL[st.operation] || humanWords(st.operation)) + ')'}), ' ', btn('Clear', () => { questionFocus = null; render(); }, {class:'btn-link','aria-label':'Clear step for questions'}));
    }
    if (scope.source) {
      const c = claimMap(C.currentResults(state)).get(C.refKey(scope.source.claim_ref));
      parts.push(h('span',{text:' · finding: ' + (c ? claimShortName(c) : 'inspected finding')}), ' ', btn('Clear', () => { questionSource = null; render(); }, {class:'btn-link','aria-label':'Clear finding for questions'}));
    }
    const full = state.case.branches.length >= C.LIMITS.branches;
    box.hidden = false; fill(box, [h('p',{class:'hint'}, ...parts), full ? h('p',{class:'hint ia-limit-note', text:'This case holds four contexts. A question that changes the plan will be held until you remove a context under Save or reopen the case, and it still uses one of the site’s shared questions.'}) : null]);
  }
  function renderLanguage() {
    const enabled = !!(window.IALanguage && catalog.language && catalog.language.enabled === true && catalog.language.schema_version === 'ia-language/1');
    // Language is optional. When it is not admitted the whole section stays hidden; guided controls are complete.
    $('#ia-question').hidden = !enabled && !languageResult;
    $('#ia-question-form').hidden = !enabled;
    $('#ia-question-preview').hidden = !enabled;  // Shown only while language questions are actually on.
    $('#ia-language-off').hidden = enabled;
    // The always-visible notice and the sent-data detail are fixed copy in the page; this adds how a question runs and
    // the question policy the server states in its catalog.
    $('#ia-question-flow').textContent = enabled ? ['A clear, supported question runs at once on the bundled data. A proposal that would change your district, add a district comparison you did not name with House or Senate, or affect earlier work is shown for review first.', languagePolicy()].filter(Boolean).join(' ') : '';
    if (languageJob && !window.IALanguage.same(languageJob.context, languageContext())) cancelLanguage('The question scope or plan changed, so the question and its preview were cancelled.');
    renderQuestionScope(enabled);
    const pending = !!(languageJob && languageJob.pending);
    const runningAnswer = pendingAnswer && !pendingAnswer.rebind && state.pending && state.pending.kind === 'run' &&
      C.canonical(state.pending.plan) === C.canonical(pendingAnswer.plan);
    const earlier = pending || runningAnswer ? C.currentResults(state) : null;
    $('#ia-earlier-findings').hidden = !earlier;
    $('#ia-earlier-answer').hidden = !earlier || !answerCurrent(earlier);
    lockQuestion();
    $('#ia-question-cancel').hidden = !pending;
    $('#ia-question-submit').setAttribute('aria-disabled', pending ? 'true' : 'false');
    $('#ia-question-submit').textContent = pending ? 'Asking…' : 'Ask';
    const result = languageResult, box = $('#ia-question-result');
    if (!result) { fill(box, []); return; }
    const refusal = refusalText(result);
    const nodes = [h('p',{class: result.status === 'pending' ? 'loading' : null, text: refusal || result.message || (result.status === 'propose' ? 'Proposed interpretation; nothing has been applied or run.' : 'Use the guided controls to continue.')})];
    if (result.after) nodes.push(h('p',{class:'hint',text:result.after}));
    if (result.limited) nodes.push(h('button', { type:'button', class:'btn btn-primary', id:'ia-quota-lookup', text:'Open Single lookup' }));
    if (result.status === 'propose') {
      const np = result.normalized_plan, job = languageJob, districtChange = districtReviewCurrent(job, result);
      if (Array.isArray(result.review) && result.review.length) nodes.splice(0, 1,
        h('h3',{class:'ia-group-title',text:districtChange ? 'Review the district change' : 'Check this before it runs'}),
        districtChange ? h('p',{text:result.review[0]}) : h('ul',{class:'ia-review-reasons'},result.review.map((r) => h('li',{text:r}))),
        districtChange ? h('p',{text:CONTEXT_FORK_TEXT}) : null);
      if (np && np.district && Array.isArray(np.steps)) {
        nodes.push(h('h4',{text:'Proposed plan · ' + districtLabel(np.district)}),
          h('ol',{class:'ia-proposal-steps'},np.steps.map(st => h('li',{text:(OP_LABEL[st.operation] || humanWords(st.operation)) + ': ' + stepScope(st)}))));
      }
      const planEnd = nodes.length;
      if (Array.isArray(result.typed_diff) && result.typed_diff.length && (result.intent === 'replace_plan')) nodes.push(h('details',{id:'ia-proposal-diff'},h('summary',{text:'What changes from the plan you asked about'}),h('ul',{},proposalDiff(result, languageJob && languageJob.context))));
      if (Array.isArray(result.inherited_fields) && result.inherited_fields.length) {
        const context = languageJob && languageJob.context, confirmed = context && context.confirmed_plan;
        nodes.push(h('h4',{text:'Inherited from your confirmed context'}), h('ul',{},result.inherited_fields.map(key => h('li',{text:fieldLabel(key) + ': ' + (key === 'focus' ? 'the step you chose to ask about' : valueText(key, confirmed && confirmed[key]))}))));
      }
      if (result.intent === 'inspect_source') {
        const refs = Array.isArray(result.source_inspection_refs) ? result.source_inspection_refs : [];
        nodes.push(h('p',{text:'Choose a source to inspect. This does not change the plan.'}),...refs.filter(r => r && typeof r.source_id === 'string').map(r => h('button',{type:'button',class:'btn-link source-btn','data-source-id':r.source_id,'data-finding-id':r.finding_id || '',text:'Inspect source: ' + srcLabel(r.source_id)})));
      } else if (result.normalized_plan) {
        const usable = () => {
          if (!job || languageJob !== job) return false;
          if (!currentLanguage(job, result)) { cancelLanguage('The context changed. Ask again or use guided controls.'); render(); return false; }
          const issues = [];
          if (!C.validPlan(result.normalized_plan,'plan',issues) || !(state.runtime.recipe_versions || []).includes(result.normalized_plan.issue_id + '/1')) { cancelLanguage('This proposal is unavailable in the current release. Use guided controls.'); render(); return false; }
          return true;
        };
        const controls = h('div',{class:'btn-row'},
          staffDateButton(districtChange ? 'Switch to ' + districtLabel(np.district) + ' and run' : 'Run this proposal', () => {
            if (!usable() || holdIncompleteStaffDate('running this proposal')) return;
            if (!districtChange) { runProposal(job, result, true); return; }
            flushActive(false);
            if (!usable()) return;
            const current = districtReviewCurrent(job, result);
            if (!current) { render(); focusQuestionResult(); return; }
            runProposal(job, result, true, current);
          }, {class:'btn btn-primary', id:'ia-proposal-run', disabled: !!state.pending}),
          staffDateButton('Use this proposal in the draft', () => {
            if (!usable() || holdIncompleteStaffDate('using this proposal in the draft')) return;
            state = Object.assign({},state,{draft:JSON.parse(JSON.stringify(result.normalized_plan))});
            cancelLanguage(); notice = 'Proposal placed in the draft under Advanced investigation. Edit it if you wish, then choose Apply plan.'; render(); openAdvanced(false); $('#ia-apply').focus();
          },{id:'ia-proposal-draft'}), staffDateButton(districtChange ? 'Keep ' + districtLabel(C.active(state).plan.district) : 'Discard proposal', () => {
            if (languageJob !== job) return;
            const returnToQuestion = districtChange && userInComposer();
            cancelLanguage();
            const dateKept = focusIncompleteStaffDate();
            if (dateKept) notice = 'Proposal discarded. You can continue editing the staff date.';
            render();
            if (!dateKept && returnToQuestion) $('#ia-question-text').focus();
          },{id:'ia-proposal-discard'}));
        nodes.splice(districtChange ? planEnd : nodes.length, 0, controls);
      }
    }
    if (result.status === 'clarify' && Array.isArray(result.choices)) {
      // A source question uses the finding whose source was last inspected; brief selections are never changed for it.
      if (result.clarify_field === 'referent') nodes.push(h('p',{text:'To ask about one finding, choose “Inspect” on that finding’s source, then ask again. The question then uses that finding; your brief selections stay as they are.'}));
      nodes.push(h('p',{text:'Choose an applicable control, then ask again if you wish. No question is sent automatically.'}),h('ul',{},result.choices.map(choice => {
        let apply = null;
        // District/chamber: the choice is written into the question as a visible canonical prefix; nothing is sent and
        // the plan is not edited. Confirmed/draft: the next question uses that plan; neither plan changes and nothing runs.
        if ((choice.field === 'district' || choice.field === 'chamber') && window.IALanguage.withChoice(lastQuestion, choice) !== lastQuestion.replace(/^(?:(?:House|Senate) \d{1,2}|In the (?:House|Senate)): /, ''))
          apply = () => { $('#ia-question-text').value = window.IALanguage.withChoice(lastQuestion, choice); return 'Added “' + choice.label + '” to your question. Choose Ask to send it.'; };
        else if (choice.field === 'control_conflict' && (choice.value === 'confirmed' || choice.value === 'draft'))
          apply = () => { questionBasis = window.IALanguage.makeBasis(state, C.active, choice.value); $('#ia-question-text').value = lastQuestion;
            return choice.value === 'confirmed' ? 'The next question uses your confirmed plan. Your draft edits are kept.' : 'The next question uses your unapplied draft. Your confirmed findings are unchanged.'; };
        const label = choice.field === 'referent' && sourceLabels[choice.label] ? srcLabel(choice.label) : String(choice.label);
        if (!apply && choice.field === 'referent') return h('li',{text:label});
        return h('li',{},apply ? btn('Use ' + label,() => {cancelLanguage();notice=apply();render();$('#ia-question-text').focus();}) : label + ' — choose this under Advanced investigation.');
      })));
    }
    const gap = snapGap(result);
    if (gap) nodes.push(gapOutreach(result, gap));
    else if (result.status === 'unsupported' || result.status === 'uncertain' || result.status === 'error' || result.status === 'expired') nodes.push(guidedAlternatives(result));
    fill(box,nodes);
  }

  // The finding(s) the latest executed question asked for, first, with measure, value, uncertainty, area,
  // period and a direct source action. Values are the server's canonical fields shown as text; nothing is computed.
  function answerItem(c, st, opts) {
    const id = 'ia-c-' + st.step_id + '-' + c.claim_ref.semantic_hash.slice(7, 19), m = c.metric || {};
    const level = typeof c.moe_confidence_level === 'number' ? Math.round(c.moe_confidence_level * 100) + '% ' : '';
    const moe = (x, unit) => /^±/.test(String(x || '')) ? moeWithUnit(x, unit) : x ? String(x) : null;
    // Each side states its own margin: a published numeric margin with its own confidence level, a controlled
    // estimate, or a margin not published as a number. None is filled in.
    const sideLevel = (x) => typeof x.moe_confidence_level === 'number' ? Math.round(x.moe_confidence_level * 100) + '% ' : level;
    const sideMoe = (x) => C.moeStatus(x) || (/^±/.test(String(x.moe_display || '')) ? sideLevel(x) + 'margin of error ' + moeWithUnit(x.moe_display, x.unit || c.unit) : x.moe_display ? 'Margin of error not published as a number: ' + x.moe_display : null);
    const refs = (Array.isArray(c.source_inspection_refs) ? c.source_inspection_refs : []).filter((r) => r && typeof r.source_id === 'string');
    const sourceBtn = (r, what) => h('button', { type: 'button', class: 'btn-link source-btn', 'data-source-id': r.source_id, 'data-finding-id': typeof r.finding_id === 'string' ? r.finding_id : c.claim_ref.finding_id, text: 'Inspect source: ' + srcLabel(r.source_id) + (what ? ' — ' + what : ''),
      on: { click: () => { const b = C.active(state); questionSource = { claim_ref: JSON.parse(JSON.stringify(c.claim_ref)), branch_id: b.branch_id, revision: b.last_ready_revision }; renderLanguage(); } } });
    // One compact, labelled column per side: place, published value, its own margin and its own source.
    const sideBox = (x, role) => {
      if (!x) return null;
      const where = shortGeo(x.geography && x.geography.label), own = refs.find((r) => r.finding_id === x.finding_id), margin = sideMoe(x);
      return h('div', { class: 'ia-answer-side', role: 'group', 'aria-label': role + ': ' + where },
        h('p', { class: 'ia-answer-side-role', text: role }),
        h('p', { class: 'ia-answer-side-place', text: where }),
        h('p', { class: 'ia-answer-value' }, h('strong', { text: x.estimate_display == null ? 'Estimate unavailable' : valueWithUnit(x.estimate_display, x.unit || c.unit) })),
        margin ? h('p', { class: 'ia-answer-moe', text: margin }) : null,
        own ? h('p', { class: 'ia-answer-tools' }, sourceBtn(own, where)) : null);
    };
    let head, value = null, sub = null, text = null, sides = null;
    if (c.kind === 'statistic') {
      head = (m.label || 'Statistic') + ' · ' + shortGeo(c.geography && c.geography.label);
      value = valueWithUnit(c.estimate_display, c.unit);
      sub = C.moeStatus(c) || (/^±/.test(String(c.moe_display || '')) ? level + 'margin of error ' + moe(c.moe_display, c.unit) : c.moe_display ? 'Margin of error not published as a number: ' + c.moe_display : null);
    } else if (c.kind === 'comparison') {
      head = (m.label || 'Comparison') + ' · ' + shortGeo(c.left && c.left.geography && c.left.geography.label) + ' compared with ' + shortGeo(c.right && c.right.geography && c.right.geography.label);
      sides = h('div', { class: 'ia-answer-sides' }, sideBox(c.left, 'District'), sideBox(c.right, 'Compared with'));
      sub = c.difference ? 'Point difference ' + c.difference.display + ' ' + c.difference.unit + '. No statistical significance test is performed.' : 'Not differenced: ' + limitText(c.not_differenced_reason);
    } else { head = claimShortName(c); text = typeof c.text === 'string' ? c.text : null; }
    const facts = [c.kind === 'statistic' && c.unit ? 'Unit: ' + c.unit : null, periodText(c.period) ? 'Period: ' + periodText(c.period) : null, c.universe ? 'Universe: ' + c.universe : null].filter(Boolean).join(' · ');
    // A comparison's sources sit with their sides; any other finding keeps its first source here.
    const ownSources = sides ? refs.filter((r) => ![c.left, c.right].some((x) => x && r.finding_id === x.finding_id)).slice(0, 1) : refs.slice(0, 1);
    const on = C.active(state).selected_claim_refs.some((r) => C.refKey(r) === C.refKey(c.claim_ref));
    return h('div', { class: 'ia-answer-item' + (sides ? ' ia-answer-compare' : '') },
      h('p', { class: 'ia-answer-measure', text: head }),
      sides,
      value ? h('p', { class: 'ia-answer-value' }, h('strong', { text: value })) : null,
      sub ? h('p', { class: 'ia-answer-moe', text: sub }) : null,
      text ? h('p', { class: 'ia-answer-text', text: text }) : null,
      facts ? h('p', { class: 'ia-answer-facts', text: facts }) : null,
      c.annotation_meaning ? h('p', { class: 'ia-limit', text: 'Note: ' + c.annotation_meaning }) : null,
      opts && opts.select ? h('label', { class: 'ia-check ia-select', for: 'ia-rel-sel-' + c.claim_ref.semantic_hash.slice(7, 19) },
        h('input', { type: 'checkbox', id: 'ia-rel-sel-' + c.claim_ref.semantic_hash.slice(7, 19), checked: on, 'aria-label': 'Select for brief: ' + head,
          on: { change: (e) => set(C.toggleClaim(state, c.claim_ref, e.target.checked), e.target.checked ? 'Finding selected for the brief.' : 'Finding removed from the brief selection.') } }), ' Select for brief') : null,
      h('p', { class: 'ia-answer-tools' },
        ownSources.map((r) => sourceBtn(r)),
        ownSources.length ? ' · ' : null,
        btn('Show in findings', () => { const el = document.getElementById(id); if (el) el.focus(); }, { class: 'btn-link', id: 'ia-answer-go-' + c.claim_ref.semantic_hash.slice(7, 19) }),
        on ? h('span', { class: 'badge badge-info', text: 'In brief' }) : null));
  }
  // When the answer has more findings than one page holds, say which ones the brief starts with.
  const focusNote = (rec) => rec.requested > rec.claims.length ? " Your answer has " + rec.requested + " findings; the brief starts with " + plural(rec.claims.length, "finding", "findings") + " so it can fit one page. Select others under Findings and evidence; the fit is measured when the brief is created." : "";
  // Notes for the kinds of finding shown: survey estimates, administrative counts, program information.
  function answerCaptions(list) {
    const kinds = new Set(list.map((c) => c.kind)), out = [];
    // A published 90% margin is claimed only where each operand has one; a controlled or missing margin is never filled in.
    const statuses = new Set(list.flatMap((c) => (c.kind === 'comparison' ? [c.left, c.right] : c.kind === 'statistic' ? [c] : [])).map((x) => C.moeStatus(x)).filter(Boolean));
    if (kinds.has('statistic') || kinds.has('comparison')) out.push((statuses.size ? 'Survey estimates are published ACS 2020–2024 figures with 90% margins of error where a numeric margin is published, shown as recorded. ' +
      (statuses.has(C.MOE_STATUS.controlled) ? 'A controlled estimate has no numeric margin of error, and none is substituted. ' : '') + (statuses.has(C.MOE_STATUS.unavailable) ? 'Where a margin of error is unavailable, none is substituted. ' : '')
      : 'Survey estimates are published ACS 2020–2024 figures with 90% margins of error, shown as recorded. ') + 'A comparison makes no statistical significance test.');
    if (kinds.has('administrative_context')) out.push('Administrative counts are recorded state, county or island figures with their own period and coverage; they are not district counts or eligibility figures.');
    if (kinds.has('program_relevance') || kinds.has('outreach_hypothesis')) out.push('Program information and outreach hypotheses are recorded references for agency follow-up; agencies decide eligibility.');
    out.push('Other findings from this plan are listed below.');
    return out;
  }
  // The answer's own brief action, with what it selects, whether that brief exists, and why no agency action is attached.
  function answerBriefAction() {
    const b = C.active(state), rec = briefFocus, dirty = !C.proposeChange(state, { plan: state.draft }).noop;
    // An answer that is not about one program, in results with mixed programs: the answer's agency action would be a
    // guess, so the one-step answer brief is not offered. The Brief panel lists the choices; nothing changes here.
    if (C.recommendationGuard(C.currentResults(state), rec)) return h('div', { class: 'ia-answer-brief' },
      h('p', { class: 'hint', id: 'ia-answer-brief-what', text: 'These results name programs that do not match one agency action, so Create brief from this answer is not offered. Select the findings you want, choose an agency action or No agency action in the brief, then choose Create brief from my selection.' }),
      btn('Show brief choices', () => { const t = $('#ia-conflict-h'); if (t) t.focus(); }, { class: 'btn-link', id: 'ia-answer-brief-choices' }));
    const on = rec.claims.length === b.selected_claim_refs.length && rec.claims.every((c) => b.selected_claim_refs.some((r) => C.refKey(r) === C.refKey(c.claim_ref))) && C.actionKey(rec.action || null) === C.actionKey(b.selected_action_ref || null);
    const made = on && C.printStatus(state).ok;
    const what = (made ? 'Shown under One-page brief. It uses ' : 'Uses ') + rec.claims.map(claimShortName).join('; ') +
      (rec.card ? ' and the agency verification step for ' + programLabel(rec.card.program_id) : '') + '.' +
      (rec.action_note === 'no_matching_action' ? ' No agency action is added: no single agency action matches this answer.' : '') + focusNote(rec) +
      (dirty ? ' Apply or discard the plan edits first; the brief uses applied results only.' : '');
    return h('div', { class: 'ia-answer-brief' }, staffDateButton(made ? 'Brief from this answer created' : 'Create brief from this answer', () => createRecommended(), { class: 'btn btn-primary', id: 'ia-answer-brief', disabled: made || !!state.pending || dirty, 'aria-describedby': 'ia-answer-brief-what' }),
      h('p', { class: 'hint', id: 'ia-answer-brief-what', text: what }));
  }
  // A SNAP participation-gap question answered without a count, beside the checked SNAP outreach it opened: the
  // ordinary recommended brief for these results, and an optional staff checklist item for the agency data question.
  function outreachAnswer(res, a) {
    const b = C.active(state), label = districtLabel(res.plan.district), dirty = !C.proposeChange(state, { plan: state.draft }).noop;
    const rec = recommendedBrief(res), guard = C.recommendationGuard(res, rec);
    const on = rec.claims.length && rec.claims.length === b.selected_claim_refs.length && rec.claims.every((c) => b.selected_claim_refs.some((r) => C.refKey(r) === C.refKey(c.claim_ref))) && C.actionKey(rec.action || null) === C.actionKey(b.selected_action_ref || null);
    const made = !!on && C.printStatus(state).ok;
    const brief = guard || !rec.claims.length ? h('div', { class: 'ia-answer-brief' },
      h('p', { class: 'hint', id: 'ia-outreach-brief-what', text: 'These results do not match one recommended brief. Select the findings you want, choose an agency action or No agency action in the brief, then choose Create brief from my selection.' }),
      btn('Show brief choices', () => { const t = $('#ia-conflict-h') || $('#ia-brief-reason'); if (t) t.focus(); }, { class: 'btn-link', id: 'ia-outreach-brief-choices' }))
      : h('div', { class: 'ia-answer-brief' }, staffDateButton(made ? 'SNAP outreach brief created' : 'Create SNAP outreach brief', () => createRecommended(), { class: 'btn btn-primary', id: 'ia-outreach-brief', disabled: made || !!state.pending || dirty, 'aria-describedby': 'ia-outreach-brief-what' }),
        h('p', { class: 'hint', id: 'ia-outreach-brief-what', text: (made ? 'Shown under One-page brief. It uses ' : 'Uses ') + rec.claims.map(claimShortName).join('; ') + (rec.card ? ' and the agency verification step for ' + programLabel(rec.card.program_id) : '') + '. It states no count of eligible or unenrolled residents.' + (dirty ? ' Apply or discard the plan edits first; the brief uses applied results only.' : '') }));
    const text = gapCheckText(res.plan.district), edits = b.checklist_edits || [], added = edits.some((c) => c.text === text), free = C.CHECK_IDS.slice(3).find((k) => !edits.some((c) => c.item_id === k));
    const checkBlocked = dirty ? ' Apply or discard the plan edits before adding it.' : preview ? ' Finish or cancel the context review before adding it.' : '';
    const check = h('div', { class: 'ia-answer-brief', id: 'ia-gap-check' },
      h('p', { class: 'hint', id: 'ia-gap-check-what', text: 'Staff action for the brief: “' + text + '” ' + (added ? 'It is in the checklist and prints in the brief after the normal staff review.' : free ? 'Adding it also selects the SNAP outreach findings and agency action, and it prints in the brief after the normal staff review. Nothing is added unless you choose it.' + checkBlocked : 'The checklist already holds three custom items; edit one to use this wording.') }),
      !added && free && !guard && rec.claims.length ? staffDateButton('Add DHS data check to brief', () => {
        // The agency action is chosen first, through the ordinary recommended selection and its reviews, so the staff
        // item never turns that choice into a new context. If a review is needed, nothing is added yet.
        if (state.pending || preview || !canPrepareRecommendedBrief() || !useRecommended()) return;
        const now = C.active(state).checklist_edits || [], slot = C.CHECK_IDS.slice(3).find((k) => !now.some((c) => c.item_id === k));
        if (!slot) { render(); return; }
        const r = C.setChecklist(state, slot, { text: text });
        set(r, r.error ? null : 'SNAP outreach findings, agency action and DHS data check selected for the brief. Review staff notes, then create the brief.');
      }, { class: 'btn', id: 'ia-gap-check-add', disabled: !!state.pending || dirty || !!preview, 'aria-describedby': 'ia-gap-check-what' }) : null);
    return [
      h('h3', { id: 'ia-answer-h', class: 'ia-answer-title', tabindex: '-1', text: 'SNAP outreach · ' + label }),
      h('p', { class: 'ia-answer-q', text: 'You asked: “' + a.question + '”' }),
      h('p', { class: 'ia-answer-gap', text: 'No count: the app has no SNAP enrollment or eligible-population data for ' + label + '. These outreach findings are for agency follow-up.' }),
      check, brief,
      h('details', { id: 'ia-answer-how' }, h('summary', { text: 'How this was run (' + plural(res.plan.steps.length, 'step', 'steps') + ')' }),
        h('ol', {}, res.plan.steps.map((st) => h('li', { text: (OP_LABEL[st.operation] || humanWords(st.operation)) + ': ' + stepScope(st) }))),
        h('p', { class: 'hint', text: 'Change the steps under Advanced investigation.' }))];
  }
  // The metadata identifies an answer only when the focus (a changed, added, narrowed, kept or only step) resolves to a
  // single finding. Several findings are never guessed between: they are shown as related findings to choose from.
  function ambiguousFocus(a, res) { return !!(a && C.focusedFindings(res, a.step_ids, a.only).length > 1); }
  function renderAnswer(res) {
    const box = $('#ia-answer'), a = answerCurrent(res);
    box.hidden = !a;
    if (!a) { fill(box, []); return; }
    if (a.kind === 'outreach') { fill(box, outreachAnswer(res, a)); return; }
    const steps = res.steps.filter((st) => a.step_ids.includes(st.step_id));
    const stepOf = (c) => steps.find((st) => (st.claim_refs || []).some((r) => C.refKey(r) === C.refKey(c.claim_ref)));
    const lead = C.focusedFindings(res, a.step_ids, a.only).map((c) => ({ c: c, st: stepOf(c) })).filter((x) => x.st);
    // A requested comparison leads, then measures, then references; order within each kind follows the plan.
    const rank = (x) => (x.c.kind === 'comparison' ? 0 : x.c.kind === 'statistic' ? 1 : 2);
    lead.sort((x, y) => rank(x) - rank(y));
    const failed = steps.filter((st) => st.status !== 'ok'), related = a.kind === 'related';
    // A whole-plan proposal that singles out no step (for example an unchanged multi-step plan): the plan's own findings,
    // in plan order, labelled as related findings and not as an answer, each with its source and a selection control.
    const ambiguous = !related && steps.length > 0 && ambiguousFocus(a, res);
    const broad = !related && (!steps.length || ambiguous), claimsOf = claimMap(res), seen = new Set();
    const inFocus = ambiguous ? new Set(C.focusedFindings(res, a.step_ids, a.only).map((c) => C.refKey(c.claim_ref))) : null;
    const relatedItems = broad ? res.plan.steps.filter((ps) => !ambiguous || a.step_ids.includes(ps.step_id)).map((ps) => res.steps.find((st) => st.step_id === ps.step_id)).filter((st) => st && st.status === 'ok')
      .flatMap((st) => (st.claim_refs || []).map((r) => claimsOf.get(C.refKey(r))).filter((c) => c && (!inFocus || inFocus.has(C.refKey(c.claim_ref))) && !seen.has(C.refKey(c.claim_ref)) && seen.add(C.refKey(c.claim_ref))).map((c) => ({ c: c, st: st }))) : [];
    // A newer question is shown above; this answer stays labelled with the question it belongs to.
    const earlier = !related && !!languageResult && a.question !== lastQuestion;
    fill(box, [
      h('h3', { id: 'ia-answer-h', class: 'ia-answer-title', tabindex: '-1', text: (related ? 'Related evidence' : broad ? 'Related findings' : earlier ? 'Answer to your earlier question' : 'Answer') + ' · ' + districtLabel(res.plan.district) }),
      h('p', { class: 'ia-answer-q' }, related ? 'Related evidence, not an answer to your question “' + a.question + '”' : 'You asked: “' + a.question + '”'),
      related ? h('p', { class: 'ia-answer-q', text: 'Shown: ' + a.label }) : null,
      broad ? h('p', { class: 'ia-answer-gap', text: ambiguous
        ? 'Not a completed answer: your question ran as a step with several findings for ' + districtLabel(res.plan.district) + ', and the proposal did not single out which one answers it. Those findings are below in plan order. Select the one you mean, then create the brief from your selection; no further question is sent.'
        : 'Not a completed answer: your question ran as the whole plan for ' + districtLabel(res.plan.district) + ', and the proposal did not single out which finding answers it. The plan’s findings are below in plan order. Select the one you mean, then create the brief from your selection; no further question is sent.' }) : null,
      ...relatedItems.slice(0, 7).map((x) => answerItem(x.c, x.st, { select: true })),
      relatedItems.length > 7 ? h('details', { id: 'ia-answer-more' }, h('summary', { text: 'Show ' + plural(relatedItems.length - 7, 'more related finding', 'more related findings') }),
        ...relatedItems.slice(7).map((x) => answerItem(x.c, x.st, { select: true }))) : null,
      broad && relatedItems.length ? h('div', { class: 'ia-answer-brief' }, btn('Create brief from my selection', () => {
        const b = C.active(state), r = C.currentResults(state), block = briefBlock(b, r, !!state.pending, !C.proposeChange(state, { plan: state.draft }).noop, C.activeStaff(state), C.reviewCurrent(state), C.pendingReview(state));
        if (block) { notice = block; render(); $("#ia-brief-reason").focus(); return; }
        createBrief(false);
      }, { class: 'btn btn-primary', id: 'ia-answer-own-brief', disabled: !C.active(state).selected_claim_refs.length || !!state.pending }),
        h('p', { class: 'hint', text: C.active(state).selected_claim_refs.length ? plural(C.active(state).selected_claim_refs.length, 'finding is', 'findings are') + ' selected. The fit to one page is measured when the brief is created.' : 'Select at least one finding above first.' })) : null,
      ...(broad ? [] : lead.slice(0, 3)).map((x) => answerItem(x.c, x.st)),
      !broad && lead.length > 3 ? h('p', { class: 'hint', text: plural(lead.length - 3, 'more finding from this question is', 'more findings from this question are') + ' listed under Findings and evidence.' }) : null,
      ...failed.map((st) => h('div', { class: 'notice notice-unsupported' }, h('p', { text: 'Not answered: ' + (st.message || 'this step did not produce a result.') }), h('p', { class: 'hint', text: 'No substitute figure was used. See this step under Findings and evidence for choices.' }))),
      steps.length && !lead.length && !failed.length ? h('p', { class: 'muted', text: 'This step ran and found nothing to report for this district.' }) : null,
      ...answerCaptions((broad ? relatedItems : lead).map((x) => x.c)).map((t) => h('p', { class: 'hint', text: t })),
      briefFocus && !related && !broad ? answerBriefAction() : null,   // never an answer brief for related findings
      h('details', { id: 'ia-answer-how' }, h('summary', { text: 'How this was run (' + plural(res.plan.steps.length, 'step', 'steps') + ')' }),
        h('ol', {}, res.plan.steps.map((st) => h('li', { text: (OP_LABEL[st.operation] || humanWords(st.operation)) + ': ' + stepScope(st) + (!broad && a.step_ids.includes(st.step_id) ? ' — asked for' : '') }))),
        h('p', { class: 'hint', text: 'Change the steps under Advanced investigation.' }))]);
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

  // What Apply does with a draft (the current one by default), from the same decision applyPlan makes below: repeat the
  // run, run at once in this context, or open the context review first. Wording only; both Apply controls share it.
  function applyOutcome(draft) {
    const p = C.proposeChange(state, { plan: draft || state.draft });
    if (p.noop && C.currentResults(state)) return "rerun";
    if (!p.material || !p.fork) return p.reorder_only ? "direct_reorder" : "direct";
    return p.branch_limit ? "review_full" : "review";
  }
  function applyHint(outcome) {
    const res = C.currentResults(state);
    if (outcome === "review") return "Opens the context review first: this change opens a new context and the current one stays saved. Nothing runs until you confirm.";
    if (outcome === "review_full") return "Opens the context review first. This case already holds four contexts, so one must be removed before this change can run.";
    if (outcome === "direct_reorder") return "Runs the reordered plan at once in this context; no review is needed because order changes no fact.";
    if (outcome === "direct") return res ? "Runs the edited plan at once in this context; no review is needed. The current results stay shown until new ones arrive." : "Runs the plan at once in this context and lists its findings; no review is needed.";
    return "No edits since the last run. Run again repeats the same plan.";
  }
  const reviewsFirst = (outcome) => outcome === "review" || outcome === "review_full";
  // The upper action's name, from the same outcome: it opens a review (which cannot confirm at the four-context limit) or
  // runs the change directly. The draft note and edit notice use this exact name.
  const contextApplyLabel = (outcome) => outcome === "review_full" ? "Review these changes" : reviewsFirst(outcome) ? "Review and apply these changes" : "Apply these changes";

  function applyPlan() {
    const p = C.proposeChange(state, { plan: state.draft });
    const res = C.currentResults(state);
    // "Run again" replays the unchanged plan at a new revision; nothing is forked or parked.
    if (p.noop && res) { preview = null; runActive(); return; }
    if (!p.material || !p.fork) return commit(p);
    preview = p; render(); focusPreview();
  }

  // The context review takes focus where it opens; a staff date still being edited keeps focus (unchanged exception).
  // A review taller than the window (for example the four-context review at 320×568) would be scrolled by focus so that
  // its heading sits above the top, so it is focused without that scroll and aligned to its top instead. Tab from the
  // panel then reaches its first enabled control: Apply change and run, or Keep current context when that is disabled.
  function focusPreview() {
    if (activeDate()) return;
    const box = $("#ia-preview");
    if (box.getBoundingClientRect().height <= window.innerHeight) { box.focus(); return; }
    box.focus({ preventScroll: true });
    box.scrollIntoView({ block: "start" });
  }

  function commit(p) {
    if (holdIncompleteStaffDate("applying the change")) return;
    const origin = C.active(state);
    const r = C.confirmChange(state, p, ids);
    preview = null;
    if (r.error) { alertUser(r.error.message); render(); return; }
    state = r.state;
    // Only an exact map-only fork opened here is remembered (page memory); any other applied change forgets it.
    mapFork = r.forked && p.kinds.length === 1 && p.kinds[0] === "map_session" && !p.action_changed
      ? { case_id: state.case.case_id, origin_branch_id: origin.branch_id, origin_revision: origin.last_ready_revision,
        branch_id: C.active(state).branch_id, plan: C.canonical(C.active(state).plan), revision: null, consumed: false } : null;
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

  // A labelled checkbox group: every option is visible and wraps; no modifier keys are needed.
  const groupNote = {};
  function multi(id, label, options, chosen, max, onChange, help) {
    const picked = options.filter((o) => chosen.includes(o[0])).length;
    const boxes = options.map((o, i) => h("label", { class: "ia-check", for: id + "-" + i },
      h("input", { type: "checkbox", id: id + "-" + i, value: o[0], checked: chosen.includes(o[0]), on: { change: (e) => {
        const v = options.filter((x, j) => (j === i ? e.target.checked : chosen.includes(x[0]))).map((x) => x[0]);
        if (!v.length || v.length > max) {
          e.target.checked = !e.target.checked;
          groupNote[id] = v.length ? "Up to " + max + " can be chosen for this step. Clear one first; the step was not changed." : "Keep at least one selected; the step was not changed.";
          render(); return;
        }
        delete groupNote[id]; onChange(v);
      } } }), " ", o[1]));
    return h("fieldset", { class: "ia-multi" }, h("legend", {}, label + " ", h("span", { class: "count", text: picked + " of " + options.length + " selected" + (max < options.length ? " · up to " + max : "") })),
      help ? h("p", { class: "hint", text: help }) : null,
      h("div", { class: "ia-multi-list" }, boxes),
      groupNote[id] ? h("p", { class: "reason", role: "status", text: groupNote[id] }) : null);
  }
  function single(id, label, options, value, onChange) {
    const sel = h("select", { id: id });
    options.forEach((o) => sel.append(h("option", { value: o[0], text: o[1], selected: o[0] === value })));
    sel.addEventListener("change", () => onChange(sel.value));
    return h("div", { class: "field" }, h("label", { for: id, text: label }), sel);
  }

  function stepEditor(s) {
    const a = s.args, id = "ia-" + s.step_id, re = (args) => editDraft(C.rescopeStep(state.draft, s.step_id, args));
    const metrics = (catalog.metrics || []).map((m) => [m.metric_id, m.label + (m.guided_only === true ? " (guided only)" : "")]);
    const guidedHelp = (catalog.metrics || []).some((m) => m.guided_only === true) ? "Measures marked guided only run here, in Single lookup and in briefs. Ask about this district does not use them." : "";
    if (s.operation === "profile") {
      const all = h("input", { type: "checkbox", id: id + "-all", checked: a.metric_ids === null, on: { change: (e) => re({ metric_ids: e.target.checked ? null : C.AGING_METRICS.filter((m) => metrics.some((x) => x[0] === m)) }) } });
      return [h("label", { class: "ia-check ia-check-strong", for: id + "-all" }, all, " All 20 measures"),
        a.metric_ids === null ? (guidedHelp ? h("p", { class: "fine", text: "All 20 measures are the original measures. Clear this box to choose added guided-only measures." }) : null)
          : multi(id + "-metrics", "Measures shown", metrics, a.metric_ids, 20, (v) => re({ metric_ids: v }), guidedHelp)];
    }
    if (s.operation === "compare") {
      const geos = (catalog.geographies || []).map((g) => [g.geography_id, placeDisplay(g.label)]).concat((catalog.unavailable_geographies || []).map((g) => [g.geography_id, placeDisplay(g.label) + " (no statistics in this data)"]));
      return [multi(id + "-metrics", "Measures compared", metrics, a.metric_ids, 4, (v) => re({ metric_ids: v, comparison_geography: a.comparison_geography }), guidedHelp),
        single(id + "-geo", "Comparison geography", geos, a.comparison_geography, (v) => re({ metric_ids: a.metric_ids, comparison_geography: v })),
        h("p", { class: "fine", text: "A separate comparison never changes a hypothesis's own State reference. No statistical difference test is performed." })];
    }
    const programs = (catalog.programs || []).map((p) => [p.program_id, p.name]);
    if (s.operation === "program_evidence") return [multi(id + "-programs", "Programs", programs, a.program_ids, 5, (v) => re({ program_ids: v }), "A program reference is dated information, not an eligibility or need finding.")];
    if (s.operation === "outreach_lead") return [single(id + "-program", "Program", programs, a.program_id, (v) => re({ program_id: v })),
      h("p", { class: "fine", text: "Uses the program's complete reviewed measure set and State references. A subset or another comparator is not supported; remove this step to keep only the general reference." })];
    return [multi(id + "-rows", "Recorded rows", adminRows().map((r) => [r.observation_id, adminLabel(r.observation_id)]), a.observation_ids, 8, (v) => re({ observation_ids: v }), "State, county or island records; never district counts.")];
  }

  // Staff-note review chip from the same current checks the brief gate uses (parked items, active staff
  // notes, the review token), not the historical branch flag. Replay blocked keeps priority.
  function reviewChip(b) {
    if (b.review_state === "replay_blocked") return h("span", { class: "badge badge-note", text: "Replay blocked" });
    if (C.pendingReview(state).length) return h("span", { class: "badge badge-note", text: "Staff review required" });
    if (C.activeStaff(state).empty) return null;
    return C.reviewCurrent(state) ? h("span", { class: "badge badge-ok", text: "Staff notes reviewed" }) : h("span", { class: "badge badge-note", text: "Staff review required" });
  }

  // One compact selector for all 76 districts (51 House, 25 Senate), grouped by chamber.
  function fillDistricts(sel) {
    fill(sel, [["house", "House", 51], ["senate", "Senate", 25]].map((c) => h("optgroup", { label: c[1] + " districts" },
      Array.from({ length: c[2] }, (_, i) => {
        const code = String(i + 1).padStart(3, "0");
        return h("option", { value: c[0] + ":" + code, text: c[1] + " " + code });
      }))));
  }

  // ------------------------------------------------------------------ render
  function render() {
    if (!state) return;
    textRenderPending = false;
    const focused = document.activeElement, keep = focused && focused.id;
    const selection = focused && typeof focused.selectionStart === "number" ? [focused.selectionStart, focused.selectionEnd, focused.selectionDirection] : null;
    // Opened detail panels stay open across re-renders.
    const opened = Array.from(document.querySelectorAll("#ia-workspace details[open]"), (d) => d.id).filter(Boolean);
    const b = C.active(state), res = C.currentResults(state), busy = !!state.pending;
    const dirty = !C.proposeChange(state, { plan: state.draft }).noop;
    const ans = answerCurrent(res);
    briefFocus = ans && ans.kind === "answer" && ans.step_ids.length && !ambiguousFocus(ans, res) ? C.focusedBrief(res, ans.step_ids, ans.only) : null;
    $("#ia-status").textContent = busy ? (PENDING_LABEL[state.pending.kind] || "Working…") : notice;
    $("#ia-cancel").hidden = !busy;
    // While a confirmed case-file import replays, the outgoing case's controls are inert: anything typed now would be
    // replaced with the case. They return when the import opens, fails or is cancelled. Cancel request stays usable.
    const importPaused = !!(state.pending && state.pending.kind === "import");
    ["#ia-question", ".ia-grid", "#ia-brief"].forEach((sel) => { const el = document.querySelector(sel); if (el) { el.inert = importPaused; if (importPaused) el.setAttribute("aria-busy", "true"); else el.removeAttribute("aria-busy"); } });

    // context bar: the draft controls, then one line naming what the results below describe
    const d = state.draft.district, dsel = $("#ia-district");
    if (!dsel.options.length) fillDistricts(dsel);
    dsel.value = d.chamber + ":" + d.code;
    $("#ia-issue").value = state.draft.issue_id;
    $("#ia-service").value = state.draft.service_area_id || "";
    $("#ia-map-session").value = String(state.draft.map_session);
    const applied = b.plan, draftOther = dirty && (districtLabel(state.draft.district) !== districtLabel(applied.district) || state.draft.issue_id !== applied.issue_id);
    const outcome = dirty ? applyOutcome() : null;
    fill($("#ia-context-summary"), [
      h("span", {}, res ? "Showing results for " : "Not run yet: ", h("strong", { text: districtLabel(applied.district) }), " · " + (applied.issue_id === "custom" && ans && ans.kind === "answer" ? "Your question" : ISSUE_LABEL[applied.issue_id]) +
        (rescopedPrograms(applied) ? " (program steps use " + rescopedPrograms(applied).map(programLabel).join("; ") + ")" : "") +
        (applied.service_area_id ? " · program area " + AREA_LABEL[applied.service_area_id] + " (staff choice)" : "") + ". "),
      dirty ? h("span", { class: "badge badge-warn", text: "Draft has unapplied changes" }) : null,
      reviewChip(b),
      draftOther ? h("span", { class: "ia-draft-note" }, " Draft: " + districtLabel(state.draft.district) + " · " + ISSUE_LABEL[state.draft.issue_id] + ". " +
        "Choose " + contextApplyLabel(outcome) + (reviewsFirst(outcome) ? " to review it before it runs; nothing from the current results moves to it." : " to run it in this context.")) : null,
    ]);

    $("#ia-context-apply").hidden = !dirty || busy;
    // The same prediction as Apply plan: a context review first, or a direct run in this context.
    $("#ia-context-apply-why").textContent = dirty ? applyHint(outcome) : "";
    if (dirty) $("#ia-context-apply-btn").textContent = contextApplyLabel(outcome);

    renderLanguage();
    renderAnswer(res);
    const rescoped = rescopedPrograms(state.draft);
    $("#ia-issue-help").textContent = state.draft.issue_id === "custom" ? "Custom keeps the current steps so you can edit them under Advanced investigation. Remove any you do not need." :
      rescoped ? "The program steps use " + rescoped.map(programLabel).join("; ") + ", not " + programLabel(C.ISSUE_PROGRAMS[state.draft.issue_id]) + ", the program of the " + ISSUE_LABEL[state.draft.issue_id] + " recipe. The issue, its recipe and saved references stay as recorded. If this plan is no longer " + ISSUE_LABEL[state.draft.issue_id] + ", staff can choose Custom." : "";
    $("#ia-advanced-sum").textContent = plural(state.draft.steps.length, "step", "steps") + (dirty ? " · unapplied edits" : "") + " · edit steps and scope";
    renderInterpretation();
    renderSteps(dirty, busy);
    renderPreview();
    renderError();
    renderEvidence(res, dirty);
    renderResponses(res);
    renderBrief(b);   // measured first, so the Brief panel reason reflects the one-page check
    renderTray(b, res, busy, dirty);
    renderCase(b, busy);
    syncMapText(b);
    opened.forEach((id) => { const d = document.getElementById(id); if (d) d.open = true; });
    if (keep) {
      const el = document.getElementById(keep);
      if (el && el !== document.activeElement) {
        el.focus();
        if (selection && el.setSelectionRange) el.setSelectionRange(...selection);
      }
    }
  }

  // A guided plan whose program steps all use programs other than its recipe's program (a complete rescope): those
  // programs, in plan order; otherwise null. Display only.
  function rescopedPrograms(plan) {
    const expected = C.ISSUE_PROGRAMS[plan.issue_id], used = C.planPrograms(plan);
    return expected && used.length && !used.includes(expected) ? used : null;
  }

  // A plan step named as staff see it: its number in that plan, operation and scope. The typed-request name (s1, s2…) is
  // added only while the typed-request help is open, as in the step list.
  function stepRef(plan, stepId) {
    const steps = plan && Array.isArray(plan.steps) ? plan.steps : [], i = steps.findIndex((s) => s && s.step_id === stepId);
    if (i < 0) return null;
    let scope = null; try { scope = stepScope(steps[i]); } catch (e) { scope = null; }
    const op = OP_LABEL[steps[i].operation] || humanWords(steps[i].operation);
    return { n: i + 1, op: op, text: "Step " + (i + 1) + " · " + op + (scope ? " — " + scope : "") };
  }
  const aliasNote = (id) => ($("#ia-typed") && $("#ia-typed").open ? " (typed-request name " + id + ")" : "");
  // Focus-only route to a step's existing scope editor in the current draft. It edits nothing; a step no longer in the
  // draft is reported instead of opening another step.
  // expected: the step as the card or proposal read it; the route is offered (and acts) only while the draft still holds
  // exactly that step under that ID.
  function scopeRoute(id, stepId, expected, naming) {
    const same = () => { const st = state.draft.steps.find((s) => s.step_id === stepId); return !!st && !!expected && C.canonical(st) === C.canonical(expected); };
    const ref = stepRef(state.draft, stepId);
    if (!ref || !same()) return null;
    const named = naming ? naming(ref) : null;
    return btn(named ? named.text : "Open step " + ref.n + " scope", () => {
      const now = stepRef(state.draft, stepId), dt = document.getElementById("ia-scope-" + stepId);
      if (!now || !dt || !same()) { notice = "That step is no longer in the draft plan as it was read. Nothing was changed."; render(); return; }
      openAdvanced(false); dt.open = true; dt.querySelector("summary").focus();
    }, { class: "btn-link", id: id, "aria-label": named ? named.aria : "Open the scope editor for step " + ref.n + ", " + ref.op + ", in your draft plan" });
  }
  // The draft a typed card was read against (its origin), for naming steps after the draft has changed.
  function originDraft(card) {
    try { return card && card.origin && typeof card.origin.draft === "string" ? JSON.parse(card.origin.draft) : null; } catch (e) { return null; }
  }

  function renderInterpretation() {
    const box = $("#ia-interpretation");
    if (!interp) { fill(box, []); return; }
    const segs = C.interpretationSegments(interp.utterance, interp.matched_fields);
    const ended = interp.status === "cancelled" || interp.status === "not_read", stale = !ended && interp.status !== "pending" && !interpCurrent();
    // Each control acts only for the request this card was rendered for; a control left from an older card does nothing.
    const card = interp, mine = () => interp === card;
    // An added program step that the plan already holds exactly: the reply equals the draft it was read for, so there is
    // nothing to place and only Discard is offered (an explicit district or a distinct scope changes the plan).
    const alreadyPresent = interp.status === "ok" && !!interp.proposed_plan && !!interp.origin && C.canonical(interp.proposed_plan) === interp.origin.draft &&
      (interp.matched_fields || []).some((m) => m.field === "program_id");
    const reread = () => btn("Read the typed request again", () => { if (mine()) rereadTyped(); }, { class: "btn", id: "ia-reread-interp" });
    const nodes = [h("h3", { class: "ia-group-title", text: interp.status === "pending" ? "Reading the request…" : ended ? "Not read" : interp.status === "ok" ? (alreadyPresent ? "Already in the plan (no change)" : "Proposed plan change (not applied)") : interp.status === "clarification" ? "A choice is needed" : "Not supported" }),
      h("p", { class: "ia-utterance" }, segs.map((s) => (s.field ? h("mark", { title: "Matched: " + fieldLabel(s.field), text: s.text }) : s.text)))];
    if (ended) nodes.push(h("p", { text: interp.status === "cancelled" ? "The request was cancelled before it was read. A late reply will be ignored." : "The request did not complete, so nothing was read." }));
    if (interp.reason) nodes.push(h("p", { text: interp.reason }));
    if (interp.status !== "pending" && interp.status !== "ok") nodes.push(h("p", { class: "hint", text: "Your plan and other work are unchanged. Use the step controls above, or edit the request and read it again." }));
    if (ended) nodes.push(h("div", { class: "btn-row" }, reread()));
    if (stale && (interp.proposed_plan || interp.choices.length)) nodes.push(h("p", { class: "alert", id: "ia-interp-stale" }, "The plan, context or case changed after this request was read, so this proposal cannot be placed. Read the typed request again for the current draft plan. Nothing has run. ", reread()));
    const list = (title, items) => items.length ? h("div", {}, h("h4", { text: title }), h("ul", { class: "ia-fields" }, items.map((m) => h("li", {}, h("strong", { text: fieldLabel(m.field) + ": " }), valueText(m.field, m.value))))) : null;
    nodes.push(list("Matched in your text", interp.matched_fields), list("Inherited from the current plan", interp.inherited_fields));
    if (interp.choices.length) nodes.push(h("ul", { class: "ia-choices" }, interp.choices.map((c) => {
      // A step choice (which comparison to change, which step to remove) is named by its number, operation and scope in
      // the draft the request was read for. While that draft is still current it offers the step's own scope editor;
      // otherwise it stays a readable reference only.
      if (c && c.field === "step_id" && typeof c.value === "string") {
        const read = originDraft(card), ref = stepRef(read, c.value), at = read && Array.isArray(read.steps) ? read.steps.find((s) => s.step_id === c.value) : null;
        const route = !ended && !stale && interpCurrent() ? scopeRoute("ia-clar-scope-" + c.value, c.value, at) : null;
        return h("li", {}, (ref ? ref.text : "A step that is no longer in the plan") + aliasNote(c.value), route ? " " : null, route);
      }
      const label = String(c.label || plain(c.value));
      const usable = c && c.field === "district" && c.value && (c.value.chamber === "house" || c.value.chamber === "senate") && typeof c.value.code === "string";
      return h("li", {}, usable ? btn("Use " + label, () => { if (!placeable(card)) return; interp = null; editDraft(C.setContext(state.draft, { district: c.value }), label + " placed in the plan. Choose Apply plan to run it."); }) : label);
    })));
    if (interp.proposed_plan) nodes.push(h("div", { class: "btn-row" },
      alreadyPresent ? null : btn("Put in draft plan", () => { if (!placeable(card)) return; const p = card.proposed_plan; interp = null; state = Object.assign({}, state, { draft: p }); notice = C.proposeChange(state, { plan: state.draft }).noop ? "Typed request placed in the draft plan. It matches the current plan, and nothing has run." : "Typed request placed in the draft plan. Nothing has run. Review the steps, then choose Apply plan."; render(); $("#ia-apply").focus(); }, { class: "btn btn-primary", id: "ia-apply-interp" }),
      btn("Discard", () => { if (!mine()) return; interp = null; notice = "Typed request discarded. The plan is unchanged."; render(); })));
    fill(box, nodes);
  }
  // The proposal on screen still answers the request, case, context, applied revision and exact draft it was read for.
  function interpCurrent() { return !!interp && C.interpretationCurrent(state, interp.origin); }
  // Placing a proposal or choice: refused (nothing changes) when it is stale or a saved context is replaying.
  function placeable(card) {
    if (!card || interp !== card) return false;   // an older request's control: the newer card and draft stay as they are
    if (state.pending && (state.pending.kind === "restore" || state.pending.kind === "import")) { alertUser("A saved context is being replayed. Wait for it to finish, or cancel the request, before editing the plan."); render(); return false; }
    if (interpCurrent()) return true;
    notice = "The typed request was not placed: the plan, context or case changed after it was read. Nothing has run. Read it again for the current draft plan.";
    render(); const r = $("#ia-reread-interp"); if (r && !activeDate()) r.focus();
    return false;
  }
  // A fresh, deterministic read of the text in the Typed request box (the latest input) against the current draft.
  function rereadTyped() { $("#ia-ask").requestSubmit(); }

  function renderSteps(dirty, busy) {
    const plan = state.draft, res = C.currentResults(state);
    fill($("#ia-steps"), plan.steps.length ? plan.steps.map((s, i) => h("li", { class: "ia-step", id: "ia-step-" + s.step_id },
      h("div", { class: "ia-step-head" }, h("span", { class: "ia-step-title" }, h("span", { class: "ia-step-num", text: String(i + 1) }), h("strong", { class: "ia-step-name", text: OP_LABEL[s.operation] })),
        h("span", { class: "ia-step-tools" },
          btn("Move up", () => editDraft(C.moveStep(plan, s.step_id, -1), "Step moved. Order does not change any fact."), { class: "btn-link", id: "ia-up-" + s.step_id, disabled: i === 0, "aria-label": "Move step " + (i + 1) + " up" }),
          btn("Move down", () => editDraft(C.moveStep(plan, s.step_id, 1), "Step moved. Order does not change any fact."), { class: "btn-link", id: "ia-down-" + s.step_id, disabled: i === plan.steps.length - 1, "aria-label": "Move step " + (i + 1) + " down" }),
          btn("Remove", () => editDraft(C.removeStep(plan, s.step_id), "Step " + (i + 1) + " removed from the draft. Choose Apply plan to run it."), { class: "btn-link btn-danger", id: "ia-rm-" + s.step_id, "aria-label": "Remove step " + (i + 1) + ", " + OP_LABEL[s.operation] }),
          // Explicit step focus for the next language question; offered only for steps of the plan the question uses.
          languageEnabled() && (() => { const c = languageContext(), held = c.confirmed_plan || c.draft_plan; return held && held.steps.some((x) => x.step_id === s.step_id); })()
            ? btn(questionFocus === s.step_id ? "Asking about this step" : "Ask about this step", () => { questionFocus = questionFocus === s.step_id ? null : s.step_id; render(); $('#ia-question-text').focus(); }, { class: "btn-link", id: "ia-ask-" + s.step_id, "aria-pressed": questionFocus === s.step_id ? "true" : "false", "aria-label": "Ask a question about step " + (i + 1) + ", " + OP_LABEL[s.operation] }) : null)),
      h("p", { class: "ia-step-scope" }, stepScope(s), $("#ia-typed").open ? h("span", { class: "ia-step-id", text: " · typed-request name " + s.step_id }) : null),
      h("details", { id: "ia-scope-" + s.step_id }, h("summary", { text: "Change scope" }), stepEditor(s))))
      : [h("li", { class: "muted", text: "No steps. An empty plan has no results or printable brief. Add a step below." })]);
    $("#ia-step-count").textContent = plan.steps.length + " of 8";
    $("#ia-add-btn").disabled = plan.steps.length >= 8;
    $("#ia-add-reason").textContent = plan.steps.length >= 8 ? "A plan holds up to 8 steps. Remove one to add another." : "";
    $("#ia-apply").disabled = busy;
    $("#ia-apply").textContent = dirty || !res ? "Apply plan" : "Run again";
    $("#ia-discard").hidden = !dirty;
    $("#ia-apply-reason").textContent = busy ? "Wait for the current request to finish, or cancel it." :
      !plan.steps.length ? "Add at least one step to get findings." :
      dirty || !res ? applyHint(applyOutcome()) :
      "No edits since the last run. Run again repeats the same plan.";
  }

  const CONTEXT_FORK_TEXT = "The proposed plan opens in a new context. Your current context stays under Save or reopen the case.";
  function renderPreview() {
    const box = $("#ia-preview");
    box.hidden = !preview;
    if (!preview) { fill(box, []); return; }
    $("#ia-advanced").open = true;   // the context review sits with the plan; it is never left in a closed panel
    const p = preview, kinds = p.kinds.map((k) => CHANGE_LABEL[k] || k).join(", ");
    if (p.draft_key === undefined) p.draft_key = C.canonical(state.draft);   // the draft this review was opened against
    // An exact map-only fork: the display year is part of every district finding's identity, so selections never match
    // exactly. Say so before it runs, and name the one explicit recovery that may follow.
    const was = C.active(state), mapOnly = p.fork && C.mapOnlyChange(was.plan, p.plan);
    fill(box, [h("h3", { text: "Review this context change" }),
      h("p", { text: "This changes the " + kinds + ". " + CONTEXT_FORK_TEXT }),
      h("ul", {},
        h("li", { id: mapOnly ? "ia-preview-map" : null, text: p.clears_selections ? "Selected findings and the agency action are not carried over. No fact from the earlier context enters the new brief." :
          mapOnly && p.provisional_selections ? "The map display year is part of each district finding's recorded identity, so " + plural(p.provisional_selections, "selected finding is", "selected findings are") + " not kept automatically, although the statistics still use the 2024 district boundaries. " +
            "After the new context runs, if the server confirms the boundaries are the same and matches a selected profile statistic to the current results, you can choose Select again in the Brief panel." +
            (was.selected_action_ref ? " The agency action is not carried; choose it again under Agency verification if it still applies." : "") :
          plural(p.provisional_selections, "selected finding is", "selected findings are") + " kept only if exactly the same finding appears in the new results." }),
        h("li", { text: p.parked.length ? plural(p.parked.length, "staff note or checklist entry goes", "staff notes or checklist entries go") + " to review. Nothing is copied unless you choose it." : "There are no staff notes or checklist progress to review." }),
        p.kinds.includes("program") || p.kinds.includes("response") ? h("li", { text: "A different agency action never inherits done marks or notes from the earlier one." }) : null),
      p.branch_limit ? h("p", { class: "alert", text: "This case already holds four contexts. " + (fullDownloadCurrent() ? "Your last download request included all of it: remove a context under Save or reopen the case before applying." :
        "To apply this, " + downloadStep() + ", then remove a context under Save or reopen the case.") }) : null,
      h("div", { class: "btn-row" },
        staffDateButton("Apply change and run", () => {
          if (C.canonical(state.draft) !== p.draft_key) { preview = null; pendingAnswer = null; notice = "The plan was edited after this review opened, so the reviewed change was not applied. Your newer edits are kept in the draft; choose Apply plan to review them."; render(); $("#ia-apply").focus(); return; }
          commit(p);
        }, { class: "btn btn-primary", id: "ia-preview-confirm", disabled: p.branch_limit }),
        staffDateButton("Keep current context", () => {
          // The plan from before the question comes back only while the draft is still exactly the question's proposal.
          const pa = pendingAnswer, prev = pa && pa.prev_draft && pa.plan && C.canonical(state.draft) === C.canonical(pa.plan) ? pa.prev_draft : null;
          preview = null; pendingAnswer = null;
          if (prev) state = Object.assign({}, state, { draft: prev });
          notice = prev ? "No change applied. The proposal was not used, and your plan is as it was before the question." : "No change applied. Your edits remain in the draft plan.";
          const dateKept = focusIncompleteStaffDate();
          render(); if (!dateKept) $("#ia-apply").focus(); }, { id: "ia-preview-cancel" }))]);
  }

  // Exact evidence identities select an established replay route; unknown snapshots are not guessed.
  function replayHelp(snapshotId) {
    const r2 = "sha256:143fb7cbdf10a8a3b05a30228e44c347a2cd21d93819a3a3e79094dc847887d3";
    const public33af = "sha256:33af0580ddd697fbe16dedf1b335303cfc9a4e958df5c684f1eade8365dd6aa3";
    const publicAc065bd = "sha256:b1f06a08f8d61f5a5a15bf1f02c3ebf71c2e70a48442fe9f702a3cc837a28479";
    if (snapshotId === r2) return h("p", { class: "fine" },
      h("a", { href: "https://haic-r2.millrace.ai/", target: "_blank", rel: "noopener noreferrer", text: "Open the earlier version of this app that matches this case (opens in a new tab)" }),
      ". In that app, choose your saved case file again and review its preview. The link carries no case or staff notes.");
    if (snapshotId === public33af) return h("div", { class: "fine" },
      h("p", {}, h("a", { href: "https://github.com/HAIC-2026/Millrace-AI/blob/e2f2cf031fe7f193de08524a9ce49d5d5f14b5d4/README.md#run-the-bundled-snapshot", target: "_blank", rel: "noopener noreferrer", text: "Open the setup instructions for the matching public release (opens in a new tab)" }),
        ". The linked page names the exact release to run. Follow its setup with a separate working folder, open that local app, and choose your saved case file there."));
    if (snapshotId === publicAc065bd) return h("div", { class: "fine" },
      h("p", {}, "This case was saved with the earlier 20-measure public evidence. It reopens only on that exact release, commit ac065bd. ",
        h("a", { href: "https://github.com/HAIC-2026/Millrace-AI/blob/ac065bd83632c69ef77d55763bfb524068485c21/README.md#run-it-locally", target: "_blank", rel: "noopener noreferrer", text: "Open the setup instructions for that release (opens in a new tab)" }),
        ". Run it with a separate working folder, open that local app, and choose your saved case file there. The link carries no case or staff notes."));
    return null;
  }

  function renderError() {
    const box = $("#ia-error"), e = state.last_error;
    box.hidden = !e;
    if (!e) { fill(box, []); return; }
    const connection = e.code === "session_restarted" || e.code === "network_unavailable" || e.code === "unreadable_response";
    const nodes = [h("h3", { id: "ia-error-h", tabindex: "-1", text: e.code === "brief_overflow" ? "The brief is too long for one page" : connection ? "Connection problem — your work is kept" : "The request was not completed" }),
      // The overflow message from the server states internal estimate units; staff see plain wording instead.
      previousBriefKept() ? h("p", { text: PREVIOUS_BRIEF }) : null,
      h("p", { text: e.code === "brief_overflow" ? "No brief was created. The length check made before page layout found the selected content longer than one printed page." : e.message })];
    if (e.issues && e.issues.length && e.code !== "brief_overflow") nodes.push(h("ul", {}, e.issues.map((i) => h("li", { text: (i.path ? fieldLabel(String(i.path).split(".").pop()) + ": " : "") + i.message }))));
    if (e.code === "brief_overflow") {
      const dt = e.detail || {};
      if (typeof dt.estimated_units === "number" && typeof dt.budget_units === "number" && dt.budget_units > 0) nodes.push(h("p", { text: "That estimate is about " + Math.max(1, Math.round((dt.estimated_units / dt.budget_units - 1) * 100)) + "% over one page. It guides shortening; the printed layout is checked again after the brief is created." }));
      nodes.push(h("p", { text: "Nothing was cropped or shrunk. Choose exactly what to leave out, then create the brief again. Left-out text stays in the editor and can be included again." }));
      nodes.push(recommendRecovery("ia-short-recommend"), choiceList(C.shorteningChoices(state), "ia-short-", "#ia-error-h"));
    } else if (e.code === "snapshot_unavailable" || e.code === "version_mismatch") {
      nodes.push(h("p", { text: "The saved case and this context are unchanged. A verified brief or print needs the matching version of the app. You can keep working in another context or start a new plan." }));
      if (C.active(state).snapshot_id !== state.runtime.snapshot_id) nodes.push(replayHelp(C.active(state).snapshot_id));
    } else if (e.code === "foreign_context" || e.code === "selection_conflict" || e.code === "action_conflict") {
      nodes.push(h("p", { text: "Remove the named selection, or restore the context it came from under Save or reopen the case. No mixed brief was created." }));
    }
    // Recovery that repeats the same operation; import asks for the file again (it is never kept by the app).
    if (e.kind === "restore" && lastRestore) nodes.push(h("p", { text: lastRestore.name + " was not restored. " + contextName(C.active(state).branch_id) + " is still open and unchanged." }));
    const retry = !connection ? null : e.kind === "restore" && lastRestore ? btn("Restore " + lastRestore.name.replace(/ \(.*$/, "") + " again", () => { const target = lastRestore.branchId; state = Object.assign({}, state, { last_error: null }); restoreContext(target); }, { class: "btn btn-primary", id: "ia-retry" })
      : e.kind === "run" || e.kind === "restore" ? btn("Run the plan again", () => { state = Object.assign({}, state, { last_error: null }); runActive(); }, { class: "btn btn-primary", id: "ia-retry" })
      : e.kind === "brief" ? btn("Create the brief again", () => { state = Object.assign({}, state, { last_error: null }); createBrief(false); }, { class: "btn btn-primary", id: "ia-retry" })
      : e.kind === "interpret" ? btn("Read the typed request again", () => { state = Object.assign({}, state, { last_error: null }); $("#ia-ask").requestSubmit(); }, { class: "btn btn-primary", id: "ia-retry" })
      : null;
    if (connection && e.kind === "import") nodes.push(h("p", { text: "Choose the case file again under Save or reopen the case to retry. The file was not kept." }));
    nodes.push(h("div", { class: "btn-row" }, retry,
      btn("Dismiss", () => { state = Object.assign({}, state, { last_error: null }); render(); }, { id: "ia-dismiss" })));
    fill(box, nodes);
  }

  // Overflow recovery beside the warning: the recommended selection, when it differs from the current one.
  function recommendRecovery(id) {
    const rec = briefFocus || C.recommendedBrief(C.currentResults(state)), b = C.active(state), key = (r) => C.refKey(r);
    if (!rec.claims.length || C.recommendationGuard(C.currentResults(state), rec)) return null;
    const sameClaims = rec.claims.length === b.selected_claim_refs.length && rec.claims.every((c) => b.selected_claim_refs.some((r) => key(r) === key(c.claim_ref)));
    const sameAction = !rec.action || (b.selected_action_ref && C.actionKey(b.selected_action_ref) === C.actionKey(rec.action));
    if (sameClaims && sameAction) return null;
    return h("div", { class: "ia-recover" }, btn(briefFocus ? "Create brief from this answer instead" : "Create recommended brief instead", () => createRecommended(), { class: "btn btn-primary", id: id }),
      h("p", { class: "hint", text: "Replaces the current selection with the " + (briefFocus ? "answer's findings" : "recommended findings") + " and agency action, sized to fit one page. Your title, summary and next steps are kept; a note on a finding that is left out waits for your review." }));
  }

  const shortGeo = (label) => placeDisplay(label || "").replace(/ \(\d{4} district boundaries\)$/, "").replace(/^House District /, "House ").replace(/^Senate District /, "Senate ");
  function valueWithUnit(display, unit) {
    display = String(display == null ? "" : display); unit = String(unit || "");
    if (unit === "percent") return /%$/.test(display) ? display : display + "%";
    if (/USD/.test(unit) && /^-?[\d,.]+$/.test(display)) return "$" + display + " (" + unit.replace("USD", "dollars") + ")";
    return (display + " " + unit).trim();
  }
  function moeWithUnit(moe, unit) {
    moe = String(moe == null ? "" : moe); unit = String(unit || "");
    if (moe === "*****") return MOE_NOT_PUBLISHED;
    if (!/^±/.test(moe)) return moe;
    if (unit === "percent") return moe + " percentage points";
    if (/USD/.test(unit)) return "±$" + moe.slice(1);
    return (moe + " " + unit).trim();
  }
  // Short name used in accessible names and leave-out choices (never an identifier).
  function statLine(c) {
    const m = c.metric || {}, level = typeof c.moe_confidence_level === "number" ? Math.round(c.moe_confidence_level * 100) + "% " : "", status = C.moeStatus(c);
    const moe = status ? " (" + status + ")" : /^±/.test(String(c.moe_display || "")) ? " (" + level + "margin of error " + moeWithUnit(c.moe_display, c.unit) + ")" : c.moe_display ? " (margin of error: " + moeWithUnit(c.moe_display, c.unit) + ")" : "";
    const note = c.annotation_meaning ? " Note: " + c.annotation_meaning : "";
    return (m.label || "Statistic") + ", " + shortGeo(c.geography && c.geography.label) + ": " + valueWithUnit(c.estimate_display, c.unit) + moe + "." + note;
  }
  const findingText = (c) => (c && c.kind === "statistic" && c.estimate_display !== undefined ? statLine(c) : c && typeof c.text === "string" ? c.text : "A finding not in the current results");
  function claimShortName(c) {
    if (!c) return "a finding not in the current results";
    const m = c.metric || {}, p = c.program || {};
    if (c.kind === "comparison") return (m.label || "Comparison") + ", " + shortGeo(c.left && c.left.geography && c.left.geography.label) + " vs " + shortGeo(c.right && c.right.geography && c.right.geography.label);
    if (c.kind === "statistic") return (m.label || "Statistic") + ", " + shortGeo(c.geography && c.geography.label);
    if (c.kind === "program_relevance") return (p.name || "Program") + " program reference";
    if (c.kind === "outreach_hypothesis") return "Outreach hypothesis, " + (p.name || "program");
    return c.series_label || c.label || KIND_LABEL[c.kind] || "Finding";
  }
  function claimChoiceText(c) {
    if (!c) return "A finding not in the current results";
    const side = (x) => x ? shortGeo(x.geography && x.geography.label) + ": " + valueWithUnit(x.estimate_display, x.unit) : "";
    if (c.kind === "comparison") return "Comparison: " + ((c.metric || {}).label || "") + " — " + side(c.left) + " vs " + side(c.right);
    if (c.kind === "statistic") return "Statistic: " + ((c.metric || {}).label || "") + ", " + side(c);
    return (KIND_LABEL[c.kind] || "Finding") + ": " + claimShortName(c);
  }
  // Leave-out / deselect choices: distinguishing text first, stable ids, and focus moved to a remaining
  // heading or the next action afterwards (never onto another choice by position).
  function choiceList(choices, prefix, headingSel) {
    const claims = claimMap(C.currentResults(state));
    const after = () => {
      const head = $(headingSel);
      if (head && !head.closest("[hidden]") && head.isConnected) { head.focus(); return; }
      const b = $("#ia-brief-btn"); if (b && !b.disabled) b.focus(); else $("#ia-brief-reason").focus();
    };
    return h("ul", { class: "ia-choices ia-choice-list" }, choices.map((c) => h("li", {}, c.kind === "leave_out_staff"
      ? btn("Leave out " + staffKeyLabel(c.key) + " (" + c.size + " characters)", () => { set(C.setExclusion(state, c.key, true), "Left out of the next brief. The text is kept. Create the brief again."); after(); }, { id: prefix + "staff-" + c.key.replace(/[^a-z0-9]+/gi, "-") })
      : btn("Deselect " + claimChoiceText(claims.get(C.refKey(c.claim_ref))), () => { set(C.toggleClaim(state, c.claim_ref, false), "Finding deselected. Create the brief again."); after(); }, { id: prefix + "f-" + c.claim_ref.semantic_hash.slice(7, 19) }))));
  }

  const claimMap = (res) => new Map((res ? res.claims : []).map((c) => [C.refKey(c.claim_ref), c]));
  // A saved finding named from its recorded finding id and the catalog labels (no claim text is invented).
  function savedFindingName(ref) {
    const res = C.currentResults(state), id = String(ref && ref.finding_id || ""), geo = (g) => shortGeo(geoLabel(g));
    // Naming only: a current result with the same finding id names it; selection still needs the exact identity.
    const c = claimMap(res).get(C.refKey(ref)) || (res ? res.claims.find((x) => x.claim_ref.finding_id === id) : null);
    if (c && (c.metric || c.program)) return claimShortName(c);
    let m;
    if ((m = /^stat:([^:]+):(.+)$/.exec(id))) return metricLabel(m[2]) + ", " + geo(m[1]);
    if ((m = /^cmp:([^~]+)~([^:]+):(.+)$/.exec(id))) return metricLabel(m[3]) + ", " + geo(m[1]) + " vs " + geo(m[2]);
    if ((m = /^prog:([^@]+)@(.+)$/.exec(id))) return programLabel(m[1]) + " program reference, " + geo(m[2]);
    if ((m = /^lead:([^@]+)@(.+)$/.exec(id))) return "Outreach hypothesis, " + programLabel(m[1]) + ", " + geo(m[2]);
    return "A saved finding";
  }
  function droppedReason(r, res) {
    const code = String(r.reason_code || ""), sameId = res && res.claims.some((c) => c.claim_ref.finding_id === (r.claim_ref || {}).finding_id);
    if (code === "foreign_primary_district" || r.state === "foreign_context") return "it belongs to another district's context and stays there.";
    if (code === "snapshot_unavailable" || r.state === "stale_snapshot") return "it was saved with a different evidence version.";
    if (sameId) return "its saved wording no longer matches the replayed evidence, so it was not reselected. Select it again below if it still applies.";
    return "it is not in this plan's current results, so it was not reselected.";
  }

  function claimTitle(ref) {
    const c = claimMap(C.currentResults(state)).get(C.refKey(ref));
    return c && typeof c.text === "string" ? (c.text.length > 90 ? c.text.slice(0, 88) + "…" : c.text) : "A finding from another context";
  }
  // The whole server statement of a dependency (estimate, margin, universe, period), never a shortened label.
  function claimFull(ref) {
    const c = claimMap(C.currentResults(state)).get(C.refKey(ref));
    return c && typeof c.text === "string" ? c.text : "A finding not in the current results";
  }
  function staffKeyLabel(key) {
    const kind = key.split(":")[0];
    return key.startsWith("finding_note:") ? "a finding note" : key.startsWith("checklist:") ? "checklist item “" + checkLabel(key.slice(10)) + "”" : kind === "note" ? "the summary" : (STAFF_LABEL[kind] || humanWords(kind)).toLowerCase();
  }

  // Every value below is a trusted field of the server's canonical claim, shown as text. Nothing is recomputed.
  // Identifiers (finding ids, claim hashes, source ids, file hashes, GEOIDs) stay in the reply and case file.
  function locatorText(loc) {
    if (!loc || typeof loc !== "object") return null;
    if (loc.sheet && loc.estimate_cell) return "Sheet " + loc.sheet + ", cell " + loc.estimate_cell + (loc.moe_cell ? " (margin of error in " + loc.moe_cell + ")" : "");
    if (loc.sheet && loc.cell) return "Sheet " + loc.sheet + ", cell " + loc.cell;
    if (loc.line_start !== undefined && loc.line_start !== null) return "Lines " + loc.line_start + "–" + (loc.line_end !== undefined && loc.line_end !== null ? loc.line_end : loc.line_start);
    if (loc.pages) return "Pages " + loc.pages + (loc.section ? " (" + loc.section + ")" : "");
    return null;
  }
  function periodText(p) {
    return p ? [p.label, p.dollar_year ? p.dollar_year + " dollars" : null].filter(Boolean).join(" · ") : null;
  }
  function moeText(c) {
    if (c.estimate_display === undefined) return null;
    const level = typeof c.moe_confidence_level === "number" ? Math.round(c.moe_confidence_level * 100) + "% " : "", status = C.moeStatus(c);
    return valueWithUnit(c.estimate_display, c.unit) + " · " + (status || level + "margin of error " + moeWithUnit(c.moe_display, c.unit));
  }
  function claimRows(c) {
    const m = c.metric || {}, g = c.geography || {}, src = c.source || {};
    // Each operand states its own margin: a published numeric margin, a controlled estimate, or no margin. Beside a
    // controlled or unavailable operand, a numeric one names its published confidence level; numeric pairs are unchanged.
    const mixed = c.kind === "comparison" && !!(C.moeStatus(c.left) || C.moeStatus(c.right));
    const sideLevel = (x) => (mixed && typeof x.moe_confidence_level === "number" ? Math.round(x.moe_confidence_level * 100) + "% " : "");
    const side = (x) => (x && x.geography ? placeDisplay(x.geography.label) + ": " + (x.estimate_display == null ? "estimate unavailable" : x.estimate_display) + " (" + (C.moeStatus(x) || sideLevel(x) + "margin of error " + x.moe_display) + ")" : null);
    const checks = c.compatibility && c.compatibility.checks ? Object.keys(c.compatibility.checks).filter((k) => c.compatibility.checks[k]).map((k) => humanWords(k).toLowerCase()) : null;
    return [
      ["Recorded statement", c.kind === "statistic" && typeof c.text === "string" ? c.text : null],
      ["Label", c.label],
      ["Measure", m.label], ["Universe", c.universe], ["Unit", c.unit], ["Period", periodText(c.period)],
      ["Area", g.label ? placeDisplay(g.label) : null],
      ["Published value and margin", moeText(c)],
      ["Note on the value", c.annotation_meaning || c.annotation || c.moe_annotation],
      ["District", side(c.left)], ["Compared with", side(c.right)],
      ["Point difference", c.kind === "comparison" ? (c.difference ? c.difference.display + " " + c.difference.unit : "Not differenced: " + limitText(c.not_differenced_reason)) : null],
      ["Matched for comparison", checks && checks.length ? checks.join(", ") : null],
      ["Method", c.transformation],
      ["ACS table", m.table_id || null], ["Official variable label", m.official_variable_label ? String(m.official_variable_label).replace(/!!/g, " › ") : null],
      ["Agency", c.program && c.program.agency ? hawaiiDisplay(c.program.agency) : null], ["Program jurisdiction", c.program && c.program.jurisdiction ? hawaiiDisplay(c.program.jurisdiction) : null], ["Recorded status", c.status_notes], ["Effective period", c.effective_text],
      ["Reviewed measures", Array.isArray(c.observed_need) ? c.observed_need.map((o) => o.label + ": " + o.estimate_display + " (" + (C.moeStatus(o) || "margin of error " + o.moe_display) + "; " + o.universe + "; " + o.period_label + ")" + (o.state_reference ? " — State reference: " + o.state_reference.estimate_display + " (" + (C.moeStatus(o.state_reference) || "margin of error " + o.state_reference.moe_display) + ")" : "")) : null],
      ["Program connection", c.program_connection && c.program_connection.text], ["Not known from this evidence", c.unknowns], ["Reviewed next step", c.next_step],
      ["Source", src.source_id ? [hawaiiDisplay(src.publisher), srcLabel(src.source_id), src.retrieved_at_utc ? "retrieved " + humanDate(src.retrieved_at_utc) : null].filter(Boolean).join(" · ") : null],
      ["Location in the source", locatorText(src.locator)],
      ["Source address", src.url || null],
    ].filter((r) => r[1] !== null && r[1] !== undefined && r[1] !== "" && !(Array.isArray(r[1]) && !r[1].length));
  }

  // The concise limit beside a result is its most specific one; limits shared by every finding are listed once below.
  let limitFreq = new Map(), limitMax = 0;
  function keyLimit(limits) {
    let best = null, n = Infinity;
    limits.forEach((l) => { const k = limitFreq.get(l) || 0; if (k <= n) { best = l; n = k; } });
    return best && (n < limitMax || limitMax <= 1) ? limitText(best) : null;
  }
  // Outreach hypothesis shown in labelled parts built from its recorded fields; the complete reviewed
  // statement stays available word for word.
  function outreachBody(c, id) {
    const obs = Array.isArray(c.observed_need) ? c.observed_need : [];
    const line = (o) => o.label + ": " + valueWithUnit(o.estimate_display, o.unit) + " (" + (C.moeStatus(o) || moeWithUnit(o.moe_display, o.unit)) + "; " + o.universe + "; " + o.period_label + ")" +
      (o.state_reference ? " — State of Hawaiʻi " + valueWithUnit(o.state_reference.estimate_display, o.unit) + " (" + (C.moeStatus(o.state_reference) || moeWithUnit(o.state_reference.moe_display, o.unit)) + ")" +
        (o.state_reference.difference ? "; point difference " + o.state_reference.difference.display + " " + o.state_reference.difference.unit : "") : "");
    return h("div", { class: "ia-outreach" },
      h("p", { class: "ia-claim-text", id: id + "-text" }, h("strong", { text: (c.label || "Outreach hypothesis") + "." }), " " + ((c.program || {}).name || "") + " · " + shortGeo(c.geography && c.geography.label)),
      obs.length ? h("div", {}, h("h4", { class: "ia-sub", text: "Observed area conditions (survey estimates, not program need)" }), h("ul", {}, obs.map((o) => h("li", { text: line(o) }))),
        h("p", { class: "hint", text: "A hypothesis always uses its program’s complete reviewed measure set and State reference, even when a profile step shows fewer measures." })) : null,
      c.program_connection && c.program_connection.text ? h("div", {}, h("h4", { class: "ia-sub", text: "Program context" }), h("p", { text: c.program_connection.text })) : null,
      Array.isArray(c.unknowns) && c.unknowns.length ? h("div", {}, h("h4", { class: "ia-sub", text: "Unknowns the agency determines" }), h("ul", {}, c.unknowns.map((u) => h("li", { text: plain(u) })))) : null,
      c.next_step ? h("div", {}, h("h4", { class: "ia-sub", text: "Next step" }), h("p", { text: c.next_step })) : null,
      typeof c.text === "string" ? h("details", { id: id + "-full" }, h("summary", { text: "Complete reviewed statement" }), h("p", { class: "ia-full-text", text: c.text })) : null);
  }

  // Source buttons for one finding. When a finding rests on both published statistics and program or legal
  // references, the two roles are listed on separate labelled rows; every source stays listed.
  function sourceRows(sources, c, claims, srcName) {
    if (!sources.length) return null;
    const isStat = (r) => {
      const dep = r.finding_id && r.finding_id !== c.claim_ref.finding_id ? Array.from(claims.values()).find((x) => x.claim_ref.finding_id === r.finding_id) : null;
      return dep ? !!dep.metric : !!c.metric;
    };
    const button = (r) => h("button", { type: "button", class: "btn-link source-btn", "data-source-id": r.source_id, "data-finding-id": typeof r.finding_id === "string" ? r.finding_id : c.claim_ref.finding_id, text: "Inspect " + srcName(r),
      on: { click: () => { const b = C.active(state); questionSource = { claim_ref: JSON.parse(JSON.stringify(c.claim_ref)), branch_id: b.branch_id, revision: b.last_ready_revision }; renderLanguage(); } } });
    const row = (label, list) => h("div", { class: "ia-sources" }, h("span", { class: "ia-sources-label", text: label }), list.map(button));
    const stats = sources.filter(isStat), refs = sources.filter((r) => !isStat(r));
    if (stats.length && refs.length) return h("div", { class: "ia-sources-group" }, row("Statistical basis:", stats), row(refs.length === 1 ? "Program source:" : "Program sources:", refs));
    return row(sources.length === 1 ? "Source:" : "Sources:", sources);
  }

  function claimNode(c, selected, prefix) {
    const key = C.refKey(c.claim_ref);
    const id = prefix + c.claim_ref.semantic_hash.slice(7, 19), on = selected.has(key);
    const seen = new Set(), sources = (Array.isArray(c.source_inspection_refs) ? c.source_inspection_refs : []).filter((r) => r && typeof r.source_id === "string" && !seen.has(r.source_id + "|" + r.finding_id) && seen.add(r.source_id + "|" + r.finding_id));
    const claims = claimMap(C.currentResults(state));
    const name = claimShortName(c);
    const cb = h("input", { type: "checkbox", id: id + "-sel", checked: on, "aria-label": "Select for brief: " + name, "aria-describedby": id + "-text", on: { change: (e) => set(C.toggleClaim(state, c.claim_ref, e.target.checked), e.target.checked ? "Finding selected for the brief." : "Finding removed from the brief selection.") } });
    const limits = Array.isArray(c.limitations) ? c.limitations : [];
    // Name each source button by what it supports; the same document can back different values.
    const srcName = (r) => {
      const dep = r.finding_id && r.finding_id !== c.claim_ref.finding_id ? Array.from(claims.values()).find((x) => x.claim_ref.finding_id === r.finding_id) : null;
      const what = dep && dep.metric ? " — " + (dep.geography && dep.geography.label ? placeDisplay(dep.geography.label).replace(/ \(\d{4} district boundaries\)$/, "") + ", " : "") + dep.metric.label : "";
      return srcLabel(r.source_id) + (what || " — " + name);
    };
    const meta = [periodText(c.period), c.universe ? "Universe: " + c.universe : null].filter(Boolean).join(" · ");
    return h("li", { class: "ia-claim" + (on ? " is-selected" : ""), id: id, tabindex: "-1" },
      h("div", { class: "ia-claim-head" }, h("span", { class: "badge", text: KIND_LABEL[c.kind] || c.kind || "Finding" }),
        on ? h("span", { class: "badge badge-info", text: "In brief" }) : null,
        h("label", { class: "ia-check ia-select", for: id + "-sel" }, cb, " Select for brief")),
      c.kind === "outreach_hypothesis" ? outreachBody(c, id) : h("p", { class: "ia-claim-text", id: id + "-text", text: c.kind === "statistic" ? findingText(c) : typeof c.text === "string" ? c.text : "Finding text unavailable" }),
      meta && c.kind !== "comparison" && c.kind !== "outreach_hypothesis" ? h("p", { class: "ia-claim-meta", text: meta }) : null,
      keyLimit(limits) ? h("p", { class: "ia-limit" }, h("strong", { text: "Limit: " }), keyLimit(limits)) : null,
      sourceRows(sources, c, claims, srcName),
      h("details", { id: id + "-more" }, h("summary", {}, "Definition, margin of error and method", h("span", { class: "sr-only", text: " for " + name })),
        h("dl", { class: "kv" }, claimRows(c).filter((r) => c.kind !== "outreach_hypothesis" || !["Reviewed measures", "Program connection", "Not known from this evidence", "Reviewed next step"].includes(r[0])).map((r) => h("div", {}, h("dt", { text: r[0] }), h("dd", { class: r[0] === "Source address" ? "url" : null }, Array.isArray(r[1]) ? h("ul", {}, r[1].map((x) => h("li", { text: plain(x) }))) : r[0] === "Source address" && /^https:\/\//.test(String(r[1])) ? h("a", { href: String(r[1]), target: "_blank", rel: "noopener noreferrer", class: "official-link", text: String(r[1]) }) : plain(r[1]))))),
        Array.isArray(c.dependencies) && c.dependencies.length ? h("div", {}, h("h4", { class: "ia-sub", text: c.kind === "outreach_hypothesis" ? "Complete reviewed basis (shown in full whatever the profile displays)" : "Depends on" }),
          h("ul", {}, c.dependencies.map((r) => h("li", { text: claimFull(r) })))) : null,
        limits.length ? h("div", {}, h("h4", { class: "ia-sub", text: "All limits of this finding" }), h("ul", {}, limits.map((l) => h("li", { text: limitText(l) })))) : null));
  }

  function renderEvidence(res, dirty) {
    const box = $("#ia-evidence");
    if (!res) { fill(box, [h("p", { class: "muted", text: state.pending ? "Running the plan…" : "No findings yet. Choose Apply plan to run the plan for this district." })]); return; }
    const claims = claimMap(res), selected = new Set(C.active(state).selected_claim_refs.map(C.refKey));
    limitFreq = new Map();
    res.claims.forEach((c) => (Array.isArray(c.limitations) ? c.limitations : []).forEach((l) => limitFreq.set(l, (limitFreq.get(l) || 0) + 1)));
    limitMax = Math.max(0, ...limitFreq.values());
    const rec = recommendedBrief(res), ans = answerCurrent(res), key = ans ? null : rec.claims[0], mixed = key ? C.recommendationGuard(res, rec) : null;
    const start = key ? h("div", { class: "ia-start", id: "ia-start" }, h("h3", { class: "ia-group-title", text: "Start here" }),
      h("p", { text: findingText(key) }),
      mixed ? h("p", { class: "hint", text: "These results name programs that do not match one recommended brief, so no agency action is suggested. Select findings below and choose an agency action or none; see Choose this brief yourself in the Brief panel." }) :
      rec.claims.length > 1 || rec.card ? h("p", { class: "hint", text: "The recommended brief adds " + rec.claims.slice(1).map(claimShortName).concat(rec.card ? ["the agency verification step for " + programLabel(rec.card.program_id) + ", which prints the program's recorded referral, open questions and sources"] : []).join("; ") + ". Choose Create recommended brief in the Brief panel, or select findings below; the program reference and every other finding stay available." }) : null) : null;
    // A selected finding kept as support of other findings has no tile below; it is named here with its way out.
    const support = C.supportingSelections(state);
    const supportNote = support.length ? h("div", { class: "ia-supporting", id: "ia-supporting" },
      h("p", { class: "hint", text: plural(support.length, "selected finding has", "selected findings have") + " no tile of its own below:" }),
      h("ul", { class: "hint" }, support.map((x) => h("li", {}, claimShortName(x.claim) + ". " + supportingText(x) + " ",
        btn("Show in Selected findings", () => { const t = document.getElementById("ia-sel-" + x.claim_ref.semantic_hash.slice(7, 19) + "-rm"); if (t) t.focus(); }, { class: "btn-link", id: "ia-supporting-go-" + x.claim_ref.semantic_hash.slice(7, 19), "aria-label": "Show " + claimShortName(x.claim) + " in Selected findings, where Remove takes it out of the brief" }))))) : null;
    const nodes = [start, supportNote, h("p", { class: "hint", text:"Findings for " + districtLabel(res.plan.district) + " from the last applied plan." + (dirty ? " The draft has unapplied edits; these findings do not include them yet." : "") + " Select findings for the brief: up to 8 can be selected; one-page fit is measured when you create the brief." })];
    res.steps.forEach((s, i) => {
      const refs = Array.isArray(s.claim_refs) ? s.claim_refs : [];
      const n = res.plan.steps.findIndex((x) => x.step_id === s.step_id);
      nodes.push(h("section", { class: "ia-step-result status-" + s.status, "aria-labelledby": "ia-res-h-" + s.step_id },
        h("h3", { class: "ia-group-title", id: "ia-res-h-" + s.step_id }, "Step " + ((n >= 0 ? n : i) + 1) + " · " + (OP_LABEL[s.operation] || humanWords(s.operation)) + " ", h("span", { class: "badge" + (s.status === "ok" ? "" : " badge-warn"), text: s.status === "ok" ? refs.length + " finding" + (refs.length === 1 ? "" : "s") : s.status === "unsupported" ? "Not supported" : humanWords(s.status) })),
        s.status !== "ok" ? h("div", { class: "notice notice-unsupported" }, h("p", { text: s.message || "This step did not produce a result." }),
          h("p", { class: "hint", text: "No substitute answer was used. Other steps are unaffected, and your plan is kept." }),
          (Array.isArray(s.next_actions) ? s.next_actions : []).map((a, j) => {
            // Typed comparator choices only: either {kind:"choose_comparator",values} or {label,request:{comparison_geography}}.
            const geos = a && a.kind === "choose_comparator" && Array.isArray(a.values) ? a.values : a && a.request && typeof a.request.comparison_geography === "string" ? [a.request.comparison_geography] : [];
            const usable = s.operation === "compare" ? geos.filter((g) => typeof g === "string") : [];
            return usable.length ? h("div", { class: "btn-row" }, usable.map((g, k) => btn("Compare with " + geoLabel(g) + " instead", () => {
              const st = state.draft.steps.find((x) => x.step_id === s.step_id);
              if (!st) return;
              editDraft(C.rescopeStep(state.draft, s.step_id, { metric_ids: st.args.metric_ids, comparison_geography: g }), "Comparison geography changed in the draft. Choose Apply plan to run it.");
              openAdvanced(false); $("#ia-apply").focus();
            }, { id: "ia-next-" + s.step_id + "-" + j + "-" + k })))
              : h("p", { class: "hint", text: plain(a && (a.label || a)) });
          })) : null,
        refs.length || s.status !== "ok" ? h("ul", { class: "ia-claims" }, refs.map((r) => claims.get(C.refKey(r))).filter(Boolean).map((c) => claimNode(c, selected, "ia-c-" + s.step_id + "-")))
          : h("p", { class: "muted", text: "This step ran and found nothing to report for this district." })));
    });
    if (res.limitations.length) nodes.push(h("details", { class: "limitations", id: "ia-res-limits" }, h("summary", { text: "Limits that apply to all of these results (" + res.limitations.length + ")" }), h("ul", {}, res.limitations.map((l) => h("li", { text: limitText(l) })))));
    fill(box, nodes);
  }

  // The program's recorded official referral, shown first on its agency card. Registry wording only.
  function officialNextStep(prog) {
    const ref = prog && prog.referral;
    if (!ref || typeof ref.next_step !== "string" || !ref.next_step) return null;
    const contact = [];
    if (typeof ref.url === "string" && /^https:\/\//.test(ref.url)) contact.push(h("a", { href: ref.url, target: "_blank", rel: "noopener noreferrer", class: "official-link", text: ref.url }));
    if (ref.phone) contact.push(" · " + ref.phone);
    if (ref.tty) contact.push(" · TTY " + ref.tty);
    if (ref.county_office) contact.push(" · county office: " + ref.county_office);
    return h("div", { class: "ia-next-step" }, h("h4", { class: "ia-sub", text: "Official next step (recorded)" }), h("p", { text: ref.next_step }), contact.length ? h("p", {}, ...contact) : null);
  }

  function renderResponses(res) {
    const box = $("#ia-responses"), b = C.active(state);
    if (!res || !res.responses.length) { fill(box, [h("p", { class: "muted", text: res ? "This plan has no program step, so there is no agency action to choose. A brief without one is valid; add a Program reference step to see options." : "Agency options appear after the plan runs." })]); return; }
    const claims = claimMap(res);
    const pick = (ref) => {
      // An action change re-applies the applied plan, so unapplied plan edits are protected: nothing changes until
      // they are applied or discarded (the radios re-render to the action actually chosen).
      if (!C.proposeChange(state, { plan: state.draft }).noop) { render(); alertUser("Apply or discard the plan edits first; changing the agency action uses the applied plan. Nothing was changed."); return; }
      const r = C.chooseAction(state, ref);
      if (r.error) return alertUser(r.error.message);
      if (r.proposal.noop) return;
      if (r.proposal.fork) { preview = r.proposal; render(); focusPreview(); } else commitAction(r.proposal);
    };
    const areas = (ids) => (Array.isArray(ids) ? ids.map((x) => AREA_LABEL[x] || humanWords(x)).join(", ") : "");
    const nodes = res.responses.map((card, i) => {
      const j = card.jurisdiction || {}, a = card.access || {}, on = card.action_ref && C.actionKey(card.action_ref) === C.actionKey(b.selected_action_ref);
      const prog = card.program_claim_ref ? claims.get(C.refKey(card.program_claim_ref)) : null, p = (prog && prog.program) || {};
      const list = (title, items, cls) => (Array.isArray(items) && items.length ? h("div", { class: cls || null }, h("h4", { class: "ia-sub", text: title }), h("ul", {}, items.map((x) => h("li", { text: plain(x) })))) : null);
      const where = [j.state && j.state !== "unknown" ? humanWords(j.state) : "Not established for this district", j.scope_kind ? humanWords(j.scope_kind).toLowerCase() : null, areas(j.area_ids) || null].filter(Boolean).join(" · ");
      const status = humanWords(a.recorded_status || "not recorded") + (a.checked_at ? " (program record checked " + humanDate(a.checked_at) + ")" : " (no check date recorded)");
      return h("article", { class: "card ia-response" + (on ? " is-selected" : ""), id: "ia-resp-" + i, "aria-labelledby": "ia-resp-h-" + i },
        h("header", {}, h("h3", { class: "ia-group-title", id: "ia-resp-h-" + i, text: programLabel(card.program_id) }), h("span", { class: "badge badge-info", text: TIER_LABEL[card.tier] || humanWords(card.tier) }),
          on ? h("span", { class: "badge badge-ok", text: "In brief" }) : null),
        officialNextStep(prog),
        h("dl", { class: "kv" },
          p.agency ? h("div", {}, h("dt", { text: "Administering agency" }), h("dd", { text: hawaiiDisplay(p.agency) })) : null,
          p.jurisdiction ? h("div", {}, h("dt", { text: "Program jurisdiction (recorded)" }), h("dd", { text: hawaiiDisplay(p.jurisdiction) })) : null,
          h("div", {}, h("dt", { text: "Service area for this district" }), h("dd", { text: where })),
          h("div", {}, h("dt", { text: "Recorded status" }), h("dd", { text: status })),
          h("div", {}, h("dt", { text: "Effective period" }), h("dd", { text: a.effective_period && (a.effective_period.from || a.effective_period.to) ? (a.effective_period.from ? "From " + a.effective_period.from : "Start date not recorded") + (a.effective_period.to ? " to " + a.effective_period.to : "; no end date recorded") : "Effective date not established" })),
          h("div", {}, h("dt", { text: "Still to confirm" }), h("dd", { text: "Availability: " + (a.current_availability || "unverified") + " · cost: " + (a.cost || "unverified") + ". A checked reference does not mean access is open." })),
          card.eligibility_area !== undefined && card.eligibility_area !== null ? h("div", {}, h("dt", { text: "Eligibility area for this district" }), h("dd", { text: card.eligibility_area === "unknown" ? "Not established" : plain(card.eligibility_area) })) : null),
        list("Questions to confirm with the agency", card.facts_to_verify, "ia-questions"),
        list("Why this may not fit", card.weakening_facts), list("Jurisdiction limits", j.limitations),
        card.tier === "reference" ? h("p", { class: "hint", text: "General reference only. It is not promoted to a hypothesis or action because it was requested, and it does not substitute for another program." }) : null,
        Array.isArray(card.support_claim_refs) && card.support_claim_refs.length ? h("details", { id: "ia-resp-basis-" + i }, h("summary", { text: "Findings this rests on (" + card.support_claim_refs.length + ")" }), h("ul", {}, card.support_claim_refs.map((r) => h("li", { text: claimTitle(r) })))) : null,
        card.action_ref ? h("label", { class: "ia-check ia-choose", for: "ia-act-" + i }, h("input", { type: "radio", name: "ia-action", id: "ia-act-" + i, checked: on, on: { change: () => pick(card.action_ref) } }), " Use this agency action in the brief") : h("p", { class: "hint", text: "No reviewed staff action is attached to this program." }));
    });
    nodes.push(h("label", { class: "ia-check ia-choose", for: "ia-act-none" }, h("input", { type: "radio", name: "ia-action", id: "ia-act-none", checked: b.selected_action_ref === null, on: { change: () => pick(null) } }), " No agency action in the brief"));
    fill(box, nodes);
  }

  function commitAction(p) {
    const r = C.confirmChange(state, p, ids);
    if (r.error) return alertUser(r.error.message);
    state = r.state; notice = p.action ? "Agency action selected. Its checklist is in the Brief panel." : "No agency action selected.";
    // A response change that opened a new branch always recomputes the plan for that branch.
    if (r.forked) { runActive(); return; }
    render();
  }

  function textField(id, label, value, max, onCommit, area) {
    const el = h(area ? "textarea" : "input", Object.assign({ id: id, maxlength: max, "aria-describedby": id + "-max" }, area ? { rows: 3 } : { type: "text" }));
    el.value = value || "";
    // A native change fires during blur, while activeElement is BODY. Commit state now, but let
    // Tab or a pointer finish moving focus before rebuilding the fields. flushActive stays synchronous.
    el.addEventListener("change", () => onCommit(el.value, document.activeElement !== el));
    return h("div", { class: "field" }, h("div", { class: "field-head" }, h("label", { for: id, text: label }), h("span", { class: "limit", id: id + "-max", text: "up to " + max + " characters" })), el);
  }

  const dateContext = () => { const b = C.active(state); return C.canonical([state.case.case_id, b.branch_id, b.plan, b.selected_action_ref]); };
  function fillDateFields(box, nodes) {
    const active = document.activeElement;
    // Replacing or detaching a native date resets its internal segment, even if value/focus are restored.
    // Keep its containing section while the editor has focus or still holds incomplete segments after blur.
    const date = incompleteStaffDate(box) || (active && active.commitDate && box.contains(active) ? active : null);
    if (date && date.dateContext === dateContext()) {
      const wanted = h("div", {}, nodes);
      // Tracking's status text can change after a number/text commit. Update it without touching
      // the native editor or queuing a needless rebuild as focus enters another field.
      ["#ia-tracking-summary", "#ia-tracking > p.hint"].forEach((sel) => {
        const current = box.querySelector(sel), next = wanted.querySelector(sel);
        if (current && next) current.textContent = next.textContent;
      });
      const preset = box.querySelector("#ia-track-preset");
      if (preset && !wanted.querySelector("#ia-track-preset")) preset.remove();
      return;
    }
    fill(box, nodes);
  }
  function dateInput(id, value, onCommit) {
    const el = h("input", { type: "date", id, value: value || "" });
    el.dateContext = dateContext();
    let committed = el.value;
    const commit = () => {
      if (el.dateContext !== dateContext()) return true;
      if (el.validity.badInput) return false;
      if (el.value === committed) return true;
      committed = el.value;
      return onCommit(committed || null, document.activeElement !== el);
    };
    // Native date editors emit change for partial year segments. Keep them provisional until
    // blur or an explicit save flush; validating/rebuilding here would interrupt the remaining keys.
    el.commitDate = commit;
    el.dateDirty = () => el.value !== committed || el.validity.badInput;
    el.addEventListener("change", (ev) => { if (!ev.isTrusted || document.activeElement !== el) commit(); });
    el.addEventListener("blur", commit);
    return el;
  }

  // Why the brief cannot be created yet, in the order staff can fix it. Null when it can.
  function briefBlock(b, res, busy, dirty, staff, reviewed, parked) {
    if (busy) return "Wait for the current request to finish, or cancel it.";
    if (!res) return "Run the plan first: choose Apply plan.";
    if (dirty) return "Apply or discard the plan edits first; the brief uses applied results only.";
    if (parked.some((i) => i.orphan_reason)) return "A staff note on a removed finding is waiting for review. Select that finding again and copy the note back, or discard it, under “Staff notes waiting for review” first; until then it is not in the brief or in a case file.";
    if (!b.selected_claim_refs.length) return "Select at least one finding under Findings and evidence.";
    if (state.last_error && state.last_error.code === "brief_overflow") return "Too long for one page: choose what to leave out under Findings and evidence, then create the brief again.";
    if (!staff.empty && !reviewed) return parked.length ? "Copy or leave each item in “Staff notes waiting for review” first, then mark staff notes reviewed." : "Check the staff notes and checklist below, then choose Mark staff notes reviewed.";
    return null;
  }

  function recommendedBrief(res) { return C.recommendedBrief(res); }
  // What "Create recommended brief" selects: the answer-focused brief when the current answer singles out
  // findings, otherwise the investigation's recommended brief.
  const currentRecommendation = (res) => briefFocus || recommendedBrief(res);
  // Selects the recommended findings and agency action. True when the selection is complete now; false when a
  // context review or a rerun is needed first (it is then shown) or nothing could be selected.
  function useRecommended() {
    const res = C.currentResults(state), rec = currentRecommendation(res);
    if (!rec.claims.length) return false;
    // Mixed programs, references that differ from the hypothesis, or one program that is not the guided issue's: the
    // shortcut never chooses for staff. Nothing is selected or changed; the Brief panel names the choices.
    if (C.recommendationGuard(res, rec)) {
      notice = "Nothing was selected or changed: these results name programs that do not match one recommended brief. Choose findings, an agency action or no agency action, then Create brief from my selection.";
      render(); const box = $("#ia-conflict-h"); if (box) box.focus(); else $("#ia-brief-reason").focus(); return false;
    }
    // A selected finding with a staff note is never dropped by a shortcut: the note would leave the brief and every
    // case file. Staff keep it with "Create brief from my selection" or remove the finding or note themselves.
    const notes = C.active(state).staff_edits.finding_notes || {};
    const noted = C.active(state).selected_claim_refs.filter((r) => notes[r.semantic_hash] && !rec.claims.some((c) => C.refKey(c.claim_ref) === C.refKey(r)));
    if (noted.length) {
      notice = "Nothing was changed: " + plural(noted.length, "selected finding has", "selected findings have") + " a staff note and " + (noted.length === 1 ? "is" : "are") + " not in this brief. To keep the note, choose Create brief from my selection. To use this brief instead, first remove that finding or its note under Selected findings.";
      render(); $("#ia-brief-reason").focus(); return false;
    }
    const want = new Set(rec.claims.map((c) => C.refKey(c.claim_ref)));
    let next = state;
    for (const r of C.active(next).selected_claim_refs.slice()) if (!want.has(C.refKey(r))) { const o = C.toggleClaim(next, r, false); if (o.error) { alertUser(o.error.message); return false; } next = o.state; }
    for (const c of rec.claims) { const o = C.toggleClaim(next, c.claim_ref, true); if (o.error) { alertUser(o.error.message); return false; } next = o.state; }
    state = next;
    const b = C.active(state);
    // The recommendation's action, including "no agency action", replaces a different chosen action through the
    // ordinary action-change review; a recommendation without an action never keeps an unrelated earlier choice.
    if (C.actionKey(rec.action || null) !== C.actionKey(b.selected_action_ref || null)) {
      const r = C.chooseAction(state, rec.action || null);
      if (r.error) { alertUser(r.error.message); return false; }
      const again = briefFocus ? "Create brief from this answer" : "Create recommended brief";
      // An agency action change that opens a new context keeps the identical plan: the answer moves with it and is
      // shown again only when the new context's replayed results arrive for that same plan.
      const carry = () => {
        const a = answerCurrent(res);
        if (a && r.proposal.kinds.length === 1 && r.proposal.kinds[0] === "response" && C.canonical(r.proposal.plan) === C.canonical(a.plan) && C.active(state).snapshot_id === state.runtime.snapshot_id)
          pendingAnswer = { kind: a.kind, question: a.question, plan: a.plan, step_ids: a.step_ids.slice(), only: a.only || {}, fallback: !!a.fallback, branch_id: null, rebind: true, district: a.district };
      };
      if (r.proposal.fork) { carry(); preview = r.proposal; notice = "Findings selected. Review the agency action change below; after it runs, choose " + again + " again."; render(); focusPreview(); return false; }
      if (!r.proposal.noop) { const c = C.confirmChange(state, r.proposal, ids); if (c.error) { alertUser(c.error.message); return false; } state = c.state; if (c.forked) { carry(); notice = "Findings and agency action selected in a new context. Choose " + again + " again when its results load."; runActive(); return false; } }
    }
    return true;
  }
  function canPrepareRecommendedBrief() {
    if (holdIncompleteStaffDate("changing the brief") || flushActive() === false) return false;
    // Unapplied plan edits are never replaced: the brief uses applied results only, so ask for Apply or Discard first.
    const dirty = !C.proposeChange(state, { plan: state.draft }).noop;
    if (state.pending || dirty) { notice = state.pending ? "Wait for the current request to finish, or cancel it." : "Apply or discard the plan edits first; the brief uses applied results only. Nothing was selected."; render(); $("#ia-brief-reason").focus(); return false; }
    return true;
  }
  // One action: select the recommended evidence and agency action, then create the brief and show it.
  function createRecommended() {
    if (!canPrepareRecommendedBrief() || !useRecommended()) return;
    if (state.last_error && state.last_error.code === "brief_overflow") state = Object.assign({}, state, { last_error: null });
    const b = C.active(state), res = C.currentResults(state), staff = C.activeStaff(state);
    const block = briefBlock(b, res, !!state.pending, !C.proposeChange(state, { plan: state.draft }).noop, staff, C.reviewCurrent(state), C.pendingReview(state));
    if (block) { notice = "Recommended findings" + (b.selected_action_ref ? " and agency action" : "") + " selected. " + block; render(); $("#ia-brief-reason").focus(); return; }
    createBrief(false);
  }
  function renderTray(b, res, busy, dirty) {
    const claims = claimMap(res), ex = new Set(state.exclusions[b.branch_id] || []);
    const notes = (b.staff_edits.finding_notes || {});
    const nSel = b.selected_claim_refs.length;
    $("#ia-tray-count").textContent = nSel ? plural(nSel, "finding", "findings") + " selected" + (b.selected_action_ref ? " · agency action chosen." : " · no agency action.") : "No findings selected yet.";
    $("#ia-tray-capacity").textContent = "You can select up to 8 findings. What fits on one printed page depends on the findings, their sources, the agency action and your title and notes; the recommended brief is sized to fit, and the fit is measured when the brief is created.";
    const rec = res && !busy && !dirty ? currentRecommendation(res) : { claims: [] }, focused = rec === briefFocus;
    const recOn = rec.claims.length && rec.claims.every((c) => b.selected_claim_refs.some((r) => C.refKey(r) === C.refKey(c.claim_ref))) && rec.claims.length === nSel && C.actionKey(rec.action || null) === C.actionKey(b.selected_action_ref || null);
    // Mixed or mismatched programs: the shortcut is not offered; the panel names the choices staff make themselves.
    const conflict = rec.claims.length ? C.recommendationGuard(res, rec) : null;
    renderConflict(conflict, rec, res);
    $("#ia-recommend").hidden = !rec.claims.length || !!conflict;
    const recMade = !!recOn && C.printStatus(state).ok;
    $("#ia-recommend-btn").disabled = recMade;
    $("#ia-recommend-btn").textContent = recMade ? (focused ? "Brief from this answer created" : "Recommended brief created") : focused ? "Create brief from this answer" : "Create recommended brief";
    $("#ia-recommend-what").textContent = (focused ? "Focused on your question. " : "") + (rec.claims.length ? (recMade ? "Shown under One-page brief. It uses " : "Selects ") + rec.claims.map((c) => (KIND_LABEL[c.kind] || humanWords(c.kind)).toLowerCase() + ": " + claimShortName(c)).join("; ") + (rec.card ? "; agency action: verify " + programLabel(rec.card.program_id) + " with the agency" : rec.action_note === "no_matching_action" ? "; no agency action (no single agency action matches this answer)" : "") + (recMade ? "." : ", then creates the brief." + (nSel && !recOn ? " Replaces the current selection." : "")) + (focused ? focusNote(rec) : "") : "");
    const supporting = new Map(C.supportingSelections(state).map((x) => [C.refKey(x.claim_ref), x]));
    fill($("#ia-selected"), nSel ? b.selected_claim_refs.map((r, i) => {
      const c = claims.get(C.refKey(r)), sid = "ia-sel-" + r.semantic_hash.slice(7, 19), sup = supporting.get(C.refKey(r));
      return h("li", { id: sid }, h("span", { class: "tray-label", text: findingText(c) }),
        sup ? h("p", { class: "hint ia-supporting-why", id: sid + "-why", text: supportingText(sup) + " It stays selected because exactly this finding is in the current results; Remove takes it out of the brief." }) : null,
        h("span", { class: "ia-step-tools" },
          btn("Move up", () => set(C.moveSelection(state, r, -1)), { class: "btn-link", id: sid + "-up", disabled: i === 0, "aria-label": "Move finding " + (i + 1) + " up" }),
          btn("Move down", () => set(C.moveSelection(state, r, 1)), { class: "btn-link", id: sid + "-down", disabled: i === b.selected_claim_refs.length - 1, "aria-label": "Move finding " + (i + 1) + " down" }),
          btn("Remove", (event) => {
            const removed = set(C.toggleClaim(state, r, false), "Finding removed from the brief selection.");
            if (removed && sup && event.detail === 0 && !activeDate()) $("#ia-tray-h").focus();
          }, { class: "btn-link btn-danger", id: sid + "-rm", "aria-label": "Remove finding " + (i + 1) + " from brief" + (sup ? ": " + claimShortName(c) + ", supporting finding" : ""), "aria-describedby": sup ? sid + "-why" : null })),
        textField(sid + "-note", "Staff note on: " + claimShortName(c), notes[r.semantic_hash], 160, (v, defer) => set(C.setFindingNote(state, r.semantic_hash, v), null, defer)));
    }) : [h("li", { class: "muted", text: "Use “Select for brief” on a finding." })]);
    const fork = liveMapFork(), forkOrigin = fork ? C.branchOf(state, fork.origin_branch_id) : null;
    const proof = fork ? C.mapReselection(state, fork) : null, resolved = new Set(proof ? proof.resolved : []);
    const retired = (state.retired[b.branch_id] || []).filter((r) => !r.claim_ref || !resolved.has(C.refKey(r.claim_ref)));
    const mapYear = forkOrigin ? forkOrigin.plan.map_session : null;
    const offer = fork && res && !fork.consumed && !dirty ? mapForkNotice(fork, res, retired, proof) : null;
    // In a map-only fork the retired selections and action carry the earlier map year; they are named as such.
    const why = (r) => mapYear ? "selected with the " + mapYear + " map display. Its recorded identity changed with the map year. It is not selected in this context." +
      (!offer ? " Choose from the current findings under Findings and evidence." : "") : droppedReason(r, res);
    const retiredHeading = mapYear ? plural(retired.length, "saved selection is", "saved selections are") + " not selected in this context:"
      : plural(retired.length, "saved selection was", "saved selections were") + " not reselected:";
    fill($("#ia-retired"), retired.length ? [h("p", { class: "hint", text: retiredHeading }), h("ul", { class: "hint" }, retired.map((r) => h("li", { text: r.claim_ref ? savedFindingName(r.claim_ref) + ": " + why(r) :
      mapYear ? "The agency action chosen earlier: it was chosen with the " + mapYear + " map display and is not carried. Choose it again under Agency verification if it still applies." : "The agency action chosen earlier: it is not offered for this plan, so it was not reselected." }))),
      offer] : []);

    // agency checklist
    const card = res && b.selected_action_ref ? res.responses.find((c) => c.action_ref && C.actionKey(c.action_ref) === C.actionKey(b.selected_action_ref)) : null;
    const edits = new Map(b.checklist_edits.map((c) => [c.item_id, c]));
    const item = (idKey, templateText) => {
      const e = edits.get(idKey) || {}, pid = "ia-chk-" + idKey;
      return h("li", Object.assign({ class: "ia-check-item", role: "group" }, templateText ? { "aria-labelledby": pid + "-what" } : { "aria-label": "Checklist item: " + (e.text || checkLabel(idKey)) }),
        templateText ? h("p", { class: "ia-template", id: pid + "-what", text: templateText }) : null,
        textField(pid + "-text", templateText ? "Staff wording (optional)" : idKey.startsWith("custom") ? "Custom item" : "Staff entry: " + checkLabel(idKey).toLowerCase(), e.text, 120, (v, defer) => set(C.setChecklist(state, idKey, { text: v }), null, defer)),
        h("div", { class: "ia-inline" },
          textField(pid + "-owner", "Staff role", e.owner_role, 80, (v, defer) => set(C.setChecklist(state, idKey, { owner_role: v }), null, defer)),
          h("div", { class: "field" }, h("label", { for: pid + "-due", text: "Date" }), dateInput(pid + "-due", e.due_date, (value, defer) => set(C.setChecklist(state, idKey, { due_date: value }), null, defer)))),
        h("label", { class: "ia-check", for: pid + "-done" }, h("input", { type: "checkbox", id: pid + "-done", checked: e.completed === true, on: { change: (ev) => set(C.setChecklist(state, idKey, { completed: ev.target.checked })) } }), " Staff marked done (not a verified fact)"),
        ex.has("checklist:" + idKey) ? h("p", { class: "hint" }, "Left out of the next brief. ", btn("Include again", () => set(C.setExclusion(state, "checklist:" + idKey, false)), { class: "btn-link", id: pid + "-incl" })) : null);
    };
    const check = $("#ia-checklist");
    const templates = card && Array.isArray(card.template_checklist) ? card.template_checklist.filter((t) => t && C.TEMPLATE_CHECK_IDS.includes(t.item_id)) : [];
    const shown = new Set(templates.map((t) => t.item_id));
    // Staff entries stay visible and editable even with no agency step selected.
    const loose = C.CHECK_IDS.filter((k) => edits.has(k) && !shown.has(k)), free = C.CHECK_IDS.slice(3).find((k) => !edits.has(k));
    // Unfinished text in the add-item box is not staff data yet: it is kept per case and context in page memory only
    // (never committed, never shown in another context, not in a case file until added). The field on screen is
    // filed under the context it was typed in before the box is rebuilt for the current context.
    const drafts = addDrafts, draftKey = state.case.case_id + "|" + b.branch_id, onScreen = $("#ia-chk-new");
    if (onScreen && onScreen.draftKey) { if (onScreen.value) drafts.set(onScreen.draftKey, onScreen.value); else drafts.delete(onScreen.draftKey); }
    const add = h("input", { type: "text", id: "ia-chk-new", maxlength: 120, "aria-describedby": "ia-chk-new-max" });
    add.draftKey = draftKey;
    add.value = drafts.get(draftKey) || "";
    fillDateFields(check, [card ? h("p", {}, h("strong", { text: programLabel(card.program_id) }), " — office checklist for this agency action") : h("p", { class: "muted", text: "No agency action selected, so no template checklist applies. You can still add custom items and office tracking as staff contributions." }),
      templates.length || loose.length ? h("ol", { class: "ia-checklist" }, templates.map((t) => item(t.item_id, String(t.text || ""))), loose.map((k) => item(k, ""))) : null,
      free ? h("div", { class: "field ia-add-item" }, h("div", { class: "field-head" }, h("label", { for: "ia-chk-new", text: "Add a custom checklist item" }), h("span", { class: "limit", id: "ia-chk-new-max", text: "up to 3 items · 120 characters · saved only after Add item" })), h("div", { class: "ia-inline-row" }, add, btn("Add item", () => {
        const text = add.value.trim(); if (!text) return;
        const r = C.setChecklist(state, free, { text: text });
        if (r.error) { set(r); return; }   // the typed text stays in the box (filed under its own context)
        add.value = ""; drafts.delete(draftKey);
        set(r, "Custom item added as a staff contribution.");
      }, { id: "ia-chk-add" }))) : null]);

    // staff notes and tracking
    const t = b.tracking || { label: "", baseline: null, as_of: null };
    const track = (patch, defer) => { const n = Object.assign({ label: "", baseline: null, as_of: null }, C.active(state).tracking, patch); return set(C.setTracking(state, !n.label && n.baseline === null && !n.as_of ? null : n), null, defer); };
    const excl = (key) => (ex.has(key) ? h("p", { class: "hint" }, "Left out of the next brief. ", btn("Include again", () => set(C.setExclusion(state, key, false)), { class: "btn-link", id: "ia-incl-" + key })) : null);
    // SNAP tracking wording applies to a SNAP outreach plan that still uses SNAP. When its program steps were rescoped to
    // other programs, neutral wording is shown; saved tracking entries and the recipe reference are unchanged.
    const planProgs = C.planPrograms(b.plan), food = b.plan.issue_id === "food_assistance_outreach" && (!planProgs.length || planProgs.includes("snap_hi"));
    fillDateFields($("#ia-staff"), [
      textField("ia-title", "Brief title", b.staff_edits.title, 90, (v, defer) => set(C.setStaffText(state, "title", v), null, defer)), excl("title"),
      textField("ia-note", "Summary", b.staff_edits.note, 400, (v, defer) => set(C.setStaffText(state, "note", v), null, defer), true), excl("note"),
      textField("ia-next", "Next steps", b.staff_edits.next_steps, 300, (v, defer) => set(C.setStaffText(state, "next_steps", v), null, defer), true), excl("next_steps"),
      h("details", { id: "ia-tracking", class: "ia-tracking", open: !!b.tracking }, h("summary", { id: "ia-tracking-summary", text: "Office tracking (optional)" + (b.tracking ? " · recorded" : "") }),
        h("p", { class: "hint", text: food ? "Optional office count of requests for SNAP information from the date tracking begins. Baseline: " + (t.baseline === null ? "not recorded" : t.baseline) + ". This is not a count of eligible or unserved residents, participation, a population rate or program impact. Do not enter resident details." : "A staff record such as “agency/partner referral sessions arranged”. Baseline: " + (t.baseline === null ? "not supplied" : t.baseline + (t.as_of ? " as of " + t.as_of : "")) + ". Never a verified dataset baseline. Do not enter resident details." }),
        food && !b.tracking ? btn("Use SNAP information-request tracking", () => {
          if (C.active(state).tracking) return;
          set(C.setTracking(state, {label:"Office requests for SNAP information",baseline:null,as_of:null}), "Tracking added as a staff contribution; baseline is not recorded.");
        }, { id: "ia-track-preset" }) : null,
        textField("ia-track-label", "Measure label", t.label, 80, (v, defer) => track({ label: v }, defer)),
        h("div", { class: "ia-inline" },
          h("div", { class: "field" }, h("label", { for: "ia-track-base", text: "Office baseline" }), h("input", { type: "number", id: "ia-track-base", min: 0, max: 1000000000, step: 1, value: t.baseline === null ? "" : String(t.baseline), on: { change: (e) => track({ baseline: e.target.value === "" ? null : Number(e.target.value) }, document.activeElement !== e.target) } })),
          h("div", { class: "field" }, h("label", { for: "ia-track-date", text: food ? "Review date" : "As of" }), dateInput("ia-track-date", t.as_of, (value, defer) => track({ as_of: value }, defer)))), excl("tracking")),
    ]);

    // parked staff work
    const parked = C.pendingReview(state), box = state.parked[b.branch_id];
    // Use the same retained slot for actions and focus as the review list filters out resolved rows.
    const parkedSlot = (p) => box.items.indexOf(p);
    const sameAction = box && box.origin_action_ref && C.actionKey(box.origin_action_ref) === C.actionKey(b.selected_action_ref);
    fill($("#ia-review"), parked.length ? [h("h3", { id: "ia-review-h", class: "ia-group-title", tabindex: -1, text: "Staff notes waiting for review (" + parked.length + ")" }),
      h("p", { class: "hint", text: parked.every((x) => x.orphan_reason) ? "These notes were on findings removed from the selection. They are left out of this brief and are not in any case file while they wait; copy them back or discard them." :
        "These entries were written for an earlier context" + (box.kinds.length ? " (changed: " + box.kinds.map((k) => CHANGE_LABEL[k] || k).join(", ") + ")" : "") + ". They are left out of this brief and stay in their original context unless you copy them. Copies remain labeled staff contributions." + (parked.some((x) => x.orphan_reason) ? " A note on a removed finding is not in any case file while it waits." : "") }),
      h("ul", { class: "ia-parked" }, parked.map((p, i) => {
        const slot = parkedSlot(p);
        const rowId = b.branch_id + "-" + slot;
        const done = p.kind === "checklist" && p.item.completed && sameAction ? h("input", { type: "checkbox", id: "ia-park-done-" + rowId }) : null;
        return h("li", {}, h("p", {}, staffLine(p, " (done in the earlier context)")),
          p.kind === "checklist" && p.item.completed && !sameAction ? h("p", { class: "hint", text: "The done mark belongs to a different agency action and is not copied." }) : null,
          p.orphan_reason ? h("p", { class: "hint", text: "This note was on a finding removed from the selection, and it is not in any case file while it waits. Select that finding again, then copy the note back; or leave it to discard it." }) : null,
          done ? h("label", { class: "ia-check", for: done.id }, done, " Also copy the done mark (same agency action)") : null,
          h("div", { class: "btn-row" },
            btn("Copy into this context", (e) => {
              const hadFocus = document.activeElement === e.currentTarget;
              if (set(C.copyParked(state, b.branch_id, slot, { include_completion: !!(done && done.checked) }), "Copied as a staff contribution. Review staff notes before creating the brief.") && hadFocus) {
                ($("#ia-review-h") || $("#ia-staff-h")).focus();
              }
            }, { id: "ia-park-copy-" + rowId }),
            btn(p.orphan_reason ? "Discard this note" : "Leave in original context", (e) => {
              const hadFocus = document.activeElement === e.currentTarget, next = parked[i + 1];
              if (set(C.leaveParked(state, b.branch_id, slot), p.orphan_reason ? "Note discarded at your choice." : "Left in its original context.") && hadFocus) {
                // The next row's action, else the review heading while notes remain, else the staff notes.
                ((next && document.getElementById("ia-park-leave-" + b.branch_id + "-" + parkedSlot(next))) || $("#ia-review-h") || $("#ia-staff-h")).focus();
              }
            }, { id: "ia-park-leave-" + rowId })));
      }))] : []);

    // brief controls: one primary action with its blocking reason beside it
    const staff = C.activeStaff(state), reviewed = C.reviewCurrent(state), block = briefBlock(b, res, busy, dirty, staff, reviewed, parked);
    $("#ia-review-state").textContent = staff.empty ? "No staff notes will be sent with this brief." : reviewed ? "Staff notes reviewed for this context and plan. They are sent to this app’s server to render the brief; the app does not save or log them." : "";
    $("#ia-review-btn").hidden = staff.empty || reviewed;
    $("#ia-review-btn").disabled = busy || parked.length > 0 || !res;
    $("#ia-brief-btn").disabled = !!block && !(state.last_error && state.last_error.code === "brief_overflow");
    const printBlocked = !block && C.printStatus(state).ok && !briefFits();
    const keptNote = previousBriefKept() ? " The latest attempt failed; the previous brief under One-page brief is kept unchanged." : "";
    $("#ia-brief-reason").textContent = (block ? block + keptNote : "") || (printBlocked ? "The brief was created but is too long to print on one page: choose what to leave out under One-page brief, then create it again." + keptNote : "") || "Ready: the brief uses the selected findings" + (b.selected_action_ref ? ", the chosen agency action" : "") + (staff.empty ? "." : " and your reviewed staff notes.") + keptNote;
    $("#ia-brief-reason").classList.toggle("is-ready", !block && !printBlocked);
    $("#ia-clean-brief-btn").hidden = staff.empty && !parked.length;
    $("#ia-clean-brief-btn").disabled = busy || !res || dirty || !b.selected_claim_refs.length;
  }

  // In place of the recommended-brief shortcut when programs are mixed or not the guided issue's: names the issue, the
  // program references and hypotheses in the results and the agency actions on offer (including none), and points to
  // the existing controls. Suggested findings are only named; nothing here selects or changes anything.
  function renderConflict(conflict, rec, res) {
    const box = $("#ia-recommend-conflict");
    if (!box) return;
    box.hidden = !conflict;
    if (!conflict) { fill(box, []); return; }
    const issue = ISSUE_LABEL[conflict.issue_id] || humanWords(conflict.issue_id), claims = claimMap(res);
    const names = (list) => (list.length ? list.map(programLabel).join("; ") : "None");
    const agency = (card) => { const prog = card.program_claim_ref ? claims.get(C.refKey(card.program_claim_ref)) : null, a = prog && prog.program && prog.program.agency; return programLabel(card.program_id) + (a ? " (" + hawaiiDisplay(a) + ")" : ""); };
    const row = (k, v) => h("div", {}, h("dt", { text: k }), h("dd", { text: v }));
    const mismatch = conflict.reasons.includes("issue_program_mismatch");
    const why = mismatch ? "The program steps use " + names(conflict.programs) + ", not " + programLabel(conflict.issue_program) + ", the program of the " + issue + " recipe."
      : "These results name more than one program" + (conflict.reasons.includes("reference_hypothesis_mismatch") ? ", and the program references and outreach hypotheses differ" : "") + ".";
    fill(box, [h("h3", { class: "ia-group-title", id: "ia-conflict-h", tabindex: "-1", text: "Choose this brief yourself" }),
      h("p", { id: "ia-conflict-why", text: why + " The app does not choose findings or an agency action for you, so " + (rec === briefFocus ? "Create brief from this answer" : "Create recommended brief") + " is not offered here. These suggestions leave your selections unchanged." }),
      h("dl", { class: "kv ia-conflict-facts" },
        row("Guided issue", issue + (conflict.issue_program ? " (its recipe uses " + programLabel(conflict.issue_program) + ")" : " (no recipe program)")),
        row("Program references in these results", names(conflict.references)),
        row("Outreach hypotheses in these results", names(conflict.hypotheses)),
        row("Agency actions you can choose", (conflict.cards.length ? conflict.cards.map(agency).join("; ") + "; or " : "") + "No agency action in the brief"),
        rec.claims.length ? row("Suggested findings", rec.claims.map(claimShortName).join("; ")) : null),
      mismatch ? h("p", { class: "hint", id: "ia-conflict-custom", text: "The issue stays " + issue + ", and its recipe and saved references are unchanged. If this context is no longer " + issue + ", staff can choose Custom under District and issue." }) : null,
      h("ol", { class: "ia-conflict-steps" },
        h("li", {}, "Select findings under Findings and evidence. ", btn("Go to Findings and evidence", () => $("#ia-evidence-h").focus(), { class: "btn-link", id: "ia-conflict-evidence" })),
        h("li", {}, "Choose one agency action, or No agency action in the brief, under Agency verification. ", btn("Go to Agency verification", () => $("#ia-responses-h").focus(), { class: "btn-link", id: "ia-conflict-agency" })),
        h("li", { text: "Choose Create brief from my selection below." }))]);
  }
  // Why a selected finding has no tile of its own: it is support of listed findings in these results.
  function supportingText(sup) {
    const parents = sup.parents.map(claimShortName);
    return "Supporting finding: it has no tile of its own in these results" + (parents.length ? "; it is part of the basis of " + parents.join("; ") + "." : "; it supports another finding here.");
  }

  // One staff contribution as a labelled sentence (case preview, review list, import preview).
  function staffLine(it, doneText) {
    const claims = claimMap(C.currentResults(state));
    if (it.kind === "checklist") {
      const c = it.item || {};
      return [h("strong", { text: "Checklist — " + checkLabel(c.item_id) + ": " }), [c.text || "(template wording)", c.owner_role ? "role: " + c.owner_role : null, c.due_date ? "date: " + c.due_date : null, c.completed ? (doneText ? doneText.trim() : "done") : "not done"].filter(Boolean).join(" · ")];
    }
    if (it.kind === "tracking") {
      const t = it.tracking || {};
      return [h("strong", { text: "Office tracking: " }), [t.label || "no label", "baseline " + (t.baseline === null || t.baseline === undefined ? "not recorded" : t.baseline), t.as_of ? "date " + t.as_of : null].filter(Boolean).join(" · ")];
    }
    if (it.kind === "finding_note") {
      const c = Array.from(claims.values()).find((x) => x.claim_ref.semantic_hash === it.semantic_hash);
      return [h("strong", { text: "Note on a finding" + (c && typeof c.text === "string" ? " (" + (c.text.length > 60 ? c.text.slice(0, 58) + "…" : c.text) + ")" : "") + ": " }), String(it.value || "")];
    }
    return [h("strong", { text: (it.kind === "note" ? "Summary" : STAFF_LABEL[it.kind] || humanWords(it.kind)) + ": " }), String(it.value || "")];
  }

  // One-page check on the real layout: a copy of the brief is laid out off screen at the printed width
  // (US letter, 0.45in margins) with the print type sizes. A brief taller than one page is refused before
  // printing, with explicit leave-out choices; nothing is shrunk. The server's estimate remains the first gate.
  const PAGE_PX = 10.1 * 96, FIT_SHARE = 0.985;   // headless calibration: 0.998 printed one page, 1.006 printed two
  let fitProbe = null, briefFit = { tag: null, ok: true, over: 0 };
  function measureBrief(out, tag) {
    if (briefFit.tag === tag) return briefFit;
    const doc = out.querySelector(".brief-doc");
    if (!doc) return (briefFit = { tag: tag, ok: true, over: 0 });
    if (!fitProbe) { fitProbe = h("div", { class: "fit-probe", "aria-hidden": "true" }); document.body.append(fitProbe); }
    const copy = doc.cloneNode(true);
    copy.removeAttribute("id"); copy.querySelectorAll("[id]").forEach((n) => n.removeAttribute("id"));
    fill(fitProbe, [copy]);
    const height = copy.getBoundingClientRect().height;
    fill(fitProbe, []);
    if (!height) return { tag: null, ok: true, over: 0 };   // not laid out yet; checked again on the next render
    return (briefFit = { tag: tag, ok: height <= PAGE_PX * FIT_SHARE, over: Math.max(1, Math.round((height / (PAGE_PX * FIT_SHARE) - 1) * 100)) });
  }

  function renderBrief(b) {
    const brief = state.briefs[b.branch_id], status = C.printStatus(state), out = $("#ia-brief-out"), fitBox = $("#ia-brief-fit");
    if (!brief) {
      if (out.dataset.rev) { fill(out, []); delete out.dataset.rev; } out.classList.remove("is-stale");
      $("#ia-brief-status").textContent = status.message; $("#ia-print-btn").disabled = true; fitBox.hidden = true; fill(fitBox, []); return;
    }
    const tag = b.branch_id + ":" + brief.revision + ":" + brief.digest.length + ":" + (brief.brief.html || "").length;
    if (out.dataset.rev !== tag) {
      // Trusted server-rendered brief from a reply whose tokens matched this exact branch and revision.
      out.innerHTML = brief.brief.html;
      out.querySelectorAll("[id]").forEach((n) => { if (n.id === "brief-doc") n.id = "ia-brief-doc"; });
      markCitationRoles(out);
      out.dataset.rev = tag;
    }
    out.classList.toggle("is-stale", !status.ok);
    const fit = measureBrief(out, tag), tooLong = status.ok && !fit.ok;
    $("#ia-brief-status").textContent = tooLong ? "Not ready to print: measured on the printed page layout, this brief is about " + fit.over + "% longer than one page."
      : previousBriefKept() ? "Ready to print the previous brief shown below. The latest attempt to create a new brief failed; this one still matches the current selections and staff notes." : status.message;
    $("#ia-print-btn").disabled = !status.ok || !fit.ok;
    fitBox.hidden = !tooLong;
    if (!tooLong) { fill(fitBox, []); return; }
    fill(fitBox, [h("h3", { id: "ia-fit-h", tabindex: "-1", text: "Too long for one printed page" }),
      h("p", { text: "Text is not shrunk to fit. Choose what to leave out, then create the brief again. Staff notes left out of the brief stay in the editor and can be included again." }),
      recommendRecovery("ia-fit-recommend"), choiceList(C.shorteningChoices(state), "ia-fit-", "#ia-fit-h")]);
  }

  // Screen preview only: the agency action's citation markers are labelled by the recorded family of each
  // cited source (catalog metadata), statistical basis apart from program references. The label is an
  // attribute shown by screen CSS inside .brief-preview; printed text, the print copy and the fit probe are
  // unchanged. No label is added when a family is unknown or the two groups are interleaved.
  function markCitationRoles(root) {
    const fam = new Map();
    (catalog && catalog.sources || []).forEach((src) => { if (typeof src.url === "string") fam.set(src.url, fam.has(src.url) && fam.get(src.url) !== src.family ? null : src.family); });
    root.querySelectorAll(".brief-action p").forEach((para) => {
      const cites = Array.from(para.querySelectorAll(":scope > a.cite"));
      const roles = cites.map((a) => {
        const li = root.querySelector('li[id="' + String(a.getAttribute("href") || "").slice(1).replace(/"/g, "") + '"]');
        const link = li && li.querySelector("a.cite-label"), f = link ? fam.get(link.getAttribute("href")) : null;
        return f === "statistics" ? "basis" : f === "programs" ? "program" : null;
      });
      const split = roles.indexOf("program");
      if (roles.some((r) => r === null) || split <= 0 || roles.slice(split).some((r) => r !== "program")) return;
      cites[0].setAttribute("data-screen-label", "Statistical basis ");
      cites[split].setAttribute("data-screen-label", "; program sources ");
    });
  }

  // Whether the current brief passed the one-page check (used by printing).
  function briefFits() { return briefFit.ok; }

  // Name a staff group in the reopen preview by its own context in the parsed file (joined by branch id).
  function importContextName(branchId) {
    const branches = importing && importing.incoming && importing.incoming.case ? importing.incoming.case.branches : [];
    const i = branches.findIndex((br) => br.branch_id === branchId);
    if (i < 0) return "Context";
    const p = branches[i].plan;
    return "Investigation " + (i + 1) + ": " + planLabel(p);
  }

  // A note on a removed finding waits for review in this page only: a case file cannot hold it until it is copied back
  // or left. While any waits (in this or another context), a download "with staff notes" would omit it, so it is held.
  function heldWork() {
    const n = Object.keys(state.parked || {}).reduce((k, id) => k + state.parked[id].items.filter((i) => i.resolved === null && i.orphan_reason).length, 0);
    // Unfinished custom checklist text (typed, not added) is in no case file either, so it holds the same guard.
    const keys = new Set(), onScreen = $("#ia-chk-new"), mine = (k) => k.indexOf(state.case.case_id + "|") === 0;
    addDrafts.forEach((v, k) => { if (mine(k) && String(v).trim()) keys.add(k); });
    if (onScreen && onScreen.draftKey && mine(onScreen.draftKey)) { if (String(onScreen.value || "").trim()) keys.add(onScreen.draftKey); else keys.delete(onScreen.draftKey); }
    return { notes: n, unfinished: keys.size };
  }
  function staffDownloadBlock() {
    const held = heldWork(), n = held.notes, keys = { size: held.unfinished };
    const parts = [];
    if (n) parts.push((n === 1 ? "A staff note on a removed finding is" : n + " staff notes on removed findings are") + " waiting for review. Select the finding again and copy the note back, or discard it, under “Staff notes waiting for review” (restore the context it belongs to if needed).");
    if (keys.size) parts.push((keys.size === 1 ? "An unfinished custom checklist item is" : keys.size + " unfinished custom checklist items are") + " typed but not added. Choose Add item or clear the text (in the context it was typed in).");
    return parts.length ? parts.join(" ") + " Until then a download with staff notes would leave " + (n + keys.size === 1 ? "it" : "them") + " out; a case file cannot hold " + (n && keys.size ? "them." : n ? "a waiting note." : "unfinished text.") : null;
  }
  // The full local download that allows Remove context: nothing held in page memory, and the last download requested
  // was the staff-inclusive export of exactly this case (a default download counts only when the case has no staff text).
  const fullDownloadCurrent = () => !staffDownloadBlock() && savedDigest === C.canonical(C.exportCase(state, { include_staff_work: true }));
  // The step that makes a context removable, worded for what this case holds.
  function downloadStep() {
    const held = heldWork(), fix = [held.notes ? "copy back or discard the staff notes waiting for review" : "", held.unfinished ? "add or clear the unfinished checklist text" : ""].filter(Boolean);
    return (fix.length ? fix.join(" and ") + " (a case file cannot hold " + (held.notes + held.unfinished === 1 ? "it" : "them") + "), then " : "") +
      "download the case" + (C.staffExportPreview(state).length ? " with staff notes included" : "");
  }
  // What replacing this case with a file would take out of the page. Counts only; no staff text is repeated here.
  function outgoingWork() {
    const brs = state.case.branches, held = heldWork(), staff = C.staffExportPreview(state);
    const entries = staff.reduce((n, r) => n + r.items.length, 0), sel = brs.reduce((n, br) => n + br.selected_claim_refs.length, 0), acts = brs.filter((br) => br.selected_action_ref).length;
    const where = (rows) => rows.length ? " (" + rows.map((r) => "Investigation " + (brs.findIndex((br) => br.branch_id === r.branch_id) + 1)).join(", ") + ")" : "";
    const items = [];
    if (entries) items.push(plural(entries, "staff entry", "staff entries") + " — notes, checklist or tracking" + where(staff) + ". A download without “Include staff notes” leaves them out.");
    if (sel || acts) items.push(plural(sel, "selected finding", "selected findings") + (acts ? " and " + plural(acts, "chosen agency action", "chosen agency actions") : "") + where(brs.filter((br) => br.selected_claim_refs.length || br.selected_action_ref)) + ".");
    if (brs.length > 1) items.push(plural(brs.length - 1, "other context", "other contexts") + " besides the current one.");
    if (held.notes) items.push(plural(held.notes, "staff note on a removed finding is", "staff notes on removed findings are") + " waiting for review. No case file holds " + (held.notes === 1 ? "it" : "them") + " until copied back.");
    if (held.unfinished) items.push(plural(held.unfinished, "unfinished custom checklist item is", "unfinished custom checklist items are") + " typed but not added. No case file holds unfinished text.");
    return { items: items, saved: fullDownloadCurrent() };
  }
  const riskKey = (o) => (o && o.items.length && !o.saved ? JSON.stringify(o.items) : "");
  function renderCase(b, busy) {
    const list = $("#ia-branches");
    const savedNow = fullDownloadCurrent();
    fill(list, state.case.branches.map((br, i) => {
      const on = br.branch_id === b.branch_id, n = C.staffItems(br).length;
      return h("li", { class: on ? "is-selected" : "" },
        h("div", { class: "ia-branch-text" },
          h("strong", { text: "Investigation " + (i + 1) + ": " + planLabel(br.plan) }),
          on ? h("span", { class: "badge badge-info", text: "Current" }) : null,
          br.review_state === "replay_blocked" ? h("span", { class: "badge badge-warn", text: "Replay blocked" }) : null,
          h("span", { class: "hint", text: br.plan.steps.length + " steps · " + br.selected_claim_refs.length + " selected · " + n + " staff entr" + (n === 1 ? "y" : "ies") })),
        br.snapshot_id !== state.runtime.snapshot_id ? replayHelp(br.snapshot_id) : null,
        on ? null : h("div", { class: "ia-branch-tools" },
          btn("Restore", () => restoreContext(br.branch_id), { class: "btn btn-small", id: "ia-restore-" + i, disabled: busy, "aria-label": "Restore context " + (i + 1) + " (" + planLabel(br.plan) + ") by replaying its evidence" }),
          btn("Remove context", () => {
            // Rechecked on activation: work typed since the last render (e.g. unfinished checklist text) is not in any download.
            // Focused staff text is collected first; a native date still being edited is never committed by this click.
            if (activeDate()) { notice = "Finish or leave the staff date being edited, then choose Remove context again. Nothing was removed."; render(); return; }
            flushActive(false);
            if (!fullDownloadCurrent()) { render(); alertUser("Nothing was removed. To remove a context, first " + downloadStep() + "."); return; }
            set(C.removeBranch(state, br.branch_id, { saved_locally: true }), "Context removed after a full local download.");
          }, { class: "btn-link btn-danger", id: "ia-rmbranch-" + i, disabled: busy || !savedNow, "aria-label": "Remove context " + (i + 1) + " (" + planLabel(br.plan) + ") from this page", "aria-describedby": "ia-rmbranch-why-" + i }),
          h("span", { class: "hint", id: "ia-rmbranch-why-" + i, text: savedNow ? "Saved in your last download." : "To remove it, first " + downloadStep() + "." })));
    }));
    const staffOn = $("#ia-download-staff").checked, pv = $("#ia-staff-preview"), held = staffOn ? staffDownloadBlock() : null;
    $("#ia-download").disabled = !!held;
    pv.hidden = !staffOn;
    if (staffOn) {
      const rows = C.staffExportPreview(state);
      fill(pv, [held ? h("p", { class: "alert", id: "ia-download-held", text: held }) : null,
        h("p", { class: "alert", text: "This file will contain the staff notes below as plain text. It is not encrypted. Anyone who can open the file can read it." }),
        rows.length ? h("ul", { class: "ia-staff-list" }, rows.map((r) => h("li", {}, h("strong", { text: contextName(r.branch_id) }), h("ul", {}, r.items.map((it) => h("li", {}, staffLine(it))))))) : h("p", { text: "There is no staff notes, checklist entry or tracking record in this case." })]);
    } else fill(pv, []);
    const ip = $("#ia-import-preview");
    ip.hidden = !importing;
    if (!importing) { fill(ip, []); return; }
    if (!importing.ok) { fill(ip, [h("h3", { text: "The file was not opened" }), h("ul", {}, importing.issues.map((i) => h("li", { text: i.code === "invalid_json" ? "This is not a case file this app can read (it could not be parsed). It was not opened." : i.message }))), h("p", { text: "Your current case is unchanged." }), btn("Close", () => { importing = null; render(); $("#ia-import-file").focus(); }, { id: "ia-import-close" })]); return; }
    const p = importing.preview, accept = h("input", { type: "checkbox", id: "ia-import-staff", checked: !!importing.accept_staff, on: { change: (e) => { importing.accept_staff = e.target.checked; } } });
    // Before Replay: what is replaced, and the outgoing work at risk unless a full download was requested since it changed.
    const out = p.runtime_match ? outgoingWork() : null, risk = out && out.items.length && !out.saved;
    importing.shown_risk = riskKey(out);   // exactly what this preview presents, compared again when Replay is chosen
    const replaceNote = out ? h("div", { id: "ia-import-replace" },
      h("p", { text: "Replay and open replaces the case open in this page now (" + plural(state.case.branches.length, "context", "contexts") + "; current: Investigation " + (state.case.branches.findIndex((br) => br.branch_id === b.branch_id) + 1) + ", " + planLabel(b.plan) + ") with the file's case. If the replay fails or you cancel, the current case stays as it is." }),
      risk ? h("div", { class: "alert", id: "ia-import-risk", tabindex: "-1" }, h("p", { text: "No full download was requested since this work last changed. After the replay it is gone from this page:" }),
        h("ul", {}, out.items.map((t) => h("li", { text: t }))),
        h("p", { text: "To keep it, choose Cancel, then under Save or reopen the case " + downloadStep() + ". A download is only a request; check your browser's downloads to confirm the file was saved, then choose the file to open again." }))
        : out.items.length ? h("p", { class: "hint", text: "A download of everything in this case was requested after its last change. Check your browser's downloads to confirm the file was saved." }) : null) : null;
    fill(ip, [h("h3", { text: "Case file preview" + (p.runtime_match ? "" : " — cannot be replayed here") }),
      h("dl", { class: "kv" },
        h("div", {}, h("dt", { text: "Active plan" }), h("dd", { text: planLabel(p.active_plan) + " · " + p.active_plan.steps.map((s, i) => (i + 1) + ". " + OP_LABEL[s.operation]).join("; ") })),
        h("div", {}, h("dt", { text: "Contexts" }), h("dd", { text: String(p.branch_count) })),
        h("div", {}, h("dt", { text: "Saved selections" }), h("dd", { text: p.selection_count + " finding" + (p.selection_count === 1 ? "" : "s") + (p.has_action ? " and one agency action" : "") + ". Facts are regenerated by replay; saved text is not used." })),
        h("div", {}, h("dt", { text: "Evidence version" }), h("dd", { text: p.runtime_match ? "Matches this app" : "Different from this app" }))),
      p.runtime_match ? null : h("p", { class: "alert", text: "This file was saved with a different evidence version. It cannot be replayed here, so no verified brief or print is available for it. Your saved file and current work are unchanged; no notes or selections are moved." }),
      !p.runtime_match && p.snapshot_id !== state.runtime.snapshot_id ? replayHelp(p.snapshot_id) : null,
      p.staff_items && p.runtime_match ? h("div", {}, h("p", { text: "The file holds " + p.staff_items + " staff entr" + (p.staff_items === 1 ? "y" : "ies") + " (unverified staff notes):" }),
        h("ul", { class: "ia-staff-list" }, p.staff_preview.map((r) => h("li", {}, h("strong", { text: importContextName(r.branch_id) }), h("ul", {}, r.items.map((it) => h("li", {}, staffLine(it))))))),
        h("label", { class: "ia-check", for: "ia-import-staff" }, accept, " Also open these staff notes (they will need review before any brief)")) : null,
      replaceNote,
      h("div", { class: "btn-row" },
        p.runtime_match ? btn("Replay and open this case", () => {
          // Work typed after this preview rendered (for example unfinished checklist text) never renders it. When the
          // risk now differs from what is shown, the preview is refreshed and nothing is sent; Replay again proceeds.
          // What was on screen before this click; collecting focused staff text below may re-render the preview.
          const shown = importing.shown_risk, opened = importing;
          if (activeDate()) { notice = "Finish or leave the staff date being edited, then choose Replay and open this case again. Nothing was sent."; render(); return; }
          flushActive(false);
          if (importing !== opened) return;
          const now = outgoingWork();
          if (now.items.length && !now.saved && riskKey(now) !== shown) {
            notice = "The work at risk changed since this preview opened. Nothing was sent. Review the updated list, then choose Replay and open this case again, or Cancel.";
            render(); const w = $("#ia-import-risk"); if (w && !activeDate()) w.focus(); return;
          }
          const r = C.beginImport(state, importing, { accept_staff_work: accept.checked }, ids); if (r.error) return alertUser(r.error.message); mapFork = null; state = r.state; notice = "Replaying the file's active plan. Only the plan and references are sent, never the file."; send(r.request); holdFocus(); }, { class: "btn btn-primary", id: "ia-import-go", disabled: busy, "aria-describedby": "ia-import-replace" }) : null,
        btn(p.runtime_match ? "Cancel" : "Close", () => {
          // After Replay and open, Cancel also cancels the pending replay (as Cancel request does), so the reply is ignored.
          const replaying = !!(state.pending && state.pending.kind === "import");
          if (replaying) { state = C.cancelPending(state); mapFork = null; }
          importing = null;
          notice = replaying ? "Import cancelled. Your current case is kept and editing is back on; a late reply for the file will be ignored." : "Import cancelled. Your current case is unchanged.";
          render(); $("#ia-import-file").focus();
        }, { id: "ia-import-cancel" }))]);
  }

  // ------------------------------------------------------------------ map
  // Wide screens only (the side-by-side layout); a narrow screen keeps the compact closed map. Focus does not move.
  function openMapForAnswer() {
    const p = C.active(state).plan;
    mapWanted = [state.runtime.snapshot_id, p.district.chamber, p.district.code, p.map_session].join("|");
    openWantedMap();
  }
  function openWantedMap() {
    const box = $("#ia-mapbox");
    if (!mapWanted || mapWanted !== mapKey || mapWanted !== mapReadyKey) return;
    mapWanted = null;
    if (!box || box.open || mapCollapsedByUser || !(window.matchMedia && window.matchMedia("(min-width: 1100px)").matches)) return;
    box.open = true;
  }
  function syncMap(force) {
    const p = C.active(state).plan, key = [state.runtime.snapshot_id, p.district.chamber, p.district.code, p.map_session].join("|");
    if (key === mapKey && !force) return;
    if (key === mapKey) return;
    mapKey = key; mapReadyKey = null;
    const box = $("#ia-map");
    if (!mapHandle && window.IA1Map && typeof window.IA1Map.mount === "function") mapHandle = window.IA1Map.mount(box, { onSummary: (t) => { $("#ia-map-summary").textContent = t; },
      onReady: (id) => { mapReadyKey = [id.snapshot_id, id.chamber, id.code, id.session].join("|"); openWantedMap(); } });
    if (!mapHandle) { fill(box, [h("p", { class: "alert", text: "The boundary map cannot be shown. The district description below and all other evidence remain available." })]); $("#ia-map-summary").textContent = "unavailable"; return; }
    // The viewer replaces its own content and ignores late geometry for an earlier identity.
    mapHandle.update({ snapshot_id: state.runtime.snapshot_id, chamber: p.district.chamber, code: p.district.code, session: p.map_session });
  }
  function syncMapText(b) {
    const d = b.plan.district;
    fill($("#ia-map-text"), [h("div", {}, h("dt", { text: "District" }), h("dd", { text: districtLabel(d) + ", Hawaiʻi" })),
      h("div", {}, h("dt", { text: "Statistics boundary" }), h("dd", { text: "2024 district boundaries" })),
      h("div", {}, h("dt", { text: "Map boundary shown" }), h("dd", { text: b.plan.map_session + " boundaries (display only)" })),
      h("div", {}, h("dt", { text: "Map shading" }), h("dd", { text: "Poverty rate for all ages (all people), not the age 65 and over rate" })),
      h("div", {}, h("dt", { text: "Area for program questions" }), h("dd", { text: b.plan.service_area_id ? AREA_LABEL[b.plan.service_area_id] + " (staff choice, not a geographic finding)" : "None chosen" }))]);
  }

  // The live map-only fork, while it still describes exactly what is on screen: same case, the forked context with the
  // plan it was applied with, and (after its run committed) the same results revision. Anything else forgets it.
  function liveMapFork() {
    const f = mapFork;
    if (!f) return null;
    const b = C.active(state), origin = C.branchOf(state, f.origin_branch_id);
    if (state.case.case_id !== f.case_id || !origin || origin.last_ready_revision !== f.origin_revision ||
        b.branch_id !== f.branch_id || C.canonical(b.plan) !== f.plan) { mapFork = null; return null; }
    return b.last_ready_revision === f.revision ? f : null;
  }
  // The Select again offer for the retired findings of a live map-only fork, or why it is not available.
  function mapForkNotice(f, res, retired, proof) {
    const origin = C.branchOf(state, f.origin_branch_id), b = C.active(state);
    if (!origin || !retired.some((r) => r.claim_ref)) return null;
    const was = origin.plan.map_session + " map display", now = b.plan.map_session + " map display", where = districtLabel(b.plan.district);
    const dropped = retired.filter((r) => r.claim_ref).length, one = dropped === 1;
    if (!proof.ok) return h("div", { class: "ia-reselect", id: "ia-reselect" },
      h("p", { id: "ia-reselect-why", text: (one ? "This finding was" : "These findings were") + " selected with the " + was + ". A finding's recorded identity includes the map display year, and that identity changed. " + (one ? "It is" : "They are") + " not selected in this context. Choose from the current findings under Findings and evidence." }),
      btn("Go to Findings and evidence", () => $("#ia-evidence-h").focus(), { class: "btn-link", id: "ia-reselect-evidence" }));
    const names = proof.pairs.map((x) => claimShortName(claimMap(res).get(C.refKey(x.current_ref))));
    const fits = Math.min(proof.free, proof.pairs.length), many = proof.pairs.length > 1;
    return h("div", { class: "ia-reselect", id: "ia-reselect" },
      h("p", { id: "ia-reselect-why", text: (many ? "These findings were" : "This finding was") + " selected with the " + was + " in " + contextName(origin.branch_id) + ". A finding's recorded identity includes the map display year, so " + (many ? "they were" : "it was") + " not kept automatically. " +
        "The server reports that the 2024 and 2026 boundaries of " + where + " are the same, and the current results (" + now + ") list " + (many ? "each one" : "it") + " with the same values, sources and step." }),
      h("ul", { class: "hint" }, names.map((n) => h("li", { text: n }))),
      fits < proof.pairs.length ? h("p", { class: "hint", id: "ia-reselect-cap", text: fits ? "The brief holds at most 8 findings, so Select again adds the first " + plural(fits, "finding", "findings") + " in this list." : "The brief already holds 8 findings. Remove one under Selected findings to select these again." } ) : null,
      btn("Select again", () => selectAgain(), { class: "btn", id: "ia-reselect-btn", disabled: !fits || !!state.pending, "aria-describedby": "ia-reselect-why ia-reselect-what" }),
      h("p", { class: "hint", id: "ia-reselect-what", text: "Selects the current findings with the ordinary selection. No agency action, staff note or checklist entry is carried, and the earlier context keeps its own selections." }));
  }
  function selectAgain() {
    const f = liveMapFork(), r = f ? C.reselectMapFork(state, f) : null;
    if (!r || r.error) { notice = "These findings can no longer be matched to the current results. Nothing was selected."; mapFork = null; render(); if (!activeDate()) $("#ia-evidence-h").focus(); return; }
    state = r.state;
    f.consumed = true;
    notice = plural(r.added.length, "finding was", "findings were") + " selected again from the current results." + (r.left.length ? " " + plural(r.left.length, "finding was", "findings were") + " not selected: the brief holds at most 8 findings." : "") + " No agency action, staff note or checklist entry was carried.";
    render(); if (!activeDate()) $("#ia-tray-h").focus();
  }

  // ------------------------------------------------------------------ wiring
  function wire() {
    // Replacing a pointer's target before release would swallow its click. State is already committed;
    // refresh after the click, or after Tab's focus transition when no pointer is pressed.
    document.addEventListener("pointerdown", () => { pointerDown = true; }, true);
    ["pointerup", "pointercancel", "blur"].forEach((type) => window.addEventListener(type, () => {
      pointerDown = false;
      if (textRenderPending) renderAfterTextCommit();
    }));
    // A click on the open map's summary (pointer or keyboard) is a staff collapse; no answer reopens it afterwards.
    $("#ia-mapbox > summary").addEventListener("click", () => { if ($("#ia-mapbox").open) mapCollapsedByUser = true; });
    const ctx = (patch) => {
      const r = C.setContext(state.draft, patch);
      if (r.error) return editDraft(r);
      // Worded from the predicted outcome for the edited draft (the same check Apply makes when chosen).
      const outcome = applyOutcome(r.plan);
      editDraft(r, outcome === "rerun" ? "Context edited. The draft matches the plan already run." : "Context edited. Choose " + contextApplyLabel(outcome) + " to " +
        (reviewsFirst(outcome) ? "review it before it runs." : "run it at once in this context."));
    };
    $("#ia-district").addEventListener("change", (e) => { const v = String(e.target.value).split(":"); if (v.length === 2) ctx({ district: { chamber: v[0], code: v[1] } }); });
    $("#ia-issue").addEventListener("change", (e) => ctx({ issue_id: e.target.value }));
    $("#ia-service").addEventListener("change", (e) => ctx({ service_area_id: e.target.value || null }));
    $("#ia-map-session").addEventListener("change", (e) => ctx({ map_session: Number(e.target.value) }));
    $("#ia-question-form").addEventListener("submit", (e) => { e.preventDefault(); if (languageJob && languageJob.pending) return; askLanguage($("#ia-question-text").value); });
    $("#ia-question-example").addEventListener("click", (e) => {
      const q = $("#ia-question-text");
      if (q.readOnly || q.value.trim()) return;
      q.value = e.currentTarget.dataset.exampleQuestion;
      q.focus();
      q.dispatchEvent(new Event("input", { bubbles: true }));
    });
    $("#ia-question-cancel").addEventListener("click", () => {
      if (document.activeElement === $("#ia-question-cancel")) $("#ia-question-text").focus();
      cancelLanguage('Question cancelled. Your work is unchanged.'); render();
    });
    // Never cancels a pending (possibly charged) question; the box is read-only then. A finished answer is cleared as before.
    $("#ia-question-text").addEventListener("input", () => {
      lockQuestion();
      if (languageJob && !languageJob.pending) { cancelLanguage('Question changed. Ask again when ready.'); render(); }
    });
    $("#ia-ask").addEventListener("submit", (e) => {
      e.preventDefault();
      const text = $("#ia-utterance").value;
      const r = C.beginInterpret(state, text, ids);
      if (r.error) return alertUser(r.error.message);
      state = r.state; interp = { utterance: text, matched_fields: [], inherited_fields: [], choices: [], reason: null, status: "pending", request_id: r.request.request_id }; notice = "Reading your typed request. Nothing runs until you apply it.";
      send(r.request);
    });
    $("#ia-add-btn").addEventListener("click", () => {
      const op = $("#ia-add-op").value, r = C.addStep(state.draft, op, defaultArgs(op));
      editDraft(r, "Step added to the draft with a default scope. Open “Change scope” to adjust it, then choose Apply plan.");
      if (!r.error) { const s = r.plan.steps[r.plan.steps.length - 1], dt = $("#ia-scope-" + s.step_id); if (dt) { dt.open = true; dt.querySelector("summary").focus(); } }
    });
    $("#ia-apply").addEventListener("click", applyPlan);
    // Step names used by typed requests are shown only while the typed-request help is open.
    $("#ia-typed").addEventListener("toggle", () => render());
    // The same review-and-run action, placed beside the edited context selects.
    $("#ia-context-apply-btn").addEventListener("click", () => { applyPlan(); if (!preview) holdFocus(); });
    $("#ia-discard").addEventListener("click", () => { state = Object.assign({}, state, { draft: JSON.parse(JSON.stringify(C.active(state).plan)) }); preview = null; pendingAnswer = null; notice = "Draft edits discarded. The plan matches the last applied context."; render(); });
    $("#ia-cancel").addEventListener("click", () => {
      // A cancelled typed request ends its own card (not a newer one); its text stays in the box to read again.
      const p = state.pending, typed = !!(p && p.kind === "interpret" && interp && interp.status === "pending" && interp.request_id === p.tokens.request_id);
      const fromCancel = document.activeElement === $("#ia-cancel");
      if (typed) interp = Object.assign({}, interp, { status: "cancelled" });
      // A cancelled request also ends any Select again offer for a map-only fork; it is not offered on a later run.
      if (p && p.kind !== "interpret" && p.kind !== "brief") mapFork = null;
      pendingAnswer = null; state = C.cancelPending(state); notice = "Request cancelled. Any late reply will be ignored. Earlier results are unchanged."; render();
      if (typed && fromCancel) $("#ia-interpretation").focus();
    });
    $("#ia-review-btn").addEventListener("click", () => {
      if (!set(C.markReviewed(state), "Staff notes marked as reviewed for this context.")) return;
      const b = $("#ia-brief-btn");
      if (b && !b.disabled) b.focus(); else $("#ia-brief-reason").focus();
    });
    $("#ia-brief-btn").addEventListener("click", () => createBrief(false));
    $("#ia-recommend-btn").addEventListener("click", () => createRecommended());
    $("#ia-clean-brief-btn").addEventListener("click", () => createBrief(true));
    $("#ia-print-btn").addEventListener("click", () => { if (C.printStatus(state).ok && briefFits()) window.print(); });
    $("#ia-download-staff").addEventListener("change", render);
    $("#ia-download").addEventListener("click", () => {
      if (flushActive() === false) return;
      const held = $("#ia-download-staff").checked ? staffDownloadBlock() : null;
      if (held) { alertUser(held); return; }
      const staff = $("#ia-download-staff").checked, data = C.exportCase(state, { include_staff_work: staff });
      const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 1)], { type: "application/json" }));
      const a = h("a", { href: url, download: "haic-case-" + districtLabel(C.active(state).plan.district).toLowerCase().replace(" ", "-") + (staff ? "-with-staff-work" : "") + ".json" });
      document.body.append(a); a.click(); a.remove(); URL.revokeObjectURL(url);
      if (staff || !C.staffExportPreview(state).length) savedDigest = C.canonical(C.exportCase(state, { include_staff_work: true }));
      // The page cannot see whether the browser saved the file, so it does not claim that it did.
      notice = (staff ? "Download requested with staff notes as plain, unencrypted text." : "Download requested: plan and references only. No typed request, title, notes, roles, dates, tracking or done marks.") + " Check your browser's downloads to confirm the file was saved.";
      render();
    });
    $("#ia-import-file").addEventListener("change", async (e) => {
      const file = e.target.files && e.target.files[0];
      e.target.value = "";
      if (!file) return;
      if (file.size > C.LIMITS.case_bytes) importing = { ok: false, issues: [{ path: "", code: "too_large", message: "The file is larger than a case file can be (256 KB). It was not read." }] };
      else {
        let text = ""; try { text = await file.text(); } catch (err) { text = ""; }
        flushActive(false);   // collect staff text while retaining any focused native date edit
        importing = C.parseCaseFile(text, state.runtime);
      }
      render(); if (!activeDate()) $("#ia-import-preview").focus();
    });
    // Only the reviewed investigation brief prints while this view is open.
    window.addEventListener("beforeprint", () => {
      if ($("#tab-investigation").hidden) return;
      const root = $("#print-root"), doc = $("#ia-brief-out .brief-doc") || $("#ia-brief-out").firstElementChild, st = C.printStatus(state);
      fill(root, st.ok && briefFits() && doc ? [doc.cloneNode(true)] : [h("p", { text: "No verified one-page brief is ready to print. " + (st.ok ? "It is longer than one page; choose what to leave out in the app." : st.message) })]);
    });
  }

  function createBrief(clean) {
    if (flushActive() === false) return;
    const r = C.beginBrief(state, { clean: clean }, ids);
    if (r.error) return alertUser(r.error.message);
    state = r.state; notice = "Creating the brief…"; send(r.request); holdFocus();
  }

  function unavailable(message) {
    fill($("#ia-boot"), [h("section", { class: "notice notice-error", role: "alert" }, h("h3", { text: "Investigation is not available" }), h("p", { text: message }),
      btn("Try again", () => start(), { id: "ia-boot-retry", class: "btn btn-primary" }), " ", btn("Open single lookup", () => $("#tab-btn-workflow").click(), { id: "ia-boot-guided" }))]);
    $("#ia-boot").hidden = false; $("#ia-workspace").hidden = true;
  }

  async function start() {
    if (!C) return unavailable("The case module did not load.");
    let cat;
    try { const r = await fetch("/api/catalog?view=summary", { credentials: "same-origin" }); cat = await r.json(); } catch (e) { return unavailable("The server did not respond. Nothing was lost; try again."); }
    boot = cat && cat.investigation;
    if (!boot || typeof boot.snapshot_id !== "string" || boot.schema_version !== C.SCHEMA_VERSION) return unavailable("This version of the app cannot open the investigation workspace. The single lookup view still works.");
    catalog = cat;
    const issueSelect = $("#ia-issue");
    const foodAvailable = (boot.recipe_versions || []).includes("food_assistance_outreach/1");
    let foodOption = issueSelect.querySelector('option[value="food_assistance_outreach"]');
    if (foodAvailable && !foodOption) issueSelect.append(h("option", { value: "food_assistance_outreach", text: "SNAP outreach" }));
    if (!foodAvailable && foodOption) foodOption.remove();
    // Descriptive source labels come from the renderer (inert JSON in the sources markup); never executed.
    try {
      const doc = new DOMParser().parseFromString(String(cat.sources_html || ""), "text/html"), data = doc.getElementById("source-label-data");
      sourceLabels = data ? JSON.parse(data.textContent) : {};
    } catch (e) { sourceLabels = {}; }
    const runtime = { snapshot_id: boot.snapshot_id, release_id: boot.release_id || "", operation_version: boot.operation_version, schema_version: boot.schema_version, recipe_versions: boot.recipe_versions || ["aging_at_home/1", "custom/1"] };
    const issues = [], plan = boot.default_plan && C.validPlan(boot.default_plan, "plan", issues) ? boot.default_plan : C.defaultPlan();
    const first = !state;
    state = C.createState(runtime, ids, plan);
    $("#ia-boot").hidden = true; $("#ia-workspace").hidden = false;
    // The map is secondary and starts closed on every screen; its summary line names the district, parts and shading.
    if (first) wire();
    // Plan editing is secondary while questions are on; with questions off it is the main way to work.
    if (first) $("#ia-advanced").open = !languageEnabled();
    render(); syncMap(false);
    bootRun = true;
    runActive();
  }

  // Read-only: the applied district of the current context, so Single lookup can start from it. Nothing else is shared.
  window.IAWorkspace = { district: () => (state ? JSON.parse(JSON.stringify(C.active(state).plan.district)) : null) };
  document.addEventListener("DOMContentLoaded", start);
})();
