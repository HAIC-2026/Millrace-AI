// One Ask guards: which server-validated language proposals may run without staff review.
const test = require("node:test");
const assert = require("node:assert/strict");
const L = require("../static/language_state.js");

const D = (chamber, code) => ({ state_fips: "15", chamber, code, boundary_session: 2024 });
const recipe = (d, extra) => ({
  district: d, map_session: 2026, issue_id: "aging_at_home", service_area_id: null,
  steps: [
    { step_id: "s1", operation: "profile", args: { metric_ids: ["population_65_plus", "poverty_rate_65_plus"] } },
    { step_id: "s2", operation: "compare", args: { metric_ids: ["poverty_rate_65_plus"], comparison_geography: "HI-STATE-2024" } },
    { step_id: "s3", operation: "program_evidence", args: { program_ids: ["kupuna_care_hi"] } },
  ].concat(extra || []),
});
const codes = (q, held, plan) => L.runBlockers(q, held, plan).map((x) => x.code);
const H28 = recipe(D("house", "028"));

test("any proposal that moves the primary district is held for review, whatever the question names", () => {
  const profile = (d) => ({ district: d, map_session: 2026, issue_id: "aging_at_home", service_area_id: null,
    steps: [{ step_id: "s1", operation: "profile", args: { metric_ids: ["population_65_plus"] } }] });
  const P28 = profile(D("house", "028")), P10 = profile(D("house", "010"));
  // A follow-up naming one other district must not move the primary district on its own.
  assert.deepEqual(codes("How does that compare with House 10?", P28, P10), ["primary_changed"]);
  assert.deepEqual(codes("Compare against House 10", P28, P10), ["primary_changed"]);
  // A bare district number proposed as the new primary district.
  assert.deepEqual(codes("Compare House 28 against district 10", H28, recipe(D("house", "010"))), ["primary_changed"]);
  assert.deepEqual(codes("Compare House 28 with House 10", H28, recipe(D("house", "010"))), ["primary_changed"]);
  assert.deepEqual(codes("older adults in district 13", H28, recipe(D("house", "013"))), ["primary_changed"]);
  // Even an explicit request for another district's profile needs the scope review (or choose the district first).
  assert.deepEqual(codes("How many older adults live in House 13?", H28, recipe(D("house", "013"))), ["primary_changed"]);
  assert.deepEqual(codes("Senate district 5 poverty", H28, recipe(D("senate", "005"))), ["primary_changed"]);
  const moved = L.runBlockers("How does that compare with House 10?", P28, P10)[0];
  assert.deepEqual([moved.from.code, moved.to.code], ["028", "010"]);
  // Same primary district: a supported comparison with an explicitly named district still runs in one action.
  const cmp10 = { ...P28, steps: P28.steps.concat([{ step_id: "s2", operation: "compare", args: { metric_ids: ["population_65_plus"], comparison_geography: "HI-HOUSE-010-2024" } }]) };
  assert.deepEqual(codes("How does that compare with House 10?", P28, cmp10), []);
  assert.deepEqual(codes("Compare against House 10", P28, cmp10), []);
  // ... but not when the comparator district is named without a chamber.
  assert.deepEqual(codes("Compare against district 10", P28, cmp10), ["district_comparator"]);
  // A proposal for the district already held runs (the user chose the district first).
  assert.deepEqual(codes("How many older adults live in House 13?", recipe(D("house", "013")), recipe(D("house", "013"))), []);
});

test("own-district wording is always reviewed, even when it names a district", () => {
  assert.deepEqual(codes("What is senior poverty in my district, House 13?", H28, recipe(D("house", "013"))), ["own_district", "primary_changed"]);
  assert.deepEqual(codes("What is senior poverty in my district, House 13?", recipe(D("house", "013")), recipe(D("house", "013"))), ["own_district"]);
  assert.deepEqual(codes("Show our district's older adults", H28, H28), ["own_district"]);
});

test("a new district comparator needs the district named with its chamber; county and State comparators run", () => {
  const withCmp = (g) => recipe(D("house", "028"), [{ step_id: "s4", operation: "compare", args: { metric_ids: ["poverty_rate_65_plus"], comparison_geography: g } }]);
  assert.deepEqual(L.runBlockers("Compare House 28 with district 10", H28, withCmp("HI-HOUSE-010-2024")), [{ code: "district_comparator", geography: "HI-HOUSE-010-2024" }]);
  assert.deepEqual(codes("Compare House 28 with Senate 10", H28, withCmp("HI-HOUSE-010-2024")), ["district_comparator"]);
  assert.deepEqual(codes("Compare House 28 with House 10", H28, withCmp("HI-HOUSE-010-2024")), []);
  assert.deepEqual(codes("Compare senior poverty with Maui County", H28, withCmp("HI-COUNTY-009-2024")), []);
  // A comparator the held plan already had is not new.
  const held = withCmp("HI-HOUSE-010-2024");
  assert.deepEqual(codes("Add median income to the profile", held, withCmp("HI-HOUSE-010-2024")), []);
});

test("the requested focus comes from the server typed diff before/after lists, not from the question text", () => {
  const prof = (ms) => ({ step_id: "s1", operation: "profile", args: { metric_ids: ms } });
  const cmp = (g) => ({ step_id: "s2", operation: "compare", args: { metric_ids: ["poverty_rate_65_plus"], comparison_geography: g } });
  const prog = (ps) => ({ step_id: "s3", operation: "program_evidence", args: { program_ids: ps } });
  const plan = (steps) => ({ district: D("house", "028"), map_session: 2026, issue_id: "aging_at_home", service_area_id: null, steps });
  const change = (before, after) => ({ field: "steps", step_id: after.step_id, change: "changed", before, after });
  const focus = (steps, diff, kept) => L.requestedFocus({ normalized_plan: plan(steps), typed_diff: diff }, kept || null);
  const A = ["population_65_plus", "poverty_rate_65_plus"], withAge = A.concat(["median_age"]);
  // A measure added to an existing profile: only that measure is asked for.
  assert.deepEqual(focus([prof(withAge), cmp("HI-STATE-2024")], [change(prof(A), prof(withAge))]), { step_ids: ["s1"], only: { s1: { metric_ids: ["median_age"] } } });
  // A kept "Ask about this step" focus does not join a diff that singles out other content ...
  assert.deepEqual(focus([prof(withAge), cmp("HI-STATE-2024")], [change(prof(A), prof(withAge))], "s2"), { step_ids: ["s1"], only: { s1: { metric_ids: ["median_age"] } } });
  // A step narrowed to what was asked is the whole remaining step, and a kept focus elsewhere does not join it.
  assert.deepEqual(focus([prof(["population_65_plus"]), cmp("HI-STATE-2024")], [change(prof(A), prof(["population_65_plus"]))], "s2"), { step_ids: ["s1"], only: {} });
  assert.deepEqual(focus([prof(["population_65_plus"]), cmp("HI-STATE-2024")], [change(prof(null), prof(["population_65_plus"]))]), { step_ids: ["s1"], only: {} });
  // A kept focus is used when the diff singles out nothing (only the map or context changed).
  assert.deepEqual(focus([prof(A), cmp("HI-STATE-2024")], [{ field: "map_session", change: "changed" }], "s2"), { step_ids: ["s2"], only: {}, fallback: true });
  // An unchanged single-step plan (empty diff) answers with its only step; an unchanged multi-step plan does not.
  // (marked as a step fallback: a step listing several findings does not say which one was asked for)
  assert.deepEqual(focus([prof(["population_65_plus"])], []), { step_ids: ["s1"], only: {}, fallback: true });
  assert.deepEqual(focus([prof(A), cmp("HI-STATE-2024")], []), { step_ids: [], only: {} });
  // A changed comparison geography, an added step and a widened profile are the whole step.
  assert.deepEqual(focus([prof(A), cmp("HI-COUNTY-009-2024")], [change(cmp("HI-STATE-2024"), cmp("HI-COUNTY-009-2024"))]), { step_ids: ["s2"], only: {} });
  assert.deepEqual(focus([prof(A), cmp("HI-STATE-2024")], [{ field: "steps", step_id: "s2", change: "added", before: null, after: cmp("HI-STATE-2024") }]), { step_ids: ["s2"], only: {} });
  assert.deepEqual(focus([prof(null)], [change(prof(A), prof(null))]), { step_ids: ["s1"], only: {} });
  // A program added to a program step: only that program.
  assert.deepEqual(focus([prof(A), prog(["kupuna_care_hi", "snap_hi"])], [change(prog(["kupuna_care_hi"]), prog(["kupuna_care_hi", "snap_hi"]))]), { step_ids: ["s3"], only: { s3: { program_ids: ["snap_hi"] } } });
  // Context-only changes single out nothing; a whole new plan of three or more steps is not focused.
  assert.deepEqual(focus([prof(A), cmp("HI-STATE-2024")], [{ field: "district", change: "changed" }]), { step_ids: [], only: {} });
  const three = [prof(A), cmp("HI-STATE-2024"), prog(["kupuna_care_hi"])];
  assert.deepEqual(focus(three, three.map((st) => ({ field: "steps", step_id: st.step_id, change: "added", before: null, after: st }))), { step_ids: [], only: {} });
});

test("named districts are read only with an explicit chamber", () => {
  assert.deepEqual([...L.namedDistricts("House 28, senate district 05 and district 10")].sort(), ["house:028", "senate:005"]);
  assert.deepEqual([...L.namedDistricts("House 2028 budget")], []);
});

test("switch review recognizes the server's HD and SD shorthand without changing other district matching", () => {
  const s8 = recipe(D("senate", "008"));
  assert.equal(L.switchDistrictWording("SD 8", s8), "single");
  assert.equal(L.switchDistrictWording("hd-028", H28), "single");
  assert.equal(L.switchDistrictWording("HD 8", s8), "review");
  assert.equal(L.switchDistrictWording("SD 8 or 9", s8), "clarify");
  assert.equal(L.switchDistrictWording("9 or SD 8", s8), "clarify");
  assert.deepEqual([...L.namedDistricts("SD 8")], []);
  assert.deepEqual(codes("SD 8", H28, s8), ["primary_changed"]);
});

test("switch review clarifies a list with a repeated location word on either side of the named district", () => {
  const s8 = recipe(D("senate", "008"));
  assert.equal(L.switchDistrictWording("What is the population in Senate 8 or in 9?", s8), "clarify");
  assert.equal(L.switchDistrictWording("What is the population in 9 or in Senate 8?", s8), "clarify");
  assert.equal(L.switchDistrictWording("What is the population in Senate 8 or district 9?", s8), "clarify");
});

test("switch review distinguishes geographic relations, omitted numbers, and planned district comparisons", () => {
  const s8 = recipe(D("senate", "008"));
  assert.equal(L.switchDistrictWording("What is the population of the district bordering Senate 8?", s8), "review");
  assert.equal(L.switchDistrictWording("Senate 8 and surrounding districts", s8), "review");
  assert.equal(L.switchDistrictWording("How many people live in Senate 8 plus 9?", s8), "clarify");
  assert.equal(L.switchDistrictWording("Compare the population in Senate 8 vs. 9", s8), "clarify");
  const cmp = recipe(s8.district, [{ operation: "compare", args: { comparison_geography: "HI-SENATE-009-2024" } }]);
  assert.equal(L.switchDistrictWording("Compare the population in Senate 8 vs. 9", cmp), "review");
});

test("switch review catches omitted comparison peers and alternatives and keeps unexplained numbers in review", () => {
  const s11 = recipe(D("senate", "011"));
  const comparison = "Compare median household income in Senate 11 with 12.";
  assert.equal(L.switchDistrictWording(comparison, s11), "clarify");
  assert.equal(L.switchDistrictWording("Change to Senate 11 or to 12.", s11), "clarify");
  assert.equal(L.switchDistrictWording("Compare Senate 11 against 12.", s11), "clarify");
  assert.equal(L.switchDistrictWording("Compare between 12 and Senate 11.", s11), "clarify");
  assert.equal(L.switchDistrictWording("Show Senate 11 population. What about 12?", s11), "review");
  const cmp = recipe(s11.district, [{ operation: "compare", args: { comparison_geography: "HI-SENATE-012-2024" } }]);
  assert.equal(L.switchDistrictWording(comparison, cmp), "review");
  assert.equal(L.switchDistrictWording("Show Senate 11 population in 2024.", s11), "single");
});
