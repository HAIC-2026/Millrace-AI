/* Request assembly for the Prototype A browser client. Plain script, no module export.
   It performs no network or DOM work; app.js reads the controls and passes a state here.

   DBRequest.collect(state) returns only the request fields that apply to the task
   being asked for, so a dimmed or unused control (for example a measure while the
   task is outreach) is never sent.

   DBRequest.snapshot(state, resolvedTask) returns the displayed context that the
   server compares with the current controls: every non-empty control as displayed
   after the last successful run. */
(function () {
  "use strict";

  // Context fields each task uses (mirrors the server's applicable-field map).
  const TASK_CONTEXT = {
    profile: ["metric_ids"],
    administrative_context: ["observation_ids"],
    compare: ["metric_ids", "comparison_geography"],
    program_relevance: ["program_ids"],
    outreach: ["program_ids"],
    brief: [],
  };

  function hasValue(v) {
    if (v === null || v === undefined || v === "") return false;
    if (Array.isArray(v)) return v.length > 0;
    if (typeof v === "object") return Object.keys(v).length > 0;
    return true;
  }

  function compact(obj) {
    const out = {};
    Object.keys(obj).forEach((k) => { if (hasValue(obj[k])) out[k] = obj[k]; });
    return out;
  }

  function copyList(v) { return Array.isArray(v) ? v.slice() : []; }

  function copyObject(v) { return v && typeof v === "object" && !Array.isArray(v) ? Object.assign({}, v) : {}; }

  // Keep explicit partial identity/session fields so later choices can resolve them.
  // Missing fields stay unresolved; an empty object does not create a district.
  function districtOf(d) {
    if (!d) return null;
    const session = hasValue(d.boundary_session) ? Number(d.boundary_session) : null;
    if (d.geoid && !d.code) return compact({ state_fips: d.state_fips || "15", geoid: String(d.geoid), boundary_session: session });
    if (!d.chamber && !d.code) {
      const partial = compact({ state_fips: d.state_fips || null, boundary_session: session });
      return Object.keys(partial).length ? partial : null;
    }
    return {
      state_fips: d.state_fips || "15",
      chamber: d.chamber || null,
      code: d.code || null,
      boundary_session: session,
    };
  }

  function contextFor(state, task) {
    const use = TASK_CONTEXT[task] || [];
    const out = {};
    if (use.includes("metric_ids") && (task !== "profile" || state.profile_mode === "selected")) out.metric_ids = copyList(state.metric_ids);
    if (use.includes("observation_ids")) out.observation_ids = copyList(state.observation_ids);
    if (use.includes("comparison_geography")) out.comparison_geography = state.comparison_geography || null;
    if (use.includes("program_ids")) out.program_ids = copyList(state.program_ids);
    return out;
  }

  // Still-open candidate sets of an ambiguous typed compare field, carried by a server-offered
  // continuation (resolution transport only). A set is dropped once its field holds a chosen value.
  const CHOICE_KEYS = ["metric_ids", "comparison_geography"];
  function choicesOf(s) {
    const src = s.clarification_choices;
    if (!src || typeof src !== "object" || Array.isArray(src)) return null;
    const out = {};
    CHOICE_KEYS.forEach((k) => {
      const chosen = k === "metric_ids" ? copyList(s.metric_ids).length > 0 : !!s.comparison_geography;
      const items = !chosen && Array.isArray(src[k]) ? src[k].filter((x) => typeof x === "string") : [];
      if (items.length) out[k] = items;
    });
    return Object.keys(out).length ? out : null;
  }

  // state: { mode: "guided"|"language", task, district, metric_ids, comparison_geography,
  //          program_ids, selected_finding_ids, edits, utterance }
  function collectFields(state) {
    const s = state || {};
    if (s.mode === "language") {
      // Typed commands carry no task; the server reads the literal command and the controls.
      const utterance = typeof s.utterance === "string" && s.utterance.trim() ? s.utterance : null;
      return compact({
        utterance: utterance,
        district: districtOf(s.district),
        metric_ids: s.task === "profile" && s.profile_mode !== "selected" ? [] : copyList(s.metric_ids),
        comparison_geography: s.comparison_geography || null,
        program_ids: copyList(s.program_ids),
        observation_ids: copyList(s.observation_ids),
        selected_finding_ids: copyList(s.selected_finding_ids),
        edits: copyObject(s.edits),
      });
    }
    const task = s.task || null;
    // A server-offered intermediate choice may settle geography before task. Keep its
    // entire stated context until the resolver offers task choices; do not infer a task.
    if (!task) return compact({
      district: districtOf(s.district),
      metric_ids: copyList(s.metric_ids),
      comparison_geography: s.comparison_geography || null,
      program_ids: copyList(s.program_ids),
      observation_ids: copyList(s.observation_ids),
      selected_finding_ids: copyList(s.selected_finding_ids),
      edits: copyObject(s.edits),
      clarification_choices: choicesOf(s),
    });
    const out = { task: task, district: districtOf(s.district) };
    Object.assign(out, contextFor(s, task));
    if (task === "compare") out.clarification_choices = choicesOf(s);
    if (task === "brief") {
      out.selected_finding_ids = copyList(s.selected_finding_ids);
      out.edits = copyObject(s.edits);
    }
    return compact(out);
  }

  function collect(state) {
    const out = collectFields(state);
    if (state && typeof state.result_reference === "string" && state.result_reference) {
      out.result_reference = state.result_reference;
    }
    return out;
  }

  // The client-carried displayed context is the full control state shown after a
  // successful run (controls are synced to the result first). The server treats a control
  // as "changed" only when it differs from this snapshot, so every non-empty control is
  // recorded, not just the fields of the last task. A district counts only with a code.
  function snapshot(state, resolvedTask) {
    const s = state || {};
    const d = districtOf(s.district);
    return compact({
      task: resolvedTask || null,
      district: d && d.code ? d : null,
      metric_ids: copyList(s.metric_ids),
      comparison_geography: s.comparison_geography || null,
      program_ids: copyList(s.program_ids),
      observation_ids: copyList(s.observation_ids),
    });
  }

  globalThis.DBRequest = { collect: collect, snapshot: snapshot };
})();
