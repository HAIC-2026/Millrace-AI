"""Common typed request/result contract shared by every routing adapter.

A request is plain JSON. ``validate_request`` checks types, enumerations and ID
syntax only (no data lookups) and returns a normalized dict or a list of
validation errors. ``envelope`` builds every result, whatever its status.
"""

from __future__ import annotations

import hashlib
import json
import re

CONTRACT_VERSION = "district-brief-contract/2"

TASKS = ("profile", "compare", "program_relevance", "outreach", "administrative_context", "brief")
TASK_TO_OPERATION = {
    "profile": "profile",
    "compare": "compare",
    "program_relevance": "program_evidence",
    "outreach": "outreach_lead",
    "administrative_context": "administrative_evidence",
    "brief": "brief",
}
TEMPLATES = {
    "profile": "Show this district's profile",
    "compare": "Compare this metric with this geography",
    "program_relevance": "Explain this program's relevance",
    "outreach": "Draft an outreach hypothesis",
    "administrative_context": "Inspect recorded administrative evidence",
    "brief": "Build a brief from these findings",
}
INPUT_MODES = ("guided", "language")
STATUSES = ("ok", "clarification", "unsupported", "error")
CHAMBERS = ("house", "senate")
SESSIONS = (2024, 2026)
DEFAULT_SESSION = 2024
ACTION_KINDS = ("run", "clarification_response", "next_action")

MAX_BRIEF_FINDINGS = 8
MAX_UTTERANCE = 500
EDIT_LIMITS = {"title": 90, "note": 400, "next_steps": 300, "finding_note": 160}
MAX_VALIDATION_ERRORS = 32

# Patterns end in \Z (not $, which also matches before a trailing newline) and use
# [0-9] (not \d, which also matches non-ASCII digits): canonical IDs only.
RE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,80}\Z")
RE_SNAPSHOT = re.compile(r"^sha256:[0-9a-f]{64}\Z")
RE_CODE = re.compile(r"^[0-9]{3}\Z")
RE_METRIC = re.compile(r"^[a-z0-9_]{1,64}\Z")
RE_OBSERVATION = re.compile(r"^[a-z0-9_]{1,64}\Z")
RE_RESULT_REFERENCE = re.compile(r"^[A-Za-z0-9._:-]{1,128}\Z")
RE_PROGRAM = re.compile(r"^[a-z0-9_]{1,40}\Z")
RE_GEOGRAPHY_ID = re.compile(r"^HI-(STATE|COUNTY-[0-9]{3}|HOUSE-[0-9]{3}|SENATE-[0-9]{3})-[0-9]{4}\Z")
RE_SESSION_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}\Z")
RE_GEOID = re.compile(r"^[0-9]{2,5}\Z")
_GEO = r"HI-(?:STATE|COUNTY-[0-9]{3}|HOUSE-[0-9]{3}|SENATE-[0-9]{3})-[0-9]{4}"
RE_FINDING_ID = re.compile(
    rf"^(?:stat:{_GEO}:[a-z0-9_]{{1,64}}"
    rf"|cmp:{_GEO}~{_GEO}:[a-z0-9_]{{1,64}}"
    rf"|prog:[a-z0-9_]{{1,40}}@{_GEO}"
    rf"|lead:[a-z0-9_]{{1,40}}@{_GEO}"
    rf"|admin:[a-z0-9_]{{1,64}})\Z"
)

REQUEST_FIELDS = {
    "request_id", "snapshot_id", "input_mode", "task", "utterance", "district",
    "metric_ids", "comparison_geography", "program_ids", "selected_finding_ids",
    "edits", "displayed_context", "action", "clarification_choices", "observation_ids", "result_reference",
}
DISTRICT_FIELDS = {"state_fips", "chamber", "code", "boundary_session", "geoid"}
EDIT_FIELDS = {"title", "note", "next_steps", "finding_notes"}
CONTEXT_FIELDS = {"task", "district", "metric_ids", "comparison_geography", "program_ids", "observation_ids"}


def _err(errors, field, message):
    if len(errors) < MAX_VALIDATION_ERRORS:
        errors.append({"field": field[:128], "message": message[:256]})


def _str_list(value, field, pattern, errors, max_len):
    if value is None:
        return []
    if not isinstance(value, list):
        _err(errors, field, "must be a list of strings")
        return []
    if len(value) > max_len:
        _err(errors, field, f"at most {max_len} items")
        return []
    out = []
    seen = set()
    for i, item in enumerate(value):
        if not isinstance(item, str) or not pattern.match(item):
            _err(errors, f"{field}[{i}]", "malformed identifier")
        elif item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _describe(value) -> str:
    """Short, bounded description of a JSON value for an error message (containers are not repr'd)."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool " + ("true" if value else "false")
    if isinstance(value, (int, float)):
        return f"{type(value).__name__} {value!r}"[:60]
    if isinstance(value, str):
        shown = value if len(value) <= 40 else value[:40] + "..."
        return f"string {shown!r}"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _district(value, field, errors):
    """Validate a district object. Types are checked strictly: 2024.0 is not 2024 and True is not 1."""
    if value is None:
        return None
    if not isinstance(value, dict):
        _err(errors, field, "must be an object")
        return None
    extra = set(value) - DISTRICT_FIELDS
    if extra:
        _err(errors, field, f"unknown fields: {sorted(extra)}")
    d = {}
    sf = value.get("state_fips")
    if sf is not None:
        if not isinstance(sf, str):
            _err(errors, f"{field}.state_fips", f"must be the string '15' (got {_describe(sf)})")
        elif sf != "15":
            _err(errors, f"{field}.state_fips", "only state FIPS '15' (Hawaii) is in this packet")
    d["state_fips"] = sf
    ch = value.get("chamber")
    if ch is not None:
        if not isinstance(ch, str):
            _err(errors, f"{field}.chamber", f"must be the string 'house' or 'senate' (got {_describe(ch)})")
        elif ch not in CHAMBERS:
            _err(errors, f"{field}.chamber", "must be 'house' or 'senate'")
    d["chamber"] = ch
    code = value.get("code")
    if code is not None:
        if not isinstance(code, str) or not RE_CODE.match(code):
            _err(errors, f"{field}.code", "must be a zero-padded 3-digit string such as '001'")
    d["code"] = code
    sess = value.get("boundary_session")
    if sess is not None and (type(sess) is not int or sess not in SESSIONS):
        _err(errors, f"{field}.boundary_session",
             f"must be the integer {SESSIONS[0]} or {SESSIONS[1]} (got {_describe(sess)})")
    d["boundary_session"] = sess
    geoid = value.get("geoid")
    if geoid is not None:
        if not isinstance(geoid, str) or not RE_GEOID.match(geoid):
            _err(errors, f"{field}.geoid", "must be a string of 2 to 5 digits")
    d["geoid"] = geoid
    if (isinstance(code, str) and RE_CODE.match(code)
            and isinstance(geoid, str) and RE_GEOID.match(geoid)
            and geoid != "15" + code):
        _err(errors, f"{field}.geoid", "does not match the supplied district code")
    return d


def _edits(value, errors):
    if value is None:
        return {}
    if not isinstance(value, dict):
        _err(errors, "edits", "must be an object")
        return {}
    extra = set(value) - EDIT_FIELDS
    if extra:
        _err(errors, "edits", f"unknown fields: {sorted(extra)}")
    out = {}
    for key in ("title", "note", "next_steps"):
        v = value.get(key)
        if v is None:
            continue
        if not isinstance(v, str):
            _err(errors, f"edits.{key}", "must be a string")
        elif len(v) > EDIT_LIMITS[key]:
            _err(errors, f"edits.{key}", f"at most {EDIT_LIMITS[key]} characters")
        elif v.strip():
            out[key] = v.strip()
    notes = value.get("finding_notes")
    if notes is not None:
        if not isinstance(notes, dict):
            _err(errors, "edits.finding_notes", "must be an object keyed by finding ID")
        else:
            fn = {}
            for fid, text in notes.items():
                if not RE_FINDING_ID.match(str(fid)):
                    _err(errors, "edits.finding_notes", f"malformed finding ID {fid!r}")
                elif not isinstance(text, str) or len(text) > EDIT_LIMITS["finding_note"]:
                    _err(errors, f"edits.finding_notes[{fid}]",
                         f"must be a string of at most {EDIT_LIMITS['finding_note']} characters")
                elif text.strip():
                    fn[fid] = text.strip()
            if fn:
                out["finding_notes"] = fn
    return out


CHOICE_PATTERNS = {"metric_ids": RE_METRIC, "comparison_geography": RE_GEOGRAPHY_ID}


def _clarification_choices(value, errors):
    """Optional compare-only candidate map carried by a guided continuation.

    It holds the still-unanswered alternatives of an ambiguous typed field (for example the three
    rent measures, or House/Senate 009) so that answering one question keeps the other pending.
    It is resolution transport only: candidates never become operation arguments.
    """
    if value is None:
        return None
    if not isinstance(value, dict):
        _err(errors, "clarification_choices", "must be an object")
        return None
    extra = set(value) - set(CHOICE_PATTERNS)
    if extra:
        _err(errors, "clarification_choices", f"unknown fields: {sorted(map(str, extra))}")
    out = {}
    for key, pattern in CHOICE_PATTERNS.items():
        items = value.get(key)
        if items is None:
            continue
        if not isinstance(items, list) or not 1 <= len(items) <= 20:
            _err(errors, f"clarification_choices.{key}", "must be a list of 1 to 20 candidate IDs")
            continue
        if not all(isinstance(i, str) and pattern.match(i) for i in items) or len(set(items)) != len(items):
            _err(errors, f"clarification_choices.{key}", "candidates must be distinct well-formed IDs")
            continue
        out[key] = list(items)
    return out or None


def validate_request(raw, snapshot_id: str):
    """Return (request, errors). ``request`` is None when errors is non-empty."""
    errors: list = []
    if not isinstance(raw, dict):
        return None, [{"field": "(body)", "message": "request must be a JSON object"}]
    extra = set(raw) - REQUEST_FIELDS
    if extra:
        _err(errors, "(body)", f"unknown fields: {sorted(extra)}")
    rid = raw.get("request_id")
    if not isinstance(rid, str) or not RE_REQUEST_ID.match(rid):
        _err(errors, "request_id", "required; 1-80 characters of letters, digits, . _ : -")
    sid = raw.get("snapshot_id")
    if not isinstance(sid, str) or not RE_SNAPSHOT.match(sid):
        _err(errors, "snapshot_id", "required; 'sha256:' plus 64 hex characters")
    elif sid != snapshot_id:
        _err(errors, "snapshot_id", "does not match the loaded, accepted snapshot; this is a different packet")
    mode = raw.get("input_mode")
    if mode not in INPUT_MODES:
        _err(errors, "input_mode", "required; 'guided' or 'language'")
    task = raw.get("task")
    if task is not None and task not in TASKS:
        _err(errors, "task", f"must be one of {list(TASKS)} or null")
    utterance = raw.get("utterance")
    if utterance is not None and not isinstance(utterance, str):
        _err(errors, "utterance", "must be a string")
        utterance = None
    if utterance is not None and len(utterance) > MAX_UTTERANCE:
        _err(errors, "utterance", f"at most {MAX_UTTERANCE} characters")
    action = raw.get("action")
    continuation = isinstance(action, dict) and action.get("kind") in ("clarification_response", "next_action")
    if mode == "guided" and task is None and not continuation:
        _err(errors, "task", "required for guided input")
    if mode == "language" and not (utterance or "").strip():
        _err(errors, "utterance", "required for language input")
    district = _district(raw.get("district"), "district", errors)
    metric_ids = _str_list(raw.get("metric_ids"), "metric_ids", RE_METRIC, errors, 20)
    program_ids = _str_list(raw.get("program_ids"), "program_ids", RE_PROGRAM, errors, 5)
    observation_ids = _str_list(raw.get("observation_ids"), "observation_ids", RE_OBSERVATION, errors, 8)
    reference = raw.get("result_reference")
    if reference is not None and (not isinstance(reference, str) or not RE_RESULT_REFERENCE.match(reference)):
        _err(errors, "result_reference", "must be an opaque identifier of 1 to 128 ASCII characters")
    finding_ids = _str_list(raw.get("selected_finding_ids"), "selected_finding_ids", RE_FINDING_ID, errors, 40)
    cg = raw.get("comparison_geography")
    if cg is not None and (not isinstance(cg, str) or not RE_GEOGRAPHY_ID.match(cg)):
        _err(errors, "comparison_geography", "malformed geography ID (e.g. 'HI-STATE-2024')")
    edits = _edits(raw.get("edits"), errors)
    ctx = raw.get("displayed_context")
    context = None
    if ctx is not None:
        if not isinstance(ctx, dict):
            _err(errors, "displayed_context", "must be an object")
        else:
            extra = set(ctx) - CONTEXT_FIELDS
            if extra:
                _err(errors, "displayed_context", f"unknown fields: {sorted(extra)}")
            ct = ctx.get("task")
            if ct is not None and ct not in TASKS:
                _err(errors, "displayed_context.task", "unknown task")
            ccg = ctx.get("comparison_geography")
            if ccg is not None and (not isinstance(ccg, str) or not RE_GEOGRAPHY_ID.match(ccg)):
                _err(errors, "displayed_context.comparison_geography", "malformed geography ID")
            context = {
                "task": ct,
                "district": _district(ctx.get("district"), "displayed_context.district", errors),
                "metric_ids": _str_list(ctx.get("metric_ids"), "displayed_context.metric_ids", RE_METRIC, errors, 20),
                "comparison_geography": ccg,
                "program_ids": _str_list(ctx.get("program_ids"), "displayed_context.program_ids", RE_PROGRAM, errors, 5),
                "observation_ids": _str_list(ctx.get("observation_ids"), "displayed_context.observation_ids", RE_OBSERVATION, errors, 8),
            }
    act = None
    if action is not None:
        if not isinstance(action, dict) or action.get("kind") not in ACTION_KINDS:
            _err(errors, "action", f"must be an object with kind in {list(ACTION_KINDS)}")
        else:
            if set(action) - {"kind", "session_id"}:
                _err(errors, "action", "unknown fields")
            sess = action.get("session_id")
            if sess is not None and (not isinstance(sess, str) or not RE_SESSION_ID.match(sess)):
                _err(errors, "action.session_id", "malformed")
            act = {"kind": action["kind"], "session_id": sess}
    choices_map = _clarification_choices(raw.get("clarification_choices"), errors)
    if choices_map:
        if mode != "guided" or not (task == "compare" or (task is None and continuation)):
            _err(errors, "clarification_choices", "allowed only on a guided compare or taskless continuation")
        if "metric_ids" in choices_map and metric_ids:
            _err(errors, "clarification_choices.metric_ids", "cannot accompany a chosen metric_ids value")
        if "comparison_geography" in choices_map and cg is not None:
            _err(errors, "clarification_choices.comparison_geography",
                 "cannot accompany a chosen comparison_geography value")
    if errors:
        return None, errors
    return {
        "request_id": rid,
        "snapshot_id": sid,
        "input_mode": mode,
        "task": task,
        "utterance": utterance.strip() if utterance else None,
        "district": district,
        "metric_ids": metric_ids,
        "comparison_geography": cg,
        "program_ids": program_ids,
        "observation_ids": observation_ids,
        "result_reference": reference,
        "selected_finding_ids": finding_ids,
        "edits": edits,
        "clarification_choices": choices_map,
        "displayed_context": context,
        "action": act,
    }, []


def district_label(d: dict | None) -> str:
    if not d or not d.get("chamber") or not d.get("code"):
        return "No district resolved"
    session = d.get("boundary_session") or DEFAULT_SESSION
    return f"{d['chamber'].capitalize()} District {d['code']} (boundary session {session})"


def context_id(resolution: dict) -> str:
    """Stable ID for a resolved context (task, district and arguments)."""
    keyed = {k: resolution.get(k) for k in ("task", "district", "args")}
    blob = json.dumps(keyed, sort_keys=True, separators=(",", ":"))
    return "ctx:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def envelope(status: str, request: dict | None, snapshot_id: str, *, resolution=None,
             findings=None, limitations=None, next_actions=None, clarification=None,
             reason=None, retry=None, validation_errors=None, data=None, request_id=None):
    assert status in STATUSES
    res = {
        "contract_version": CONTRACT_VERSION,
        "status": status,
        "request_id": (request or {}).get("request_id") or request_id,
        "snapshot_id": snapshot_id,
        "input_mode": (request or {}).get("input_mode"),
        "context_id": context_id(resolution) if resolution and resolution.get("resolved") else None,
        "resolution": resolution,
        "findings": findings or [],
        "limitations": limitations or [],
        "next_actions": next_actions or [],
        "model_calls": 0,
    }
    if clarification is not None:
        res["clarification"] = clarification
    if reason is not None:
        res["reason"] = reason
    if retry is not None:
        res["retry"] = retry
    if validation_errors:
        res["validation_errors"] = validation_errors
    if data is not None:
        res["data"] = data
    return res
