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
  let languageJob = null, languageResult = null;
  let notice = "";
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
  const OP_LABEL = { profile: "Profile measures", compare: "Compare with a geography", program_evidence: "Program reference", outreach_lead: "Reviewed outreach hypothesis", administrative_evidence: "Administrative records" };
  const ISSUE_LABEL = { aging_at_home: "Older-adult support at home", food_assistance_outreach: "SNAP outreach", custom: "Custom (staff-composed steps)" };
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
  const PENDING_LABEL = { run: "Running the plan…", brief: "Creating the brief…", interpret: "Reading your typed request…", restore: "Replaying the saved context…", import: "Replaying the case file…" };
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
  // The scope that tells saved contexts of one district and issue apart: each comparison geography in the
  // plan's steps and the staff-chosen program area. A geography not in the catalog is named as unlisted.
  function planScope(p) {
    const bits = [];
    (p && Array.isArray(p.steps) ? p.steps : []).forEach((st) => {
      const g = st && st.operation === "compare" && st.args ? st.args.comparison_geography : null;
      if (typeof g === "string") {
        const known = (catalog.geographies || []).concat(catalog.unavailable_geographies || []).find((x) => x.geography_id === g);
        bits.push("compared with " + (known ? known.label : "an unlisted geography"));
      }
    });
    if (p && p.service_area_id) bits.push("program area " + (AREA_LABEL[p.service_area_id] || "not listed"));
    return Array.from(new Set(bits)).join(", ");
  }
  const planLabel = (p) => districtLabel(p.district) + " · " + (ISSUE_LABEL[p.issue_id] || humanWords(p.issue_id)) + (planScope(p) ? " · " + planScope(p) : "");

  const metricLabel = (id) => ((catalog.metrics || []).find((m) => m.metric_id === id) || {}).label || id;
  const programLabel = (id) => ((catalog.programs || []).find((p) => p.program_id === id) || {}).name || id;
  function geoLabel(id) {
    const g = (catalog.geographies || []).concat(catalog.unavailable_geographies || []).find((x) => x.geography_id === id);
    return g ? g.label : id;
  }
  const adminRows = () => catalog.administrative_rows || catalog.participation || [];
  function adminLabel(id) {
    const r = adminRows().find((x) => x.observation_id === id);
    return r ? [r.series_label || r.label || r.program_id, typeof r.geography === "object" && r.geography ? (r.geography.label || r.geography.name) : r.geography, r.period].filter(Boolean).join(" · ") : "Recorded administrative row";
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
    if (v.chamber && v.code) return districtLabel(v);
    return Object.keys(v).filter((k) => v[k] !== null && v[k] !== "" && !/(^|_)(id|ids|hash|sha256|digest|path)$/.test(k)).map((k) => humanWords(k) + ": " + plain(v[k], (depth || 0) + 1)).join(", ");
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
    const quiet = bootRun; bootRun = false;
    state = result.state;
    flushActive();
    if (result.outcome === "discarded") { notice = "A late reply for an earlier request was ignored. The current context is unchanged."; render(); return; }
    if (result.outcome === "error") {
      const e = state.last_error || {};
      notice = previousBriefKept() ? (e.code === "brief_overflow" ? "The new brief was not created: it is too long for one page." : "The new brief was not created.") + " " + PREVIOUS_BRIEF + " Your work is kept." :
        (e.code === "brief_overflow" ? "No brief was created: it is too long for one page. Choose what to leave out." :
        e.kind === "brief" ? "The brief was not created." : e.kind === "restore" && lastRestore ? lastRestore.name + " was not restored. You are still on " + contextName(C.active(state).branch_id) + "." : e.kind === "run" || e.kind === "restore" ? "The plan did not run." :
        e.kind === "interpret" ? "The typed request was not read." : e.kind === "import" ? "The case file was not opened." : "The request did not complete.") + " Your work is kept.";
      render(); const box = $("#ia-error"); if (box && !quiet) box.focus(); return;
    }
    if (result.outcome === "interpreted") { interp = Object.assign({ status: result.status, utterance: interp ? interp.utterance : "" }, result.interpretation); notice = result.status === "ok" ? "Typed request read. Review the proposed change, then choose Put in draft plan." : "The typed request needs a choice or is not supported. Nothing was run."; render(); const t = $("#ia-interpretation"); t.focus(); return; }
    if (result.outcome === "brief") {
      notice = "Brief created for the current results."; render();
      if (!briefFits()) { notice = "Brief drafted, but it is too long to print on one page. Choose what to leave out under One-page brief."; render(); }
      const out = $("#ia-brief"); out.focus(); return;
    }
    const dropped = (result.retired || []).filter((r) => r.claim_ref).length;
    if (result.outcome === "imported") { importing = null; notice = "Case file replayed against this release's evidence and opened." + (dropped ? " " + plural(dropped, "saved selection was", "saved selections were") + " not reselected; see Selected findings." : ""); }
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
    return "Context " + (i + 1) + " (" + planLabel(p) + ")";
  }
  function restoreContext(branchId) {
    lastRestore = { branchId: branchId, name: contextName(branchId) };
    const r = C.beginRestore(state, branchId, ids);
    if (r.error) { if (r.state) state = r.state; alertUser(r.error.message); render(); return; }
    state = r.state; notice = "Replaying " + lastRestore.name + " against its exact evidence…"; send(r.request); holdFocus();
  }

  function runActive() {
    const r = C.beginRun(state, ids);
    if (r.error) { if (r.state) state = r.state; alertUser(r.error.message); render(); return; }
    state = r.state; clearAlert(); notice = "Running the plan…";
    syncMap(false);
    send(r.request);
    holdFocus();
  }

  // Optional language uses its own request lifecycle; it never dispatches a plan.
  function languageContext() { return window.IALanguage.context(state, C.active); }
  async function languagePost(action, body) {
    const r = await fetch('/api/language/' + action, {method:'POST', credentials:'same-origin', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
    let data = null; try { data = await r.json(); } catch (_) { /* handled as unavailable */ }
    return {http:r.status, data};
  }
  function cancelLanguage(message) {
    const job = languageJob;
    if (!job) return;
    languageJob = null;
    job.cancelled = true;
    clearTimeout(job.timer);
    clearTimeout(job.deadlineTimer);
    if (job.pending) languagePost('cancel', {schema_version:'ia-language/1', request_id:job.request_id}).catch(() => {});
    languageResult = message ? {status:'notice', message} : null;
  }
  function currentLanguage(job, body) {
    return languageJob === job && !job.cancelled && window.IALanguage.matches(body, job, languageContext(), state.runtime.release_id);
  }
  async function askLanguage(text) {
    if (!catalog.language || catalog.language.enabled !== true || !window.IALanguage) return;
    if (!text.trim() || Array.from(text).length > 500) { alertUser('Enter a question of up to 500 characters.'); return; }
    if (state.pending) { alertUser('Wait for the current request to finish or cancel it first.'); return; }
    cancelLanguage();
    const job = {request_id:ids.uuid(), context:languageContext(), context_digest:null, pending:true, cancelled:false, started:Date.now(), timer:null, polls:0};
    languageJob = job; languageResult = {status:'pending',message:'Preparing a proposal. Nothing has been applied or run.'};
    job.deadlineTimer = setTimeout(() => { if (languageJob === job && job.pending) { cancelLanguage('The question timed out. Use Typed request or guided controls; your work is unchanged.'); render(); } }, 25000);
    render();
    const body = {schema_version:'ia-language/1',request_id:job.request_id,context:job.context,utterance:text};
    try {
      const reply = await languagePost('start',body);
      if (languageJob !== job || job.cancelled) {
        // Cancel again after a late successful start, which may have raced an earlier cancellation.
        if (reply.http === 202) languagePost('cancel',{schema_version:'ia-language/1',request_id:job.request_id}).catch(() => {});
        return;
      }
      if (reply.http !== 202 || !currentLanguage(job,reply.data)) throw new Error(reply.http === 429 && reply.data && reply.data.code === 'shared_demonstration_rate_limit' ? 'rate_limited' : 'unavailable');
      job.context_digest = reply.data.context_digest;
      scheduleLanguagePoll(job);
    } catch (e) {
      if (languageJob !== job) return;
      clearTimeout(job.deadlineTimer); job.pending = false;
      languageResult = {status:'error',message:(e && e.message === 'rate_limited' ? 'The shared demonstration limit is reached: 5 language questions per session per hour and 15 shared across the site per hour. ' : 'Language question unavailable. ') + 'Use Typed request or guided controls; your work is unchanged.'}; render();
    }
  }
  function scheduleLanguagePoll(job) {
    const delays = [500,1000,2000];
    const delay = delays[Math.min(job.polls++,delays.length-1)];
    job.timer = setTimeout(() => pollLanguage(job),delay);
  }
  async function pollLanguage(job) {
    if (languageJob !== job) return;
    if (Date.now() - job.started >= 25000) { cancelLanguage('The question timed out. Use Typed request or guided controls; your work is unchanged.'); render(); return; }
    try {
      const reply = await languagePost('status',{schema_version:'ia-language/1',request_id:job.request_id});
      if (languageJob !== job) return;
      if (reply.http !== 200 || !currentLanguage(job,reply.data)) throw new Error('unavailable');
      if (reply.data.status === 'pending') { scheduleLanguagePoll(job); return; }
      clearTimeout(job.deadlineTimer); job.pending = false; languageResult = reply.data; render(); $('#ia-question-result').focus();
    } catch (_) {
      if (languageJob !== job) return;
      cancelLanguage('Language question unavailable. Use Typed request or guided controls; your work is unchanged.'); render();
    }
  }
  function renderLanguage() {
    const enabled = !!(window.IALanguage && catalog.language && catalog.language.enabled === true && catalog.language.schema_version === 'ia-language/1');
    // Language is optional. When it is not admitted the whole section stays hidden; guided controls are complete.
    $('#ia-question').hidden = !enabled && !languageResult;
    $('#ia-question-form').hidden = !enabled;
    $('#ia-language-off').hidden = enabled;
    $('#ia-question-privacy').textContent = enabled ? 'The answer is a proposed plan you can review. The figures come only from the bundled data when you run it; nothing changes until you choose.' : '';
    if (languageJob && !window.IALanguage.same(languageJob.context, languageContext())) cancelLanguage('The context changed, so the question and its preview were cancelled.');
    $('#ia-question-cancel').hidden = !(languageJob && languageJob.pending);
    const result = languageResult, box = $('#ia-question-result');
    if (!result) { fill(box, []); return; }
    const nodes = [h('p',{text:result.message || (result.status === 'propose' ? 'Proposed interpretation; nothing has been applied or run.' : 'Use the guided controls to continue.')})];
    if (result.status === 'propose') {
      const np = result.normalized_plan;
      if (np && np.district && Array.isArray(np.steps)) {
        nodes.push(h('h4',{text:'Proposed plan · ' + districtLabel(np.district)}),
          h('ol',{class:'ia-proposal-steps'},np.steps.map(st => h('li',{text:(OP_LABEL[st.operation] || humanWords(st.operation)) + ': ' + stepScope(st)}))));
      }
      if (Array.isArray(result.typed_diff) && result.typed_diff.length && (result.intent === 'replace_plan')) nodes.push(h('h4',{text:'What changes from your current plan'}),h('ul',{},result.typed_diff.map(d => h('li',{text:[humanWords(d.change), fieldLabel(d.field || ''), d.step_id ? 'step ' + d.step_id : '', 'from ' + plain(d.before), 'to ' + plain(d.after)].filter(Boolean).join(' · ')}))));
      if (Array.isArray(result.inherited_fields) && result.inherited_fields.length) {
        const context = languageJob && languageJob.context, confirmed = context && context.confirmed_plan;
        nodes.push(h('h4',{text:'Inherited from your confirmed context'}), h('ul',{},result.inherited_fields.map(key => h('li',{text:fieldLabel(key) + ': ' + plain(key === 'focus' ? context.focused_step_id : confirmed && confirmed[key])}))));
      }
      if (result.intent === 'inspect_source') {
        const refs = Array.isArray(result.source_inspection_refs) ? result.source_inspection_refs : [];
        nodes.push(h('p',{text:'Choose a source to inspect. This does not change the plan.'}),...refs.filter(r => r && typeof r.source_id === 'string').map(r => h('button',{type:'button',class:'btn-link source-btn','data-source-id':r.source_id,'data-finding-id':r.finding_id || '',text:'Inspect source: ' + srcLabel(r.source_id)})));
      } else if (result.normalized_plan) {
        nodes.push(btn('Use this proposal in the draft', () => {
          if (!languageJob || !currentLanguage(languageJob, result)) { cancelLanguage('The context changed. Ask again or use guided controls.'); render(); return; }
          const issues = [];
          if (!C.validPlan(result.normalized_plan,'plan',issues) || !(state.runtime.recipe_versions || []).includes(result.normalized_plan.issue_id + '/1')) { cancelLanguage('This proposal is unavailable in the current release. Use guided controls.'); render(); return; }
          state = Object.assign({},state,{draft:JSON.parse(JSON.stringify(result.normalized_plan))});
          cancelLanguage(); notice = 'Proposal placed in the draft. Choose Apply plan to run it and see the findings.'; render();
        },{class:'btn btn-primary'}), ' ', btn('Discard proposal', () => {cancelLanguage();render();}));
      }
    }
    if (result.status === 'clarify' && Array.isArray(result.choices)) {
      nodes.push(h('p',{text:'Choose an applicable control, then ask again if you wish. No question is sent automatically.'}),h('ul',{},result.choices.map(choice => {
        let apply = null;
        if (choice.field === 'district' && choice.value && ['house','senate'].includes(choice.value.chamber) && typeof choice.value.code === 'string') apply = () => editDraft(C.setContext(state.draft,{district:choice.value}));
        else if (choice.field === 'chamber' && ['house','senate'].includes(choice.value) && Number(state.draft.district.code) <= (choice.value === 'senate' ? 25 : 51)) apply = () => editDraft(C.setContext(state.draft,{district:{chamber:choice.value,code:state.draft.district.code}}));
        else if (choice.field === 'control_conflict' && choice.value === 'confirmed') apply = () => {state=Object.assign({},state,{draft:JSON.parse(JSON.stringify(C.active(state).plan))});render();};
        else if (choice.field === 'control_conflict' && choice.value === 'draft') apply = () => render();
        return h('li',{},apply ? btn('Use ' + String(choice.label),() => {cancelLanguage();apply();notice='Choice placed in controls. Ask again or continue with the plan.';render();}) : String(choice.label) + ' — choose this in the guided controls.');
      })));
    }
    fill(box,nodes);
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
    const metrics = (catalog.metrics || []).map((m) => [m.metric_id, m.label]);
    if (s.operation === "profile") {
      const all = h("input", { type: "checkbox", id: id + "-all", checked: a.metric_ids === null, on: { change: (e) => re({ metric_ids: e.target.checked ? null : C.AGING_METRICS.filter((m) => metrics.some((x) => x[0] === m)) }) } });
      return [h("label", { class: "ia-check ia-check-strong", for: id + "-all" }, all, " All 20 measures"),
        a.metric_ids === null ? null : multi(id + "-metrics", "Measures shown", metrics, a.metric_ids, 20, (v) => re({ metric_ids: v }))];
    }
    if (s.operation === "compare") {
      const geos = (catalog.geographies || []).map((g) => [g.geography_id, g.label]).concat((catalog.unavailable_geographies || []).map((g) => [g.geography_id, g.label + " (no statistics in this data)"]));
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
    const keep = document.activeElement && document.activeElement.id;
    // Opened detail panels stay open across re-renders.
    const opened = Array.from(document.querySelectorAll("#ia-workspace details[open]"), (d) => d.id).filter(Boolean);
    const b = C.active(state), res = C.currentResults(state), busy = !!state.pending;
    const dirty = !C.proposeChange(state, { plan: state.draft }).noop;
    $("#ia-status").textContent = busy ? (PENDING_LABEL[state.pending.kind] || "Working…") : notice;
    $("#ia-cancel").hidden = !busy;

    // context bar: the draft controls, then one line naming what the results below describe
    const d = state.draft.district, dsel = $("#ia-district");
    if (!dsel.options.length) fillDistricts(dsel);
    dsel.value = d.chamber + ":" + d.code;
    $("#ia-issue").value = state.draft.issue_id;
    $("#ia-service").value = state.draft.service_area_id || "";
    $("#ia-map-session").value = String(state.draft.map_session);
    const applied = b.plan, draftOther = dirty && (districtLabel(state.draft.district) !== districtLabel(applied.district) || state.draft.issue_id !== applied.issue_id);
    fill($("#ia-context-summary"), [
      h("span", {}, res ? "Showing results for " : "Not run yet: ", h("strong", { text: districtLabel(applied.district) }), " · " + ISSUE_LABEL[applied.issue_id] +
        (applied.service_area_id ? " · program area " + AREA_LABEL[applied.service_area_id] + " (staff choice)" : "") + ". "),
      dirty ? h("span", { class: "badge badge-warn", text: "Draft has unapplied changes" }) : null,
      reviewChip(b),
      draftOther ? h("span", { class: "ia-draft-note" }, " Draft: " + districtLabel(state.draft.district) + " · " + ISSUE_LABEL[state.draft.issue_id] + ". Choose Review and apply these changes to review and run it; nothing from the current results moves to it.") : null,
    ]);

    $("#ia-context-apply").hidden = !dirty || busy;

    renderLanguage();
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
    if (!interp) { fill(box, []); return; }
    const segs = C.interpretationSegments(interp.utterance, interp.matched_fields);
    const nodes = [h("h3", { class: "ia-group-title", text: interp.status === "pending" ? "Reading the request…" : interp.status === "ok" ? "Proposed plan change (not applied)" : interp.status === "clarification" ? "A choice is needed" : "Not supported" }),
      h("p", { class: "ia-utterance" }, segs.map((s) => (s.field ? h("mark", { title: "Matched: " + fieldLabel(s.field), text: s.text }) : s.text)))];
    if (interp.reason) nodes.push(h("p", { text: interp.reason }));
    if (interp.status !== "pending" && interp.status !== "ok") nodes.push(h("p", { class: "hint", text: "Your plan and other work are unchanged. Use the step controls above, or edit the request and read it again." }));
    const list = (title, items) => items.length ? h("div", {}, h("h4", { text: title }), h("ul", { class: "ia-fields" }, items.map((m) => h("li", {}, h("strong", { text: fieldLabel(m.field) + ": " }), valueText(m.field, m.value))))) : null;
    nodes.push(list("Matched in your text", interp.matched_fields), list("Inherited from the current plan", interp.inherited_fields));
    if (interp.choices.length) nodes.push(h("ul", { class: "ia-choices" }, interp.choices.map((c) => {
      const label = String(c.label || plain(c.value));
      const usable = c && c.field === "district" && c.value && (c.value.chamber === "house" || c.value.chamber === "senate") && typeof c.value.code === "string";
      return h("li", {}, usable ? btn("Use " + label, () => { interp = null; editDraft(C.setContext(state.draft, { district: c.value }), label + " placed in the plan. Choose Apply plan to run it."); }) : label);
    })));
    if (interp.proposed_plan) nodes.push(h("div", { class: "btn-row" },
      btn("Put in draft plan", () => { const p = interp.proposed_plan; interp = null; state = Object.assign({}, state, { draft: p }); notice = C.proposeChange(state, { plan: state.draft }).noop ? "Typed request placed in the draft plan. It matches the current plan, and nothing has run." : "Typed request placed in the draft plan. Nothing has run. Review the steps, then choose Apply plan."; render(); $("#ia-apply").focus(); }, { class: "btn btn-primary", id: "ia-apply-interp" }),
      btn("Discard", () => { interp = null; notice = "Typed request discarded. The plan is unchanged."; render(); })));
    fill(box, nodes);
  }

  function renderSteps(dirty, busy) {
    const plan = state.draft, res = C.currentResults(state);
    fill($("#ia-steps"), plan.steps.length ? plan.steps.map((s, i) => h("li", { class: "ia-step", id: "ia-step-" + s.step_id },
      h("div", { class: "ia-step-head" }, h("span", { class: "ia-step-title" }, h("span", { class: "ia-step-num", text: String(i + 1) }), h("strong", { class: "ia-step-name", text: OP_LABEL[s.operation] })),
        h("span", { class: "ia-step-tools" },
          btn("Move up", () => editDraft(C.moveStep(plan, s.step_id, -1), "Step moved. Order does not change any fact."), { class: "btn-link", id: "ia-up-" + s.step_id, disabled: i === 0, "aria-label": "Move step " + (i + 1) + " up" }),
          btn("Move down", () => editDraft(C.moveStep(plan, s.step_id, 1), "Step moved. Order does not change any fact."), { class: "btn-link", id: "ia-down-" + s.step_id, disabled: i === plan.steps.length - 1, "aria-label": "Move step " + (i + 1) + " down" }),
          btn("Remove", () => editDraft(C.removeStep(plan, s.step_id), "Step " + (i + 1) + " removed from the draft. Choose Apply plan to run it."), { class: "btn-link btn-danger", id: "ia-rm-" + s.step_id, "aria-label": "Remove step " + (i + 1) + ", " + OP_LABEL[s.operation] }))),
      h("p", { class: "ia-step-scope" }, stepScope(s), $("#ia-typed").open ? h("span", { class: "ia-step-id", text: " · typed-request name " + s.step_id }) : null),
      h("details", { id: "ia-scope-" + s.step_id }, h("summary", { text: "Change scope" }), stepEditor(s))))
      : [h("li", { class: "muted", text: "No steps. An empty plan has no results or printable brief. Add a step below." })]);
    $("#ia-step-count").textContent = plan.steps.length + " of 8";
    $("#ia-add-btn").disabled = plan.steps.length >= 8;
    $("#ia-add-reason").textContent = plan.steps.length >= 8 ? "A plan holds up to 8 steps. Remove one to add another." : "";
    $("#ia-apply").disabled = busy;
    $("#ia-apply").textContent = dirty ? "Apply plan" : "Run again";
    $("#ia-discard").hidden = !dirty;
    $("#ia-apply-reason").textContent = busy ? "Wait for the current request to finish, or cancel it." :
      !plan.steps.length ? "Add at least one step to get findings." :
      dirty ? (res ? "Runs the edited plan. The current results stay saved until new ones arrive." : "Runs the plan and lists its findings.") :
      "No edits since the last run. Run again repeats the same plan.";
  }

  function renderPreview() {
    const box = $("#ia-preview");
    box.hidden = !preview;
    if (!preview) { fill(box, []); return; }
    const p = preview, kinds = p.kinds.map((k) => CHANGE_LABEL[k] || k).join(", ");
    fill(box, [h("h3", { text: "Review this context change" }),
      h("p", { text: "This changes the " + kinds + ". The current context stays saved exactly as it is (see Save or reopen the case), and a new context opens for the change." }),
      h("ul", {},
        h("li", { text: p.clears_selections ? "Selected findings and the agency action are not carried over. No fact from the earlier context enters the new brief." : plural(p.provisional_selections, "selected finding is", "selected findings are") + " kept only if exactly the same finding appears in the new results." }),
        h("li", { text: p.parked.length ? plural(p.parked.length, "staff note or checklist entry goes", "staff notes or checklist entries go") + " to review. Nothing is copied unless you choose it." : "There are no staff notes or checklist progress to review." }),
        p.kinds.includes("program") || p.kinds.includes("response") ? h("li", { text: "A different agency action never inherits done marks or notes from the earlier one." }) : null),
      p.branch_limit ? h("p", { class: "alert", text: "This case already holds four contexts. Download the case with staff notes, then remove a context under Save or reopen the case before applying." }) : null,
      h("div", { class: "btn-row" },
        btn("Apply change and run", () => { commit(p); }, { class: "btn btn-primary", id: "ia-preview-confirm", disabled: p.branch_limit }),
        btn("Keep current context", () => { preview = null; notice = "No change applied. Your edits remain in the draft plan."; render(); $("#ia-apply").focus(); }, { id: "ia-preview-cancel" }))]);
  }

  // Exact evidence identities select an established replay route; unknown snapshots are not guessed.
  function replayHelp(snapshotId) {
    const r2 = "sha256:143fb7cbdf10a8a3b05a30228e44c347a2cd21d93819a3a3e79094dc847887d3";
    const public33af = "sha256:33af0580ddd697fbe16dedf1b335303cfc9a4e958df5c684f1eade8365dd6aa3";
    if (snapshotId === r2) return h("p", { class: "fine" },
      h("a", { href: "https://haic-r2.millrace.ai/", target: "_blank", rel: "noopener noreferrer", text: "Open the earlier version of this app that matches this case (opens in a new tab)" }),
      ". In that app, choose your saved case file again and review its preview. The link carries no case or staff notes.");
    if (snapshotId === public33af) return h("div", { class: "fine" },
      h("p", {}, h("a", { href: "https://github.com/HAIC-2026/Millrace-AI/blob/e2f2cf031fe7f193de08524a9ce49d5d5f14b5d4/README.md#run-the-bundled-snapshot", target: "_blank", rel: "noopener noreferrer", text: "Open the setup instructions for the matching public release (opens in a new tab)" }),
        ". The linked page names the exact release to run. Follow its setup with a separate working folder, open that local app, and choose your saved case file there."));
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
      nodes.push(h("p", { text: "Nothing was cropped or shrunk. Choose exactly what to leave out, then choose Create one-page brief again. Left-out text stays in the editor and can be included again." }));
      nodes.push(choiceList(C.shorteningChoices(state), "ia-short-", "#ia-error-h"));
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

  const shortGeo = (label) => String(label || "").replace(/ \(boundary session \d{4}\)$/, "").replace(/^House District /, "House ").replace(/^Senate District /, "Senate ");
  function valueWithUnit(display, unit) {
    display = String(display == null ? "" : display); unit = String(unit || "");
    if (unit === "percent") return /%$/.test(display) ? display : display + "%";
    if (/USD/.test(unit) && /^-?[\d,.]+$/.test(display)) return "$" + display + " (" + unit.replace("USD", "dollars") + ")";
    return (display + " " + unit).trim();
  }
  function moeWithUnit(moe, unit) {
    moe = String(moe == null ? "" : moe); unit = String(unit || "");
    if (!/^±/.test(moe)) return moe;
    if (unit === "percent") return moe + " percentage points";
    if (/USD/.test(unit)) return "±$" + moe.slice(1);
    return (moe + " " + unit).trim();
  }
  // Short name used in accessible names and leave-out choices (never an identifier).
  function statLine(c) {
    const m = c.metric || {}, level = typeof c.moe_confidence_level === "number" ? Math.round(c.moe_confidence_level * 100) + "% " : "";
    const moe = /^±/.test(String(c.moe_display || "")) ? " (" + level + "margin of error " + moeWithUnit(c.moe_display, c.unit) + ")" : c.moe_display ? " (margin of error: " + c.moe_display + ")" : "";
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
    const level = typeof c.moe_confidence_level === "number" ? Math.round(c.moe_confidence_level * 100) + "% " : "";
    return valueWithUnit(c.estimate_display, c.unit) + " · " + level + "margin of error " + moeWithUnit(c.moe_display, c.unit);
  }
  function claimRows(c) {
    const m = c.metric || {}, g = c.geography || {}, src = c.source || {};
    const side = (x) => (x && x.geography ? x.geography.label + ": " + x.estimate_display + " (margin of error " + x.moe_display + ")" : null);
    const checks = c.compatibility && c.compatibility.checks ? Object.keys(c.compatibility.checks).filter((k) => c.compatibility.checks[k]).map((k) => humanWords(k).toLowerCase()) : null;
    return [
      ["Recorded statement", c.kind === "statistic" && typeof c.text === "string" ? c.text : null],
      ["Label", c.label],
      ["Measure", m.label], ["Universe", c.universe], ["Unit", c.unit], ["Period", periodText(c.period)],
      ["Area", g.label || null],
      ["Published value and margin", moeText(c)],
      ["Note on the value", c.annotation_meaning || c.annotation || c.moe_annotation],
      ["District", side(c.left)], ["Compared with", side(c.right)],
      ["Point difference", c.kind === "comparison" ? (c.difference ? c.difference.display + " " + c.difference.unit : "Not differenced: " + plain(c.not_differenced_reason)) : null],
      ["Matched for comparison", checks && checks.length ? checks.join(", ") : null],
      ["Method", c.transformation],
      ["ACS table", m.table_id || null], ["Official variable label", m.official_variable_label ? String(m.official_variable_label).replace(/!!/g, " › ") : null],
      ["Agency", c.program && c.program.agency ? hawaiiDisplay(c.program.agency) : null], ["Program jurisdiction", c.program && c.program.jurisdiction ? hawaiiDisplay(c.program.jurisdiction) : null], ["Recorded status", c.status_notes], ["Effective period", c.effective_text],
      ["Reviewed measures", Array.isArray(c.observed_need) ? c.observed_need.map((o) => o.label + ": " + o.estimate_display + " (margin of error " + o.moe_display + "; " + o.universe + "; " + o.period_label + ")" + (o.state_reference ? " — State reference: " + o.state_reference.estimate_display + " (margin of error " + o.state_reference.moe_display + ")" : "")) : null],
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
    return best && (n < limitMax || limitMax <= 1) ? plain(best) : null;
  }
  // Outreach hypothesis shown in labelled parts built from its recorded fields; the complete reviewed
  // statement stays available word for word.
  function outreachBody(c, id) {
    const obs = Array.isArray(c.observed_need) ? c.observed_need : [];
    const line = (o) => o.label + ": " + valueWithUnit(o.estimate_display, o.unit) + " (" + moeWithUnit(o.moe_display, o.unit) + "; " + o.universe + "; " + o.period_label + ")" +
      (o.state_reference ? " — State of Hawaiʻi " + valueWithUnit(o.state_reference.estimate_display, o.unit) + " (" + moeWithUnit(o.state_reference.moe_display, o.unit) + ")" +
        (o.state_reference.difference ? "; point difference " + o.state_reference.difference.display + " " + o.state_reference.difference.unit : "") : "");
    return h("div", { class: "ia-outreach" },
      h("p", { class: "ia-claim-text", id: id + "-text" }, h("strong", { text: (c.label || "Outreach hypothesis") + "." }), " " + ((c.program || {}).name || "") + " · " + shortGeo(c.geography && c.geography.label)),
      obs.length ? h("div", {}, h("h4", { class: "ia-sub", text: "Observed area conditions (survey estimates, not program need)" }), h("ul", {}, obs.map((o) => h("li", { text: line(o) })))) : null,
      c.program_connection && c.program_connection.text ? h("div", {}, h("h4", { class: "ia-sub", text: "Program context" }), h("p", { text: c.program_connection.text })) : null,
      Array.isArray(c.unknowns) && c.unknowns.length ? h("div", {}, h("h4", { class: "ia-sub", text: "Unknowns the agency determines" }), h("ul", {}, c.unknowns.map((u) => h("li", { text: plain(u) })))) : null,
      c.next_step ? h("div", {}, h("h4", { class: "ia-sub", text: "Next step" }), h("p", { text: c.next_step })) : null,
      typeof c.text === "string" ? h("details", { id: id + "-full" }, h("summary", { text: "Complete reviewed statement" }), h("p", { class: "ia-full-text", text: c.text })) : null);
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
      const what = dep && dep.metric ? " — " + (dep.geography && dep.geography.label ? dep.geography.label.replace(/ \(boundary session \d{4}\)$/, "") + ", " : "") + dep.metric.label : "";
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
      sources.length ? h("div", { class: "ia-sources" }, h("span", { class: "ia-sources-label", text: sources.length === 1 ? "Source:" : "Sources:" }),
        sources.map((r) => h("button", { type: "button", class: "btn-link source-btn", "data-source-id": r.source_id, "data-finding-id": typeof r.finding_id === "string" ? r.finding_id : c.claim_ref.finding_id, text: "Inspect " + srcName(r) }))) : null,
      h("details", { id: id + "-more" }, h("summary", {}, "Definition, margin of error and method", h("span", { class: "sr-only", text: " for " + name })),
        h("dl", { class: "kv" }, claimRows(c).filter((r) => c.kind !== "outreach_hypothesis" || !["Reviewed measures", "Program connection", "Not known from this evidence", "Reviewed next step"].includes(r[0])).map((r) => h("div", {}, h("dt", { text: r[0] }), h("dd", { class: r[0] === "Source address" ? "url" : null }, Array.isArray(r[1]) ? h("ul", {}, r[1].map((x) => h("li", { text: plain(x) }))) : r[0] === "Source address" && /^https:\/\//.test(String(r[1])) ? h("a", { href: String(r[1]), target: "_blank", rel: "noopener noreferrer", class: "official-link", text: String(r[1]) }) : plain(r[1]))))),
        Array.isArray(c.dependencies) && c.dependencies.length ? h("div", {}, h("h4", { class: "ia-sub", text: c.kind === "outreach_hypothesis" ? "Complete reviewed basis (shown in full whatever the profile displays)" : "Depends on" }),
          h("ul", {}, c.dependencies.map((r) => h("li", { text: claimFull(r) })))) : null,
        limits.length ? h("div", {}, h("h4", { class: "ia-sub", text: "All limits of this finding" }), h("ul", {}, limits.map((l) => h("li", { text: plain(l) })))) : null));
  }

  function renderEvidence(res, dirty) {
    const box = $("#ia-evidence");
    if (!res) { fill(box, [h("p", { class: "muted", text: state.pending ? "Running the plan…" : "No findings yet. Choose Apply plan to run the plan for this district." })]); return; }
    const claims = claimMap(res), selected = new Set(C.active(state).selected_claim_refs.map(C.refKey));
    limitFreq = new Map();
    res.claims.forEach((c) => (Array.isArray(c.limitations) ? c.limitations : []).forEach((l) => limitFreq.set(l, (limitFreq.get(l) || 0) + 1)));
    limitMax = Math.max(0, ...limitFreq.values());
    const rec = recommendedBrief(res), key = rec.claims[0];
    const start = key ? h("div", { class: "ia-start", id: "ia-start" }, h("h3", { class: "ia-group-title", text: "Start here" }),
      h("p", { text: findingText(key) }),
      rec.claims.length > 1 || rec.card ? h("p", { class: "hint", text: "The recommended brief adds " + rec.claims.slice(1).map(claimShortName).concat(rec.card ? ["the agency verification step for " + programLabel(rec.card.program_id) + ", which prints the program's recorded referral, open questions and sources"] : []).join("; ") + ". Use recommended brief in the Brief panel, or select findings below; the program reference and every other finding stay available." }) : null) : null;
    const nodes = [start, h("p", { class: "hint", text: "Findings for " + districtLabel(res.plan.district) + " from the last applied plan." + (dirty ? " The draft has unapplied edits; these findings do not include them yet." : "") + " Select findings for the brief: up to 8 can be selected; one-page fit is measured when you create the brief." })];
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
              if (st) editDraft(C.rescopeStep(state.draft, s.step_id, { metric_ids: st.args.metric_ids, comparison_geography: g }), "Comparison geography changed in the draft. Choose Apply plan to run it.");
            }, { id: "ia-next-" + s.step_id + "-" + j + "-" + k })))
              : h("p", { class: "hint", text: plain(a && (a.label || a)) });
          })) : null,
        refs.length || s.status !== "ok" ? h("ul", { class: "ia-claims" }, refs.map((r) => claims.get(C.refKey(r))).filter(Boolean).map((c) => claimNode(c, selected, "ia-c-" + s.step_id + "-")))
          : h("p", { class: "muted", text: "This step ran and found nothing to report for this district." })));
    });
    if (res.limitations.length) nodes.push(h("details", { class: "limitations", id: "ia-res-limits" }, h("summary", { text: "Limits that apply to all of these results (" + res.limitations.length + ")" }), h("ul", {}, res.limitations.map((l) => h("li", { text: plain(l) })))));
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
      const r = C.chooseAction(state, ref);
      if (r.error) return alertUser(r.error.message);
      if (r.proposal.noop) return;
      if (r.proposal.fork) { preview = r.proposal; render(); $("#ia-preview").focus(); } else commitAction(r.proposal);
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
    el.addEventListener("change", () => onCommit(el.value));
    return h("div", { class: "field" }, h("div", { class: "field-head" }, h("label", { for: id, text: label }), h("span", { class: "limit", id: id + "-max", text: "up to " + max + " characters" })), el);
  }

  // Why the brief cannot be created yet, in the order staff can fix it. Null when it can.
  function briefBlock(b, res, busy, dirty, staff, reviewed, parked) {
    if (busy) return "Wait for the current request to finish, or cancel it.";
    if (!res) return "Run the plan first: choose Apply plan.";
    if (dirty) return "Apply or discard the plan edits first; the brief uses applied results only.";
    if (!b.selected_claim_refs.length) return "Select at least one finding under Findings and evidence.";
    if (state.last_error && state.last_error.code === "brief_overflow") return "Too long for one page: choose what to leave out under Findings and evidence, then create the brief again.";
    if (!staff.empty && !reviewed) return parked.length ? "Copy or leave each item in “Staff notes waiting for review” first, then mark staff notes reviewed." : "Check the staff notes and checklist below, then choose Mark staff notes reviewed.";
    return null;
  }

  function recommendedBrief(res) { return C.recommendedBrief(res); }
  function useRecommended() {
    const res = C.currentResults(state), rec = recommendedBrief(res);
    if (!rec.claims.length) return;
    const want = new Set(rec.claims.map((c) => C.refKey(c.claim_ref)));
    let next = state;
    for (const r of C.active(next).selected_claim_refs.slice()) if (!want.has(C.refKey(r))) { const o = C.toggleClaim(next, r, false); if (o.error) return alertUser(o.error.message); next = o.state; }
    for (const c of rec.claims) { const o = C.toggleClaim(next, c.claim_ref, true); if (o.error) return alertUser(o.error.message); next = o.state; }
    state = next;
    const b = C.active(state);
    if (rec.action && !(b.selected_action_ref && C.actionKey(b.selected_action_ref) === C.actionKey(rec.action))) {
      const r = C.chooseAction(state, rec.action);
      if (r.error) return alertUser(r.error.message);
      if (r.proposal.fork) { preview = r.proposal; notice = "Recommended findings selected. Review the agency action change below."; render(); $("#ia-preview").focus(); return; }
      if (!r.proposal.noop) { const c = C.confirmChange(state, r.proposal, ids); if (c.error) return alertUser(c.error.message); state = c.state; if (c.forked) { notice = "Recommended findings and agency action selected."; runActive(); return; } }
    }
    notice = "Recommended findings" + (rec.action ? " and agency action" : "") + " selected. Add a short summary if you wish, then choose Create one-page brief.";
    render();
  }

  function renderTray(b, res, busy, dirty) {
    const claims = claimMap(res), ex = new Set(state.exclusions[b.branch_id] || []);
    const notes = (b.staff_edits.finding_notes || {});
    const nSel = b.selected_claim_refs.length;
    $("#ia-tray-count").textContent = nSel ? plural(nSel, "finding", "findings") + " selected" + (b.selected_action_ref ? " · agency action chosen." : " · no agency action.") : "No findings selected yet.";
    $("#ia-tray-capacity").textContent = "With an agency action, one printed page usually has room for one comparison or about two short measure findings, plus a short title, summary and next step. The recommended brief is sized for that. Program reference tiles, extra findings and longer notes may not fit; the fit is measured when you create the brief.";
    const rec = res && !busy && !dirty ? recommendedBrief(res) : { claims: [] };
    const recOn = rec.claims.length && rec.claims.every((c) => b.selected_claim_refs.some((r) => C.refKey(r) === C.refKey(c.claim_ref))) && rec.claims.length === nSel && (!rec.action || (b.selected_action_ref && C.actionKey(b.selected_action_ref) === C.actionKey(rec.action)));
    $("#ia-recommend").hidden = !rec.claims.length;
    $("#ia-recommend-btn").disabled = !!recOn;
    $("#ia-recommend-btn").className = nSel ? "btn" : "btn btn-primary";
    $("#ia-recommend-btn").textContent = recOn ? "Recommended brief selected" : "Use recommended brief";
    $("#ia-recommend-what").textContent = rec.claims.length ? "Selects " + rec.claims.map((c) => (KIND_LABEL[c.kind] || humanWords(c.kind)).toLowerCase() + ": " + claimShortName(c)).join("; ") + (rec.card ? "; agency action: verify " + programLabel(rec.card.program_id) + " with the agency" : "") + (nSel && !recOn ? ". Replaces the current selection." : ".") : "";
    fill($("#ia-selected"), nSel ? b.selected_claim_refs.map((r, i) => {
      const c = claims.get(C.refKey(r)), sid = "ia-sel-" + r.semantic_hash.slice(7, 19);
      return h("li", { id: sid }, h("span", { class: "tray-label", text: findingText(c) }),
        h("span", { class: "ia-step-tools" },
          btn("Move up", () => set(C.moveSelection(state, r, -1)), { class: "btn-link", id: sid + "-up", disabled: i === 0, "aria-label": "Move finding " + (i + 1) + " up" }),
          btn("Move down", () => set(C.moveSelection(state, r, 1)), { class: "btn-link", id: sid + "-down", disabled: i === b.selected_claim_refs.length - 1, "aria-label": "Move finding " + (i + 1) + " down" }),
          btn("Remove", () => set(C.toggleClaim(state, r, false), "Finding removed from the brief selection."), { class: "btn-link btn-danger", id: sid + "-rm", "aria-label": "Remove finding " + (i + 1) + " from brief" })),
        textField(sid + "-note", "Staff note on: " + claimShortName(c), notes[r.semantic_hash], 160, (v) => set(C.setFindingNote(state, r.semantic_hash, v))));
    }) : [h("li", { class: "muted", text: "Use “Select for brief” on a finding." })]);
    const retired = state.retired[b.branch_id] || [];
    fill($("#ia-retired"), retired.length ? [h("p", { class: "hint", text: plural(retired.length, "saved selection was", "saved selections were") + " not reselected:" }), h("ul", { class: "hint" }, retired.map((r) => h("li", { text: r.claim_ref ? savedFindingName(r.claim_ref) + ": " + droppedReason(r, res) : "The agency action chosen earlier: it is not offered for this plan, so it was not reselected." })))] : []);

    // agency checklist
    const card = res && b.selected_action_ref ? res.responses.find((c) => c.action_ref && C.actionKey(c.action_ref) === C.actionKey(b.selected_action_ref)) : null;
    const edits = new Map(b.checklist_edits.map((c) => [c.item_id, c]));
    const item = (idKey, templateText) => {
      const e = edits.get(idKey) || {}, pid = "ia-chk-" + idKey;
      return h("li", Object.assign({ class: "ia-check-item", role: "group" }, templateText ? { "aria-labelledby": pid + "-what" } : { "aria-label": "Checklist item: " + (e.text || checkLabel(idKey)) }),
        templateText ? h("p", { class: "ia-template", id: pid + "-what", text: templateText }) : null,
        textField(pid + "-text", templateText ? "Staff wording (optional)" : idKey.startsWith("custom") ? "Custom item" : "Staff entry: " + checkLabel(idKey).toLowerCase(), e.text, 120, (v) => set(C.setChecklist(state, idKey, { text: v }))),
        h("div", { class: "ia-inline" },
          textField(pid + "-owner", "Staff role", e.owner_role, 80, (v) => set(C.setChecklist(state, idKey, { owner_role: v }))),
          h("div", { class: "field" }, h("label", { for: pid + "-due", text: "Date" }), h("input", { type: "date", id: pid + "-due", value: e.due_date || "", on: { change: (ev) => set(C.setChecklist(state, idKey, { due_date: ev.target.value || null })) } }))),
        h("label", { class: "ia-check", for: pid + "-done" }, h("input", { type: "checkbox", id: pid + "-done", checked: e.completed === true, on: { change: (ev) => set(C.setChecklist(state, idKey, { completed: ev.target.checked })) } }), " Staff marked done (not a verified fact)"),
        ex.has("checklist:" + idKey) ? h("p", { class: "hint" }, "Left out of the next brief. ", btn("Include again", () => set(C.setExclusion(state, "checklist:" + idKey, false)), { class: "btn-link", id: pid + "-incl" })) : null);
    };
    const check = $("#ia-checklist");
    const templates = card && Array.isArray(card.template_checklist) ? card.template_checklist.filter((t) => t && C.TEMPLATE_CHECK_IDS.includes(t.item_id)) : [];
    const shown = new Set(templates.map((t) => t.item_id));
    // Staff entries stay visible and editable even with no agency step selected.
    const loose = C.CHECK_IDS.filter((k) => edits.has(k) && !shown.has(k)), free = C.CHECK_IDS.slice(3).find((k) => !edits.has(k));
    const add = h("input", { type: "text", id: "ia-chk-new", maxlength: 120, "aria-describedby": "ia-chk-new-max" });
    fill(check, [card ? h("p", {}, h("strong", { text: programLabel(card.program_id) }), " — office checklist for this agency action") : h("p", { class: "muted", text: "No agency action selected, so no template checklist applies. You can still add custom items and office tracking as staff contributions." }),
      templates.length || loose.length ? h("ol", { class: "ia-checklist" }, templates.map((t) => item(t.item_id, String(t.text || ""))), loose.map((k) => item(k, ""))) : null,
      free ? h("div", { class: "field ia-add-item" }, h("div", { class: "field-head" }, h("label", { for: "ia-chk-new", text: "Add a custom checklist item" }), h("span", { class: "limit", id: "ia-chk-new-max", text: "up to 3 items · 120 characters" })), h("div", { class: "ia-inline-row" }, add, btn("Add item", () => { if (add.value.trim()) set(C.setChecklist(state, free, { text: add.value.trim() }), "Custom item added as a staff contribution."); }, { id: "ia-chk-add" }))) : null]);

    // staff notes and tracking
    const t = b.tracking || { label: "", baseline: null, as_of: null };
    const track = (patch) => { const n = Object.assign({}, t, patch); set(C.setTracking(state, !n.label && n.baseline === null && !n.as_of ? null : n)); };
    const excl = (key) => (ex.has(key) ? h("p", { class: "hint" }, "Left out of the next brief. ", btn("Include again", () => set(C.setExclusion(state, key, false)), { class: "btn-link", id: "ia-incl-" + key })) : null);
    const food = b.plan.issue_id === "food_assistance_outreach";
    fill($("#ia-staff"), [
      textField("ia-title", "Brief title", b.staff_edits.title, 90, (v) => set(C.setStaffText(state, "title", v))), excl("title"),
      textField("ia-note", "Summary", b.staff_edits.note, 400, (v) => set(C.setStaffText(state, "note", v)), true), excl("note"),
      textField("ia-next", "Next steps", b.staff_edits.next_steps, 300, (v) => set(C.setStaffText(state, "next_steps", v)), true), excl("next_steps"),
      h("details", { id: "ia-tracking", class: "ia-tracking", open: !!b.tracking }, h("summary", { text: "Office tracking (optional)" + (b.tracking ? " · recorded" : "") }),
        h("p", { class: "hint", text: food ? "Optional office count of requests for SNAP information from the date tracking begins. Baseline: " + (t.baseline === null ? "not recorded" : t.baseline) + ". This is not a count of eligible or unserved residents, participation, a population rate or program impact. Do not enter resident details." : "A staff record such as “agency/partner referral sessions arranged”. Baseline: " + (t.baseline === null ? "not supplied" : t.baseline + (t.as_of ? " as of " + t.as_of : "")) + ". Never a verified dataset baseline. Do not enter resident details." }),
        food && !b.tracking ? btn("Use SNAP information-request tracking", () => set(C.setTracking(state, {label:"Office requests for SNAP information",baseline:null,as_of:null}), "Tracking added as a staff contribution; baseline is not recorded.")) : null,
        textField("ia-track-label", "Measure label", t.label, 80, (v) => track({ label: v })),
        h("div", { class: "ia-inline" },
          h("div", { class: "field" }, h("label", { for: "ia-track-base", text: "Office baseline" }), h("input", { type: "number", id: "ia-track-base", min: 0, max: 1000000000, step: 1, value: t.baseline === null ? "" : String(t.baseline), on: { change: (e) => track({ baseline: e.target.value === "" ? null : Number(e.target.value) }) } })),
          h("div", { class: "field" }, h("label", { for: "ia-track-date", text: food ? "Review date" : "As of" }), h("input", { type: "date", id: "ia-track-date", value: t.as_of || "", on: { change: (e) => track({ as_of: e.target.value || null }) } }))), excl("tracking")),
    ]);

    // parked staff work
    const parked = C.pendingReview(state), box = state.parked[b.branch_id];
    const sameAction = box && box.origin_action_ref && C.actionKey(box.origin_action_ref) === C.actionKey(b.selected_action_ref);
    fill($("#ia-review"), parked.length ? [h("h3", { class: "ia-group-title", text: "Staff notes waiting for review (" + parked.length + ")" }),
      h("p", { class: "hint", text: "These entries were written for an earlier context" + (box.kinds.length ? " (changed: " + box.kinds.map((k) => CHANGE_LABEL[k] || k).join(", ") + ")" : "") + ". They are left out of this brief and stay in their original context unless you copy them. Copies remain labeled staff contributions." }),
      h("ul", { class: "ia-parked" }, parked.map((p, i) => {
        const done = p.kind === "checklist" && p.item.completed && sameAction ? h("input", { type: "checkbox", id: "ia-park-done-" + i }) : null;
        return h("li", {}, h("p", {}, staffLine(p, " (done in the earlier context)")),
          p.kind === "checklist" && p.item.completed && !sameAction ? h("p", { class: "hint", text: "The done mark belongs to a different agency action and is not copied." }) : null,
          done ? h("label", { class: "ia-check", for: "ia-park-done-" + i }, done, " Also copy the done mark (same agency action)") : null,
          h("div", { class: "btn-row" },
            btn("Copy into this context", () => set(C.copyParked(state, p.key, { include_completion: !!(done && done.checked) }), "Copied as a staff contribution. Review staff notes before creating the brief."), { id: "ia-park-copy-" + i }),
            btn("Leave in original context", () => set(C.leaveParked(state, p.key), "Left in its original context."), { id: "ia-park-leave-" + i })));
      }))] : []);

    // brief controls: one primary action with its blocking reason beside it
    const staff = C.activeStaff(state), reviewed = C.reviewCurrent(state), block = briefBlock(b, res, busy, dirty, staff, reviewed, parked);
    $("#ia-review-state").textContent = staff.empty ? "No staff notes will be sent with this brief." : reviewed ? "Staff notes reviewed for this context and plan. They are sent only when you create the brief and are not stored by the app." : "";
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
      choiceList(C.shorteningChoices(state), "ia-fit-", "#ia-fit-h")]);
  }

  // Whether the current brief passed the one-page check (used by printing).
  function briefFits() { return briefFit.ok; }

  // Name a staff group in the reopen preview by its own context in the parsed file (joined by branch id).
  function importContextName(branchId) {
    const branches = importing && importing.incoming && importing.incoming.case ? importing.incoming.case.branches : [];
    const i = branches.findIndex((br) => br.branch_id === branchId);
    if (i < 0) return "Context";
    const p = branches[i].plan;
    return "Context " + (i + 1) + ": " + planLabel(p);
  }

  function renderCase(b, busy) {
    const list = $("#ia-branches");
    const savedNow = savedDigest === C.canonical(C.exportCase(state, { include_staff_work: true }));
    fill(list, state.case.branches.map((br, i) => {
      const on = br.branch_id === b.branch_id, n = C.staffItems(br).length;
      return h("li", { class: on ? "is-selected" : "" },
        h("div", { class: "ia-branch-text" },
          h("strong", { text: "Context " + (i + 1) + ": " + planLabel(br.plan) }),
          on ? h("span", { class: "badge badge-info", text: "Current" }) : null,
          br.review_state === "replay_blocked" ? h("span", { class: "badge badge-warn", text: "Replay blocked" }) : null,
          h("span", { class: "hint", text: br.plan.steps.length + " steps · " + br.selected_claim_refs.length + " selected · " + n + " staff entr" + (n === 1 ? "y" : "ies") })),
        br.snapshot_id !== state.runtime.snapshot_id ? replayHelp(br.snapshot_id) : null,
        on ? null : h("div", { class: "ia-branch-tools" },
          btn("Restore", () => restoreContext(br.branch_id), { class: "btn btn-small", id: "ia-restore-" + i, disabled: busy, "aria-label": "Restore context " + (i + 1) + " (" + planLabel(br.plan) + ") by replaying its evidence" }),
          btn("Remove context", () => set(C.removeBranch(state, br.branch_id, { saved_locally: savedNow }), "Context removed after a full local download."), { class: "btn-link btn-danger", id: "ia-rmbranch-" + i, disabled: busy, "aria-label": "Remove context " + (i + 1) + " (" + planLabel(br.plan) + ") from this page", "aria-describedby": "ia-rmbranch-why-" + i }),
          h("span", { class: "hint", id: "ia-rmbranch-why-" + i, text: savedNow ? "Saved in your last download with staff notes." : "Removing needs a download with staff notes first." })));
    }));
    const staffOn = $("#ia-download-staff").checked, pv = $("#ia-staff-preview");
    pv.hidden = !staffOn;
    if (staffOn) {
      const rows = C.staffExportPreview(state);
      fill(pv, [h("p", { class: "alert", text: "This file will contain the staff notes below as plain text. It is not encrypted. Anyone who can open the file can read it." }),
        rows.length ? h("ul", { class: "ia-staff-list" }, rows.map((r) => h("li", {}, h("strong", { text: contextName(r.branch_id) }), h("ul", {}, r.items.map((it) => h("li", {}, staffLine(it))))))) : h("p", { text: "There is no staff notes, checklist entry or tracking record in this case." })]);
    } else fill(pv, []);
    const ip = $("#ia-import-preview");
    ip.hidden = !importing;
    if (!importing) { fill(ip, []); return; }
    if (!importing.ok) { fill(ip, [h("h3", { text: "The file was not opened" }), h("ul", {}, importing.issues.map((i) => h("li", { text: i.code === "invalid_json" ? "This is not a case file this app can read (it could not be parsed). It was not opened." : i.message }))), h("p", { text: "Your current case is unchanged." }), btn("Close", () => { importing = null; render(); $("#ia-import-file").focus(); }, { id: "ia-import-close" })]); return; }
    const p = importing.preview, accept = h("input", { type: "checkbox", id: "ia-import-staff" });
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
      h("div", { class: "btn-row" },
        p.runtime_match ? btn("Replay and open this case", () => { const r = C.beginImport(state, importing, { accept_staff_work: accept.checked }, ids); if (r.error) return alertUser(r.error.message); state = r.state; notice = "Replaying the file's active plan. Only the plan and references are sent, never the file."; send(r.request); holdFocus(); }, { class: "btn btn-primary", id: "ia-import-go", disabled: busy }) : null,
        btn(p.runtime_match ? "Cancel" : "Close", () => { importing = null; notice = "Import cancelled. Your current case is unchanged."; render(); $("#ia-import-file").focus(); }, { id: "ia-import-cancel" }))]);
  }

  // ------------------------------------------------------------------ map
  function syncMap(force) {
    const p = C.active(state).plan, key = [state.runtime.snapshot_id, p.district.chamber, p.district.code, p.map_session].join("|");
    if (key === mapKey && !force) return;
    if (key === mapKey) return;
    mapKey = key;
    const box = $("#ia-map");
    if (!mapHandle && window.IA1Map && typeof window.IA1Map.mount === "function") mapHandle = window.IA1Map.mount(box, { onSummary: (t) => { $("#ia-map-summary").textContent = t; } });
    if (!mapHandle) { fill(box, [h("p", { class: "alert", text: "The boundary map cannot be shown. The district description below and all other evidence remain available." })]); $("#ia-map-summary").textContent = "unavailable"; return; }
    // The viewer replaces its own content and ignores late geometry for an earlier identity.
    mapHandle.update({ snapshot_id: state.runtime.snapshot_id, chamber: p.district.chamber, code: p.district.code, session: p.map_session });
  }
  function syncMapText(b) {
    const d = b.plan.district;
    fill($("#ia-map-text"), [h("div", {}, h("dt", { text: "District" }), h("dd", { text: districtLabel(d) + ", Hawaiʻi" })),
      h("div", {}, h("dt", { text: "Statistics boundary" }), h("dd", { text: "2024 session" })),
      h("div", {}, h("dt", { text: "Map boundary shown" }), h("dd", { text: b.plan.map_session + " session" })),
      h("div", {}, h("dt", { text: "Area for program questions" }), h("dd", { text: b.plan.service_area_id ? AREA_LABEL[b.plan.service_area_id] + " (staff choice, not a geographic finding)" : "None chosen" }))]);
  }

  // ------------------------------------------------------------------ wiring
  function wire() {
    const ctx = (patch) => editDraft(C.setContext(state.draft, patch), "Context edited. Choose Review and apply these changes to review and run it.");
    $("#ia-district").addEventListener("change", (e) => { const v = String(e.target.value).split(":"); if (v.length === 2) ctx({ district: { chamber: v[0], code: v[1] } }); });
    $("#ia-issue").addEventListener("change", (e) => ctx({ issue_id: e.target.value }));
    $("#ia-service").addEventListener("change", (e) => ctx({ service_area_id: e.target.value || null }));
    $("#ia-map-session").addEventListener("change", (e) => ctx({ map_session: Number(e.target.value) }));
    $("#ia-question-form").addEventListener("submit", (e) => { e.preventDefault(); askLanguage($("#ia-question-text").value); });
    $("#ia-question-cancel").addEventListener("click", () => { cancelLanguage('Question cancelled. Your work is unchanged.'); render(); });
    $("#ia-question-text").addEventListener("input", () => { if (languageJob) { cancelLanguage('Question changed. Ask again when ready.'); render(); } });
    $("#ia-ask").addEventListener("submit", (e) => {
      e.preventDefault();
      const text = $("#ia-utterance").value;
      const r = C.beginInterpret(state, text, ids);
      if (r.error) return alertUser(r.error.message);
      state = r.state; interp = { utterance: text, matched_fields: [], inherited_fields: [], choices: [], reason: null, status: "pending" }; notice = "Reading your typed request. Nothing runs until you apply it.";
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
    $("#ia-discard").addEventListener("click", () => { state = Object.assign({}, state, { draft: JSON.parse(JSON.stringify(C.active(state).plan)) }); preview = null; notice = "Draft edits discarded. The plan matches the last applied context."; render(); });
    $("#ia-cancel").addEventListener("click", () => { state = C.cancelPending(state); notice = "Request cancelled. Any late reply will be ignored. Earlier results are unchanged."; render(); });
    $("#ia-review-btn").addEventListener("click", () => {
      if (!set(C.markReviewed(state), "Staff notes marked as reviewed for this context.")) return;
      const b = $("#ia-brief-btn");
      if (b && !b.disabled) b.focus(); else $("#ia-brief-reason").focus();
    });
    $("#ia-brief-btn").addEventListener("click", () => createBrief(false));
    $("#ia-recommend-btn").addEventListener("click", () => useRecommended());
    $("#ia-clean-brief-btn").addEventListener("click", () => createBrief(true));
    $("#ia-print-btn").addEventListener("click", () => { if (C.printStatus(state).ok && briefFits()) window.print(); });
    $("#ia-download-staff").addEventListener("change", render);
    $("#ia-download").addEventListener("click", () => {
      const staff = $("#ia-download-staff").checked, data = C.exportCase(state, { include_staff_work: staff });
      const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 1)], { type: "application/json" }));
      const a = h("a", { href: url, download: "haic-case-" + districtLabel(C.active(state).plan.district).toLowerCase().replace(" ", "-") + (staff ? "-with-staff-work" : "") + ".json" });
      document.body.append(a); a.click(); a.remove(); URL.revokeObjectURL(url);
      if (staff) savedDigest = C.canonical(data);
      // The page cannot see whether the browser saved the file, so it does not claim that it did.
      notice = (staff ? "Download requested with staff notes as plain, unencrypted text." : "Download requested: plan and references only. No typed request, title, notes, roles, dates, tracking or done marks.") + " Check your browser's downloads to confirm the file was saved.";
      render();
    });
    $("#ia-import-file").addEventListener("change", async (e) => {
      const file = e.target.files && e.target.files[0];
      e.target.value = "";
      if (!file) return;
      if (file.size > C.LIMITS.case_bytes) importing = { ok: false, issues: [{ path: "", code: "too_large", message: "The file is larger than a case file can be (256 KB). It was not read." }] };
      else { let text = ""; try { text = await file.text(); } catch (err) { text = ""; } importing = C.parseCaseFile(text, state.runtime); }
      render(); $("#ia-import-preview").focus();
    });
    // Only the reviewed investigation brief prints while this view is open.
    window.addEventListener("beforeprint", () => {
      if ($("#tab-investigation").hidden) return;
      const root = $("#print-root"), doc = $("#ia-brief-out .brief-doc") || $("#ia-brief-out").firstElementChild, st = C.printStatus(state);
      fill(root, st.ok && briefFits() && doc ? [doc.cloneNode(true)] : [h("p", { text: "No verified one-page brief is ready to print. " + (st.ok ? "It is longer than one page; choose what to leave out in the app." : st.message) })]);
    });
  }

  function createBrief(clean) {
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
    try { const r = await fetch("/api/catalog", { credentials: "same-origin" }); cat = await r.json(); } catch (e) { return unavailable("The server did not respond. Nothing was lost; try again."); }
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
    render(); syncMap(false);
    bootRun = true;
    runActive();
  }

  document.addEventListener("DOMContentLoaded", start);
})();
