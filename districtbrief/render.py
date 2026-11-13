"""Deterministic factual renderer.

Builds every screen view and the printable one-page brief from result objects
and stored citations. It formats nothing new: every number shown is a
``*_display`` string supplied by the core. All text is HTML-escaped.
"""

from __future__ import annotations

from html import escape

from .contract import EDIT_LIMITS, TEMPLATES


def e(value) -> str:
    return escape("" if value is None else str(value), quote=True)


def _list(items, cls="") -> str:
    if not items:
        return ""
    return f'<ul class="{cls}">' + "".join(f"<li>{e(i)}</li>" for i in items) + "</ul>"


def _source_button(source_id, finding_id=None, label="Source") -> str:
    fid = f' data-finding-id="{e(finding_id)}"' if finding_id else ""
    return (f'<button type="button" class="btn-link source-btn" data-source-id="{e(source_id)}"{fid}>'
            f'{e(label)}<span class="sr-only"> for {e(finding_id or source_id)}</span></button>')


def _select_box(finding_id, label) -> str:
    return (f'<label class="select-finding"><input type="checkbox" class="finding-select" '
            f'data-finding-id="{e(finding_id)}"> <span>Add to brief</span>'
            f'<span class="sr-only">: {e(label)}</span></label>')


def _request_attr(req) -> str:
    import json
    return e(json.dumps(req, separators=(",", ":"), sort_keys=True))


def _choice_buttons(choices, kind) -> str:
    if not choices:
        return ""
    btns = "".join(
        f'<li><button type="button" class="choice-btn" data-kind="{e(kind)}" '
        f'data-request="{_request_attr(c["request"])}">{e(c["label"])}</button></li>'
        for c in choices)
    return f'<ul class="choices">{btns}</ul>'


# ----------------------------------------------------------------- header
def header_html(resolution: dict | None, status: str, input_mode: str | None, request_id=None,
                context_id=None) -> str:
    r = resolution or {}
    task = r.get("task")
    task_label = TEMPLATES.get(task, "Task not resolved")
    mode = {"guided": "Guided controls", "language": "Typed command"}.get(input_mode or "", "—")
    state = {"resolved": "Resolved — running", "ok": "Resolved", "clarification": "Needs clarification",
             "unsupported": "Not supported", "error": "Error"}.get(status, status)
    args = r.get("args") or {}
    arg_bits = []
    if args.get("metric_ids"):
        arg_bits.append("Measure: " + ", ".join(args["metric_ids"]))
    if args.get("comparison_geography"):
        arg_bits.append("Compare with: " + args["comparison_geography"])
    if args.get("program_ids"):
        arg_bits.append("Programs: " + ", ".join(args["program_ids"]))
    if args.get("program_id"):
        arg_bits.append("Program: " + args["program_id"])
    if args.get("observation_ids"):
        arg_bits.append("Administrative rows: " + ", ".join(args["observation_ids"]))
    if args.get("finding_ids"):
        arg_bits.append(f"Findings: {len(args['finding_ids'])} selected")
    defaults = r.get("defaults_applied") or []
    return (
        f'<div class="resolution status-{e(status)}">'
        f'<dl class="res-grid">'
        f'<div><dt>Task</dt><dd>{e(task_label)}</dd></div>'
        f'<div><dt>District context</dt><dd>{e(r.get("district_label") or "No district resolved")}</dd></div>'
        f'<div><dt>Input</dt><dd>{e(mode)}</dd></div>'
        f'<div><dt>Status</dt><dd class="res-state">{e(state)}</dd></div>'
        f'</dl>'
        + (f'<p class="res-args">{e(" · ".join(arg_bits))}</p>' if arg_bits else "")
        + (f'<p class="res-defaults">Defaults applied: {e(", ".join(defaults))}</p>' if defaults else "")
        + (f'<p class="res-ids">Route {e(r.get("route_id") or "—")} · operation {e(r.get("operation") or "—")}'
           f' · request {e(request_id)}' + (f' · context {e(context_id)}' if context_id else "") + "</p>")
        + "</div>"
    )


# ------------------------------------------------------------- findings
def _stat_row(f, selectable=True) -> str:
    badges = []
    if f["moe_annotation"] == "*****":
        badges.append('<span class="badge badge-note" title="Controlled estimate">controlled estimate</span>')
    elif f["annotation"] or f["moe_annotation"]:
        badges.append(f'<span class="badge badge-note">annotation {e(f["annotation"] or f["moe_annotation"])}</span>')
    if f["metric"]["joint_statistic"]:
        badges.append('<span class="badge">joint statistic</span>')
    est = f["estimate_display"] if f["estimate"] is not None else "Unavailable"
    est_cls = "num" if f["estimate"] is not None else "num missing"
    return (
        f'<tr id="row-{e(f["finding_id"])}">'
        f'<th scope="row"><span class="metric-label">{e(f["metric"]["label"])}</span> {"".join(badges)}'
        f'<div class="fine">{e(f["metric"]["variable_id"])} · {e(f["metric"]["official_variable_label"])}</div></th>'
        f'<td class="{est_cls}">{e(est)}</td>'
        f'<td class="num">{e(f["moe_display"])}</td>'
        f'<td>{e(f["unit"])}</td>'
        f'<td class="universe">{e(f["universe"])}</td>'
        f'<td>{e(f["period"]["label"])}</td>'
        f'<td class="actions">{_source_button(f["source"]["source_id"], f["finding_id"])}'
        + (_select_box(f["finding_id"], f["metric"]["label"]) if selectable else "")
        + "</td></tr>"
    )


def profile_html(env) -> str:
    data = env.get("data") or {}
    ident = data.get("identity") or {}
    cov = data.get("coverage") or {}
    groups: dict = {}
    for f in env["findings"]:
        groups.setdefault(f["metric"]["group"], []).append(f)
    eq = ident.get("geometry_equal_to_other_session")
    ident_html = ""
    if ident:
        ident_html = (
            '<section class="identity" aria-label="District identity">'
            f'<h3>{e(data.get("label"))}</h3><dl class="kv">'
            f'<div><dt>TIGERweb name</dt><dd>{e(ident.get("name"))}</dd></div>'
            f'<div><dt>State FIPS · chamber · code</dt><dd>{e(ident.get("state_fips"))} · {e(ident.get("chamber"))} · {e(ident.get("code"))}</dd></div>'
            f'<div><dt>Boundary session</dt><dd>{e(ident.get("boundary_session"))} (ACS 2024 geography)</dd></div>'
            f'<div><dt>GEOID</dt><dd>{e(ident.get("geoid"))} <span class="fine">(shared across chambers; not used alone)</span></dd></div>'
            '<div><dt>County and service coverage</dt><dd>Unverified; a district internal point does not establish jurisdiction.</dd></div>'
            f'<div><dt>2024 vs 2026 geometry</dt><dd>'
            + ("Equal at supplied precision (not a legal certification)" if eq else
               ("Differs" if eq is False else "Not available")) +
            f'</dd></div>'
            f'<div><dt>Boundary source</dt><dd>{_source_button(ident.get("source_id"), None, ident.get("source_id"))}</dd></div>'
            '</dl><p class="fine">No map is rendered in this experiment.</p></section>'
        )
    scope_html = ('<p class="coverage">Selected-measure profile: ' + e(", ".join(cov.get("returned_metric_ids") or [])) + '</p>') if cov.get("filtered") else '<p class="coverage">Full profile (all 20 measures).</p>'
    missing = cov.get("missing_estimates") or []
    cov_html = (f'<p class="coverage">Coverage: {e(cov.get("observations"))} of {e(cov.get("metrics_total"))} '
                f'normalized measures for this geography. '
                + (f'Unavailable estimates: {e(", ".join(missing))}. ' if missing else "No unavailable estimates. ")
                + (f'Annotated values: {e(len(cov.get("annotated") or []))}.' if cov.get("annotated") else "")
                + "</p>")
    tables = []
    for group, items in groups.items():
        tables.append(
            f'<table class="data-table"><caption>{e(group)}</caption><thead><tr>'
            '<th scope="col">Measure</th><th scope="col">Estimate</th><th scope="col">90% MOE</th>'
            '<th scope="col">Unit</th><th scope="col">Universe</th><th scope="col">Period</th>'
            '<th scope="col">Source · brief</th></tr></thead><tbody>'
            + "".join(_stat_row(f) for f in items) + "</tbody></table>")
    return ident_html + scope_html + cov_html + "".join(tables)


def compare_html(env) -> str:
    rows = []
    for f in env["findings"]:
        L, R = f["left"], f["right"]
        if f["difference"]:
            diff = (f'<span class="num">{e(f["difference"]["display"])}</span> {e(f["difference"]["unit"])}'
                    f'<div class="fine">{e(f["difference"]["method"])}</div>')
        else:
            diff = f'<span class="muted">Not differenced</span><div class="fine">{e(f["not_differenced_reason"])}</div>'
        checks = ", ".join(k for k, v in f["compatibility"]["checks"].items() if v)
        rows.append(
            f'<tr id="row-{e(f["finding_id"])}"><th scope="row">{e(f["metric"]["label"])}'
            f'<div class="fine">{e(f["universe"])} · {e(f["unit"])} · {e(f["period"]["label"])}</div></th>'
            f'<td><span class="num">{e(L["estimate_display"])}</span> <span class="moe">MOE {e(L["moe_display"])}</span>'
            f'<div class="fine">{e(L["geography"]["label"])}</div>{_source_button(L["source"]["source_id"], L["finding_id"])}</td>'
            f'<td><span class="num">{e(R["estimate_display"])}</span> <span class="moe">MOE {e(R["moe_display"])}</span>'
            f'<div class="fine">{e(R["geography"]["label"])}</div>{_source_button(R["source"]["source_id"], R["finding_id"])}</td>'
            f'<td>{diff}</td><td class="fine">Matched: {e(checks)}</td>'
            f'<td class="actions">{_select_box(f["finding_id"], f["metric"]["label"] + " comparison")}</td></tr>')
    return ('<table class="data-table"><caption>Compatible comparison</caption><thead><tr>'
            '<th scope="col">Measure</th><th scope="col">District</th><th scope="col">Comparison geography</th>'
            '<th scope="col">Point difference</th><th scope="col">Compatibility</th><th scope="col">Brief</th>'
            '</tr></thead><tbody>' + "".join(rows) + "</tbody></table>")


def _participation_table(rows) -> str:
    if not rows:
        return '<p class="muted">No administrative participation observations for this program in the packet.</p>'
    body = "".join(
        f'<tr><td>{e(r["geography"]["name"])} <span class="fine">({e(r["geography"]["type"])})</span></td>'
        f'<td>{e(r["period"])}</td>'
        f'<td class="{"num" if r["value"] is not None else "num missing"}">{e(r["value_display"])}</td>'
        f'<td>{e(r["unit"])}</td><td class="fine">{e(r["coverage"])}'
        + (f'<div>{e(r["raw_value_note"])}</div>' if r.get("raw_value_note") else "")
        + f'<div>{e(r["revision_status"])}</div></td>'
        f'<td>{_source_button(r["source_id"], None, r["source_id"])}</td></tr>' for r in rows)
    return ('<table class="data-table compact"><caption>Administrative context — not district data; '
            'no gap computed</caption><thead><tr><th scope="col">Geography</th><th scope="col">Period</th>'
            '<th scope="col">Value</th><th scope="col">Unit</th><th scope="col">Coverage · revision</th>'
            '<th scope="col">Source</th></tr></thead><tbody>' + body + "</tbody></table>")


def administrative_html(env) -> str:
    cards = []
    for f in env.get("findings") or []:
        geo = f["geography"]
        geography = (geo.get("label") or geo.get("name")) if isinstance(geo, dict) else geo
        fields = [("Series", f["series_label"]), ("Geography", geography),
                  ("Period", f["period"]), ("Unit", f["unit"]),
                  ("Status", f["status"]), ("Coverage", f["coverage"]),
                  ("Revision", f.get("revision_status")), ("Suppression", f.get("suppression")),
                  ("Missing reason", f.get("missing_reason"))]
        metadata = "".join(f'<div><dt>{e(k)}</dt><dd>{e(v)}</dd></div>' for k, v in fields if v is not None and v != "")
        value = f.get("value_display") or _count_display(f["value"])
        cards.append(
            f'<article class="card administrative" id="row-{e(f["finding_id"])}">'
            f'<h3>{e(f["series_label"])}</h3><p class="num">{e(value)}</p>'
            f'<dl class="kv">{metadata}</dl>'
            '<p class="fine">Administrative context only; not a district count. No district participation gap is computed.</p>'
            f'<p class="fine"><code>{e(f["observation_id"])}</code></p>'
            + _list(f.get("limitations") or [])
            + f'<footer>{_source_button(f["source"]["source_id"], f["finding_id"])} '
            + _select_box(f["finding_id"], str(f["series_label"]) + " · " + str(f["period"]) + " · " + str(f["unit"]))
            + '</footer></article>')
    return "".join(cards)


def _evidence_list(evidence, finding_id) -> str:
    items = []
    for ev in evidence:
        ver = ('authored reference; historical locator, origin bytes not bundled'
               if ev.get('verification_kind') == 'authored_reference' else
               {True: "matches retained extract", False: "DOES NOT match retained extract",
                None: "page locator (raw PDF retained)"}[ev["verified_against_extract"]])
        items.append(
            f'<li><details><summary>{e(ev["claim"])} <span class="fine">— {e(ev["source_id"])}, '
            f'{e(ev["locator_text"])}; {e(ver)}</span></summary>'
            f'<pre class="support">{e(ev["support_text"])}</pre>'
            f'{_source_button(ev["source_id"], finding_id, "Open source record")}</details></li>')
    return '<ul class="evidence">' + "".join(items) + "</ul>"


def _program_population_html(env) -> str:
    context = env["data"]["population_context"]
    definitions = "".join(
        f'<li><strong>{e(d["label"])}</strong>: {e(d["unit"])}; universe: {e(d["universe"])}. '
        f'<span class="fine">{e(d["table_id"])} · {e(d["variable_id"])}'
        + (f' · {e(d["period_label"])}' if d.get("period_label") else "") + '</span>'
        + (f' {_source_button(d["source_id"], label="Definition source")}' if d.get("source_id") else "")
        + '</li>' for d in context["definitions"] + [context["snap_receipt_definition"]])
    return ('<section class="population-context"><h3>What these populations mean</h3>'
            f'<ul>{definitions}</ul>' + "".join(f'<p>{e(n)}</p>' for n in context["notes"]) + '</section>')


def program_html(env) -> str:
    cards = []
    for f in env["findings"]:
        p = f["program"]
        jc = f["jurisdiction_check"]
        rel = f["relevance"]
        related = "".join(
            f'<li>{e(o["label"])}: <span class="num">{e(o["estimate_display"])}</span> '
            f'<span class="moe">(90% MOE {e(o["moe_display"])}{" percentage points" if o["unit"] == "percent" else ""})</span> '
            f'<span class="fine">Unit: {e(o["unit"])}; universe: {e(o["universe"])}; '
            f'{e(o["period_label"])}</span></li>' for o in rel["related_observations"])
        ref = f["referral"]
        cards.append(
            f'<article class="card program" id="row-{e(f["finding_id"])}">'
            f'<header><h3>{e(p["name"])}</h3><span class="badge badge-info">Informational only</span> '
            f'<span class="badge status-{e(p["status"])}">{e(f["status_notes"][0])}</span></header>'
            f'<dl class="kv"><div><dt>Agency</dt><dd>{e(p["agency"])}</dd></div>'
            f'<div><dt>Jurisdiction</dt><dd>{e(p["jurisdiction"])}</dd></div>'
            f'<div><dt>Checked</dt><dd>{e(p["checked_at"])}</dd></div>'
            f'<div><dt>Effective period</dt><dd>{e(f["effective_text"])} <span class="fine">({e(p["effective_period"].get("scope"))})</span></dd></div></dl>'
            + ("" if jc["in_agency_area"] else f'<p class="alert" role="note">{e(jc["note"])}</p>')
            + "".join(f'<p class="alert" role="note">{e(n)}</p>' for n in f["status_notes"][1:])
            + f'<h4>Why it may be relevant here</h4><p>{e(rel["connection"])}</p>'
            + (f'<ul class="related">{related}</ul>' if related else
               '<p class="muted">No fixture observation is linked to this program.</p>')
            + f'<h4>Unknowns the agency determines</h4>{_list(f["unknowns"], "unknowns")}'
            f'<h4>Official referral</h4><p>{e(ref["next_step"])}<br>'
            f'<span class="url">{e(ref["url"])}</span>'
            + (f' · {e(ref["phone"])}' if ref.get("phone") else "")
            + (f' · TTY {e(ref["tty"])}' if ref.get("tty") else "")
            + (f' · county office: {e(ref["county_office"])}' if ref.get("county_office") else "")
            + '</p>'
            + (f'<p class="fine">Review notes: {e(" ".join(p["review_notes"]))}</p>' if p["review_notes"] else "")
            + f'<h4>Evidence spans</h4>{_evidence_list(f["evidence"], f["finding_id"])}'
            + _participation_table(f["participation_context"])
            + f'<footer>{_select_box(f["finding_id"], p["name"] + " relevance")}</footer></article>')
    return _program_population_html(env) + "".join(cards)


def outreach_html(env) -> str:
    out = []
    for f in env["findings"]:
        rows = "".join(
            f'<tr><th scope="row">{e(o["label"])}<div class="fine">{e(o["universe"])}</div></th>'
            f'<td><span class="num">{e(o["estimate_display"])}</span> <span class="moe">MOE {e(o["moe_display"])}</span></td>'
            f'<td>' + (f'<span class="num">{e(o["state_reference"]["estimate_display"])}</span> '
                       f'<span class="moe">MOE {e(o["state_reference"]["moe_display"])}</span>'
                       if o["state_reference"] else "—") + '</td>'
            f'<td>' + (f'{e(o["state_reference"]["difference"]["display"])} {e(o["state_reference"]["difference"]["unit"])}'
                       if o["state_reference"] and o["state_reference"]["difference"] else
                       '<span class="muted">not differenced</span>') + '</td>'
            f'<td>{e(o["unit"])} · {e(o["period_label"])}</td></tr>' for o in f["observed_need"])
        pc = f["program_connection"]
        out.append(
            f'<article class="card hypothesis" id="row-{e(f["finding_id"])}">'
            f'<header><h3>{e(f["program"]["name"])} — {e(f["geography"]["label"])}</h3>'
            f'<span class="badge badge-warn">{e(f["label"])}</span></header>'
            f'<h4>1. Observed area conditions (ACS estimates, not program need)</h4>'
            f'<table class="data-table compact"><thead><tr><th scope="col">Measure</th><th scope="col">District</th>'
            f'<th scope="col">State</th><th scope="col">Point difference</th><th scope="col">Unit · period</th></tr></thead>'
            f'<tbody>{rows}</tbody></table>'
            f'<h4>2. Program connection (informational)</h4><p>{e(pc["text"])}</p>'
            f'<p class="fine">{e(" ".join(pc["status_notes"]))} Rules {e(pc["effective_text"])}.</p>'
            f'<h4>3. Unknowns</h4>{_list(f["unknowns"], "unknowns")}'
            f'<h4>4. Practical next step</h4><p>{e(f["next_step"])}</p>'
            f'<footer>{_select_box(f["finding_id"], "outreach hypothesis")}</footer></article>')
    return _program_population_html(env) + "".join(out)


def action_checklist_text(brief):
    action=brief.get("action")
    parts=[]
    if action:
        parts += ["Verification action", (brief.get("action_program") or {}).get("name",action["program_id"]), (brief.get("action_program") or {}).get("agency",""), action["access"]["recorded_status"], action["access"]["checked_at"] or "", *action["facts_to_verify"]]
    for row in brief.get("checklist",[]):
        parts += [row["text"],row.get("owner_role") or "",row.get("due_date") or "", "Complete" if row.get("completed") else "To do"]
    if brief.get("tracking"):parts.append(str(brief["tracking"]))
    return " ".join(parts)


def action_checklist_html(brief):
    action=brief.get("action")
    tracking=brief.get("tracking")
    tracking_html=(f'<p class="staff-edit">Staff tracking — not a verified fact: {e(tracking["label"])}; baseline {e(tracking["baseline"] if tracking["baseline"] is not None else "not supplied")}; as of {e(tracking["as_of"] or "not supplied")}.</p>' if tracking else '')
    rows="".join(f'<li>{e(row["text"])} <span class="staff-label">Staff record: {e(row.get("owner_role") or "role not set")}; {e(row.get("due_date") or "date not set")}; {"complete" if row.get("completed") else "to do"}</span></li>' for row in brief.get("checklist",[]))
    checklist_html=('<h3>Office checklist <span class="staff-label">Staff work — not verified facts</span></h3><ol>'+rows+'</ol>') if rows else ''
    action_html=''
    if action:
        cites="".join(f'<a class="cite" href="#cite-{n}">[{n}]</a>' for n in brief.get("action_citations",[]))
        program=brief.get("action_program") or {}
        action_html=('<h3>Verification action</h3>'
            f'<p>{e(program.get("name",action["program_id"]))} · {e(program.get("agency",""))} · {e(action["access"]["recorded_status"])} at {e(action["access"]["checked_at"])}. Current availability and cost unverified. {cites}</p>'
            + _list(action["facts_to_verify"],"brief-questions"))
    return '<section class="brief-action">'+action_html+checklist_html+tracking_html+'</section>' if action_html or checklist_html or tracking_html else ''


def brief_doc_html(brief: dict) -> str:
    """The one printable brief. Screen preview and print use this same markup."""
    staff = brief["staff_edits"]
    lbl = brief["staff_edit_label"]
    kind_label = {"statistic": "Statistic", "comparison": "Comparison", "program_relevance": "Program (informational)",
                  "outreach_hypothesis": "Outreach hypothesis", "administrative_context": "Administrative context (not district data)"}
    items = []
    for i, en in enumerate(brief["entries"], 1):
        cites = "".join(f'<a class="cite" href="#cite-{n}">[{n}]</a>' for n in en["citations"])
        note = (f'<div class="staff-edit"><span class="staff-label">{e(lbl)}:</span> {e(en["staff_note"])}</div>'
                if en.get("staff_note") else "")
        items.append(f'<li class="brief-finding" data-finding-id="{e(en["finding_id"])}">'
                     f'<span class="kind">{e(kind_label.get(en["kind"], en["kind"]))}</span> '
                     f'{e(en["text"])} {cites}<span class="fid">{e(en["finding_id"])}</span>{note}</li>')
    cites = "".join(
        f'<li id="cite-{c["n"]}">[{c["n"]}] {e(c["publisher"])} — <span class="srcid">{e(c["source_id"])}</span>. '
        f'<span class="url">{e(c["url"])}</span> · retrieved {e((c["retrieved_at_utc"] or "")[:10])}'
        f' · sha256 {e((c["sha256"] or "")[:12])}… · <span class="locators">{e("; ".join(c["locators"]))}</span></li>'
        for c in brief["citations"])
    title_label = f' <span class="staff-label">({e(lbl)})</span>' if brief["title_is_staff_edit"] else ""
    return (
        f'<article id="brief-doc" class="brief-doc" data-brief-id="{e(brief["brief_id"])}">'
        f'<header class="brief-head"><h2>{e(brief["title"])}{title_label}</h2>'
        f'<p class="brief-meta">{e(brief["geography"]["label"])} · Verified facts from the frozen fixture '
        f'(snapshot {e(brief["snapshot_id"][:19])}…) · {e(brief["brief_id"])} · statistical session 2024; map session {e(brief.get("map_session",2024))}</p></header>'
        + (f'<section class="staff-edit"><h3>Staff summary <span class="staff-label">({e(lbl)})</span></h3>'
           f'<p>{e(staff["note"])}</p></section>' if staff.get("note") else "")
        + f'<section><h3>Verified findings</h3><ol class="brief-findings">{"".join(items)}</ol></section>'
        + (f'<section class="staff-edit"><h3>Staff next steps <span class="staff-label">({e(lbl)})</span></h3>'
           f'<p>{e(staff["next_steps"])}</p></section>' if staff.get("next_steps") else "")
        + action_checklist_html(brief)
        + f'<section><h3>Limitations</h3>{_list(brief["limitations"], "brief-limits")}</section>'
        + f'<section><h3>Sources</h3><ol class="brief-cites">{cites}</ol></section>'
        + '<footer class="brief-foot">Programs are informational; the administering agency determines '
          'eligibility. Outreach items are hypotheses, not measured gaps. No model generated any text.</footer>'
        + "</article>"
    )


def brief_editor_html(brief: dict) -> str:
    staff = brief["staff_edits"]
    notes = {en["finding_id"]: en.get("staff_note") or "" for en in brief["entries"]}
    rows = "".join(
        f'<div class="field"><label for="note-{i}">Staff note for {e(en["finding_id"])}</label>'
        f'<textarea id="note-{i}" class="finding-note" data-finding-id="{e(en["finding_id"])}" '
        f'maxlength="{EDIT_LIMITS["finding_note"]}" rows="2">{e(notes[en["finding_id"]])}</textarea></div>'
        for i, en in enumerate(brief["entries"]))
    return (
        '<form id="brief-editor" class="brief-editor" aria-label="Brief editor">'
        '<h3>Edit brief</h3><p class="fine">Edits are printed as labeled staff text. They never change '
        'verified findings, numbers or citations.</p>'
        f'<div class="field"><label for="edit-title">Title</label><input id="edit-title" type="text" '
        f'maxlength="{EDIT_LIMITS["title"]}" value="{e(staff.get("title") or "")}" '
        f'placeholder="{e(brief["default_title"])}"></div>'
        f'<div class="field"><label for="edit-note">Staff summary</label><textarea id="edit-note" rows="3" '
        f'maxlength="{EDIT_LIMITS["note"]}">{e(staff.get("note") or "")}</textarea></div>'
        f'{rows}'
        f'<div class="field"><label for="edit-next">Staff next steps</label><textarea id="edit-next" rows="2" '
        f'maxlength="{EDIT_LIMITS["next_steps"]}">{e(staff.get("next_steps") or "")}</textarea></div>'
        '<div class="btn-row"><button type="submit" class="btn">Apply edits</button>'
        '<button type="button" id="print-brief" class="btn btn-primary">Print brief</button></div></form>'
    )


def result_html(env: dict) -> str:
    status = env["status"]
    parts = []
    if status == "clarification":
        c = env["clarification"]
        parts.append(f'<section class="notice notice-clarify" role="status"><h3>Clarification needed</h3>'
                     f'<p>{e(c["question"])}</p>{_choice_buttons(c["choices"], "clarification_response")}'
                     f'<p class="fine">No data was queried for this request.</p></section>')
    elif status == "unsupported":
        parts.append(f'<section class="notice notice-unsupported" role="status"><h3>Not supported</h3>'
                     f'<p>{e(env.get("reason"))}</p>'
                     + ('<h4>Supported choices</h4>' + _choice_buttons(env["next_actions"], "next_action")
                        if env["next_actions"] else "") + '</section>')
    elif status == "error":
        errs = "".join(f'<li><code>{e(v["field"])}</code>: {e(v["message"])}</li>'
                       for v in env.get("validation_errors") or [])
        parts.append(f'<section class="notice notice-error" role="alert"><h3>Error</h3><p>{e(env.get("reason"))}</p>'
                     + (f'<ul>{errs}</ul>' if errs else "")
                     + (f'<p>{e(env.get("retry"))}</p>' if env.get("retry") else "")
                     + _choice_buttons(env.get("next_actions") or [], "next_action") + '</section>')
    else:
        task = (env.get("resolution") or {}).get("task")
        if task == "profile":
            parts.append(profile_html(env))
        elif task == "compare":
            parts.append(compare_html(env))
        elif task == "program_relevance":
            parts.append(program_html(env))
        elif task == "outreach":
            parts.append(outreach_html(env))
        elif task == "administrative_context":
            parts.append(administrative_html(env))
        elif task == "brief":
            brief = env["data"]["brief"]
            parts.append('<div class="brief-layout">' + brief_editor_html(brief)
                         + '<div class="brief-preview"><h3 class="screen-only">Print preview (one page)</h3>'
                         + brief_doc_html(brief) + '</div></div>')
        if env["next_actions"]:
            parts.append('<section class="next-actions"><h3>Next steps</h3>'
                         + _choice_buttons(env["next_actions"], "next_action") + "</section>")
    if env.get("limitations") and status in ("ok", "unsupported"):
        parts.append('<section class="limitations"><h3>Limitations</h3>' + _list(env["limitations"]) + "</section>")
    return "".join(parts)


# ------------------------------------------------------------ catalog/source
def _count_display(value) -> str:
    return "Unpublished (no value)" if value is None else f"{value:,}"


def catalog_html(cat: dict) -> str:
    geos = {g["geography_id"]: g["label"] for g in cat["geographies"]}
    metrics = {m["metric_id"]: m for m in cat["metrics"]}
    geo_opts = "".join(f'<option value="{e(g)}">{e(l)}</option>' for g, l in geos.items())
    rows = "".join(
        f'<tr data-geo="{e(o["geography_id"])}" data-metric="{e(o["metric_id"])}">'
        f'<td>{e(geos[o["geography_id"]])}</td><th scope="row">{e(metrics[o["metric_id"]]["label"])}'
        f'<div class="fine">{e(o["metric_id"])}</div></th>'
        f'<td class="num">{e(o["estimate_display"])}</td><td class="num">{e(o["moe_display"])}</td>'
        f'<td>{e(o["unit"])}</td><td class="universe fine">{e(metrics[o["metric_id"]]["universe"])}</td>'
        f'<td>{_source_button(o["source_id"], o["finding_id"])}</td></tr>' for o in cat["observations"])
    geo_rows = "".join(
        f'<tr><td>{e(g["label"])}</td><td><code>{e(g["geography_id"])}</code></td><td>{e(g["geoid"])}</td>'
        f'<td>{e(g["summary_level"])}</td><td>{e(g["observation_count"])}</td></tr>' for g in cat["geographies"])
    unavailable = ", ".join(u["label"] for u in cat["unavailable_geographies"])
    dc = cat["district_counts"]
    part_rows = "".join(
        f'<tr><td><code>{e(r["observation_id"])}</code></td><td>{e(r["program_id"])}</td>'
        f'<td>{e(r["geography"]["name"])} ({e(r["geography"]["type"])})</td><td>{e(r["period"])}</td>'
        f'<td class="{"num" if r["value"] is not None else "num missing"}">{e(_count_display(r["value"]))}</td>'
        f'<td>{e(r["unit"])}</td><td class="fine">{e(r.get("series_label"))}<br>{e(r.get("status"))}<br>{e(r["coverage"])}</td>'
        f'<td>{_source_button(r["source_id"], "admin:" + r["observation_id"], r["source_id"])}</td></tr>' for r in cat["participation"])
    return (
        '<section aria-labelledby="cov-h"><h3 id="cov-h">Coverage</h3>'
        f'<p>{e(cat["coverage"]["statistics_observations"])} normalized observations: '
        f'{e(cat["coverage"]["metrics"])} measures × {e(cat["coverage"]["statistics_geographies"])} geographies. '
        f'Boundary layers: 2024 — {e(dc["2024"]["house"])} House, {e(dc["2024"]["senate"])} Senate; '
        f'2026 — {e(dc["2026"]["house"])} House, {e(dc["2026"]["senate"])} Senate. '
        f'Every House and Senate district of the 2024 boundary session has normalized statistics; the '
        f'State of Hawaiʻi and Maui County are comparison geographies. '
        f'Not normalized: {e(unavailable)}.</p>'
        f'<p class="fine">{e(cat["coverage"]["map"])}</p>'
        + _list(cat["limitations"]) +
        '<table class="data-table compact"><caption>Normalized geographies</caption><thead><tr>'
        '<th scope="col">Geography</th><th scope="col">ID</th><th scope="col">GEOID</th>'
        '<th scope="col">Summary level</th><th scope="col">Observations</th></tr></thead>'
        f'<tbody>{geo_rows}</tbody></table></section>'
        '<section aria-labelledby="obs-h"><h3 id="obs-h">All normalized observations</h3>'
        '<div class="filters"><label for="cat-geo">Geography</label>'
        f'<select id="cat-geo"><option value="">All geographies</option>{geo_opts}</select>'
        '<label for="cat-q">Measure contains</label><input id="cat-q" type="search">'
        '<span id="cat-count" class="fine" aria-live="polite"></span></div>'
        '<table class="data-table" id="cat-table"><thead><tr><th scope="col">Geography</th>'
        '<th scope="col">Measure</th><th scope="col">Estimate</th><th scope="col">90% MOE</th>'
        '<th scope="col">Unit</th><th scope="col">Universe</th><th scope="col">Source</th></tr></thead>'
        f'<tbody>{rows}</tbody></table></section>'
        '<section aria-labelledby="part-h"><h3 id="part-h">Administrative participation rows (context only)</h3>'
        '<p class="fine">State, county or island aggregates. None is usable for a district gap.</p>'
        '<table class="data-table compact"><thead><tr><th scope="col">ID</th><th scope="col">Program</th>'
        '<th scope="col">Geography</th><th scope="col">Period</th><th scope="col">Value</th><th scope="col">Unit</th>'
        f'<th scope="col">Coverage</th><th scope="col">Source</th></tr></thead><tbody>{part_rows}</tbody></table></section>'
    )


def sources_html(cat: dict) -> str:
    rows = "".join(
        f'<tr><td>{e(s["family"])}</td><td><code>{e(s["source_id"])}</code></td><td>{e(s["publisher"])}</td>'
        f'<td class="url">{e(s["url"])}</td><td>{e((s["retrieved_at_utc"] or "")[:10])}</td>'
        f'<td>{_source_button(s["source_id"], None, "Inspect")}</td></tr>' for s in cat["sources"])
    caption = ('Historical origin records (omitted captures are not verified)'
               if any(s.get('record_scope') == 'historical_origin_capture' for s in cat['sources'])
               else 'Retained sources (packet manifests)')
    return (f'<table class="data-table compact"><caption>{e(caption)}</caption><thead><tr>'
            '<th scope="col">Family</th><th scope="col">Source ID</th><th scope="col">Publisher</th>'
            '<th scope="col">URL (provenance only, never fetched)</th><th scope="col">Retrieved</th>'
            f'<th scope="col">Record</th></tr></thead><tbody>{rows}</tbody></table>')


def source_html(res: dict) -> str:
    s = res["source"]
    rf = res["retained_file"]
    cited = res["cited_by"]
    detail = res.get("detail") or {}
    d_html = ""
    if detail.get("type") == "sheet_cell":
        if not detail.get("available"):
            d_html = f'<p class="alert">Retained workbook unavailable: {e(detail.get("reason"))}</p>'
        else:
            cells = "".join(f'<tr><td>{e(c["role"])}</td><td><code>{e(detail["locator"]["sheet"])}!{e(c["ref"])}</code></td>'
                            f'<td>{e(c["stored_text"])}</td></tr>' for c in detail["cells"])
            d_html = (f'<h4>Retained workbook cells</h4><table class="data-table compact"><thead><tr>'
                      f'<th scope="col">Role</th><th scope="col">Cell</th><th scope="col">Stored text</th></tr></thead>'
                      f'<tbody>{cells}</tbody></table>'
                      f'<p>Normalized estimate {e(detail["published_display"]["estimate"])} '
                      f'{"matches" if detail["estimate_matches"] else "DOES NOT match"} the retained cell; MOE '
                      f'{e(detail["published_display"]["moe"])} {"matches" if detail["moe_matches"] else "DOES NOT match"}.</p>')
    elif detail.get("type") == "administrative_row":
        import json
        verified = detail.get("cell_verified")
        verification = {True: "Cell verified: true (matches retained cell)",
                        False: "Cell verified: false (not verified against retained cell)",
                        None: "Cell verified: null (no raw-cell reread)"}[verified]
        locator = json.dumps(detail.get("locator") or {}, ensure_ascii=False, sort_keys=True, indent=2)
        normalized = json.dumps(detail.get("normalized_row") or {}, ensure_ascii=False, sort_keys=True, indent=2)
        d_html = ('<h4>Administrative row evidence</h4>'
                  f'<p>{e(verification)} · {e(detail.get("verification_kind"))}</p>'
                  f'<p>{e(detail.get("verification_note"))}</p>'
                  '<h4>Full recorded locator</h4>'
                  f'<pre class="support">{e(locator)}</pre>'
                  '<h4>Normalized row (null means no published value)</h4>'
                  f'<pre class="support">{e(normalized)}</pre>'
                  + (f'<p>Retained cell text: <code>{e(detail["stored_text"])}</code></p>'
                     if "stored_text" in detail else ""))
    elif detail.get("type") == "projection_reference":
        import json
        d_html = ('<h4>Bundled factual reference</h4>'
                  f'<p>{e(detail["verification_note"])}</p>'
                  '<h4>Historical locator</h4>'
                  f'<pre class="support">{e(json.dumps(detail.get("locator"), ensure_ascii=False, indent=2))}</pre>'
                  '<h4>Normalized reference</h4>'
                  f'<pre class="support">{e(json.dumps(detail["normalized_reference"], ensure_ascii=False, indent=2))}</pre>')
    elif detail.get("type") == "text_spans":
        d_html = "<h4>Cited spans</h4>" + "".join(
            f'<p><strong>{e(sp["claim"])}</strong> — {e(sp["locator_text"])} '
            f'({"matches retained extract" if sp["verified_against_extract"] else ("page locator" if sp["verified_against_extract"] is None else "MISMATCH")})</p>'
            f'<pre class="support">{e(sp["support_text"])}</pre>' for sp in detail["spans"])
    return (
        f'<h3>{e(s["source_id"])}</h3><dl class="kv">'
        f'<div><dt>Publisher</dt><dd>{e(s["publisher"])}</dd></div>'
        f'<div><dt>Family</dt><dd>{e(s["family"])}</dd></div>'
        f'<div><dt>URL</dt><dd class="url">{e(s["url"])}</dd></div>'
        + (f'<div><dt>Final URL</dt><dd class="url">{e(s["final_url"])}</dd></div>'
           if s.get("final_url") and s["final_url"] != s["url"] else "")
        + f'<div><dt>Retrieved</dt><dd>{e(s["retrieved_at_utc"])}</dd></div>'
        f'<div><dt>Content type · bytes</dt><dd>{e(s["content_type"])} · {e(s["bytes"])}</dd></div>'
        f'<div><dt>{"Historical packet path" if s.get("record_scope") == "historical_origin_capture" else "Packet file"}</dt><dd><code>{e(s["packet_path"])}</code></dd></div>'
        f'<div><dt>{"Historical origin SHA-256" if s.get("record_scope") == "historical_origin_capture" else "SHA-256 (manifest)"}</dt><dd><code class="hash">{e(s["sha256"])}</code></dd></div>'
        f'<div><dt>Retained bytes</dt><dd>'
        + ("Available; re-hashed and matches manifest" if rf.get("available") else f'Unavailable: {e(rf.get("reason"))}')
        + '</dd></div>'
        f'<div><dt>Cited by</dt><dd>{e(len(cited["observations"]))} observations, '
        f'{e(len(cited["programs"]))} program records, {e(len(cited["participation"]))} participation rows'
        + (" — not cited by any record" if res.get("not_cited") else "") + '</dd></div></dl>'
        f'<p class="fine">{e(res["fetch_policy"])}</p>' + d_html
    )
