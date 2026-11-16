"""Deterministic factual renderer.

Builds every screen view and the printable one-page brief from result objects
and stored citations. It formats nothing new: every number shown is a
``*_display`` string supplied by the core. All text is HTML-escaped.
"""

from __future__ import annotations

import json
import re
from html import escape

from .contract import EDIT_LIMITS, TEMPLATES


def e(value) -> str:
    return escape("" if value is None else str(value), quote=True)


def _list(items, cls="") -> str:
    if not items:
        return ""
    return f'<ul class="{cls}">' + "".join(f"<li>{e(i)}</li>" for i in items) + "</ul>"


# ------------------------------------------------------- human source labels
# Descriptive labels for staff. They are written from each record's recorded publisher, address and file
# name; they are NOT official document titles, which the source records do not hold. Machine identifiers
# (source ids, hashes, packet paths) stay in API results, case files and diagnostics, never in this text.
SOURCE_LABELS = {
    "dbedt_2024_index": "ACS 2024 data page",
    "dbedt_2024_house": "ACS 2020–2024 5-year estimates by House district (workbook)",
    "dbedt_2024_senate": "ACS 2020–2024 5-year estimates by Senate district (workbook)",
    "dbedt_2024_state": "ACS 2020–2024 5-year estimates for the State (workbook)",
    "dbedt_2024_counties": "ACS 2020–2024 5-year estimates by county (workbook)",
    "acs_2024_DP02_metadata": "ACS 2024 5-year table DP02 variable list",
    "acs_2024_DP03_metadata": "ACS 2024 5-year table DP03 variable list",
    "acs_2024_DP04_metadata": "ACS 2024 5-year table DP04 variable list",
    "acs_2024_DP05_metadata": "ACS 2024 5-year table DP05 variable list",
    "acs_2024_B17001_metadata": "ACS 2024 5-year table B17001 variable list",
    "acs_2024_api_examples": "ACS 2024 5-year data examples page",
    "acs_derived_moe_guidance": "ACS general handbook (2020), chapter 8 (PDF)",
    "acs_controlled_estimate_guidance": "ACS help page on controlled estimates",
    "acs_2024_geography_documentation": "ACS 2024 geography boundaries page",
    "tigerweb_acs2024_service": "TIGERweb ACS 2024 map service",
    "tigerweb_current_service": "TIGERweb legislative map service",
    "tigerweb_2024_senate_metadata": "TIGERweb 2024 Senate district layer description",
    "tigerweb_2024_senate_geometry": "TIGERweb 2024 Senate district boundaries",
    "tigerweb_2024_house_metadata": "TIGERweb 2024 House district layer description",
    "tigerweb_2024_house_geometry": "TIGERweb 2024 House district boundaries",
    "tigerweb_2026_senate_metadata": "TIGERweb current Senate district layer description",
    "tigerweb_2026_senate_geometry": "TIGERweb current Senate district boundaries",
    "tigerweb_2026_house_metadata": "TIGERweb current House district layer description",
    "tigerweb_2026_house_geometry": "TIGERweb current House district boundaries",
    "hawaii_elections_current_maps": "Election maps page",
    "hawaii_elections_HD_01": "2024 election map, House District 1 (PDF)",
    "hawaii_elections_SD_01": "2024 election map, Senate District 1 (PDF)",
    "hawaii_elections_HD_09": "2024 election map, House District 9 (PDF)",
    "hi_snap_rules": "SNAP program page",
    "hi_medquest_start": "Med-QUEST “get started” page",
    "hi_medquest_apply": "Med-QUEST how-to-apply page",
    "hi_medquest_rules": "Med-QUEST rules and policy page",
    "hi_hpha_apply": "Public housing how-to-apply page",
    "hud_hcv_rules": "Housing Choice Voucher (Section 8) program page",
    "hi_wic_rules": "WIC program details page",
    "hi_eoa_referral": "Executive Office on Aging home page",
    "hi_kupuna_definition": "Hawaiʻi Revised Statutes §349-16 (web text)",
    "hi_kupuna_law": "Hawaiʻi Revised Statutes §349-17 (web text)",
    "hi_medquest_chart": "2026 MAGI and MAGI-excepted income standards chart (PDF)",
    "honolulu_hcv_rules": "Section 8 Housing Choice Voucher page",
    "hi_snap_sfy2027": "SNAP summary, state fiscal year 2027 (spreadsheet)",
    "hi_snap_sfy2026": "Participation, state fiscal year 2026 (spreadsheet)",
    "hi_mqd_reports": "Med-QUEST reports page",
    "hi_mqd_reports_canonical": "Med-QUEST reports page",
    "hi_mqd_enrollment_2026": "Enrollment report 2026 (PDF)",
    "btg_dashboards": "Reports and dashboards page",
    "btg_outreach_experience": "Outreach dashboard description (ArcGIS)",
    "btg_outreach_config": "Outreach dashboard data (ArcGIS)",
    "btg_senate_dashboard_config": "Senate district dashboard data (ArcGIS)",
    "btg_house_dashboard_config": "House district dashboard data (ArcGIS)",
    "dbedt_county_index": "County report, section H index page",
    "dbedt_county_h": "County report 2024, section H (workbook)",
    "usda_snap_hi_factsheet": "SNAP state fact sheet, Hawaiʻi (PDF)",
    "usda_snap_participation_2022_page": "SNAP state participation rates, 2022 (page)",
    "usda_snap_rates2022": "Reaching Those in Need, 2022 (PDF)",
}


def source_label(source_id, url=None) -> str:
    """Descriptive staff label for a recorded source (never an official title, never an identifier)."""
    if source_id in SOURCE_LABELS:
        return SOURCE_LABELS[source_id]
    from urllib.parse import unquote, urlparse
    try:
        parts = urlparse(url or "")
    except ValueError:
        parts = None
    if parts and parts.netloc:
        name = unquote(parts.path.rstrip("/").rsplit("/", 1)[-1])
        name = re.sub(r"\.(html?|aspx|php)$", "", name)
        return f"{parts.netloc} — {name.replace('_', ' ').replace('-', ' ')}" if name else f"{parts.netloc} page"
    return "Recorded source"


def human_date(value) -> str:
    """Date part of a recorded ISO timestamp (no time zone or clock detail)."""
    text = "" if value is None else str(value)
    return text[:10] if re.match(r"^\d{4}-\d{2}-\d{2}", text) else (text or "not recorded")


def value_with_unit(display, unit) -> str:
    """Published value with its unit, worded once: 29.0% · 6,463 persons · $57,784 (2024 inflation-adjusted dollars)."""
    display, unit = str(display or ""), str(unit or "")
    if unit == "percent":
        return display if display.endswith("%") else display + "%"
    if "USD" in unit and re.match(r"^-?[\d,.]+$", display):
        return f"${display} ({unit.replace('USD', 'dollars')})"
    return f"{display} {unit}".strip()


# Screen wording for the publisher's "*****" margin-of-error marker (controlled estimate, no MOE published).
# The marker itself stays visible; stored data and the printed brief text are unchanged.
MOE_NOT_PUBLISHED = "Not published (source marker *****: controlled estimate)"


def _moe_cell(display) -> str:
    return ('Not published <span class="fine">(source marker *****)</span>' if str(display) == "*****"
            else e(display))


def moe_with_unit(moe, unit) -> str:
    """Margin of error with its unit: ±4.3 percentage points · ±542 persons · ±$1,121."""
    moe, unit = str(moe or ""), str(unit or "")
    if moe == "*****":
        return MOE_NOT_PUBLISHED
    if not moe.startswith("±"):
        return moe
    if unit == "percent":
        return moe + " percentage points"
    if "USD" in unit:
        return "±$" + moe[1:]
    return f"{moe} {unit}".strip()


def readable_label(label) -> str:
    """Census official labels use '!!' between levels; show them as a readable path."""
    return str(label or "").replace("!!", " › ")


_HAWAII_BODY = re.compile(r"\bHawaii (?=(DBEDT|DOH|DHS|Legislature|Office of Elections|Public Housing Authority|statewide)\b)")


def hawaii_display(text) -> str:
    """Display form for app-shown agency, publisher and jurisdiction names ("Hawaii DOH" -> "Hawaiʻi DOH").
    Official document titles, URLs, Census names and stored records are not passed through this."""
    return _HAWAII_BODY.sub("Hawaiʻi ", str(text or ""))


def human_words(value) -> str:
    """Recorded snake_case status text as plain words, first letter capitalised."""
    text = str(value or "").replace("_", " ").strip()
    return text[:1].upper() + text[1:] if text else "Not recorded"


_SHEET_CELL = re.compile(r"^(?P<sheet>[^!]+)!(?P<cell>[A-Z]+\d+) \(MOE (?P<moe>[A-Z]+\d+)\)$")
_TEXT_LINES = re.compile(r"^(?:\S+/)?\S+ lines (?P<a>\d+)[–-](?P<b>\d+)$")
_PAGES = re.compile(r"^\S+ pages (?P<pages>.+?)(?: \((?P<section>.*)\))?$")
_PATHLIKE = re.compile(r"(^|/)[\w.-]+\.(txt|pdf|xlsx?|json|csv|html?)$|^[0-9a-f]{40,}$|^sha256:", re.I)


def human_locator(text) -> str:
    """Plain wording for a recorded source location. Paths, hashes and raw JSON are not shown."""
    text = str(text or "").strip()
    if text.startswith("Historical source locator:"):
        try:
            loc = json.loads(text.split(":", 1)[1])
        except ValueError:
            return "Recorded location"
        return _locator_from_dict(loc)
    if text.startswith("{"):
        try:
            return _locator_from_dict(json.loads(text))
        except ValueError:
            return "Recorded location"
    m = _SHEET_CELL.match(text)
    if m:
        return f"Sheet {m['sheet']}, cell {m['cell']} (MOE {m['moe']})"
    m = _TEXT_LINES.match(text)
    if m:
        return f"Lines {m['a']}–{m['b']}"
    m = _PAGES.match(text)
    if m:
        return f"Pages {m['pages']}" + (f" ({m['section']})" if m["section"] else "")
    if "; " in text and ": " in text:
        pairs = [p.split(": ", 1) for p in text.split("; ") if ": " in p]
        shown = [f"{human_words(k)} {v}" for k, v in pairs if not _PATHLIKE.search(str(v).strip())]
        return "; ".join(shown) or "Recorded location"
    return "Recorded location" if _PATHLIKE.search(text) else text


def _locator_from_dict(loc) -> str:
    if not isinstance(loc, dict):
        return "Recorded location"
    if loc.get("sheet") and loc.get("estimate_cell"):
        return f"Sheet {loc['sheet']}, cell {loc['estimate_cell']}" + (f" (MOE {loc['moe_cell']})" if loc.get("moe_cell") else "")
    if loc.get("sheet") and loc.get("cell"):
        extra = ", ".join(f"{w} {loc[k]}" for k, w in (("row_label", "row"), ("column_label", "column"), ("section", "section")) if loc.get(k))
        return f"Sheet {loc['sheet']}, cell {loc['cell']}" + (f" ({extra})" if extra else "")
    if loc.get("line_start") is not None:
        return f"Lines {loc['line_start']}–{loc.get('line_end', loc['line_start'])}"
    if loc.get("pages"):
        return f"Pages {loc['pages']}" + (f" ({loc['section']})" if loc.get("section") else "")
    return _plain_pairs(loc) or "Recorded location"


def _plain_pairs(d) -> str:
    """Scalar key/values as plain text, leaving out identifiers, paths and hashes."""
    out = []
    for k, v in (d or {}).items():
        if isinstance(v, (dict, list)) or v is None or v == "":
            continue
        if re.search(r"(^|_)(id|ids|path|sha256|hash|digest|bytes)$", str(k)) or _PATHLIKE.search(str(v)):
            continue
        out.append(f"{human_words(k)}: {v}")
    return "; ".join(out)


def _plain_dl(d) -> str:
    rows = []
    for k, v in (d or {}).items():
        if isinstance(v, (dict, list)) or v == "":
            continue
        if re.search(r"(^|_)(id|ids|path|sha256|hash|digest|bytes)$", str(k)) or _PATHLIKE.search(str(v)):
            continue
        rows.append(f'<div><dt>{e(human_words(k))}</dt><dd>{e("No published value" if v is None else v)}</dd></div>')
    return f'<dl class="kv">{"".join(rows)}</dl>' if rows else ""


def _source_button(source_id, finding_id=None, label="Source", context=None) -> str:
    fid = f' data-finding-id="{e(finding_id)}"' if finding_id else ""
    about = context or source_label(source_id)
    return (f'<button type="button" class="btn-link source-btn" data-source-id="{e(source_id)}"{fid}>'
            f'{e(label)}<span class="sr-only">: {e(about)}</span></button>')


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
def _geo_words(geography_id) -> str:
    """HI-HOUSE-028-2024 style identifiers as words; other text unchanged."""
    m = re.match(r"^HI-(HOUSE|SENATE|COUNTY|STATE)(?:-(\d+))?-(\d{4})$", str(geography_id or ""))
    if not m:
        return str(geography_id or "")
    if m[1] == "COUNTY":
        return _COUNTY_NAMES.get(m[2], f"County {m[2]}")
    kind = {"HOUSE": "House District", "SENATE": "Senate District", "STATE": "State of Hawaiʻi"}[m[1]]
    return f"{kind} {m[2]}" if m[2] else kind


_COUNTY_NAMES = {"001": "Hawaiʻi County", "003": "City and County of Honolulu", "005": "Kalawao County",
                 "007": "Kauaʻi County", "009": "Maui County"}


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
        arg_bits.append("Measure: " + ", ".join(human_words(m) for m in args["metric_ids"]))
    if args.get("comparison_geography"):
        arg_bits.append("Compare with: " + _geo_words(args["comparison_geography"]))
    if args.get("program_ids"):
        arg_bits.append("Programs: " + ", ".join(human_words(p) for p in args["program_ids"]))
    if args.get("program_id"):
        arg_bits.append("Program: " + human_words(args["program_id"]))
    if args.get("observation_ids"):
        arg_bits.append(f"Administrative rows: {len(args['observation_ids'])} selected")
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
        + (f'<p class="res-defaults">Defaults applied: {e(", ".join(human_words(d) for d in defaults))}</p>' if defaults else "")
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
        f'<div class="fine">{e(f["metric"]["official_variable_label"])}</div></th>'
        f'<td class="{est_cls}">{e(est)}</td>'
        f'<td class="num">{_moe_cell(f["moe_display"])}</td>'
        f'<td>{e(f["unit"])}</td>'
        f'<td class="universe">{e(f["universe"])}</td>'
        f'<td>{e(f["period"]["label"])}</td>'
        f'<td class="actions">{_source_button(f["source"]["source_id"], f["finding_id"], context=f["metric"]["label"])}'
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
            f'<div><dt>District name (Census)</dt><dd>{e(ident.get("name"))}</dd></div>'
            f'<div><dt>Boundary session</dt><dd>{e(ident.get("boundary_session"))} (ACS 2024 geography)</dd></div>'
            '<div><dt>County and service coverage</dt><dd>Unverified; a district internal point does not establish jurisdiction.</dd></div>'
            f'<div><dt>2024 vs 2026 geometry</dt><dd>'
            + ("Equal at supplied precision (not a legal certification)" if eq else
               ("Differs" if eq is False else "Not available")) +
            f'</dd></div>'
            f'<div><dt>Boundary source</dt><dd>{_source_button(ident.get("source_id"), None, source_label(ident.get("source_id")))}</dd></div>'
            '</dl></section>'
        )
    scope_html = ('<p class="coverage">Selected-measure profile: ' + e(", ".join(human_words(m) for m in cov.get("returned_metric_ids") or [])) + '</p>') if cov.get("filtered") else '<p class="coverage">Full profile (all 20 measures).</p>'
    missing = cov.get("missing_estimates") or []
    cov_html = (f'<p class="coverage">Coverage: {e(cov.get("observations"))} of {e(cov.get("metrics_total"))} '
                f'normalized measures for this geography. '
                + (f'Unavailable estimates: {e(", ".join(human_words(m) for m in missing))}. ' if missing else "No unavailable estimates. ")
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
        checks = ", ".join(k.replace("_", " ") for k, v in f["compatibility"]["checks"].items() if v)
        rows.append(
            f'<tr id="row-{e(f["finding_id"])}"><th scope="row">{e(f["metric"]["label"])}'
            f'<div class="fine">{e(f["universe"])} · {e(f["unit"])} · {e(f["period"]["label"])}</div></th>'
            f'<td><span class="num">{e(L["estimate_display"])}</span> <span class="moe">MOE {e(L["moe_display"])}</span>'
            f'<div class="fine">{e(L["geography"]["label"])}</div>{_source_button(L["source"]["source_id"], L["finding_id"], context=L["geography"]["label"])}</td>'
            f'<td><span class="num">{e(R["estimate_display"])}</span> <span class="moe">MOE {e(R["moe_display"])}</span>'
            f'<div class="fine">{e(R["geography"]["label"])}</div>{_source_button(R["source"]["source_id"], R["finding_id"], context=R["geography"]["label"])}</td>'
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
        f'<td>{_source_button(r["source_id"], None, source_label(r["source_id"]))}</td></tr>' for r in rows)
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
            + _list(f.get("limitations") or [])
            + f'<footer>{_source_button(f["source"]["source_id"], f["finding_id"], context=f["series_label"])} '
            + _select_box(f["finding_id"], str(f["series_label"]) + " · " + str(f["period"]) + " · " + str(f["unit"]))
            + '</footer></article>')
    return "".join(cards)


def _evidence_list(evidence, finding_id) -> str:
    items = []
    for ev in evidence:
        ver = ('reviewed reference; the original page is not bundled'
               if ev.get('verification_kind') == 'authored_reference' else
               {True: "matches the retained text", False: "DOES NOT match the retained text",
                None: "page reference"}[ev["verified_against_extract"]])
        items.append(
            f'<li><details><summary>{e(ev["claim"])} <span class="fine">— {e(source_label(ev["source_id"]))}, '
            f'{e(human_locator(ev["locator_text"]))}; {e(ver)}</span></summary>'
            f'<pre class="support">{e(ev["support_text"])}</pre>'
            f'{_source_button(ev["source_id"], finding_id, "Inspect source")}</details></li>')
    return '<ul class="evidence">' + "".join(items) + "</ul>"


def _program_population_html(env) -> str:
    context = env["data"]["population_context"]
    definitions = "".join(
        f'<li><strong>{e(d["label"])}</strong>: {e(d["unit"])}; universe: {e(d["universe"])}. '
        f'<span class="fine">ACS table {e(d["table_id"])}'
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
            f'<span class="url">{_official_link(ref["url"], e(ref["url"]))}</span>'
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
    if brief.get("tracking"):
        parts.append(str(brief["tracking"]))
        if brief.get("recipe_version") == "food_assistance_outreach/1":
            parts.append("Office requests for SNAP information from the tracking start date; not eligible or unserved residents, participation, a population rate or program impact.")
    return " ".join(parts)


def action_checklist_html(brief):
    action=brief.get("action")
    tracking=brief.get("tracking")
    food = brief.get('recipe_version') == 'food_assistance_outreach/1'
    missing = 'not recorded' if food else 'not supplied'
    date_label = 'review date' if food else 'as of'
    tracking_html=(f'<p class="staff-edit">Staff tracking — not a verified fact: {e(tracking["label"])}; baseline {e(tracking["baseline"] if tracking["baseline"] is not None else missing)}; {date_label} {e(tracking["as_of"] or missing)}.</p>' if tracking else '')
    if food and tracking:
        tracking_html += '<p class="fine">Office requests for SNAP information from the tracking start date; not eligible or unserved residents, participation, a population rate or program impact.</p>'

    def record(row):
        return " · ".join(x for x in (row.get("owner_role"), row.get("due_date"), "done" if row.get("completed") else "to do") if x)
    rows="".join(f'<li>{e(row["text"])} <span class="staff-label">({e(record(row))})</span></li>' for row in brief.get("checklist",[]))
    checklist_html=('<h3>Office checklist — <span class="staff-label">staff work, not verified facts</span></h3><ol>'+rows+'</ol>') if rows else ''
    action_html=''
    if action:
        cites="".join(f'<a class="cite" href="#cite-{n}">[{n}]</a>' for n in sorted(brief.get("action_citations",[])))
        program=brief.get("action_program") or {}
        # Same recorded items as before, grouped by their recorded origin: the program's missing eligibility
        # facts, then the remaining routing/access questions (for example the unresolved Kalawao route).
        eligibility=[x for x in action["facts_to_verify"] if x in (program.get("missing_facts") or [])]
        routing=[x for x in action["facts_to_verify"] if x not in eligibility]
        next_step=((program.get("referral") or {}).get("next_step"))
        lims=brief.get("limitations") or []
        cost_note=("" if any(l.startswith("Current availability, capacity, wait, funding and cost remain unverified") for l in lims)
                   else " Current availability and cost unverified.")
        hyp_unknowns=set()
        for en in brief.get("entries") or []:
            parts=outreach_parts(en["text"]) if en["kind"]=="outreach_hypothesis" else None
            if parts:
                for head,items in parts[1]:
                    if head.startswith("Unknowns"):
                        hyp_unknowns.update(x.rstrip(".") for x in items)
        elig_html=(f'<p class="brief-elig"><strong>Eligibility facts the agency determines:</strong> the same open questions as listed under the outreach hypothesis above.</p>'
                   if eligibility and all(x in hyp_unknowns for x in eligibility) else
                   f'<p class="brief-elig"><strong>Eligibility facts the agency determines:</strong> {e("; ".join(eligibility))}.</p>' if eligibility else "")
        # The agency is already named by a selected program reference for the same program; it is not repeated.
        same_program=any(en["kind"]=="program_relevance" and str(en.get("finding_id","")).startswith(f'prog:{action["program_id"]}@')
                         for en in brief.get("entries") or [])
        agency="" if same_program else f' · {e(hawaii_display(program.get("agency","")))}'
        # Without the program reference tile, the agency step carries the recorded official referral contact.
        referral=brief.get("action_referral") or {};referral_contact=not same_program and bool(referral.get("url") or referral.get("phone"))
        action_html=('<h3>Agency action</h3>'
            f'<p>{e(program.get("name",action["program_id"]))}{agency} · {e(human_words(action["access"]["recorded_status"]))}{(" (" + e(human_date(action["access"]["checked_at"])) + ")") if action["access"]["checked_at"] else ""}.{cost_note} {cites}'
            + (f' · <strong>Recorded next step:</strong> {e(next_step)}' if next_step else "")
            + (f' · Referral: {e(", ".join(x for x in (referral.get("url"), referral.get("phone"), ("TTY " + referral["tty"]) if referral.get("tty") else None) if x))}' if referral_contact else "") + '</p>'
            + (f'<p class="brief-sub">Routing and access to confirm (open questions, not verified facts):</p>{_list(routing,"brief-questions brief-routing")}' if routing else "")
            + elig_html)
    return '<section class="brief-action">'+action_html+checklist_html+tracking_html+'</section>' if action_html or checklist_html or tracking_html else ''


def indicator_context_text(brief):
    indicator = brief.get('district_indicator')
    if not indicator:return ''
    value = indicator['estimate']
    numeric = type(value) in (int, float) and not indicator['annotation']
    label = ('0–<5%' if value < 5 else '5–<10%' if value < 10 else '10–<15%' if value < 15 else '15–<20%' if value < 20 else '20% or more') if numeric else 'unavailable'
    estimate = f"{value:g}%" if numeric else 'unavailable'
    moe = f"±{indicator['margin_of_error']:g} percentage points (90% MOE)" if indicator['margin_of_error'] is not None else '90% MOE unavailable'
    geometry = ('Displayed boundary matches the 2024 statistical geometry.' if indicator['geometry_compatible'] else 'Displayed 2026 boundary differs from the 2024 statistical geometry and remains unshaded.')
    return (f"District map context: poverty rate, all people {estimate}; {moe}; display class {label}. "
            f"{indicator['period']['label']}; universe: {indicator['universe']}. "
            f"{indicator['publisher']}, {indicator['source_title']}. "
            "Illustrative bins: 0–<5%, 5–<10%, 10–<15%, 15–<20%, 20% or more. "
            "Bins are display intervals, not policy thresholds or statistical tests. "
            "One district cannot establish rank, significance, eligibility or causality. " + geometry)


def indicator_context_html(brief):
    """Printed map context. Same facts as indicator_context_text (which stays the fit estimate's input),
    worded without repeating the section heading."""
    text = indicator_context_text(brief)
    if not text:return ''
    text = text.replace("District map context: poverty rate", "Poverty rate", 1)
    # Printed wording only: the source is named by the citation and the Sources list, so it is not repeated
    # inline, and the bin caveat joins the bin list. The fit estimate keeps the longer text (conservative).
    source = f"{brief['district_indicator']['publisher']}, {brief['district_indicator']['source_title']}. "
    text = text.replace(source, "", 1).replace(" Bins are display intervals,", " These are display intervals,", 1)
    text = hawaii_display(text)
    cites = ''.join(f'<a class="cite" href="#cite-{n}">[{n}]</a>' for n in brief.get('indicator_citations', []))
    return '<section class="brief-map-context"><h3>District map context</h3><p>' + e(text) + ' ' + cites + '</p></section>'


def _url_html(url) -> str:
    """The address as text. Line breaks are offered only after path slashes; scheme://host stays on one line."""
    url = str(url or "")
    scheme, sep, rest = url.partition("://")
    if not sep:
        return "/<wbr>".join(e(part) for part in url.split("/"))
    host, slash, path = rest.partition("/")
    return (f'<span class="url-host">{e(scheme + sep + host)}</span>'
            + ("/<wbr>" + "/<wbr>".join(e(part) for part in path.split("/")) if slash else ""))


def _official_link(url, inner=None) -> str:
    """An official https address as a link that opens in a new tab; other values stay plain text."""
    url = str(url or "")
    shown = inner if inner is not None else _url_html(url)
    if not url.startswith("https://"):
        return shown
    return f'<a class="official-link" href="{e(url)}" target="_blank" rel="noopener noreferrer">{shown}</a>'


_ISSUE_NAMES = {"aging_at_home/1": "Older-adult support at home", "food_assistance_outreach/1": "SNAP outreach",
                "custom/1": "Custom (staff-composed steps)"}


def printed_limitations(brief) -> list:
    from .core import L_COMPARE, L_EDITS, L_HYPOTHESIS
    kinds = {en["kind"] for en in brief["entries"]}
    out = []
    for lim in brief["limitations"]:
        # Every staff title, note, checklist and tracking line carries its own inline staff label.
        if lim == L_EDITS:
            continue
        if lim == L_COMPARE and not kinds & {"comparison", "outreach_hypothesis"}:
            continue
        if lim == L_HYPOTHESIS and "outreach_hypothesis" not in kinds and not brief.get("action"):
            continue
        out.append(lim)
    return out


def _host(url) -> str:
    from urllib.parse import urlparse
    try:
        return urlparse(str(url or "")).netloc
    except ValueError:
        return ""


def _citation_html(c) -> str:
    """One numbered source: publisher, descriptive label, address, retrieval date and plain locations."""
    places, sheets = [], {}
    for raw in c["locators"]:
        m = _SHEET_CELL.match(str(raw))
        if m:
            sheets.setdefault(m["sheet"], []).append(f'{m["cell"]} (MOE {m["moe"]})')
        else:
            places.append(human_locator(raw))
    places = [f'Sheet {name}, cells {", ".join(dict.fromkeys(cells))}' if len(cells) > 1 else f'Sheet {name}, cell {cells[0]}'
              for name, cells in sheets.items()] + list(dict.fromkeys(places))
    return (f'<li id="cite-{c["n"]}"><span class="cite-n">[{c["n"]}]</span> {e(hawaii_display(c["publisher"]))} — '
            f'<a class="cite-label" href="{e(c["url"])}">{e(source_label(c["source_id"], c.get("url")))}</a>. '
            # The full recorded address is printed as text: saved PDFs may drop link targets.
            f'<span class="url">{_url_html(c["url"])}</span> · Retrieved {e(human_date(c.get("retrieved_at_utc")))}'
            + (f' · <span class="locators">{e("; ".join(places))}</span>' if places else "") + '</li>')


_GROUPS = (("Published estimates (survey estimates with margins of error)", ("statistic", "comparison")),
           ("Program information (informational; the agency determines eligibility)", ("program_relevance",)),
           ("Administrative context (not district data)", ("administrative_context",)),
           ("Outreach hypotheses (not measured gaps or eligibility findings)", ("outreach_hypothesis",)))
_OUTREACH_PARTS = (" Observed area conditions (", " Program context (informational): ", " Unknowns the agency determines: ", " Next step: ")


def _top_level_items(text) -> list:
    """Split on "; " outside parentheses; joining the parts with "; " gives back the exact text."""
    parts, depth, start, i = [], 0, 0, 0
    while i < len(text):
        ch = text[i]
        depth += ch == "(" ; depth -= ch == ")"
        if depth == 0 and text.startswith("; ", i):
            parts.append(text[start:i]); start = i + 2; i += 2; continue
        i += 1
    parts.append(text[start:])
    return parts


def outreach_parts(text):
    """The recorded outreach sentence as (claim, [(label, [items])]) segments, or None when its recorded
    section labels are not all present in order. Every character of the text is kept (verified by tests)."""
    idx, pos = [], 0
    for label in _OUTREACH_PARTS:
        i = text.find(label, pos)
        if i < 0:
            return None
        idx.append(i); pos = i + len(label)
    claim = text[:idx[0]]
    out = []
    for k, label in enumerate(_OUTREACH_PARTS):
        end = idx[k + 1] if k + 1 < len(idx) else len(text)
        seg = text[idx[k] + 1:end]
        if k == 0:
            head, _, rest = seg.partition("): ")
            out.append((head + "):", _top_level_items(rest)))
        else:
            head, rest = label.strip(), seg[len(label.strip()):].lstrip(" ")
            out.append((head, _top_level_items(rest) if k == 2 else [rest]))
    return claim, out


# Printed dollar wording. The recorded text writes dollar values as "57,784 2024 inflation-adjusted USD
# (±5,211 90% MOE)". Only the exact recorded phrasings below are re-presented as "$57,784 (2024
# inflation-adjusted dollars) (90% margin of error ±$5,211)"; every number and sign is kept, and any other
# wording is printed unchanged. The recorded text itself is never modified.
_USD_UNITS = {"2024 inflation-adjusted USD": "2024 inflation-adjusted dollars", "USD per month": "dollars per month"}
_UNIT = "(?P<unit>2024 inflation-adjusted USD|USD per month)"
_NUM = r"-?[\d,]+(?:\.\d+)?"
_STAT_USD = re.compile(rf"^(?P<geo>[^:]+): (?P<label>.+?) (?P<v>{_NUM}) {_UNIT} \(±(?P<m>[\d,]+(?:\.\d+)?) 90% MOE\); (?P<rest>universe: .+)$")
_CMP_USD = re.compile(rf"^(?P<label>[^:]+): (?P<lg>.+?) (?P<lv>{_NUM}) {_UNIT} \(±(?P<lm>[\d,.]+)\) vs (?P<rg>.+?) (?P<rv>{_NUM}) (?P=unit) \(±(?P<rm>[\d,.]+)\); "
                      rf"point difference (?P<d>[+−-]?[\d,.]+) (?P=unit) (?P<rest>\(no significance implied\); .+)$")
_ITEM_USD = re.compile(rf"^(?P<label>.+?) (?P<v>{_NUM}) ±(?P<m>[\d,.]+)(?: \(state (?P<sv>{_NUM}) ±(?P<sm>[\d,.]+); difference (?P<d>[+−-]?[\d,.]+)\))? {_UNIT}(?P<end>\.?)$")


def _dollars(n) -> str:
    n = str(n)
    return (n[0] + "$" + n[1:]) if n[:1] in "+−-" else "$" + n


def dollar_wording(text) -> str:
    """Display wording for the recorded dollar phrasings; any other text is returned unchanged."""
    text = str(text or "")
    m = _STAT_USD.match(text)
    if m:
        return (f'{m["geo"]}: {m["label"]}: {_dollars(m["v"])} ({_USD_UNITS[m["unit"]]}) '
                f'(90% margin of error ±{_dollars(m["m"])}); {m["rest"]}')
    m = _CMP_USD.match(text)
    if m:
        return (f'{m["label"]} ({_USD_UNITS[m["unit"]]}): {m["lg"]} {_dollars(m["lv"])} (±{_dollars(m["lm"])}) vs '
                f'{m["rg"]} {_dollars(m["rv"])} (±{_dollars(m["rm"])}); point difference {_dollars(m["d"])} {m["rest"]}')
    m = _ITEM_USD.match(text)
    if m:
        state = f' (state {_dollars(m["sv"])} ±{_dollars(m["sm"])}; difference {_dollars(m["d"])})' if m["sv"] else ""
        return f'{m["label"]}: {_dollars(m["v"])} ±{_dollars(m["m"])}{state} ({_USD_UNITS[m["unit"]]}){m["end"]}'
    return text


_STAT_FIG = re.compile(r"^(?P<geo>[^:]+): (?P<label>.+?) (?P<v>-?[\d,]+(?:\.\d+)?%?)(?: (?P<unit>persons|households|housing units|years))? "
                       r"\(±(?P<m>[\d,]+(?:\.\d+)?) (?P<pp>percentage points )?90% MOE\); (?P<rest>universe: .+)$")
_ITEM_FIG = re.compile(r"^(?P<label>.+?) (?P<v>-?[\d,]+(?:\.\d+)?%?) ±(?P<rest>\d[\d,.]*(?: .*)?)$")


def figure_wording(text) -> str:
    """Display wording for recorded statistic sentences and outreach clauses: a colon between the measure and
    its value, and "90% margin of error" spelled out. Dollar phrasings use dollar_wording. Every value, sign,
    unit and geography is kept; any other wording is returned unchanged."""
    text = str(text or "")
    shown = dollar_wording(text)
    if shown != text:
        return shown
    m = _STAT_FIG.match(text)
    if m:
        pct = m["v"].endswith("%")
        if pct and m["pp"] and not m["unit"]:
            return f'{m["geo"]}: {m["label"]}: {m["v"]} (90% margin of error ±{m["m"]} percentage points); {m["rest"]}'
        if not pct and m["unit"] and not m["pp"]:
            return f'{m["geo"]}: {m["label"]}: {m["v"]} {m["unit"]} (90% margin of error ±{m["m"]} {m["unit"]}); {m["rest"]}'
        return text
    m = _ITEM_FIG.match(text)
    if m and not m["label"].endswith(":"):
        return f'{m["label"]}: {m["v"]} ±{m["rest"]}'
    return text


def _finding_body(en) -> str:
    if en["kind"] == "outreach_hypothesis":
        parts = outreach_parts(en["text"])
        if parts:
            claim, segs = parts
            return (f'{e(claim)}' + "".join(
                f'<span class="brief-part"><strong>{e(head)}</strong> '
                + ("; ".join(e(x) for x in items) if len(items) == 1 or not head.startswith("Observed") else
                   '<span class="brief-part-list">' + "".join(f'<span class="brief-part-item">{e(figure_wording(x) if head.startswith("Observed") else x)}{";" if j < len(items) - 1 else ""}</span>' for j, x in enumerate(items)) + '</span>')
                + '</span>' for head, items in segs))
    return e(figure_wording(en["text"]))


def brief_doc_html(brief: dict) -> str:
    """The one printable brief. Screen preview and print use this same markup.

    Machine identities (brief id, snapshot, finding ids, source ids and hashes) stay in the brief data,
    case files and diagnostics; the printed page carries human labels only."""
    staff = brief["staff_edits"]
    lbl = brief["staff_edit_label"]
    kind_label = {"statistic": "Statistic", "comparison": "Comparison", "program_relevance": "Program (informational)",
                  "outreach_hypothesis": "Outreach hypothesis", "administrative_context": "Administrative context (not district data)"}
    def item(en):
        cites = "".join(f'<a class="cite" href="#cite-{n}">[{n}]</a>' for n in sorted(en["citations"]))
        note = (f'<div class="staff-edit"><span class="staff-label">{e(lbl)}:</span> {e(en["staff_note"])}</div>'
                if en.get("staff_note") else "")
        kind = "" if en["kind"] == "outreach_hypothesis" else f'<span class="kind">{e(kind_label.get(en["kind"], en["kind"]))}</span> '
        return (f'<li class="brief-finding" data-finding-id="{e(en["finding_id"])}">'
                f'{kind}'
                f'{_finding_body(en)} {cites}{note}</li>')
    groups = []
    for name, kinds in _GROUPS:
        chosen = [en for en in brief["entries"] if en["kind"] in kinds]
        if chosen:
            groups.append(f'<p class="brief-group">{e(name)}</p><ol class="brief-findings">{"".join(item(en) for en in chosen)}</ol>')
    known = {k for _, ks in _GROUPS for k in ks}
    other = [en for en in brief["entries"] if en["kind"] not in known]
    if other:
        groups.append(f'<ol class="brief-findings">{"".join(item(en) for en in other)}</ol>')
    cites = "".join(_citation_html(c) for c in brief["citations"])
    limits = printed_limitations(brief)
    from .core import L_NO_ELIG, L_HYPOTHESIS
    # The footer only repeats two limitations; it prints when those limitations are not on the page.
    footer = "" if L_NO_ELIG in limits and (L_HYPOTHESIS in limits or not any(en["kind"] == "outreach_hypothesis" for en in brief["entries"])) else (
        '<footer class="brief-foot">Programs are informational; the administering agency determines '
        'eligibility. Outreach items are hypotheses, not measured gaps.</footer>')
    title_label = f' <span class="staff-label">({e(lbl)})</span>' if brief["title_is_staff_edit"] else ""
    map_session = brief.get("map_session", 2024)
    return (
        f'<article id="brief-doc" class="brief-doc" data-brief-id="{e(brief["brief_id"])}">'
        f'<header class="brief-head"><h2>{e(brief["title"])}{title_label}</h2>'
        f'<p class="brief-meta">{e(brief["geography"]["label"])}'
        + (f' · Issue: {e(_ISSUE_NAMES[brief.get("recipe_version")])}' if brief.get("recipe_version") in _ISSUE_NAMES else "")
        + ' · Statistics use 2024 district boundaries'
        + (f'; map shows the {e(map_session)} boundary' if map_session != 2024 else "")
        + ' · Facts from bundled public sources listed below</p></header>'
        + (f'<section class="staff-edit"><h3>Staff summary <span class="staff-label">({e(lbl)})</span></h3>'
           f'<p>{e(staff["note"])}</p></section>' if staff.get("note") else "")
        + f'<section><h3>Selected findings</h3>{"".join(groups)}</section>'
        + (f'<section class="staff-edit"><h3>Staff next steps <span class="staff-label">({e(lbl)})</span></h3>'
           f'<p>{e(staff["next_steps"])}</p></section>' if staff.get("next_steps") else "")
        + action_checklist_html(brief)
        + indicator_context_html(brief)
        + f'<section><h3>Limitations</h3>{_list(limits, "brief-limits")}</section>'
        + f'<section><h3>Sources</h3><ol class="brief-cites">{cites}</ol></section>'
        + footer
        + "</article>"
    )


def brief_editor_html(brief: dict) -> str:
    staff = brief["staff_edits"]
    notes = {en["finding_id"]: en.get("staff_note") or "" for en in brief["entries"]}
    rows = "".join(
        f'<div class="field"><label for="note-{i}">Staff note for finding {i + 1}: '
        f'{e(en["text"] if len(en["text"]) <= 90 else en["text"][:88] + "…")}</label>'
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
        errs = "".join(f'<li><strong>{e(human_words(v["field"]))}</strong>: {e(v["message"])}</li>'
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
CATALOG_PAGE_SIZE = 50
CATALOG_QUERY_MAX = 100


def catalog_rows_html(cat: dict, observations) -> str:
    """Table rows for one page of catalog observations (the same markup for the first page and later pages)."""
    geos = {g["geography_id"]: g["label"] for g in cat["geographies"]}
    metrics = {m["metric_id"]: m for m in cat["metrics"]}
    rows = "".join(
        f'<tr data-geo="{e(o["geography_id"])}" data-metric="{e(o["metric_id"])}" data-finding-id="{e(o["finding_id"])}">'
        f'<td>{e(geos[o["geography_id"]])}</td><th scope="row">{e(metrics[o["metric_id"]]["label"])}</th>'
        f'<td class="num">{e(o["estimate_display"])}</td><td class="num">{_moe_cell(o["moe_display"])}</td>'
        f'<td>{e(o["unit"])}</td><td class="universe fine">{e(metrics[o["metric_id"]]["universe"])}</td>'
        f'<td>{_source_button(o["source_id"], o["finding_id"], context=geos[o["geography_id"]] + ", " + metrics[o["metric_id"]]["label"])}</td></tr>'
        for o in observations)
    return rows or '<tr class="cat-empty"><td colspan="7">No statistics match these filters. Choose Clear filters to see every row.</td></tr>'


def _count_display(value) -> str:
    return "Unpublished (no value)" if value is None else f"{value:,}"


def catalog_html(cat: dict) -> str:
    geos = {g["geography_id"]: g["label"] for g in cat["geographies"]}
    programs = {p["program_id"]: p.get("name") or human_words(p["program_id"]) for p in cat.get("programs") or []}
    geo_opts = "".join(f'<option value="{e(g)}">{e(l)}</option>' for g, l in geos.items())
    rows = catalog_rows_html(cat, cat["observations"][:CATALOG_PAGE_SIZE])
    metric_groups = {}
    for m in cat["metrics"]:
        metric_groups.setdefault(m.get("group") or "Measures", []).append(m)
    metric_opts = "".join(
        f'<optgroup label="{e(g)}">' + "".join(f'<option value="{e(m["metric_id"])}">{e(m["label"])}</option>' for m in ms)
        + '</optgroup>' for g, ms in metric_groups.items())
    geo_rows = "".join(
        f'<tr><td>{e(g["label"])}</td><td>{e(g["geoid"])}</td>'
        f'<td>{e(g["observation_count"])}</td></tr>' for g in cat["geographies"])
    unavailable = ", ".join(u["label"] for u in cat["unavailable_geographies"])
    dc = cat["district_counts"]
    # Coverage wording comes from the catalog's own geography kinds, so a limited snapshot stays truthful.
    cat_count = int(cat["coverage"]["statistics_observations"])
    with_stats = sum(1 for g in cat["geographies"] if g.get("kind") == "district")
    districts_2024 = dc["2024"]["house"] + dc["2024"]["senate"]
    comparisons = [g["label"] for g in cat["geographies"] if g.get("kind") != "district"]
    stats_text = (f'Every House and Senate district of the 2024 boundary session has statistics ({with_stats}). '
                  if with_stats == districts_2024 else
                  f'{with_stats} of {districts_2024} House and Senate districts of the 2024 boundary session have statistics. ')
    comparison_text = (f'Comparison geographies ({len(comparisons)}): {", ".join(comparisons)}. ' if comparisons else
                       'No comparison geographies are included. ')
    map_text = str(cat["coverage"]["map"]).replace("IA-1 displays", "This app displays", 1)
    part_rows = "".join(
        f'<tr><td>{e(programs.get(r["program_id"], human_words(r["program_id"])))}</td>'
        f'<td>{e(r["geography"]["name"])} ({e(r["geography"]["type"])})</td><td>{e(r["period"])}</td>'
        f'<td class="{"num" if r["value"] is not None else "num missing"}">{e(_count_display(r["value"]))}</td>'
        f'<td>{e(r["unit"])}</td><td class="fine">{e(r.get("series_label"))}<br>{e(r.get("status"))}<br>{e(r["coverage"])}</td>'
        f'<td>{_source_button(r["source_id"], "admin:" + r["observation_id"], source_label(r["source_id"]))}</td></tr>' for r in cat["participation"])
    return (
        '<section aria-labelledby="cov-h"><h3 id="cov-h">Coverage</h3>'
        f'<p>{e(f"{cat_count:,}")} statistics in this data: '
        f'{e(cat["coverage"]["metrics"])} measures × {e(cat["coverage"]["statistics_geographies"])} geographies. '
        f'Boundary layers: 2024 — {e(dc["2024"]["house"])} House, {e(dc["2024"]["senate"])} Senate; '
        f'2026 — {e(dc["2026"]["house"])} House, {e(dc["2026"]["senate"])} Senate. '
        + e(stats_text) + e(comparison_text)
        + (f'Geographies without statistics in this data: {e(unavailable)}.' if unavailable else "") + '</p>'
        f'<p class="fine">{e(map_text)}</p>'
        + _list(cat["limitations"]) +
        '<table class="data-table compact"><caption>Normalized geographies</caption><thead><tr>'
        '<th scope="col">Geography</th><th scope="col">Census GEOID</th>'
        '<th scope="col">Observations</th></tr></thead>'
        f'<tbody>{geo_rows}</tbody></table></section>'
        '<section aria-labelledby="obs-h"><h3 id="obs-h">All statistics</h3>'
        '<div class="filters cat-filters" role="group" aria-label="Filter all statistics">'
        '<label for="cat-geo">Geography</label>'
        f'<select id="cat-geo"><option value="">All geographies</option>{geo_opts}</select>'
        '<label for="cat-metric">Measure</label>'
        f'<select id="cat-metric"><option value="">All measures</option>{metric_opts}</select>'
        '<label for="cat-q">Search text</label>'
        f'<input id="cat-q" type="search" maxlength="{CATALOG_QUERY_MAX}" autocomplete="off" aria-describedby="cat-q-help">'
        '<button type="button" id="cat-clear" class="btn btn-small">Clear filters</button></div>'
        f'<p id="cat-q-help" class="fine">Filters and search cover all {e(f"{cat_count:,}")} statistics, not only the rows shown. '
        'Search matches geography, measure, estimate, margin of error, unit and universe text. '
        'Search text goes to this app’s server, not to OpenAI.</p>'
        '<div class="cat-pager"><p id="cat-count" class="fine" role="status" aria-live="polite" tabindex="-1"></p>'
        '<div class="btn-row"><button type="button" id="cat-prev" class="btn btn-small">Previous page</button>'
        '<button type="button" id="cat-next" class="btn btn-small">Next page</button></div></div>'
        '<div id="cat-error" class="notice notice-error" role="alert" tabindex="-1" hidden></div>'
        f'<table class="data-table" id="cat-table" data-total="{len(cat["observations"])}" '
        f'data-matched="{len(cat["observations"])}" data-offset="0" data-limit="{CATALOG_PAGE_SIZE}">'
        '<thead><tr><th scope="col">Geography</th>'
        '<th scope="col">Measure</th><th scope="col">Estimate</th><th scope="col">90% MOE</th>'
        '<th scope="col">Unit</th><th scope="col">Universe</th><th scope="col">Source</th></tr></thead>'
        f'<tbody>{rows}</tbody></table></section>'
        '<section aria-labelledby="part-h"><h3 id="part-h">Administrative participation rows (context only)</h3>'
        '<p class="fine">State, county or island aggregates. None is usable for a district gap.</p>'
        '<table class="data-table compact"><thead><tr><th scope="col">Program</th>'
        '<th scope="col">Geography</th><th scope="col">Period</th><th scope="col">Value</th><th scope="col">Unit</th>'
        f'<th scope="col">Coverage</th><th scope="col">Source</th></tr></thead><tbody>{part_rows}</tbody></table></section>'
    )


def sources_html(cat: dict) -> str:
    rows = "".join(
        f'<tr><th scope="row">{e(source_label(s["source_id"], s.get("url")))}</th><td>{e(hawaii_display(s["publisher"]))}</td>'
        f'<td class="url">{_official_link(s["url"], e(s["url"]))}</td><td>{e(human_date(s.get("retrieved_at_utc")))}</td>'
        f'<td>{_source_button(s["source_id"], None, "Inspect")}</td></tr>' for s in cat["sources"])
    labels = {s["source_id"]: source_label(s["source_id"], s.get("url")) for s in cat["sources"]}
    # Label map for the investigation view (inert JSON data; never executed).
    data = json.dumps(labels, ensure_ascii=False, sort_keys=True).replace("<", "\\u003c")
    return ('<p class="fine">Labels describe each recorded source from its publisher, address and file name; '
            'official document titles and publication dates are not recorded here. Addresses are shown for '
            'reference and are not opened by the app.</p>'
            '<table class="data-table compact"><caption>Recorded sources</caption><thead><tr>'
            '<th scope="col">Source (descriptive label)</th><th scope="col">Publisher</th>'
            '<th scope="col">Address</th><th scope="col">Retrieved</th>'
            f'<th scope="col">Details</th></tr></thead><tbody>{rows}</tbody></table>'
            f'<script type="application/json" id="source-label-data">{data}</script>')


_CANNOT = {
    "statistics": "Published survey estimates for whole areas, with margins of error, describing a five-year period. "
                  "They cannot identify eligible residents, individual need or current service capacity.",
    "programs": "A dated program reference. It cannot establish current availability, wait time, cost or any "
                "person's eligibility; the administering agency decides eligibility.",
    "participation": "Recorded state, county or island counts. They are not district counts and cannot measure a "
                     "district participation gap or an eligible-but-not-enrolled population.",
    "geography": "Boundary records. They show where a district is drawn; they do not establish program service "
                 "areas, agency jurisdiction or travel distance.",
}


def _row(label, value) -> str:
    return f'<div><dt>{e(label)}</dt><dd>{e(value)}</dd></div>' if value not in (None, "", []) else ""


def _supports_html(ref: dict, source_id: str) -> str:
    """What the selected finding takes from this source, in plain labelled rows."""
    if not isinstance(ref, dict):
        return ""
    if ref.get("kind") in ("statistic", "comparison") or ref.get("metric"):
        m, g, per = ref.get("metric") or {}, ref.get("geography") or {}, ref.get("period") or {}
        value = ref.get("estimate_display")
        moe = ref.get("moe_display")
        return ('<dl class="kv">' + _row("Measure", m.get("label")) + _row("Area", g.get("label"))
                + _row("Published value", value_with_unit(value, ref.get("unit")) if value is not None else None)
                + _row("Margin of error (90%)", moe_with_unit(moe, ref.get("unit"))) + _row("Universe", ref.get("universe"))
                + _row("Period", per.get("label")) + _row("ACS table", m.get("table_id"))
                + _row("Official variable label", readable_label(m.get("official_variable_label")))
                + _row("Note", ref.get("annotation_meaning")) + '</dl>')
    if ref.get("program"):
        p = ref["program"]
        spans = [x for x in ref.get("evidence") or [] if x.get("source_id") == source_id]
        quotes = "".join(
            f'<li><p><strong>{e(x.get("claim"))}</strong> <span class="fine">({e(human_locator(x.get("locator_text")))})</span></p>'
            + (f'<blockquote class="support">{e(x.get("support_text"))}</blockquote>' if x.get("support_text") else "")
            + '</li>' for x in spans)
        return ('<dl class="kv">' + _row("Program", p.get("name")) + _row("Agency", p.get("agency"))
                + _row("Jurisdiction", p.get("jurisdiction")) + _row("Recorded status", human_words(p.get("status")))
                + _row("Program record checked", human_date(p.get("checked_at")) if p.get("checked_at") else None)
                + _row("Effective date", ref.get("effective_text")) + '</dl>'
                + (f'<h4>Passages this program reference relies on</h4><ul class="support-list">{quotes}</ul>' if quotes else ""))
    if "value" in ref and ref.get("program_id"):
        g = ref.get("geography") or {}
        value = ref.get("value")
        return ('<dl class="kv">' + _row("Program", human_words(ref.get("program_id")))
                + _row("Geography", g.get("name") if isinstance(g, dict) else g) + _row("Period", ref.get("period"))
                + _row("Value", "No published value" if value is None else f"{value:,}" if isinstance(value, int) else value)
                + _row("Unit", ref.get("unit")) + _row("Status", human_words(ref.get("status")))
                + _row("Coverage", ref.get("coverage")) + _row("Revision", ref.get("revision_status")) + '</dl>')
    return _plain_dl(ref)


def source_html(res: dict) -> str:
    """Source inspection for staff: what the claim uses, where it sits, and what the source cannot establish.

    Packet paths, hashes, byte counts and raw locator JSON remain in the API result and diagnostics."""
    s = res["source"]
    rf = res["retained_file"]
    detail = res.get("detail") or {}
    label = source_label(s["source_id"], s.get("url"))
    kind = detail.get("type")
    where, supports = "", ""
    if kind == "sheet_cell":
        if not detail.get("available"):
            supports = '<p class="alert">The workbook copy is not available in this app, so its cells cannot be shown.</p>'
        else:
            cells = "".join(f'<tr><td>{e(human_words(c["role"]))}</td><td>Sheet {e(detail["locator"]["sheet"])}, cell {e(c["ref"])}</td>'
                            f'<td>{e(c["stored_text"])}</td></tr>' for c in detail["cells"])
            supports = (f'<table class="data-table compact"><caption>Workbook cells used</caption><thead><tr>'
                        f'<th scope="col">Role</th><th scope="col">Location</th><th scope="col">Text in the workbook</th></tr></thead>'
                        f'<tbody>{cells}</tbody></table>'
                        f'<p>The app’s estimate {e(detail["published_display"]["estimate"])} '
                        f'{"matches" if detail["estimate_matches"] else "DOES NOT match"} the workbook cell; margin of error '
                        f'{e(detail["published_display"]["moe"])} {"matches" if detail["moe_matches"] else "DOES NOT match"}.</p>')
        where = _locator_from_dict(detail.get("locator") or {})
    elif kind == "administrative_row":
        verified = detail.get("cell_verified")
        check = {True: "The recorded value matches the retained cell.",
                 False: "The recorded value was not checked against a retained cell.",
                 None: "The original cell was not reread."}[verified]
        supports = (_supports_html(detail.get("normalized_row") or {}, s["source_id"])
                    + f'<p class="fine">{e(check)}</p>'
                    + (f'<p>Text in the source cell: “{e(detail["stored_text"])}”</p>' if "stored_text" in detail else ""))
        where = _locator_from_dict(detail.get("locator") or {})
    elif kind == "projection_reference":
        supports = _supports_html(detail.get("normalized_reference") or {}, s["source_id"])
        where = _locator_from_dict(detail.get("locator")) if detail.get("locator") else ""
    elif kind == "text_spans":
        supports = '<ul class="support-list">' + "".join(
            f'<li><p><strong>{e(sp["claim"])}</strong> <span class="fine">({e(human_locator(sp["locator_text"]))}; '
            f'{"matches the retained text" if sp["verified_against_extract"] else ("page reference" if sp["verified_against_extract"] is None else "DOES NOT match the retained text")})</span></p>'
            f'<blockquote class="support">{e(sp["support_text"])}</blockquote></li>' for sp in detail["spans"]) + '</ul>'
    copy_note = ("The app holds a copy of this file and confirmed it is unchanged." if rf.get("available") else
                 "The original file is not bundled with this app. The recorded values and their location are kept.")
    final = s.get("final_url") if s.get("final_url") and s.get("final_url") != s["url"] else None
    return (
        f'<h3 class="source-title">{e(label)}</h3>'
        '<p class="fine">Descriptive label. The official document title and publication date are not recorded.</p>'
        '<dl class="kv source-facts">'
        f'<div><dt>Publisher</dt><dd>{e(hawaii_display(s["publisher"]))}</dd></div>'
        f'<div><dt>Retrieved</dt><dd>{e(human_date(s.get("retrieved_at_utc")))}</dd></div>'
        + (f'<div><dt>Location in the source</dt><dd>{e(where)}</dd></div>' if where else "")
        + f'<div class="kv-wide"><dt>Address</dt><dd class="url">{_official_link(s["url"])}</dd></div>'
        + (f'<div class="kv-wide"><dt>Address after redirect</dt><dd class="url">{e(final)}</dd></div>' if final else "")
        + '</dl>'
        + (f'<h4>What the selected finding uses</h4>{supports}' if supports else "")
        + f'<h4>What this source cannot establish</h4><p>{e(_CANNOT.get(s.get("family"), "It records only what is shown above; other facts need separate confirmation."))}</p>'
        + f'<p class="fine">{e(copy_note)} The address opens the publisher’s page in a new browser tab; the app itself does not fetch it.</p>'
    )
