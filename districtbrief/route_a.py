"""Prototype A: guided deterministic routing.

Guided input uses the controls as given. Language input accepts only the
documented literal commands below (see COMMAND_HELP); unknown prose returns
``unsupported`` with choices, incomplete commands return ``clarification``.
A fixed route table maps the resolved task to one shared core operation. No
model is ever consulted.
"""

from __future__ import annotations

import re
import unicodedata

from .contract import DEFAULT_SESSION, SESSIONS, TEMPLATES, district_label
from .resolve import COUNTY_NAMES, Outcome, _req, geography_label, resolve_fields

ROUTE_TABLE = {
    # task: (route_id, operation, required arguments)
    "profile": ("A.profile", "profile", ("district",)),
    "compare": ("A.compare", "compare", ("district", "metric_ids", "comparison_geography")),
    "program_relevance": ("A.program_relevance", "program_evidence", ("district", "program_ids")),
    "outreach": ("A.outreach", "outreach_lead", ("district", "program_ids[1]")),
    "administrative_context": ("A.administrative_context", "administrative_evidence", ("observation_ids",)),
    "brief": ("A.brief", "brief", ("district", "selected_finding_ids")),
}

COMMAND_HELP = [
    {"task": "profile", "forms": ["profile house 1", "show profile for senate 1",
                                  "show this district's profile"]},
    {"task": "compare", "forms": ["compare poverty rate all people with state",
                                  "compare median household income with maui county for house 9",
                                  "compare this metric with this geography"]},
    {"task": "program_relevance", "forms": ["program snap for house 1", "explain snap relevance",
                                            "explain this program's relevance"]},
    {"task": "outreach", "forms": ["outreach snap for house 1", "draft an outreach hypothesis for kupuna care",
                                   "draft an outreach hypothesis"]},
    {"task": "brief", "forms": ["brief", "build a brief from these findings"]},
]
COMMAND_RULES = [
    "Districts: 'house 1', 'house district 001', 'hd 1', 'senate 1', 'sd 1'; add 'session 2026' to "
    "name a session (default 2024). A number without House/Senate, or a bare GEOID, asks which chamber.",
    "Measures: the measure name or ID as listed in the catalog (e.g. 'unemployment rate', 'median gross rent').",
    "Comparison geographies: 'state', 'maui county', or a district ('house 9', 'senate 1').",
    "Programs: snap, med-quest (medicaid), hcv (section 8, Honolulu DCS), kupuna care, wic.",
    "Words like 'this district', 'this metric', 'this geography', 'this program', 'these findings' "
    "use the current controls.",
    "Text and changed controls that disagree ask you to choose; text otherwise replaces the previous context.",
]

PROGRAM_ALIASES = {
    "snap_hi": ["snap", "food stamps", "food stamp", "food assistance", "supplemental nutrition assistance program",
                "supplemental nutrition"],
    "medquest_hi": ["med-quest", "medquest", "med quest", "medicaid", "quest integration"],
    "hcv_honolulu": ["hcv", "section 8", "housing choice voucher", "housing choice vouchers", "housing voucher"],
    "kupuna_care_hi": ["kupuna care", "kupuna"],
    "wic_hi": ["wic", "women infants and children"],
}
UNREGISTERED_PROGRAMS = {
    "hpha": "HPHA (Hawaii Public Housing Authority) pages are saved in the packet but no registry record cites "
            "them; Honolulu DCS HCV is a different agency and list.",
    "tanf": "TANF has no program registry record in this packet.",
    "liheap": "LIHEAP has no program registry record in this packet.",
}
METRIC_ALIASES = {
    "households": ["total_households"],
    "population": ["total_population"],
    "seniors": ["population_65_plus"],
    "older adults": ["population_65_plus"],
    "65+": ["population_65_plus"],
    "population 65+": ["population_65_plus"],
    "income": ["median_household_income"],
    "median income": ["median_household_income"],
    "household income": ["median_household_income"],
    "poverty": ["poverty_rate_all_people", "poverty_rate_65_plus"],
    "poverty rate": ["poverty_rate_all_people", "poverty_rate_65_plus"],
    "senior poverty": ["poverty_rate_65_plus"],
    "poverty 65+": ["poverty_rate_65_plus"],
    "poverty rate 65+": ["poverty_rate_65_plus"],
    "unemployment": ["unemployment_rate"],
    "rent": ["median_gross_rent", "rent_35_plus_percent_income", "rent_burden_denominator"],
    "median rent": ["median_gross_rent"],
    "gross rent": ["median_gross_rent"],
    "rent burden": ["rent_35_plus_percent_income", "rent_burden_denominator"],
    "renters": ["renter_occupied_units"],
    "age": ["median_age"],
    "social security": ["households_with_social_security"],
    "labor force": ["civilian_labor_force"],
    "housing units": ["total_housing_units"],
    "living alone": ["male_householder_65_plus_living_alone", "female_householder_65_plus_living_alone"],
    "seniors living alone": ["male_householder_65_plus_living_alone", "female_householder_65_plus_living_alone"],
}
GEO_ALIASES = {
    "state": "HI-STATE-2024", "the state": "HI-STATE-2024", "hawaii": "HI-STATE-2024",
    "state of hawaii": "HI-STATE-2024", "statewide": "HI-STATE-2024",
    "maui county": "HI-COUNTY-009-2024", "maui": "HI-COUNTY-009-2024", "county of maui": "HI-COUNTY-009-2024",
    "hawaii county": "HI-COUNTY-001-2024", "big island": "HI-COUNTY-001-2024", "hawaii island": "HI-COUNTY-001-2024",
    "honolulu county": "HI-COUNTY-003-2024", "honolulu": "HI-COUNTY-003-2024", "oahu": "HI-COUNTY-003-2024",
    "city and county of honolulu": "HI-COUNTY-003-2024",
    "kauai county": "HI-COUNTY-007-2024", "kauai": "HI-COUNTY-007-2024",
    "kalawao county": "HI-COUNTY-005-2024", "kalawao": "HI-COUNTY-005-2024",
}

REFUSALS = [
    ("gap", re.compile(r"\b(gap|gaps|take-?up|uptake|non-?participa\w*|not enrolled|unenrolled|missing out|"
                       r"under-?enrolled|left on the table|participation rate)\b"),
     "No measured district participation gap, take-up rate or eligible-nonparticipant estimate is supported. "
     "Participation counts are state, county or island aggregates and are not allocated to districts."),
    ("eligibility", re.compile(r"\b(eligib\w*|qualif\w*|who can get|entitled)\b"),
     "No individual eligibility determination or eligibility count is made; the administering agency determines "
     "eligibility. Program relevance here is informational."),
    ("intersection", re.compile(r"\b(intersection|overlap of|who are also|who also|that are also|who both|"
                                r"cross-?tab\w*)\b"),
     "The fixture has no published joint statistic for that combination, and it does not invent population "
     "intersections from separate estimates."),
    ("aggregation", re.compile(r"\b(sum|add up|total of|combine\w*|average|averaged|mean of|aggregate\w*)\b"),
     "Combining geographies or measures is not supported: medians are not summed, unweighted percentages are "
     "not averaged and no derived uncertainty replaces published MOEs."),
    ("significance", re.compile(r"\b(significant\w*|significance|statistically|caus\w*|because of)\b"),
     "Point differences of published estimates imply no statistical significance or causality, and no "
     "significance test is run."),
    ("map", re.compile(r"\bmaps?\b|\bmapping\b"),
     "No rendered or interactive map is part of this experiment; geometry is used only for district identity, "
     "session and compatibility checks."),
    ("external", re.compile(r"\b(latest|live|refresh\w*|update the data|download|fetch\w*|browse|google|"
                            r"search the web|web search|census api|sql|database|internet|online data)\b"),
     "Only the frozen packet is read. No live fetching, browsing, Census API queries, source refresh or SQL."),
    ("undefined_population", re.compile(r"\bfixed[\s-]income\b"),
     "Fixed-income status has no defined measured population in this fixture. Households with Social "
     "Security income measures household receipt in the past 12 months, not fixed-income status or an "
     "individual recipient count. Choose a published catalog measure instead."),
]
# A count question that joins two population concepts asks for an unpublished intersection.
POPULATION_CONCEPTS = {
    "older adults": re.compile(r"\b(alone|seniors?|elderly|older adults?|65\+?|kupuna|kūpuna|aged)\b"),
    "poverty/income": re.compile(r"\b(poverty|poor|low.income|fixed.income)\b"),
    "renters": re.compile(r"\b(renters?|rent.burdened|rent burden)\b"),
    "social security": re.compile(r"\bsocial security\b"),
    "unemployed": re.compile(r"\b(unemployed|jobless)\b"),
    "children/families": re.compile(r"\b(children|kids|infants?|pregnant|families)\b"),
}
RE_COUNT_QUESTION = re.compile(r"\b(how many|number of|count of|count|who)\b")
INTERSECTION_REASON = REFUSALS[2][2]


def intersection_concepts(text: str) -> list:
    if not RE_COUNT_QUESTION.search(text):
        return []
    hits = [k for k, p in POPULATION_CONCEPTS.items() if p.search(text)]
    return hits if len(hits) >= 2 else []


TASK_VERBS = [
    ("brief", re.compile(r"^(build (a |the )?brief|brief|make (a |the )?brief|create (a |the )?brief)\b")),
    ("outreach", re.compile(r"^(draft (an |the |a )?outreach( hypothesis| lead)?|outreach( hypothesis| lead)?)\b")),
    ("program_relevance", re.compile(r"^(explain|program|programs|relevance of|show program)\b")),
    ("compare", re.compile(r"^(compare|comparison)\b")),
    ("profile", re.compile(r"^(show|profile|open profile|district profile)\b")),
]

RE_DISTRICT = re.compile(
    r"\b(?:(house|senate|hd|sd)\s*(?:district\s*|dist\.?\s*|#\s*)?(\d{1,3})|(?:district|dist\.?)\s*#?\s*(\d{1,3}))"
    r"(?:\s*\(?\s*(?:boundary\s*)?session\s*(\d{4})\)?|\s*\((\d{4})\))?\b")
RE_SESSION_ONLY = re.compile(r"\b(?:(?:boundary\s*)?session\s*(\d{4})|(\d{4})\s*(?:boundary\s*)?session)\b")
RE_GEOID = re.compile(r"\b(?:geoid\s*)?(15\d{3})\b")


def normalize(text: str) -> str:
    t = unicodedata.normalize("NFKD", text)
    t = "".join(c for c in t if not unicodedata.combining(c)).replace("ʻ", "").replace("‘", "").replace("’", "'")
    t = t.lower().strip()
    t = re.sub(r"[?!.;:,]+$", "", t)
    t = re.sub(r"[,;]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def guided_fields(request: dict) -> dict:
    return {k: request.get(k) for k in ("task", "district", "metric_ids", "comparison_geography",
                                        "program_ids", "observation_ids", "selected_finding_ids", "edits", "clarification_choices")}


def _district_from_match(m) -> dict:
    chamber_tok, num1, num2, s1, s2 = m.groups()
    chamber = None
    if chamber_tok:
        chamber = "house" if chamber_tok in ("house", "hd") else "senate"
    num = num1 or num2
    session = int(s1 or s2) if (s1 or s2) else None
    return {"state_fips": "15", "chamber": chamber, "code": f"{int(num):03d}", "boundary_session": session}


def _same_district(a, b) -> bool:
    if not a or not b:
        return False
    return (a.get("chamber"), a.get("code"), a.get("boundary_session") or DEFAULT_SESSION) == \
           (b.get("chamber"), b.get("code"), b.get("boundary_session") or DEFAULT_SESSION)


def _match_metric(core, phrase: str):
    p = phrase.strip()
    p = re.sub(r"^(the|a|an)\s+", "", p)
    if not p:
        return []
    if p.replace(" ", "_") in core.metrics:
        return [p.replace(" ", "_")]
    exact = [mid for mid, m in core.metrics.items() if normalize(m["label"]) == p]
    if exact:
        return exact
    if p in METRIC_ALIASES:
        return METRIC_ALIASES[p]
    cands = [mid for mid, m in core.metrics.items()
             if p in normalize(m["label"]) or p in mid.replace("_", " ")]
    return cands


def _match_programs(text: str) -> tuple[list, list]:
    found, unreg = [], []
    for pid, aliases in PROGRAM_ALIASES.items():
        for a in aliases:
            if re.search(rf"(?<![a-z]){re.escape(a)}(?![a-z])", text):
                found.append(pid)
                break
    for key, reason in UNREGISTERED_PROGRAMS.items():
        if re.search(rf"\b{key}\b", text):
            unreg.append(reason)
    return found, unreg


def _match_geo(core, phrase: str):
    """Return (geography_id | None, kind) where kind is 'geo', 'metric', 'ambiguous' or 'none'."""
    p = re.sub(r"^(the|a)\s+", "", phrase.strip())
    p = re.sub(r"\s+(for|in|of)\s+.*$", "", p) if p not in GEO_ALIASES else p
    if p in GEO_ALIASES:
        return GEO_ALIASES[p], "geo"
    if p == "this geography":
        return None, "controls"
    m = RE_DISTRICT.search(p)
    if m and m.group(0).strip() == p.strip():
        d = _district_from_match(m)
        if not d["chamber"]:
            return d, "district_without_chamber"
        return core.profile_id_for(d["chamber"], d["code"], d["boundary_session"] or DEFAULT_SESSION), "geo"
    if p in ("county", "the county", "its county", "county level"):
        return None, "county_ambiguous"
    if _match_metric(core, p):
        return None, "metric"
    return None, "none"


def _unresolved(task, controls, notes, label="Not resolved", unresolved=("utterance",)):
    return {"resolved": False, "task": task, "template": TEMPLATES.get(task), "operation": None,
            "district": (controls or {}).get("district"), "district_label": label, "geography_id": None,
            "args": {}, "input_source": "literal_command", "defaults_applied": [], "notes": notes,
            "unresolved": list(unresolved)}


def _find_district(segment: str):
    """Return (district | None, geoid | None, matched_text)."""
    if not segment:
        return None, None, ""
    m = RE_DISTRICT.search(segment)
    if m:
        d = _district_from_match(m)
        if d["boundary_session"] is None:
            sm = RE_SESSION_ONLY.search(segment)
            if sm:
                d["boundary_session"] = int(sm.group(1) or sm.group(2))
        return d, None, m.group(0)
    g = RE_GEOID.search(segment)
    if g:
        return None, g.group(1), g.group(0)
    return None, None, ""


def language_guard(core, request):
    """Return the literal outcome and its deterministic preemption decision."""
    outcome = route_language(core, request)
    notes = (outcome.resolution or {}).get("notes") or []
    refusals = [n.removeprefix("Refusal category: ") for n in notes if n.startswith("Refusal category:")]
    return outcome, refusals, bool(refusals) or outcome.status == "clarification"


def route_language(core, request: dict) -> Outcome:
    text = normalize(request["utterance"])
    controls = guided_fields(request)
    shown = request.get("displayed_context") or {}
    notes = [f"Literal command parsed from: “{request['utterance']}”"]
    programs, unregistered = _match_programs(text)

    def unsupported(reason, choices, task=None, *, reason_id):
        return Outcome("unsupported", _unresolved(task, controls, notes), reason=reason, reason_id=reason_id, next_actions=choices)

    # -- task verb ---------------------------------------------------------
    task, rest = None, text
    for t, pattern in TASK_VERBS:
        m = pattern.match(text)
        if m:
            task, rest = t, text[m.end():].strip()
            break
    if task == "profile" and text.startswith("show") and "profile" not in text:
        task, rest = None, text  # 'show …' is a profile command only when it says profile
    if task is None and re.search(r"\brelevan\w*\b", text) and programs:
        task, rest = "program_relevance", re.sub(r"\brelevan\w*\b", " ", text).strip()
    if task is None and re.search(r"\bprofile\b", text):
        task, rest = "profile", re.sub(r"\bprofile\b", " ", text).strip()

    # -- segments: compare has '<measure> with <geography> [for <district>]' -
    measure_seg = geo_seg = None
    district_seg = rest
    if task == "compare":
        m = re.match(r"^(.*?)\s+(?:with|to|against|vs\.?|versus)\s+(.*?)(?:\s+(?:for|in)\s+(.+))?$", rest)
        if m:
            measure_seg, geo_seg, district_seg = m.group(1).strip(), m.group(2).strip(), (m.group(3) or "")
        else:
            m2 = re.match(r"^(.*?)(?:\s+(?:for|in)\s+(.+))?$", rest)
            measure_seg, district_seg = m2.group(1).strip(), (m2.group(2) or "")
    text_district, geoid, dtext = _find_district(district_seg)
    if task == "compare" and text_district is None and geoid is None and measure_seg:
        text_district, geoid, dtext = _find_district(measure_seg)
        if dtext:
            measure_seg = measure_seg.replace(dtext, " ").strip()
    if text_district is None and geoid is None and task in ("profile", "program_relevance", "outreach", "brief"):
        bare = re.search(r"(?:^|\b(?:for|in)\s+)(\d{1,3})$", district_seg)  # 'profile 1' → which chamber?
        if bare:
            text_district = {"state_fips": "15", "chamber": None, "code": f"{int(bare.group(1)):03d}",
                             "boundary_session": None}
            dtext = bare.group(0)

    def supported_choices():
        d = text_district if text_district and text_district.get("chamber") and (
            text_district.get("boundary_session") in (None,) + SESSIONS) else controls.get("district")
        base = dict(controls, district=d)
        out = [{"label": label, "request": _req(base, task=t)} for t, label in TEMPLATES.items()]
        if programs:
            out.insert(0, {"label": f"Explain {core.programs[programs[0]]['name']} relevance",
                           "request": _req(base, task="program_relevance", program_ids=[programs[0]])})
        return out

    # -- refusals come before any routing ----------------------------------
    for key, pattern, reason in REFUSALS:
        if pattern.search(text):
            # Informational program/outreach tasks can explain the undefined category;
            # a count request must not turn it into a measured population.
            if key == "undefined_population" and task in ("program_relevance", "outreach") and not RE_COUNT_QUESTION.search(text):
                continue
            notes.append(f"Refusal category: {key}")
            return unsupported(reason, supported_choices(), reason_id={"gap": "participation_gap", "external": "external_data"}.get(key, key))
    concepts = intersection_concepts(text)
    if concepts:
        notes.append(f"Refusal category: intersection ({' + '.join(concepts)})")
        choices = supported_choices()
        if "older adults" in concepts and "poverty/income" in concepts:
            d = text_district if text_district and text_district.get("chamber") else controls.get("district")
            choices.insert(0, {"label": "Compare the published poverty rate, age 65 and over, with the state",
                               "request": _req(dict(controls, district=d), task="compare",
                                               metric_ids=["poverty_rate_65_plus"],
                                               comparison_geography="HI-STATE-2024")})
        return unsupported(INTERSECTION_REASON, choices, reason_id="intersection")

    if task is None:
        reason = ("This typed request is not one of the documented literal commands, so Prototype A does not "
                  "interpret it. Choose a supported task below or type a command such as 'profile house 1'.")
        if unregistered:
            reason = unregistered[0] + " " + reason
        return unsupported(reason, supported_choices(), reason_id="unregistered_program" if unregistered else "complex_request")

    # -- 1. parse the complete typed intent before any resolution -------------------------------
    # named: exact typed values (a district may be partial: no chamber, or a GEOID only).
    # candidates: finite alternatives of an ambiguously typed compare field (carried as
    # clarification_choices so each later question keeps every other stated fact).
    named, candidates, invalid = {}, {}, None
    if geoid:
        named["district"] = {"state_fips": "15", "geoid": geoid}
    elif text_district:
        if text_district["boundary_session"] is not None and text_district["boundary_session"] not in SESSIONS:
            invalid = ("district", text_district)
        named["district"] = dict(text_district)
    leftover_text = (district_seg.replace(dtext, " ") if dtext else district_seg)
    leftover_text = re.sub(r"\s+", " ", re.sub(r"\b(for|in|of)\s*$", "", leftover_text)).strip()

    if task == "compare":
        # Do not turn an unconsumed second geography into a missing-field question or
        # silently replace it with a control. B may interpret wording outside A's forms.
        extra = re.sub(r"\b(the|this|selected|district|for|in|of)\b", " ", leftover_text).strip()
        if extra:
            return unsupported("This comparison wording is outside the documented literal command forms. "
                               "Use 'compare <measure> with <geography> for <district>'.",
                               supported_choices(), task, reason_id="complex_request")
        ms = re.sub(r"^(this|the selected|selected)\s+(metric|measure)$", "this metric", measure_seg or "")
        if ms and ms not in ("this metric", "it"):
            mids = _match_metric(core, ms)
            if not mids:
                return unsupported(f"“{ms}” is not a measure in the catalog.", supported_choices(), task, reason_id="unresolved_referent")
            if len(mids) > 1:
                candidates["metric_ids"] = mids
            else:
                named["metric_ids"] = mids
        if geo_seg is not None:
            gid, kind = _match_geo(core, geo_seg)
            if kind == "geo":
                named["comparison_geography"] = gid
            elif kind == "metric":
                notes.append("Refusal category: incompatible_comparison")
                return unsupported(
                    "Comparisons require the same measure, universe, unit and period in two geographies; two "
                    "different measures cannot be compared with each other.",
                    [{"label": f"Compare {core.metrics[m]['label']} with the state",
                      "request": _req({"district": controls.get("district")}, task="compare", metric_ids=[m],
                                      comparison_geography="HI-STATE-2024")}
                     for m in (named.get("metric_ids") or [])] + supported_choices(), task, reason_id="unsupported_operation")
            elif kind == "district_without_chamber":
                session = gid["boundary_session"] or DEFAULT_SESSION
                if session not in SESSIONS:
                    invalid = invalid or ("comparison_geography", gid)
                else:
                    ids = [core.profile_id_for(ch, gid["code"], session) for ch in ("house", "senate")
                           if core.geo.get(ch, gid["code"], session)]
                    if not ids:
                        return unsupported(f"District {gid['code']} does not exist in the {session} boundary "
                                           "layers. No data was queried.", supported_choices(), task, reason_id="unresolved_referent")
                    candidates["comparison_geography"] = ids
            elif kind == "county_ambiguous":
                candidates["comparison_geography"] = [f"HI-COUNTY-{c}-{DEFAULT_SESSION}" for c in COUNTY_NAMES]
            elif kind != "controls":
                return unsupported(f"“{geo_seg}” is not a comparison geography in this fixture.",
                                   supported_choices(), task, reason_id="unresolved_referent")
    elif task in ("program_relevance", "outreach"):
        if programs:
            named["program_ids"] = programs
        elif unregistered:
            return unsupported(unregistered[0], supported_choices(), task, reason_id="unregistered_program")
        else:
            left = re.sub(r"\b(this|program'?s?|relevance|hypothesis|lead|an|a|the|for|of|explain|draft)\b",
                          " ", leftover_text).strip()
            if left:
                return unsupported(f"“{left}” is not a program in the registry.", supported_choices(), task, reason_id="unregistered_program")
    elif task == "profile":
        left = re.sub(r"\b(the|this|district'?s?|profile|for|of|show)\b", " ", leftover_text).strip()
        if left:
            return unsupported(f"“{left}” is not part of a profile command.", supported_choices(), task, reason_id="complex_request")
    elif task == "brief":
        left = re.sub(r"\b(from|these|this|the|selected|findings?|a|for|of)\b", " ", leftover_text).strip()
        if left:
            return unsupported(f"“{left}” is not part of a brief command.", supported_choices(), task, reason_id="complex_request")

    # -- 2. one draft: baseline (current control, else displayed context), typed facts overlaid ---
    # A field the text named — exactly, partially or ambiguously — is owned by the text: no stale
    # baseline value survives for it.
    current = _applicable(controls, task)
    draft, reused = {"task": task}, []
    for f in APPLICABLE[task]:
        if f in named or f in candidates:
            continue
        if f in current:
            draft[f] = current[f]
        elif f == "district" and (shown.get("district") or {}).get("code") or f != "district" and shown.get(f):
            draft[f] = shown[f]
            reused.append(f)
    draft.update(named)
    if candidates:
        draft["clarification_choices"] = dict(candidates)
    if task == "brief":
        draft["edits"] = controls.get("edits")
    for f in reused:
        notes.append(f"{FIELD_LABELS[f].capitalize()} reused from the displayed context.")

    if invalid:
        return _invalid_session(core, task, draft, notes, invalid, supported_choices)

    # -- 3. shared context rule on the complete draft --------------------------------------------
    # A control changed since the displayed context (control ≠ displayed) that is incompatible with the
    # typed value → one clarification. Each choice settles only the conflicted fields and keeps every
    # other typed fact, candidate set and reused default.
    conflicts = []
    for f in APPLICABLE[task]:
        if f not in current or (f not in named and f not in candidates):
            continue
        ctrl, prior = current[f], shown.get(f)
        changed = (not _same_district(ctrl, prior)) if f == "district" else ctrl != prior
        if not changed:
            continue
        if f == "district":
            compatible = _district_compatible(core, named[f], ctrl)
        elif f in candidates:
            compatible = (ctrl in candidates[f]) if f == "comparison_geography" else (
                len(ctrl) == 1 and ctrl[0] in candidates[f])
        else:
            compatible = named[f] == ctrl
        if not compatible:
            conflicts.append(f)
    if conflicts:
        typed = dict(draft)
        kept = dict(draft, **{f: current[f] for f in conflicts})
        kept_cands = {k: v for k, v in candidates.items() if k not in conflicts}
        kept.pop("clarification_choices", None)
        if kept_cands:
            kept["clarification_choices"] = kept_cands

        def desc(branch):
            out = []
            for f in conflicts:
                if f in (branch.get("clarification_choices") or {}):
                    out.append("one of " + ", ".join(_describe(core, f, [c] if f == "metric_ids" else c)
                                                     for c in branch["clarification_choices"][f]))
                else:
                    out.append(_describe(core, f, branch[f]))
            return "; ".join(out)
        return Outcome("clarification", _unresolved(task, controls, notes, "Typed command and controls differ",
                                                    conflicts),
                       clarification={
                           "field": ",".join(conflicts), "reason": "control_conflict",
                           "candidates": candidates,
                           "question": "The typed command and the controls you changed disagree on "
                                       + ", ".join(FIELD_LABELS[f] for f in conflicts) + ". Which should be used?",
                           "choices": [{"label": f"Use the typed command ({desc(typed)})", "request": _req(typed)},
                                       {"label": f"Use the current controls ({desc(kept)})", "request": _req(kept)}]})

    # -- 4. the shared resolver asks any remaining question (district → session → candidates → missing
    # fields → comparison session) with self-contained choices; it executes only when all are canonical.
    outcome = resolve_fields(core, draft, input_source="literal_command", notes=notes)
    if outcome.status == "unsupported":
        outcome.resolution["notes"].append("Refusal category: unsupported_context")
    return outcome


def _district_compatible(core, typed: dict, ctrl: dict) -> bool:
    """A typed (possibly partial) district conflicts with a control only on the components it states."""
    if typed.get("geoid") and not typed.get("code"):
        rec = core.geo.get(ctrl.get("chamber"), ctrl.get("code"), ctrl.get("boundary_session") or DEFAULT_SESSION)
        return bool(rec) and rec["geoid"] == typed["geoid"]
    if typed.get("code") != ctrl.get("code"):
        return False
    if typed.get("chamber") and typed["chamber"] != ctrl.get("chamber"):
        return False
    if typed.get("boundary_session") and typed["boundary_session"] != (ctrl.get("boundary_session") or DEFAULT_SESSION):
        return False
    return True

APPLICABLE = {
    "profile": ("district",),
    "compare": ("district", "metric_ids", "comparison_geography"),
    "program_relevance": ("district", "program_ids"),
    "outreach": ("district", "program_ids"),
    "administrative_context": ("observation_ids",),
    "brief": ("district", "selected_finding_ids"),
}
FIELD_LABELS = {"district": "district", "metric_ids": "measure", "comparison_geography": "comparison geography",
                "program_ids": "program", "observation_ids": "administrative observation", "selected_finding_ids": "selected findings"}


def _applicable(controls: dict, task: str) -> dict:
    """Non-empty current control values that apply to the task."""
    out = {}
    for f in APPLICABLE.get(task, ()):
        v = controls.get(f)
        if f == "district":
            if v and v.get("code"):
                out[f] = {k: v.get(k) for k in ("state_fips", "chamber", "code", "boundary_session")}
        elif v:
            out[f] = v
    return out


def _canon(value):
    if isinstance(value, dict) and "code" in value:
        return dict(value, boundary_session=value.get("boundary_session") or DEFAULT_SESSION)
    return value


def _describe(core, field, value) -> str:
    if field == "district":
        if value.get("geoid") and not value.get("code"):
            return f"GEOID {value['geoid']} (chamber not yet chosen)"
        if not value.get("chamber"):
            sess = value.get("boundary_session")
            return f"District {value['code']}" + (f" (boundary session {sess})" if sess else "") + \
                " (chamber not yet chosen)"
        return district_label(_canon(value))
    if field == "metric_ids":
        return ", ".join(core.metrics[m]["label"] if m in core.metrics else m for m in value)
    if field == "program_ids":
        return ", ".join(core.programs[p]["name"] if p in core.programs else p for p in value)
    if field == "comparison_geography":
        return geography_label(core, value)
    return str(value)


def _invalid_session(core, task, draft, notes, invalid, supported_choices) -> Outcome:
    """A typed boundary session outside the packet: structured refusal, no core query. The explicit 2024
    alternative keeps every other typed fact and candidate set of the draft."""
    field, d = invalid
    s = d["boundary_session"]
    choices = []
    if d.get("chamber"):
        alt = {"state_fips": "15", "chamber": d["chamber"], "code": d["code"], "boundary_session": DEFAULT_SESSION}
        if core.geo.get(alt["chamber"], alt["code"], DEFAULT_SESSION):
            if field == "comparison_geography":
                choices.append({"label": f"Compare with {district_label(alt)}",
                                "request": _req(draft, comparison_geography=core.profile_id_for(
                                    alt["chamber"], alt["code"], DEFAULT_SESSION))})
            else:
                choices.append({"label": f"Use {district_label(alt)}", "request": _req(draft, district=alt)})
    reason = (f"Boundary session {s} is not in this packet. Boundary layers exist for sessions 2024 and 2026; "
              "ACS 2020–2024 statistics are tabulated on the 2024 session. No data was queried.")
    res = _unresolved(task, {"district": draft.get("district")},
                      notes + [f"Invalid boundary session {s}", "Refusal category: unsupported_context"],
                      "Not resolved", [field if field == "comparison_geography" else "district.boundary_session"])
    return Outcome("unsupported", res, reason=reason, reason_id="unavailable_geography", next_actions=choices + supported_choices())


def route(core, request: dict) -> Outcome:
    if request["input_mode"] == "guided":
        outcome = resolve_fields(core, guided_fields(request), input_source="guided_controls")
    else:
        outcome = route_language(core, request)
    if outcome.resolution and outcome.resolution.get("task") in ROUTE_TABLE:
        route_id, _, required = ROUTE_TABLE[outcome.resolution["task"]]
        outcome.resolution["route_id"] = route_id
        outcome.resolution["route_required"] = list(required)
    return outcome
