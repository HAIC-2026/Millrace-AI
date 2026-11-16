/* Pure guards for optional language requests; this module never sends data. */
(function (root, factory) {
  'use strict';
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.IALanguage = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  const stable = (x) => Array.isArray(x) ? '[' + x.map(stable).join(',') + ']' : x && typeof x === 'object' ? '{' + Object.keys(x).sort().map(k => JSON.stringify(k) + ':' + stable(x[k])).join(',') + '}' : JSON.stringify(x);
  const same = (a, b) => stable(a) === stable(b);
  const copy = x => JSON.parse(JSON.stringify(x));
  // One context builder for every question. q (optional, ephemeral, never saved in the case) carries:
  //  basis  {kind:'confirmed'|'draft', confirmed_key, draft_key}: the staff choice after a confirmed/draft conflict;
  //         valid only while both plans are unchanged. 'confirmed' asks about the confirmed plan (draft untouched);
  //         'draft' asks about the unapplied draft alone (no confirmed plan, so no selected findings).
  //  focus  a step_id chosen with "Ask about this step"; kept only while it is a step of the held plan.
  //  source {claim_ref, branch_id, revision}: the finding whose source was last inspected; used as the only
  //         selected reference while it belongs to the current confirmed revision (brief selections are untouched).
  function basisOf(state, b, q) {
    const x = q && q.basis;
    return x && x.confirmed_key === stable(b.plan) && x.draft_key === stable(state.draft) && (x.kind === 'confirmed' || x.kind === 'draft') ? x.kind : null;
  }
  function context(state, active, q) {
    const b = active(state), basis = basisOf(state, b, q);
    let confirmed = copy(b.plan), draft = copy(state.draft), refs = copy(b.selected_claim_refs);
    if (basis === 'confirmed') draft = copy(b.plan);
    else if (basis === 'draft') { confirmed = null; refs = []; }
    const held = confirmed || draft, focus = q && q.focus;
    const focused = focus && held && held.steps.some((s) => s.step_id === focus) ? focus : null;
    const src = q && q.source;
    if (confirmed && src && src.branch_id === b.branch_id && src.revision === b.last_ready_revision && src.claim_ref) refs = [copy(src.claim_ref)];
    return {case_id:state.case.case_id, branch_id:b.branch_id, revision:b.last_ready_revision === null ? 0 : b.last_ready_revision,
      snapshot_id:b.snapshot_id, operation_version:b.operation_version, recipe_version:b.recipe_version,
      confirmed_plan:confirmed, draft_plan:draft, focused_step_id:focused, selected_claim_refs:refs};
  }
  function makeBasis(state, active, kind) {
    const b = active(state);
    return {kind:kind, confirmed_key:stable(b.plan), draft_key:stable(state.draft)};
  }
  // A district or chamber choice becomes a visible canonical prefix of the next question ("House 5: ..."), so the
  // next request names the chosen House/Senate district instead of repeating the ambiguous wording.
  const PREFIX = /^(?:(?:House|Senate) \d{1,2}|In the (?:House|Senate)): /;
  function withChoice(question, choice) {
    const base = String(question || '').replace(PREFIX, '');
    if (choice && choice.field === 'district' && choice.value && /^(house|senate)$/.test(choice.value.chamber) && /^\d{3}$/.test(choice.value.code))
      return (choice.value.chamber === 'house' ? 'House ' : 'Senate ') + Number(choice.value.code) + ': ' + base;
    if (choice && choice.field === 'chamber' && /^(house|senate)$/.test(choice.value)) return 'In the ' + (choice.value === 'house' ? 'House' : 'Senate') + ': ' + base;
    return base;
  }
  function matches(reply, job, current, releaseId) {
    if (!reply || reply.request_id !== job.request_id || !same(reply.context, job.context) || !same(current, job.context)) return false;
    if (typeof reply.context_digest !== 'string' || !/^sha256:[0-9a-f]{64}$/.test(reply.context_digest)) return false;
    if (job.context_digest && reply.context_digest !== job.context_digest) return false;
    const t = reply.tokens, c = job.context;
    return !!t && t.schema_version === 'ia-language/1' && t.release_id === releaseId &&
      ['case_id','branch_id','revision','snapshot_id','operation_version','recipe_version'].every(k => t[k] === c[k]);
  }
  // One Ask guards. They only decide whether a server-validated proposal may run without review; they never
  // choose, fill or change any part of a plan, and they do not interpret the question.
  // Explicit district mentions with a chamber ("House 28", "Senate district 5"), as "house:028" keys.
  function namedDistricts(text) {
    const out = new Set(), re = /\b(house|senate)(?:\s+district)?\s+0*(\d{1,2})\b/gi;
    let m;
    while ((m = re.exec(String(text || '')))) out.add(m[1].toLowerCase() + ':' + String(Number(m[2])).padStart(3, '0'));
    return out;
  }
  const districtKey = (d) => d.chamber + ':' + d.code;
  const geoDistrictKey = (g) => { const m = /^HI-(HOUSE|SENATE)-(\d{3})-\d{4}$/.exec(String(g || '')); return m ? m[1].toLowerCase() + ':' + m[2] : null; };
  // What a validated proposal asked for, read only from the server's typed diff (never from the question text):
  // - an added step, or a step whose operation or comparison geography changed: the whole step;
  // - a changed step that gained measures, programs or administrative rows: only those (before/after lists); widening a profile to all
  //   measures, or narrowing a step to fewer measures or programs, is the whole (remaining) step;
  // - when nothing is singled out: an explicit "Ask about this step" focus the proposal keeps, else the plan's only step.
  // Returns {step_ids, only[, fallback]}: only[step_id] = {metric_ids}, {program_ids} or {observation_ids} narrows that step. Empty step_ids means
  // the answer is the whole plan, and nothing is presented as focused.
  function requestedFocus(result, focusedStepId) {
    const plan = result.normalized_plan, picked = new Set(), only = {};
    const KEY = { profile: 'metric_ids', compare: 'metric_ids', program_evidence: 'program_ids', administrative_evidence: 'observation_ids' };
    (Array.isArray(result.typed_diff) ? result.typed_diff : []).forEach((d) => {
      if (!d || d.field !== 'steps' || typeof d.step_id !== 'string' || d.change === 'removed') return;
      const sid = d.step_id, before = d.before, after = d.after;
      if (d.change === 'added' || !before || !after || !before.args || !after.args || before.operation !== after.operation) { picked.add(sid); return; }
      if (after.operation === 'compare' && before.args.comparison_geography !== after.args.comparison_geography) { picked.add(sid); return; }
      const key = KEY[after.operation];
      if (!key) { picked.add(sid); return; }
      const now = after.args[key], was = before.args[key];
      if (now === null) { if (was !== null) picked.add(sid); return; }
      if (!Array.isArray(now)) return;
      if (was === null || !Array.isArray(was)) { picked.add(sid); return; }
      const gained = now.filter((x) => !was.includes(x));
      if (!gained.length) { if (now.length < was.length) picked.add(sid); return; }
      picked.add(sid);
      only[sid] = { [key]: gained };
    });
    let ids = plan.steps.filter((st) => picked.has(st.step_id)).map((st) => st.step_id), fallback = false;
    if (ids.length === plan.steps.length && ids.length > 2) ids = [];
    else if (!ids.length && focusedStepId && plan.steps.some((st) => st.step_id === focusedStepId)) { ids = [focusedStepId]; fallback = true; }
    else if (!ids.length && !picked.size && plan.steps.length === 1) { ids = [plan.steps[0].step_id]; fallback = true; }
    const kept = {};
    ids.forEach((sid) => { if (only[sid]) kept[sid] = only[sid]; });
    // fallback: the step was chosen without the diff naming its content, so a step listing several findings does not
    // say which one was asked for (the page then shows them as related findings, not as an answer).
    return fallback ? { step_ids: ids, only: kept, fallback: true } : { step_ids: ids, only: kept };
  }
  // Why a proposal must be reviewed before it runs, judged against the plan the question was asked about:
  // an own-district phrase, ANY change of the primary district (a district named in a question may be meant as
  // a comparison, and the wording is not used to guess its role), or a new district comparator the question
  // does not name with its chamber. To ask about another district without review, choose it as the district first.
  function runBlockers(question, held, plan) {
    const out = [], named = namedDistricts(question);
    if (/\b(my|our)\s+(own\s+)?district\b/i.test(String(question || ''))) out.push({ code: 'own_district' });
    if (held && districtKey(held.district) !== districtKey(plan.district))
      out.push({ code: 'primary_changed', from: copy(held.district), to: copy(plan.district) });
    const before = new Map((held ? held.steps : []).map((st) => [st.step_id, st]));
    plan.steps.forEach((st) => {
      if (st.operation !== 'compare') return;
      const old = before.get(st.step_id), g = st.args.comparison_geography, gk = geoDistrictKey(g);
      if (old && old.operation === 'compare' && old.args.comparison_geography === g) return;
      if (gk && !named.has(gk)) out.push({ code: 'district_comparator', geography: g });
    });
    return out;
  }
  return {context, matches, same, makeBasis, withChoice, namedDistricts, requestedFocus, runBlockers};
});
