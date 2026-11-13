/* Shared A/B browser client. It only collects controls, calls the local API and
   inserts server-rendered HTML. It computes no factual values. */
(function () {
  "use strict";

  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));
  const SESSION_ID = "s" + crypto.randomUUID().replaceAll("-", "");
  const MAX_BRIEF = 8;
  let SNAPSHOT = null;
  let catalog = null;
  let cRuntime = null, cMetadata = null, activeRun = null;
  let seq = 0;
  let resultReference = null;
  let displayed = null;            // client-carried display snapshot after the last successful result
  let edits = {};                  // staff edits for the brief (labeled; never facts)
  const selection = new Map();     // finding_id -> label (insertion order kept)

  // ------------------------------------------------------------ helpers
  async function api(method, url, body, headers) {
    const opts = { method, headers: Object.assign({}, headers || {}) };
    if (body !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
    let resp;
    try {
      resp = await fetch(url, opts);
    } catch (err) {
      return { status: "error", reason: "The server did not respond. Please try again.",
               html: '<section class="notice notice-error" role="alert"><h3>Error</h3><p>The server did not respond. Please try again.</p></section>' };
    }
    try {
      return await resp.json();
    } catch (err) {
      return { status: "error", reason: "Unreadable server response (" + resp.status + ")." };
    }
  }

  function logEvent(kind, extra) {
    api("POST", "/api/event", Object.assign({ kind, session_id: SESSION_ID }, extra || {}));
  }

  function text(el, value) { el.textContent = value; }

  function option(value, label, disabled) {
    const o = document.createElement("option");
    o.value = value; o.textContent = label; if (disabled) o.disabled = true;
    return o;
  }

  // ------------------------------------------------------------ controls
  function buildControls() {
    const tasks = $("#task-options");
    catalog.templates.forEach((t, i) => {
      const id = "task-" + t.task;
      const lab = document.createElement("label");
      lab.className = "task-option";
      lab.innerHTML = '<input type="radio" name="task"> <span></span>';
      const input = lab.querySelector("input");
      input.value = t.task; input.id = id; if (i === 0) input.checked = true;
      lab.querySelector("span").textContent = t.label;
      tasks.appendChild(lab);
    });
    const metric = $("#ctl-metric");
    const groups = {};
    catalog.metrics.forEach((m) => {
      if (!groups[m.group]) {
        groups[m.group] = document.createElement("optgroup");
        groups[m.group].label = m.group;
        metric.appendChild(groups[m.group]);
      }
      groups[m.group].appendChild(option(m.metric_id, m.label));
      $("#ctl-profile-metrics").appendChild(option(m.metric_id, m.label));
    });
    const geo = $("#ctl-geo");
    catalog.geographies.forEach((g) => geo.appendChild(option(g.geography_id, g.label)));
    catalog.unavailable_geographies.forEach((g) => geo.appendChild(option(g.geography_id, g.label + " (not normalized)")));
    const prog = $("#ctl-program");
    catalog.programs.forEach((p) => prog.appendChild(option(p.program_id, p.name)));
    (catalog.administrative_rows || catalog.participation || []).forEach((r) => {
      const geography = typeof r.geography === "object" ? (r.geography.label || r.geography.name) : r.geography;
      const label = [r.series_label || r.label || r.program_id, geography, r.period, r.unit, r.status || r.publication_status || r.revision_status, r.observation_id].filter(Boolean).join(" · ");
      const rowOption = option(r.observation_id, label);
      rowOption.title = label;
      $("#ctl-admin").appendChild(rowOption);
    });
    $("#ctl-admin").addEventListener("change", administrativeSelectionNote);
    $("#ctl-profile-mode").addEventListener("change", relevantFieldsets);
    $("#ctl-chamber").addEventListener("change", fillDistricts);
    $("#ctl-session").addEventListener("change", fillDistricts);
    $("#ctl-code").addEventListener("change", districtNote);
    $("#ctl-utterance").addEventListener("input", () => {
      if ($("#ctl-utterance").value.trim()) $('input[name="mode"][value="language"]').checked = true;
    });
    $$('input[name="task"]').forEach((r) => r.addEventListener("change", relevantFieldsets));
    relevantFieldsets();
  }

  function administrativeSelectionNote() {
    const chosen = Array.from($("#ctl-admin").selectedOptions);
    text($("#admin-count"), chosen.length + " of 8 rows selected." + (chosen.length > 8 ? " Choose at most 8 before running." : ""));
    const details = $("#admin-details");
    details.innerHTML = "";
    chosen.forEach((o) => {
      const li = document.createElement("li"); li.textContent = o.textContent; details.appendChild(li);
    });
  }

  function fillDistricts() {
    const chamber = $("#ctl-chamber").value;
    const session = Number($("#ctl-session").value);
    const sel = $("#ctl-code");
    const keep = sel.value;
    sel.innerHTML = "";
    if (!chamber) {
      sel.appendChild(option("", "Choose chamber first…"));
    } else {
      sel.appendChild(option("", "Choose district…"));
      catalog.districts.filter((d) => d.chamber === chamber && d.boundary_session === session).forEach((d) => {
        const stats = d.has_statistics || (session !== 2024 && catalog.districts.some((x) =>
          x.chamber === d.chamber && x.code === d.code && x.boundary_session === 2024 && x.has_statistics));
        sel.appendChild(option(d.code, d.code + " — " + d.name + (stats ? " · statistics available" : " · no normalized statistics")));
      });
      if (keep && $$("option", sel).some((o) => o.value === keep)) sel.value = keep;
    }
    districtNote();
  }

  function districtNote() {
    const chamber = $("#ctl-chamber").value, code = $("#ctl-code").value, session = Number($("#ctl-session").value);
    const note = $("#district-note");
    if (currentTask() === "administrative_context") {
      text(note, "No district is required for administrative evidence. Any district choice is retained as brief context only.");
      return;
    }
    if (!chamber || !code) { text(note, "Chamber and district are both required; a GEOID alone is ambiguous."); return; }
    const d = catalog.districts.find((x) => x.chamber === chamber && x.code === code && x.boundary_session === session);
    const has = catalog.districts.some((x) => x.chamber === chamber && x.code === code && x.boundary_session === 2024 && x.has_statistics);
    let msg = (d ? d.name + " · GEOID " + d.geoid + " · service coverage requires agency confirmation" : "") + ". ";
    msg += has ? "Normalized statistics are available (2024 session)." : "No normalized statistics for this district in the fixture.";
    if (session !== 2024) msg += " Statistics are tabulated on the 2024 session; Run will ask before using them.";
    text(note, msg);
  }

  function currentTask() {
    const r = $('input[name="task"]:checked');
    return r ? r.value : null;
  }

  function relevantFieldsets() {
    const t = currentTask();
    districtNote();
    $("#fs-profile").classList.toggle("dim", t !== "profile");
    $("#ctl-profile-metrics").disabled = $("#ctl-profile-mode").value !== "selected";
    $("#fs-admin").classList.toggle("dim", t !== "administrative_context");
    $("#fs-measure").classList.toggle("dim", !(t === "compare"));
    $("#fs-program").classList.toggle("dim", !(t === "program_relevance" || t === "outreach"));
  }

  function districtFromControls() {
    const chamber = $("#ctl-chamber").value || null;
    const code = $("#ctl-code").value || null;
    const boundary_session = Number($("#ctl-session").value) || null;
    // A non-default session is meaningful even before the district is chosen.
    if (!chamber && !code) return boundary_session && boundary_session !== 2024 ? { state_fips: "15", boundary_session } : null;
    return { state_fips: "15", chamber, code, boundary_session };
  }

  function prunedEdits() {
    const out = {};
    ["title", "note", "next_steps"].forEach((k) => { if (edits[k]) out[k] = edits[k]; });
    if (edits.finding_notes) {
      const fn = {};
      Object.keys(edits.finding_notes).forEach((fid) => {
        if (selection.has(fid) && edits.finding_notes[fid]) fn[fid] = edits.finding_notes[fid];
      });
      if (Object.keys(fn).length) out.finding_notes = fn;
    }
    return out;
  }

  // Everything the controls currently hold. DBRequest.collect decides which of these
  // a task sends, so dimmed or unused controls never reach the server.
  function readState() {
    const metric = $("#ctl-metric").value, geo = $("#ctl-geo").value, prog = $("#ctl-program").value;
    return {
      mode: $('input[name="mode"]:checked').value,
      task: currentTask(),
      district: districtFromControls(),
      profile_mode: $("#ctl-profile-mode").value,
      metric_ids: currentTask() === "profile" && $("#ctl-profile-mode").value === "selected" ? Array.from($("#ctl-profile-metrics").selectedOptions, (o) => o.value) : (metric ? [metric] : []),
      observation_ids: Array.from($("#ctl-admin").selectedOptions, (o) => o.value),
      comparison_geography: geo || null,
      program_ids: prog ? [prog] : [],
      selected_finding_ids: Array.from(selection.keys()),
      edits: prunedEdits(),
      utterance: $("#ctl-utterance").value,
    };
  }

  // State for a continuation the server offered (choice button or brief editor). The
  // server's request is the whole, self-contained request — including any still-open
  // clarification_choices — so the controls are not merged in.
  function stateFromChoice(cr) {
    const brief = cr.task === "brief";
    const useSel = brief && (cr.use_selection || !cr.selected_finding_ids);
    return {
      mode: "guided",
      task: cr.task || null,
      district: cr.district || null,
      profile_mode: cr.metric_ids && cr.metric_ids.length ? "selected" : "full",
      metric_ids: cr.metric_ids || [],
      observation_ids: cr.observation_ids || [],
      comparison_geography: cr.comparison_geography || null,
      program_ids: cr.program_ids || [],
      clarification_choices: cr.clarification_choices || null,
      selected_finding_ids: brief ? (useSel ? Array.from(selection.keys()) : cr.selected_finding_ids) :
        (!cr.task ? cr.selected_finding_ids || [] : []),
      edits: brief ? cr.edits || prunedEdits() : (!cr.task ? cr.edits || {} : {}),
      utterance: "",
    };
  }

  function applyToControls(req) {
    if (req.task) { const r = $("#task-" + req.task); if (r) r.checked = true; }
    if (req.district && req.district.chamber) {
      $("#ctl-chamber").value = req.district.chamber;
      $("#ctl-session").value = String(req.district.boundary_session || 2024);
      fillDistricts();
      $("#ctl-code").value = req.district.code || "";
      districtNote();
    }
    if (req.task === "profile") {
      $("#ctl-profile-mode").value = req.metric_ids && req.metric_ids.length ? "selected" : "full";
      $$("option", $("#ctl-profile-metrics")).forEach((o) => { o.selected = (req.metric_ids || []).includes(o.value); });
    } else if (req.metric_ids && req.metric_ids.length) $("#ctl-metric").value = req.metric_ids[0];
    if (req.observation_ids) {
      $$("option", $("#ctl-admin")).forEach((o) => { o.selected = req.observation_ids.includes(o.value); });
      administrativeSelectionNote();
    }
    if (req.comparison_geography) $("#ctl-geo").value = req.comparison_geography;
    if (req.program_ids && req.program_ids.length) $("#ctl-program").value = req.program_ids[0];
    relevantFieldsets();
  }

  // ------------------------------------------------------------ run
  async function run(kind, choiceRequest) {
    if (activeRun) return;
    if ($("#brief-editor")) collectEdits();
    seq += 1;
    const mode = choiceRequest ? "guided" : $('input[name="mode"]:checked').value;
    const state = choiceRequest ? stateFromChoice(choiceRequest) : readState();
    if (mode === "guided" && state.task === "profile" && state.profile_mode === "selected" && !state.metric_ids.length) {
      show({ status: "error", reason: "Choose at least one profile measure, or switch to Full profile." });
      return;
    }
    if (mode === "guided" && state.task === "administrative_context" && state.observation_ids.length > 8) {
      show({ status: "error", reason: "Choose at most 8 administrative rows per run." });
      return;
    }
    const fields = DBRequest.collect(state);
    if (choiceRequest) {
      applyToControls(fields);
      $('input[name="mode"][value="guided"]').checked = true;
    }
    const req = Object.assign({}, fields, {
      request_id: catalog.runtime && catalog.runtime.execution_kind === "hosted" ? crypto.randomUUID() : "a-" + SESSION_ID + "-" + seq,
      snapshot_id: SNAPSHOT,
      input_mode: mode,
      action: { kind: kind || "run", session_id: SESSION_ID },
    });
    if (displayed) req.displayed_context = displayed;
    if (resultReference) req.result_reference = resultReference;

    const runToken = {cancelled:false, transaction:null, executing:false, requestId:req.request_id, hosted:catalog.runtime && catalog.runtime.execution_kind === "hosted"};
    activeRun = runToken;
    const current = () => activeRun === runToken && !runToken.cancelled;
    const runBtn = $("#run-btn");
    runBtn.disabled = true; runBtn.setAttribute("aria-busy", "true");
    const isC = catalog.runtime && catalog.runtime.variant === "C";
    const progress = $("#run-progress");
    if (isC) { $("#c-feedback").hidden = true; $("#c-feedback").innerHTML = ""; progress.hidden = false; text(progress, "Resolving…"); $("#cancel-run").hidden = false; }
    else $("#result").innerHTML = '<p class="loading">Resolving…</p>';
    try {
      let first;
      if (runToken.hosted) {
        text($("#model-calls"), "pending");
        text($("#hosted-usage"), "Hosted request in progress. Usage and estimated inference cost are pending.");
        $("#hosted-usage").hidden = false;
        text(progress, mode === "language" ? "Interpreting supported request…" : "Resolving guided controls…");
        first = await api("POST", "/api/resolve", req, {"X-HAIC-Request-ID":req.request_id});
        if (current()) showHostedUsage(first);
        else if (runToken.cancelled && activeRun === runToken) showHostedUsage(first, true);
      } else if (isC) {
        if (mode === "language" && cMetadata && cMetadata.status === "ready") {
          text(progress, "Loading local model…");
          await cRuntime.load(cMetadata);
          if (!current()) return;
        }
        first = await api("POST", "/api/c/prepare", req);
        if (first.status === "inference") {
          runToken.transaction = first;
          if (!current()) { await cancelTransaction(first, "cancelled"); return; }
          text(progress, "Running local inference…");
          const logits = await cRuntime.infer(first);
          if (!current()) return;
          first = await api("POST", "/api/c/complete", Object.assign(transactionFields(first), {logits}));
        }
      } else first = await api("POST", "/api/resolve", req);
      if (!current()) return;
      if (first.header_html && !runToken.hosted && (!isC || (first.status !== "error" && first.status !== "resolved"))) $("#res-header").innerHTML = first.header_html;
      if (first.model_usage) text($("#model-calls"), first.model_usage.model_calls == null ? "unknown" : String(first.model_usage.model_calls));
      if (first.status !== "resolved") { show(first); return; }
      if (isC) text(progress, "Running " + first.resolution.operation + "…");
      else $("#result").innerHTML = '<p class="loading">Running ' + escapeText(first.resolution.operation) + "…</p>";
      if (!current()) return;
      runToken.executing = true;
      $("#cancel-run").hidden = true;
      const env = await api("POST", "/api/execute", Object.assign({ request_id: first.request_id, snapshot_id: SNAPSHOT }, runToken.hosted ? {session_id:SESSION_ID} : first.c_transaction || {}));
      if (!current()) return;
      if (!isC || (runToken.hosted ? env.status === "ok" : env.status !== "error")) {
        if (env.header_html) $("#res-header").innerHTML = env.header_html;
        else if (isC && first.header_html) $("#res-header").innerHTML = first.header_html;
      }
      show(env);
      if (env.status === "ok" && env.resolution) {
        const r = env.resolution, a = r.args || {};
        applyToControls({
          task: r.task,
          district: r.district,
          metric_ids: a.metric_ids,
          observation_ids: a.observation_ids,
          comparison_geography: a.comparison_geography,
          program_ids: a.program_ids || (a.program_id ? [a.program_id] : undefined),
        });
        displayed = DBRequest.snapshot(readState(), r.task);
        resultReference = env.result_reference || null;
      }
    } catch (error) {
      if (runToken.transaction) await cancelTransaction(runToken.transaction, error.code || "worker_error");
      if (current()) {
        if (runToken.hosted) {
          text($("#c-runtime-status"), "Hosted request failed. Previous results remain available. Run again or use guided controls.");
          show({status:"error", reason:"Hosted request could not continue. Previous results and selections are retained."});
        } else {
        text($("#c-runtime-status"), "Local inference failed. Run again to start a fresh worker, or use guided controls.");
        show({status:"error", reason:error.code === "timeout" ? "Local inference exceeded its deadline and the worker was stopped. No analytical request was dispatched." : "Local model could not run: " + error.message});
        }
      }
    } finally {
      if (activeRun === runToken) {
        activeRun = null;
        $("#cancel-run").hidden = true; progress.hidden = true;
        runBtn.disabled = false; runBtn.removeAttribute("aria-busy");
      }
    }
  }

  function showHostedUsage(env, usageOnly) {
    const usage = env.model_usage || {};
    text($("#model-calls"), usage.model_calls == null ? "unknown" : String(usage.model_calls));
    const calls = usage.calls || [];
    const route = calls.map(c => [c.provider, c.model, c.effort, c.lane].filter(Boolean).join(" / ")).join(" → ");
    const amounts = calls.map(c => {
      const u = c.usage || {};
      return (u.input_tokens == null ? "?" : u.input_tokens) + " input / " +
        (u.output_tokens == null ? "?" : u.output_tokens) + " output tokens";
    }).join("; ");
    const cost = (usage.request_total_cost_usd == null && usage.cost_usd == null) || usage.request_total_cost_usd === null || usage.cost_usd === null ? "unknown cost; admission may be halted" :
      "$" + Number(usage.request_total_cost_usd == null ? usage.cost_usd || 0 : usage.request_total_cost_usd).toFixed(6);
    const line = [usage.lane || "no_model", route, (usage.model_calls == null ? "unknown" : String(usage.model_calls)) + " inference attempts", amounts,
      "Estimated inference cost: " + cost, usage.cost_basis || "documented usage-rate estimate; not invoice", usage.error].filter(Boolean).join(" · ");
    text($("#hosted-usage"), line);
    $("#hosted-usage").hidden = false;
    if (usageOnly) return;
    text($("#c-runtime-status"), env.status === "error" ? "Hosted routing could not complete. Use guided controls or run again." :
      env.status === "resolved" ? "Hosted routing resolved the request. Facts come from the checked fixture." : "Hosted routing returned " + env.status + ".");
  }

  function transactionFields(t) {
    return {transaction_id:t.transaction_id, binding:t.binding, artifact_id:t.artifact_id};
  }
  function cancelTransaction(t, reason) {
    const allowed = ["cancelled", "timeout", "worker_error", "worker_crashed"];
    return api("POST", "/api/c/cancel", Object.assign(transactionFields(t), {reason:allowed.includes(reason) ? reason : "worker_error"}));
  }
  async function cancelRun() {
    const token = activeRun;
    if (!token || token.executing) return;
    token.cancelled = true;
    if (cRuntime) cRuntime.stop("cancelled");
    text($("#c-runtime-status"), token.hosted ? "Cancelled. Previous results and selections are retained. An admitted call may still finish and settle." : "Cancelled. Previous results and selections are retained. Run again to start a fresh worker.");
    $("#cancel-run").hidden = true;
    text($("#run-progress"), "Cancelled. Previous results and selections are retained.");
    if (token.hosted) {
      text($("#hosted-usage"), "Cancellation requested. In-flight usage is pending and may be billed. Settlement is not yet displayed.");
      $("#hosted-usage").hidden = false;
      await api("POST", "/api/hosted/cancel", {request_id:token.requestId, session_id:SESSION_ID});
    }
    else if (token.transaction) await cancelTransaction(token.transaction, "cancelled");
  }

  function escapeText(s) {
    const d = document.createElement("div"); d.textContent = s == null ? "" : String(s); return d.innerHTML;
  }

  function show(env) {
    const cError = catalog && catalog.runtime && catalog.runtime.variant === "C" &&
      (env.status === "error" || (catalog.runtime.execution_kind === "hosted" && env.status !== "ok"));
    const result = $(cError ? "#c-feedback" : "#result");
    result.hidden = false;
    result.innerHTML = env.html || ('<section class="notice notice-error" role="alert"><h3>Error</h3><p>' +
      escapeText(env.reason || "Unknown error") + "</p></section>");
    if (cError) {
      const recovery = document.createElement("button");
      recovery.type = "button"; recovery.className = "btn"; recovery.textContent = "Use guided controls";
      recovery.addEventListener("click", () => {
        $('input[name="mode"][value="guided"]').checked = true;
        $("#run-btn").focus();
      });
      result.appendChild(recovery);
      recovery.focus();
      return;
    }
    syncCheckboxes();
    const editor = $("#brief-editor");
    if (editor) {
      editor.addEventListener("submit", (ev) => { ev.preventDefault(); collectEdits(); logEvent("apply_edits"); run("run", { task: "brief", district: env.resolution.district, use_selection: true }); });
      $("#print-brief").addEventListener("click", () => { logEvent("print"); preparePrint(); window.print(); });
    }
    if (env.status === "clarification" || env.status === "unsupported" || env.status === "error") {
      const first = $(".notice button, .notice", result);
      if (first && first.focus) { if (!first.hasAttribute("tabindex") && first.tagName !== "BUTTON") first.setAttribute("tabindex", "-1"); first.focus(); }
    }
  }

  function collectEdits() {
    const fn = {};
    $$(".finding-note").forEach((t) => { if (t.value.trim()) fn[t.dataset.findingId] = t.value.trim(); });
    edits = {
      title: $("#edit-title").value.trim() || undefined,
      note: $("#edit-note").value.trim() || undefined,
      next_steps: $("#edit-next").value.trim() || undefined,
      finding_notes: fn,
    };
  }

  function preparePrint() {
    const doc = $("#brief-doc");
    const root = $("#print-root");
    root.innerHTML = "";
    if (doc) root.appendChild(doc.cloneNode(true));
    else root.innerHTML = "<p>No brief has been built yet. Select findings and run “Build a brief from these findings”.</p>";
  }
  window.addEventListener("beforeprint", preparePrint);

  // ------------------------------------------------------------ selection tray
  function syncCheckboxes() {
    $$(".finding-select").forEach((cb) => { cb.checked = selection.has(cb.dataset.findingId); });
  }

  function renderTray() {
    const list = $("#tray-list");
    list.innerHTML = "";
    selection.forEach((label, fid) => {
      const li = document.createElement("li");
      const span = document.createElement("span");
      span.className = "tray-label";
      span.textContent = label;
      const code = document.createElement("code");
      code.className = "fine";
      code.textContent = fid;
      const btn = document.createElement("button");
      btn.type = "button"; btn.className = "btn-link tray-remove"; btn.dataset.findingId = fid;
      btn.textContent = "Remove"; btn.setAttribute("aria-label", "Remove " + label + " from brief");
      li.append(span, document.createElement("br"), code, document.createTextNode(" "), btn);
      list.appendChild(li);
    });
    const n = selection.size;
    text($("#tray-count"), n ? n + " finding" + (n === 1 ? "" : "s") + " selected" + (n > MAX_BRIEF ? " — more than fit on one page" : "") + "." : "No findings selected.");
  }

  function toggleSelection(fid, label, on) {
    if (on) selection.set(fid, label); else selection.delete(fid);
    logEvent(on ? "select_finding" : "deselect_finding", { finding_id: fid });
    renderTray(); syncCheckboxes();
  }

  // ------------------------------------------------------------ source dialog
  async function openSource(sourceId, findingId) {
    logEvent("view_source", { detail: sourceId, finding_id: findingId || undefined });
    let url = "/api/source?source_id=" + encodeURIComponent(sourceId);
    if (findingId) url += "&finding_id=" + encodeURIComponent(findingId);
    const body = $("#source-body");
    body.innerHTML = '<p class="loading">Loading retained source…</p>';
    const dlg = $("#source-dialog");
    if (!dlg.open) dlg.showModal();
    const out = await api("GET", url);
    body.innerHTML = out.html || ('<p class="alert">' + escapeText(out.reason || "Source unavailable.") + "</p>");
    $("#close-source").focus();
  }

  // ------------------------------------------------------------ tabs
  function selectTab(btn) {
    $$('[role="tab"]').forEach((b) => {
      const on = b === btn;
      b.setAttribute("aria-selected", on ? "true" : "false");
      b.tabIndex = on ? 0 : -1;
      $("#" + b.getAttribute("aria-controls")).hidden = !on;
    });
    logEvent("open_tab", { detail: btn.id });
  }

  function wireTabs() {
    const tabs = $$('[role="tab"]');
    tabs.forEach((b, i) => {
      b.addEventListener("click", () => selectTab(b));
      b.addEventListener("keydown", (ev) => {
        let j = null;
        if (ev.key === "ArrowRight") j = (i + 1) % tabs.length;
        if (ev.key === "ArrowLeft") j = (i - 1 + tabs.length) % tabs.length;
        if (ev.key === "Home") j = 0;
        if (ev.key === "End") j = tabs.length - 1;
        if (j !== null) { ev.preventDefault(); tabs[j].focus(); selectTab(tabs[j]); }
      });
    });
  }

  // ------------------------------------------------------------ catalog tab
  function wireCatalogFilters() {
    const geo = $("#cat-geo"), q = $("#cat-q");
    const apply = () => {
      const g = geo.value, s = q.value.trim().toLowerCase();
      let shown = 0;
      $$("#cat-table tbody tr").forEach((tr) => {
        const ok = (!g || tr.dataset.geo === g) && (!s || tr.textContent.toLowerCase().includes(s));
        tr.hidden = !ok; if (ok) shown += 1;
      });
      text($("#cat-count"), shown + " of " + $$("#cat-table tbody tr").length + " observations shown");
    };
    geo.addEventListener("change", apply); q.addEventListener("input", apply); apply();
  }

  function renderCommands() {
    const body = $("#commands-body");
    const intro = document.createElement("p");
    intro.textContent = catalog.runtime && catalog.runtime.execution_kind === "hosted" ? "Prototype C uses bounded hosted interpretation for supported typed requests. Guided controls use the shared deterministic resolver with zero model calls. All facts and printable content come from the checked fixture. Inference attempts and estimated usage costs appear after each request." : catalog.runtime && catalog.runtime.variant === "C" ? "Prototype C uses an optional local model for typed requests. Its package and browser runtime must be ready before inference. Guided controls use the shared deterministic resolver. No remote or model API calls are made. Browser mechanics do not establish learned accuracy." : (catalog.runtime && catalog.runtime.variant === "B") ? "Prototype B uses bounded model routing for typed requests. The same supported tasks, fixture, clarification rules and factual renderer apply. Guided controls use deterministic routing with zero model calls. These literal forms also describe supported tasks." : "Prototype A recognizes only these literal command forms for the supported tasks. Anything else returns “Not supported” with supported choices; incomplete commands ask a clarification question. No model interprets text.";
    body.appendChild(intro);
    const dl = document.createElement("dl");
    dl.className = "kv";
    catalog.commands.forms.forEach((c) => {
      const div = document.createElement("div");
      const dt = document.createElement("dt");
      dt.textContent = catalog.templates.find((t) => t.task === c.task).label;
      const dd = document.createElement("dd");
      c.forms.forEach((f, i) => { const code = document.createElement("code"); code.textContent = f; dd.appendChild(code); if (i < c.forms.length - 1) dd.appendChild(document.createTextNode(" · ")); });
      div.append(dt, dd); dl.appendChild(div);
    });
    body.appendChild(dl);
    const ul = document.createElement("ul");
    catalog.commands.rules.forEach((r) => { const li = document.createElement("li"); li.textContent = r; ul.appendChild(li); });
    body.appendChild(ul);
  }

  // ------------------------------------------------------------ events
  function wireDelegation() {
    document.addEventListener("click", (ev) => {
      const choice = ev.target.closest(".choice-btn");
      if (choice) {
        ev.preventDefault();
        logEvent("choice_click", { detail: choice.textContent.slice(0, 200) });
        run(choice.dataset.kind || "next_action", JSON.parse(choice.dataset.request));
        return;
      }
      const src = ev.target.closest(".source-btn");
      if (src) { ev.preventDefault(); openSource(src.dataset.sourceId, src.dataset.findingId); return; }
      const rm = ev.target.closest(".tray-remove");
      if (rm) { toggleSelection(rm.dataset.findingId, "", false); return; }
    });
    document.addEventListener("change", (ev) => {
      const cb = ev.target.closest(".finding-select");
      if (cb) {
        const label = (cb.closest("label").querySelector(".sr-only") || {}).textContent || cb.dataset.findingId;
        toggleSelection(cb.dataset.findingId, label.replace(/^:\s*/, ""), cb.checked);
      }
    });
    $("#controls").addEventListener("submit", (ev) => { ev.preventDefault(); run("run"); });
    $("#build-brief").addEventListener("click", () => {
      const d = (displayed && displayed.district) || districtFromControls();
      run("run", { task: "brief", district: d, use_selection: true });
    });
    $("#clear-tray").addEventListener("click", () => { Array.from(selection.keys()).forEach((f) => selection.delete(f)); edits = {}; renderTray(); syncCheckboxes(); });
    $("#close-source").addEventListener("click", () => $("#source-dialog").close());
  }

  // ------------------------------------------------------------ boot
  async function boot() {
    wireTabs();
    const health = await api("GET", "/api/health");
    if (health.status !== "ok") {
      text($("#packet-status"), "packet check failed");
      $("#result").innerHTML = '<section class="notice notice-error" role="alert"><h3>Error</h3><p>The local server is not ready.</p></section>';
      return;
    }
    SNAPSHOT = health.snapshot_id;
    text($("#snapshot-id"), SNAPSHOT.slice(0, 19) + "…");
    $("#snapshot-id").title = SNAPSHOT;
    text($("#packet-status"), "packet verified (" + health.packet.file_count + " files)");
    const runtime = health.runtime || {};
    if (runtime.label) {
      text($(".variant"), runtime.label);
      document.title = "District Brief Builder — " + runtime.label;
      text($("#utterance-help"), runtime.language_help);
    }
    catalog = await api("GET", "/api/catalog");
    if (catalog.runtime && catalog.runtime.label) {
      text($(".variant"), catalog.runtime.label);
      document.title = "District Brief Builder — " + catalog.runtime.label;
      if (catalog.runtime.language_help) text($("#utterance-help"), catalog.runtime.language_help);
    }
    if (catalog.runtime && catalog.runtime.variant === "C") {
      $("#c-runtime-panel").hidden = false;
      $("#cancel-run").addEventListener("click", cancelRun);
      if (catalog.runtime.execution_kind === "hosted") {
        text($("#c-runtime-status"), catalog.runtime.ready ? "Hosted routing enabled. Guided controls use zero model calls." : "Hosted inference disabled. Guided controls remain available.");
      } else {
      await new Promise((resolve, reject) => {
        const script = document.createElement("script");
        script.src = "/static/c-runtime.js";
        script.onload = resolve; script.onerror = reject;
        document.head.appendChild(script);
      });
      cRuntime = new CRuntime({notify: state => {
        text($("#c-runtime-status"), state === "loading" ? "Loading local model…" : state === "ready" ? "Local model ready. Learned quality depends on its accepted package." : state === "error" ? "Local worker stopped. Run again to recover, or use guided controls." : "Local inference running…");
      }});
      cMetadata = await api("GET", "/api/c/runtime");
      text($("#c-runtime-status"), cMetadata.status === "ready" ? "Local package available. Model loads when a typed request runs." : cMetadata.status === "absent" ? "No local model installed. Use guided controls." : "Local package unavailable or incompatible. Use guided controls.");
      }
    }
    buildControls();
    fillDistricts();
    $("#catalog-body").innerHTML = catalog.html;
    $("#sources-body").innerHTML = catalog.sources_html;
    wireCatalogFilters();
    renderCommands();
    wireDelegation();
    renderTray();
  }

  document.addEventListener("DOMContentLoaded", boot);
})();
