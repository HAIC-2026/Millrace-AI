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
  function context(state, active) {
    const b = active(state);
    return {case_id:state.case.case_id, branch_id:b.branch_id, revision:b.last_ready_revision === null ? 0 : b.last_ready_revision,
      snapshot_id:b.snapshot_id, operation_version:b.operation_version, recipe_version:b.recipe_version,
      confirmed_plan:copy(b.plan), draft_plan:copy(state.draft), focused_step_id:null, selected_claim_refs:copy(b.selected_claim_refs)};
  }
  function matches(reply, job, current, releaseId) {
    if (!reply || reply.request_id !== job.request_id || !same(reply.context, job.context) || !same(current, job.context)) return false;
    if (typeof reply.context_digest !== 'string' || !/^sha256:[0-9a-f]{64}$/.test(reply.context_digest)) return false;
    if (job.context_digest && reply.context_digest !== job.context_digest) return false;
    const t = reply.tokens, c = job.context;
    return !!t && t.schema_version === 'ia-language/1' && t.release_id === releaseId &&
      ['case_id','branch_id','revision','snapshot_id','operation_version','recipe_version'].every(k => t[k] === c[k]);
  }
  return {context, matches, same};
});
