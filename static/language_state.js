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
  return {context, matches, same, makeBasis, withChoice};
});
