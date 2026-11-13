"""Shared canonical resolution of task fields (no core query).

Given explicit field values (from guided controls, or from an adapter's reading
of typed input) this decides whether the request is resolved, needs
clarification or is unsupported. It consults only catalog metadata (IDs that
exist), never an analytical operation, so a clarification costs no core query.

Choices and next actions are complete guided requests: ``{"label", "request"}``.
"""

from __future__ import annotations

import re

from .contract import DEFAULT_SESSION, SESSIONS, TASK_TO_OPERATION, TEMPLATES, district_label


class Outcome:
    def __init__(self, status, resolution, *, clarification=None, reason=None, reason_id=None, next_actions=None):
        self.status = status          # resolved | clarification | unsupported
        self.resolution = resolution
        self.clarification = clarification
        self.reason = reason
        self.reason_id = reason_id
        self.next_actions = next_actions or []


APPLICABLE_FIELDS = {
    "profile": ("district", "metric_ids"),
    "compare": ("district", "metric_ids", "comparison_geography", "clarification_choices"),
    "program_relevance": ("district", "program_ids"),
    "outreach": ("district", "program_ids"),
    "administrative_context": ("observation_ids",),
    "brief": ("district", "selected_finding_ids", "edits"),
}
RE_GEO_ID = re.compile(r"^HI-(STATE|COUNTY|HOUSE|SENATE)(?:-(\d{3}))?-(\d{4})$")


def _req(fields: dict, **over) -> dict:
    """A complete, self-contained guided request carrying only the fields that apply to its task.

    Choices are the whole continuation (the client does not merge controls), so every stated field
    and every still-open candidate set (``clarification_choices``) must travel in the request. A
    candidate entry is dropped once its field holds a chosen canonical value: answering one question
    removes only that question's candidates.
    """
    r = {k: fields.get(k) for k in ("task", "district", "metric_ids", "comparison_geography",
                                    "program_ids", "observation_ids", "selected_finding_ids", "edits", "clarification_choices")}
    r.update(over)
    keep = APPLICABLE_FIELDS.get(r.get("task"))
    if keep is not None:
        r = {k: v for k, v in r.items() if k == "task" or k in keep}
    cand = {k: list(v) for k, v in (r.get("clarification_choices") or {}).items() if v and not r.get(k)}
    r["clarification_choices"] = cand
    return {k: v for k, v in r.items() if v not in (None, [], {})}


COUNTY_NAMES = {"001": "Hawaii County", "003": "Honolulu County", "005": "Kalawao County", "007": "Kauai County",
                "009": "Maui County"}


def geography_label(core, gid: str) -> str:
    if gid in core.profiles:
        return core.profiles[gid]["label"]
    m = RE_GEO_ID.match(gid)
    if m and m.group(1) in ("HOUSE", "SENATE"):
        return district_label({"chamber": m.group(1).lower(), "code": m.group(2), "boundary_session": int(m.group(3))})
    if m and m.group(1) == "COUNTY":
        return f"{COUNTY_NAMES.get(m.group(2), 'County ' + m.group(2))} (not normalized in this fixture)"
    return gid


def district_choices(core, fields: dict, chambers=("house", "senate"), code=None, geoid=None, session=None) -> list:
    out = []
    session = session or DEFAULT_SESSION
    if geoid:
        recs = [r for r in core.geo.find_by_geoid(geoid) if r["boundary_session"] == session]
    elif code:
        recs = [r for r in (core.geo.get(c, code, session) for c in chambers) if r]
    else:
        recs = [r for r in core.geo.list(session=session) if r["chamber"] in chambers
                and core.has_statistics(r["chamber"], r["code"], DEFAULT_SESSION)]
    for r in recs:
        d = {"state_fips": "15", "chamber": r["chamber"], "code": r["code"], "boundary_session": session}
        out.append({"label": district_label(d) + ("" if core.has_statistics(r["chamber"], r["code"], DEFAULT_SESSION)
                                                  else " — no normalized statistics"),
                    "request": _req(fields, district=d)})
    return out


def resolve_fields(core, fields: dict, *, input_source: str, notes=None) -> Outcome:
    """fields: task, district, metric_ids, comparison_geography, program_ids, selected_finding_ids, edits."""
    task = fields.get("task")
    district = dict(fields.get("district") or {})
    res = {
        "resolved": False,
        "task": task,
        "template": TEMPLATES.get(task),
        "operation": TASK_TO_OPERATION.get(task),
        "district": None,
        "district_label": "No district resolved",
        "geography_id": None,
        "args": {},
        "input_source": input_source,
        "defaults_applied": [],
        "notes": list(notes or []),
        "unresolved": [],
    }

    restrictions = fields.get("clarification_choices") or {}
    accepted = {"metric_ids": set(core.metrics), "comparison_geography": {
        core.profile_id_for(d["chamber"], d["code"], d["boundary_session"]) for d in core.geo.list()}
        | set(core.profiles) | {f"HI-COUNTY-{c}-{DEFAULT_SESSION}" for c in COUNTY_NAMES}}
    restrictions = {k: [v for v in values if v in accepted[k]] for k, values in restrictions.items()
                    if k in accepted and values and not fields.get(k)}
    if any(not values for values in restrictions.values()):
        return Outcome("unsupported", res, reason="None of the candidates is in the catalog.",
                       reason_id="unresolved_referent")
    fields = dict(fields, clarification_choices=restrictions)

    def clarify(field, question, choices, *, reason="missing_information", candidates=None, semantic_field=None):
        res["unresolved"].append(field)
        return Outcome("clarification", res, clarification={"field": field, "question": question,
                                                             "choices": choices, "reason": reason,
                                                             "candidates": restrictions if candidates is None else candidates,
                                                             **({"semantic_field": semantic_field} if semantic_field else {})})

    if task is not None and task not in TASK_TO_OPERATION:
        return Outcome("unsupported", res, reason="Unknown task.", reason_id="unsupported_operation")

    # Administrative rows retain their own geography. District is brief context only.
    if task == "administrative_context":
        ids = list(fields.get("observation_ids") or [])
        unknown = [oid for oid in ids if oid not in core.administrative_rows]
        if unknown:
            return Outcome("unsupported", res, reason="Unknown administrative observation ID(s): " + ", ".join(unknown) + ".", reason_id="unavailable_observation")
        if not ids:
            return clarify("observation_ids", "Which recorded administrative observation(s)? Choose up to eight exact rows.",
                           [{"label": core.admin_label(oid), "request": _req(fields, observation_ids=[oid])}
                            for oid in core.administrative_rows])
        if len(ids) > 8:
            return Outcome("unsupported", res, reason="At most eight administrative observations may be inspected per Run.", reason_id="unsupported_operation")
        res["args"] = {"observation_ids": list(dict.fromkeys(ids))}
        res["resolved"] = True
        return Outcome("resolved", res)

    # -- district --------------------------------------------------------
    sess = district.get("boundary_session")
    if sess is not None and (type(sess) is not int or sess not in SESSIONS):
        alt = None
        if district.get("chamber") and district.get("code") and core.geo.get(district["chamber"], district["code"],
                                                                              DEFAULT_SESSION):
            alt = dict(district, state_fips="15", boundary_session=DEFAULT_SESSION)
            alt.pop("geoid", None)
        res["unresolved"].append("district.boundary_session")
        return Outcome("unsupported", res,
                       reason_id="unavailable_geography", reason=f"Boundary session {sess!r} is not in this packet. Boundary layers exist for sessions "
                              "2024 and 2026; ACS 2020–2024 statistics are tabulated on the 2024 session. "
                              "No data was queried.",
                       next_actions=([{"label": f"Use {district_label(alt)}", "request": _req(fields, district=alt)}]
                                     if alt else []) + district_choices(core, fields))
    if district.get("geoid") and not (district.get("chamber") and district.get("code")):
        g = district["geoid"]
        return clarify("district.chamber",
                       f"GEOID {g} alone is ambiguous: House and Senate districts share GEOIDs "
                       f"(and county GEOIDs can match too). Which district do you mean?",
                       district_choices(core, fields, geoid=g, session=district.get("boundary_session")),
                       reason="ambiguous_referent")
    if not district.get("code"):
        if not task:
            pass  # task clarification below covers both
        else:
            return clarify("district", "Which district? Choose chamber and district number.",
                           district_choices(core, fields,
                                            chambers=(district["chamber"],) if district.get("chamber") else ("house", "senate"),
                                            session=district.get("boundary_session")))
    elif not district.get("chamber"):
        return clarify("district.chamber",
                       f"District {district['code']} exists in both chambers. House or Senate?",
                       district_choices(core, fields, code=district["code"],
                                        session=district.get("boundary_session")), reason="ambiguous_referent")
    if district.get("code"):
        if district.get("boundary_session") is None:
            district["boundary_session"] = DEFAULT_SESSION
            res["defaults_applied"].append(f"boundary_session={DEFAULT_SESSION}")
        if district.get("state_fips") is None:
            district["state_fips"] = "15"
            res["defaults_applied"].append("state_fips=15")
        district.pop("geoid", None)
        res["district"] = district
        res["district_label"] = district_label(district)
        rec = core.geo.get(district["chamber"], district["code"], district["boundary_session"])
        if rec is None:
            n = core.geo.count()[str(district["boundary_session"])][district["chamber"]]
            return Outcome("unsupported", res,
                           reason_id="unresolved_referent", reason=f"{res['district_label']} does not exist: the {district['chamber']} layer for "
                                  f"session {district['boundary_session']} has districts 001–{n:03d}.",
                           next_actions=district_choices(core, fields))
        if district["boundary_session"] != DEFAULT_SESSION:
            same = core.geo.geometry_equal_across_sessions(district["chamber"], district["code"])
            alt = dict(district, boundary_session=DEFAULT_SESSION)
            if same:
                return clarify(
                    "district.boundary_session",
                    f"ACS 2020–2024 statistics are tabulated on the 2024 boundary session. The saved "
                    f"{district['boundary_session']} geometry for {district['chamber'].capitalize()} District "
                    f"{district['code']} equals the 2024 geometry at supplied precision (not a legal "
                    f"certification). Use the 2024-session statistics?",
                    [{"label": district_label(alt), "request": _req(fields, district=alt)}],
                    reason="boundary_compatibility")
            return Outcome("unsupported", res,
                           reason_id="boundary_compatibility", reason=f"{res['district_label']} geometry differs from 2024; ACS 2024 statistics "
                                  "cannot be assigned to it.",
                           next_actions=[{"label": district_label(alt), "request": _req(fields, district=alt)}])
        res["geography_id"] = core.profile_id_for(district["chamber"], district["code"], DEFAULT_SESSION)

    # -- task ------------------------------------------------------------
    if not task:
        return clarify("task", "Which task?",
                       [{"label": label, "request": _req(fields, task=t, district=res["district"] or district)}
                        for t, label in TEMPLATES.items()])
    res["template"] = TEMPLATES[task]
    res["operation"] = TASK_TO_OPERATION[task]
    base = dict(fields, district=res["district"])

    metric_ids = list(fields.get("metric_ids") or [])
    program_ids = list(fields.get("program_ids") or [])
    unknown_m = [m for m in metric_ids if m not in core.metrics]
    unknown_p = [p for p in program_ids if p not in core.programs]

    if task in ("profile", "compare", "outreach") and unknown_m:
        return Outcome("unsupported", res, reason_id="unresolved_referent", reason=f"Unknown measure ID(s): {', '.join(unknown_m)}.",
                       next_actions=[{"label": f"Use {m['label']}", "request": _req(base, metric_ids=[m["metric_id"]])}
                                     for m in core.metrics.values()][:6])
    if task in ("program_relevance", "outreach") and unknown_p:
        return Outcome("unsupported", res,
                       reason_id="unregistered_program", reason=f"No program registry record for: {', '.join(unknown_p)}. Registry programs: "
                              + ", ".join(p["name"] for p in core.programs.values()) + ".",
                       next_actions=[{"label": f"Explain {p['name']} relevance",
                                      "request": _req(base, task="program_relevance", program_ids=[pid])}
                                     for pid, p in core.programs.items()])

    if task == "profile":
        res["args"] = {"profile_id": res["geography_id"]}
        if metric_ids:
            res["args"]["metric_ids"] = metric_ids
    elif task == "compare":
        cand = restrictions
        base = dict(base, clarification_choices=cand)
        if cand.get("metric_ids"):
            options = cand["metric_ids"]
            return clarify("metric_ids", "The typed measure matches several measures. Which one?",
                           [{"label": core.metrics[m]["label"], "request": _req(base, metric_ids=[m])}
                            for m in options], reason="ambiguous_referent", candidates=cand)
        if cand.get("comparison_geography"):
            parts = [RE_GEO_ID.match(g) for g in cand["comparison_geography"]]
            if all(p and p.group(1) in ("HOUSE", "SENATE") for p in parts) and \
                    len({(p.group(2), p.group(3)) for p in parts}) == 1:
                question = (f"Comparison district {parts[0].group(2)} (boundary session {parts[0].group(3)}) "
                            "exists in both chambers. House or Senate?" if len(parts) > 1 else
                            f"Comparison district {parts[0].group(2)} exists only as "
                            f"{geography_label(core, cand['comparison_geography'][0])}. Use it?")
            elif all(p and p.group(1) == "COUNTY" for p in parts):
                question = "Which county? Only Maui County has normalized statistics in this fixture."
            else:
                question = "Which comparison geography did you mean?"
            return clarify("comparison_geography", question,
                           [{"label": geography_label(core, g), "request": _req(base, comparison_geography=g)}
                            for g in cand["comparison_geography"]],
                           reason="ambiguous_referent", candidates=cand)
        if not metric_ids:
            return clarify("metric_ids", "Which measure should be compared?",
                           [{"label": m["label"], "request": _req(base, metric_ids=[m["metric_id"]])}
                            for m in core.metrics.values()])
        cg = fields.get("comparison_geography")
        if not cg:
            return clarify("comparison_geography", "Compare with which geography?",
                           [{"label": core.profiles[p]["label"], "request": _req(base, comparison_geography=p)}
                            for p in core.comparison_choices(res["geography_id"])])
        check = _check_comparison_geography(core, cg, base, res)
        if check is not None:
            return check
        res["args"] = {"profile_id": res["geography_id"], "metric_ids": metric_ids, "comparison_geography": cg}
    elif task == "program_relevance":
        if not program_ids:
            return clarify("program_ids", "Which program?",
                           [{"label": p["name"], "request": _req(base, program_ids=[pid])}
                            for pid, p in core.programs.items()])
        res["args"] = {"profile_id": res["geography_id"], "program_ids": program_ids}
    elif task == "outreach":
        if metric_ids:
            canonical = {k: v for k, v in base.items() if k != "metric_ids"}
            res["unresolved"].append("metric_ids")
            return Outcome(
                "unsupported", res, reason_id="unsupported_operation",
                reason="An outreach hypothesis always uses the full reviewed measure set for its program, so its "
                       "finding ID always means the same facts. Measure subsets are not supported; run it without "
                       "a measure, or compare a single measure instead.",
                next_actions=[{"label": "Draft the outreach hypothesis (full reviewed measure set)",
                               "request": _req(canonical, task="outreach")}]
                + [{"label": f"Compare {core.metrics[m]['label']} with the State of Hawaiʻi",
                    "request": _req(base, task="compare", metric_ids=[m], comparison_geography="HI-STATE-2024")}
                   for m in metric_ids if m in core.metrics][:3])
        if len(program_ids) != 1:
            return clarify("program_ids",
                           "An outreach hypothesis covers one program. Which program?",
                           [{"label": p["name"], "request": _req(base, program_ids=[pid])}
                            for pid, p in core.programs.items() if not program_ids or pid in program_ids],
                           reason="ambiguous_referent" if program_ids else "missing_information",
                           candidates={"program_ids": program_ids} if program_ids else {})
        res["args"] = {"profile_id": res["geography_id"], "program_id": program_ids[0]}
    elif task == "brief":
        fids = list(fields.get("selected_finding_ids") or [])
        if not fids:
            return clarify("selected_finding_ids",
                           "Select at least one finding (profile row, comparison, program or outreach "
                           "hypothesis) before building a brief.",
                           [{"label": "Show this district's profile", "request": _req(base, task="profile")}])
        res["args"] = {"profile_id": res["geography_id"], "finding_ids": fids, "edits": fields.get("edits") or {}}

    res["resolved"] = True
    return Outcome("resolved", res)


def _check_comparison_geography(core, cg: str, base: dict, res: dict):
    """Validate a comparison geography's vintage/session before any core query (step by step, no downgrade)."""
    m = RE_GEO_ID.match(cg)
    if not m:
        return None
    kind, code, year = m.group(1), m.group(2), int(m.group(3))
    if kind == "COUNTY" and code not in COUNTY_NAMES:
        return Outcome("unsupported", res, reason=f"Unknown comparison geography {cg}.", reason_id="unresolved_referent")
    if kind in ("HOUSE", "SENATE") and year in SESSIONS and core.geo.get(kind.lower(), code, year) is None:
        return Outcome("unsupported", res, reason=f"Unknown comparison geography {cg}.", reason_id="unresolved_referent")
    if year == DEFAULT_SESSION:
        return None
    res["unresolved"].append("comparison_geography")
    alt_id = f"HI-{kind}{'-' + code if code else ''}-{DEFAULT_SESSION}"
    # Offer the 2024 counterpart of the same geography whenever it exists (statistics may still be
    # unavailable; the core then says so truthfully) — never a different geography.
    exists_2024 = alt_id in core.profiles or (kind in ("HOUSE", "SENATE")
                                              and core.geo.get(kind.lower(), code, DEFAULT_SESSION) is not None)
    alt = [{"label": f"Compare with {geography_label(core, alt_id)}"
            + ("" if alt_id in core.profiles else " (no normalized statistics)"),
            "request": _req(base, comparison_geography=alt_id)}] if exists_2024 else []
    if kind in ("STATE", "COUNTY"):
        return Outcome("unsupported", res,
                       reason_id="unavailable_geography", reason=f"{cg} is not available: state and county statistics in this fixture are ACS 2020–2024 "
                              "on 2024 geography only. No data was queried.", next_actions=alt)
    chamber = kind.lower()
    if year not in SESSIONS:
        return Outcome("unsupported", res,
                       reason_id="unavailable_geography", reason=f"Boundary session {year} is not in this packet (sessions 2024 and 2026 only). "
                              "No data was queried.", next_actions=alt)
    if core.geo.get(chamber, code, year) is None:
        return Outcome("unsupported", res, reason_id="unresolved_referent", reason=f"{chamber.capitalize()} District {code} does not exist in the "
                                                  f"{year} boundary layer. No data was queried.", next_actions=alt)
    if not core.geo.geometry_equal_across_sessions(chamber, code):
        return Outcome("unsupported", res,
                       reason_id="boundary_compatibility", reason=f"{chamber.capitalize()} District {code} ({year}) geometry differs from 2024; ACS 2024 "
                              "statistics cannot be assigned to it.", next_actions=alt)
    return Outcome("clarification", res, clarification={
        "field": "comparison_geography.boundary_session", "reason": "boundary_compatibility", "candidates": {},
        "question": f"ACS 2020–2024 statistics are tabulated on the 2024 boundary session. The saved {year} geometry "
                    f"for comparison {chamber.capitalize()} District {code} equals the 2024 geometry at supplied "
                    "precision (not a legal certification). Use its 2024-session statistics?",
        "choices": alt})
