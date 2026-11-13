"""Authoritative router input, proposal and catalog contract (no language parser).

Adapters may propose metadata only. The existing resolver remains the single
membership/applicability/context gate; only the core supplies facts.
"""
from __future__ import annotations

import copy
import hashlib
import json

from .contract import (CHAMBERS, CONTRACT_VERSION, DISTRICT_FIELDS, INPUT_MODES,
                       MAX_UTTERANCE, RE_FINDING_ID, SESSIONS, TASKS, TASK_TO_OPERATION,
                       TEMPLATES, validate_request)
from . import admin_labels
from .resolve import APPLICABLE_FIELDS, Outcome, _req, district_choices, resolve_fields

INPUT_VERSION = "haic-router-input/1"
PROPOSAL_VERSION = "haic-router-proposal/1"
PANEL_VERSION = "haic-language-panel/1"
METADATA_FIELDS = ("task", "district", "metric_ids", "comparison_geography", "program_ids", "observation_ids")
PROPOSAL_FIELDS = METADATA_FIELDS[1:]
CLARIFY_FIELDS = ("task", "district", "chamber", "session", "metric", "comparison", "program",
                  "admin_row", "admin_series", "admin_period", "admin_unit", "finding_selection")
CLARIFY_TO_RESOLVER = {
    "task": "task", "district": "district", "chamber": "district.chamber",
    "session": "district.boundary_session", "metric": "metric_ids", "comparison": "comparison_geography",
    "program": "program_ids", "admin_row": "observation_ids", "admin_series": "observation_ids",
    "admin_period": "observation_ids", "admin_unit": "observation_ids", "finding_selection": "selected_finding_ids",
}
# Transport paths are deliberately explicit: the two boundary questions are distinct.
RESOLVER_TO_CLARIFY = {
    "task": "task", "district": "district", "district.chamber": "chamber",
    "district.boundary_session": "session", "metric_ids": "metric",
    "comparison_geography": "comparison", "comparison_geography.boundary_session": "comparison",
    "program_ids": "program", "observation_ids": "admin_row", "selected_finding_ids": "finding_selection",
}
SEMANTIC_REASONS = (
    "missing_information", "ambiguous_referent", "control_conflict", "unresolved_referent",
    "boundary_compatibility", "unavailable_geography", "unavailable_observation", "eligibility",
    "participation_gap", "intersection", "aggregation", "significance", "map", "external_data",
    "undefined_population", "district_admin_count", "unregistered_program", "unsupported_operation",
    "complex_request", "uncertain_interpretation",
)
ACTION_TABLE = {
    "use_guided_controls": {"label": "Use guided controls", "kind": "guided"},
    "choose_supported_task": {"label": "Choose a supported task", "kind": "task_choices"},
}
REASON_TABLE = {r: {"message": text, "action_ids": ["use_guided_controls"]} for r, text in {
    "missing_information": "More information is needed to resolve this request.",
    "ambiguous_referent": "The request has more than one possible reference.",
    "control_conflict": "The request and current controls disagree.",
    "unresolved_referent": "The referenced item is not resolved.",
    "boundary_compatibility": "The requested boundary session requires review.",
    "unavailable_geography": "The requested geography has no normalized observations.",
    "unavailable_observation": "The requested observation is not available.",
    "eligibility": "Individual eligibility or an eligibility count is not supported.",
    "participation_gap": "A district participation gap is not measured.",
    "intersection": "The requested population intersection is not measured.",
    "aggregation": "The requested aggregation is not supported.",
    "significance": "Statistical significance is not established by this fixture.",
    "map": "Map operations are not supported.",
    "external_data": "The requested external data is not in the retained packet.",
    "undefined_population": "The requested population is not defined in this fixture.",
    "district_admin_count": "Administrative counts cannot be assigned to a district.",
    "unregistered_program": "The requested program is not registered in this fixture.",
    "unsupported_operation": "The requested operation is not supported.",
    "complex_request": "This request requires a more specific guided operation.",
    "uncertain_interpretation": "The language route is uncertain; use guided controls.",
}.items()}
QUESTION_TABLE = {
    "task": "Which task?", "district": "Which district?", "chamber": "House or Senate?",
    "session": "Which boundary session?", "metric": "Which measure(s)?",
    "comparison": "Which comparison geography?", "program": "Which program(s)?",
    "admin_row": "Which administrative observation(s)?", "admin_series": "Which administrative series?",
    "admin_period": "Which administrative period?", "admin_unit": "Which administrative unit?",
    "finding_selection": "Select findings before building a brief.",
}
RUNTIME_REASONS = (
    "model_not_installed", "input_encoding_overflow", "input_encoding_invalid_unicode", "provider_invalid",
    "artifact_mismatch", "artifact_incomplete", "calibration_mismatch", "provider_response_invalid", "provider_timeout", "provider_malformed",
    "invalid_tensor_shape", "nonfinite_logits", "calibration_missing", "calibration_invalid",
    "score_tie", "low_confidence", "validation_rejected", "validation_rejected:outreach_program_count",
    "validation_rejected:admin_row_count", "validation_rejected:profile_mode_invalid", "validation_rejected:call_comparator_count",
    "validation_rejected:target_roundtrip_mismatch", "validation_rejected:call_candidate_mode",
    "validation_rejected:compare_full_mode", "validation_rejected:selected_metrics_empty",
)
RUNTIME_REASON_TABLE = {r: {"message": r.replace("_", " "), "action_ids": ["use_guided_controls"]} for r in RUNTIME_REASONS}

CANDIDATE_FIELDS = {"metric_ids": "metric", "comparison_geography": "comparison",
                    "program_ids": "program", "observation_ids": "admin_row"}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def _district_schema(nullable=True):
    props = {"state_fips": {"type": ["string", "null"], "enum": ["15", None]},
             "chamber": {"type": ["string", "null"], "enum": [*CHAMBERS, None]},
             "code": {"type": ["string", "null"], "pattern": "^[0-9]{3}$"},
             "boundary_session": {"type": ["integer", "null"], "enum": [*SESSIONS, None]},
             "geoid": {"type": ["string", "null"], "pattern": "^[0-9]{2,5}$"}}
    return {"type": ["object", "null"] if nullable else "object", "additionalProperties": False, "properties": props}


def _list_schema(ids=None, *, limit=20, pattern=None, nullable=True):
    items = {"type": "string"}
    if ids is not None: items["enum"] = list(ids)
    if pattern: items["pattern"] = pattern
    return {"type": ["array", "null"] if nullable else "array", "maxItems": limit, "items": items}


def metadata_schema(core=None, *, include_task=True):
    props = {
        "district": _district_schema(),
        "metric_ids": _list_schema(sorted(core.metrics) if core else None, pattern="^[a-z0-9_]{1,64}$"),
        "comparison_geography": {**({"enum": [*catalog_metadata(core)["comparison_geographies"], None]} if core else {}), "type": ["string", "null"], "pattern": "^HI-(STATE|COUNTY-[0-9]{3}|HOUSE-[0-9]{3}|SENATE-[0-9]{3})-[0-9]{4}$"},
        "program_ids": _list_schema(sorted(core.programs) if core else None, limit=5, pattern="^[a-z0-9_]{1,40}$"),
        "observation_ids": _list_schema(sorted(core.administrative_rows) if core else None, limit=8, pattern="^[a-z0-9_]{1,64}$"),
    }
    if include_task: props["task"] = {"type": ["string", "null"], "enum": [*TASKS, None]}
    return {"type": "object", "additionalProperties": False, "properties": props}


def request_schema():
    props = metadata_schema()["properties"]
    props.update({
        "request_id": {"type": "string", "pattern": "^[A-Za-z0-9._:-]{1,80}$"},
        "snapshot_id": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
        "input_mode": {"type": "string", "enum": list(INPUT_MODES)},
        "utterance": {"type": ["string", "null"], "maxLength": MAX_UTTERANCE},
        "selected_finding_ids": _list_schema(limit=40, pattern=RE_FINDING_ID.pattern.replace("\\Z", "$")),
        "result_reference": {"type": ["string", "null"], "pattern": "^[A-Za-z0-9._:-]{1,128}$"},
        "displayed_context": {**metadata_schema(), "type": ["object", "null"]},
        "action": {"type": ["object", "null"], "additionalProperties": False, "required": ["kind"],
                   "properties": {"kind": {"enum": ["run", "clarification_response", "next_action"]},
                                  "session_id": {"type": ["string", "null"], "pattern": "^[A-Za-z0-9_-]{1,64}$"}}},
        "edits": {"type": ["object", "null"], "additionalProperties": False, "properties": {
            **{k: {"type": ["string", "null"], "maxLength": n} for k, n in (("title", 90), ("note", 400), ("next_steps", 300))},
            "finding_notes": {"type": ["object", "null"], "propertyNames": {"pattern": RE_FINDING_ID.pattern.replace("\\Z", "$")},
                              "additionalProperties": {"type": "string", "maxLength": 160}}}},
        "clarification_choices": {"type": ["object", "null"], "additionalProperties": False, "properties": {
            "metric_ids": {**_list_schema(limit=20, pattern="^[a-z0-9_]{1,64}$"), "minItems": 1, "uniqueItems": True},
            "comparison_geography": {**_list_schema(limit=20, pattern="^HI-(STATE|COUNTY-[0-9]{3}|HOUSE-[0-9]{3}|SENATE-[0-9]{3})-[0-9]{4}$"), "minItems": 1, "uniqueItems": True}}},
    })
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", "$id": CONTRACT_VERSION,
            "type": "object", "additionalProperties": False,
            "required": ["request_id", "snapshot_id", "input_mode"], "properties": props,
            "allOf": [
                {"if": {"properties": {"input_mode": {"const": "language"}}},
                 "then": {"required": ["utterance"], "properties": {"utterance": {"type": "string", "pattern": "\\S"}}}},
                {"if": {"properties": {"input_mode": {"const": "guided"}}},
                 "then": {"anyOf": [{"required": ["task"], "properties": {"task": {"type": "string"}}},
                                    {"required": ["action"], "properties": {"action": {"type": "object", "required": ["kind"],
                                     "properties": {"kind": {"enum": ["clarification_response", "next_action"]}}}}}]}},
            ],
            "x-normalization": "omitted/null/[] lists are not supplied; first occurrence deduplication after raw length check",
            "x-applicability": {k: list(v) for k, v in APPLICABLE_FIELDS.items()}}


def proposal_schema(core=None):
    fields = metadata_schema(core, include_task=False)
    candidates = {"type": "object", "additionalProperties": False, "properties": {}}
    for key in CANDIDATE_FIELDS:
        value = copy.deepcopy(fields["properties"][key])
        if key == "comparison_geography":
            value["type"] = "string"
            if "enum" in value: value["enum"] = [i for i in value["enum"] if i is not None]
            value = {"type": "array", "maxItems": 20, "items": value}
        else: value["type"] = "array"
        if key == "observation_ids": value["maxItems"] = len(core.administrative_rows) if core else 24
        value.update(minItems=1, uniqueItems=True)
        candidates["properties"][key] = value
    def obj(kind, props, required):
        return {"type": "object", "additionalProperties": False, "required": ["kind", *required],
                "properties": {"kind": {"const": kind}, **props}}
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", "$id": PROPOSAL_VERSION, "oneOf": [
        obj("call", {"task": {"enum": list(TASKS)}, "fields": fields}, ["task", "fields"]),
        obj("clarify", {"task": {"enum": [*TASKS, None]}, "fields": fields, "candidates": candidates,
                        "field": {"enum": list(CLARIFY_FIELDS)}, "reason": {"enum": list(SEMANTIC_REASONS)}},
            ["field", "reason", "fields", "candidates"]),
        obj("unsupported", {"reason": {"enum": list(SEMANTIC_REASONS)}}, ["reason"]),
        obj("escalate", {"reason": {"enum": list(SEMANTIC_REASONS)}}, ["reason"]),
    ], "x-applicability": {k: [f for f in v if f in PROPOSAL_FIELDS] for k, v in APPLICABLE_FIELDS.items()}}



def decision_schema(core=None):
    """Service decisions carry fixed IDs or canonical core arguments, never model prose."""
    fields = metadata_schema(core)["properties"]
    profile = {"type": "string", "pattern": "^HI-(HOUSE|SENATE)-[0-9]{3}-2024$"}
    def selected(key, minimum=1):
        return {**fields[key], "type": "array", "minItems": minimum}
    op_args = {
        "profile": ({"profile_id": profile, "metric_ids": selected("metric_ids")}, ["profile_id"]),
        "compare": ({"profile_id": profile, "metric_ids": selected("metric_ids"),
                     "comparison_geography": {**fields["comparison_geography"], "type": "string"}},
                    ["profile_id", "metric_ids", "comparison_geography"]),
        "program_evidence": ({"profile_id": profile, "program_ids": selected("program_ids")}, ["profile_id", "program_ids"]),
        "outreach_lead": ({"profile_id": profile, "program_id": selected("program_ids")["items"]}, ["profile_id", "program_id"]),
        "administrative_evidence": ({"observation_ids": selected("observation_ids")}, ["observation_ids"]),
        "brief": ({"profile_id": profile, "finding_ids": {**request_schema()["properties"]["selected_finding_ids"], "type": "array", "minItems": 1, "maxItems": 8},
                   "edits": request_schema()["properties"]["edits"]}, ["profile_id", "finding_ids", "edits"]),
    }
    def obj(props, required):
        return {"type": "object", "additionalProperties": False, "properties": props, "required": required}
    calls = [obj({"kind": {"const": "call"}, "operation": {"const": op},
                  "args": obj(props, required)}, ["kind", "operation", "args"]) for op, (props, required) in op_args.items()]
    action_ids = {"type": "array", "uniqueItems": True, "items": {"enum": list(ACTION_TABLE)}}
    others = [obj({"kind": {"const": kind}, "reason": {"enum": list(SEMANTIC_REASONS) + (list(RUNTIME_REASONS) if kind == "escalate" else [])}, "action_ids": action_ids},
                  ["kind", "reason", "action_ids"]) for kind in ("unsupported", "escalate")]
    # Runtime reasons are explicitly separate from learned semantic reasons.
    others.append(obj({"kind": {"const": "error"}, "reason": {"type": ["string", "null"]}, "action_ids": action_ids}, ["kind", "reason"]))
    others.append(obj({"kind": {"const": "clarify"}, "field": {"enum": list(CLARIFY_FIELDS)},
                       "reason": {"enum": list(SEMANTIC_REASONS)}, "candidates": proposal_schema(core)["oneOf"][1]["properties"]["candidates"]},
                      ["kind", "field", "reason", "candidates"]))
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", "$id": "haic-router-decision/1", "oneOf": calls + others}


def router_input_schema(core=None):
    metadata = metadata_schema(core)
    context = {**metadata, "type": ["object", "null"]}
    descriptor = {"type": "object", "additionalProperties": False, "required": ["finding_id"], "properties": {
        "finding_id": {"type": "string", "pattern": RE_FINDING_ID.pattern.replace("\\Z", "$")},
        "kind": {"enum": ["statistic", "comparison", "program_relevance", "outreach_hypothesis", "administrative_context"]},
        "valid": {"type": "boolean"}, "profile_id": {"type": ["string", "null"]},
        "observation_id": {"type": "string"}, "metric_id": {"type": "string"}, "program_id": {"type": "string"},
        "series_id": {"type": "string"}, "unit": {"type": "string"}, "period": {"type": ["object", "string"]},
        "status": {"type": "string"}}}
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", "$id": INPUT_VERSION,
            "type": "object", "additionalProperties": False,
            "required": ["version", "utterance", "controls", "displayed", "confirmed", "server_context", "selected_finding_ids", "selected_findings", "value_free_catalog", "bindings"],
            "properties": {"version": {"const": INPUT_VERSION}, "utterance": {"type": ["string", "null"], "maxLength": MAX_UTTERANCE},
                "controls": metadata, "displayed": context, "confirmed": context,
                "server_context": {"type": ["object", "null"], "additionalProperties": False,
                    "required": ["submitted_controls", "finding_descriptors", "cited_pairs", "provenance"], "properties": {
                    "submitted_controls": context, "finding_descriptors": {"type": "array", "maxItems": 40, "items": descriptor},
                    "cited_pairs": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                        "required": ["source_id", "finding_id"], "properties": {"source_id": {"type": "string"}, "finding_id": {"type": "string"}}}},
                    "provenance": {"enum": ["server_issued_in_this_process", "reviewed_offline_result_record"]}}},
                "selected_finding_ids": request_schema()["properties"]["selected_finding_ids"],
                "selected_findings": {"type": "array", "maxItems": 40, "items": descriptor},
                "value_free_catalog": {"const": catalog_metadata(core)} if core else {"type": "object"}, "bindings": {"type": "object", "additionalProperties": False,
                    "required": ["contract", "proposal", "router_input", "snapshot_id", "catalog_sha256", "panel_sha256"],
                    "properties": {"contract": {"const": CONTRACT_VERSION}, "proposal": {"const": PROPOSAL_VERSION},
                        "router_input": {"const": INPUT_VERSION}, "snapshot_id": {"type": "string"},
                        "catalog_sha256": {"type": "string"}, "panel_sha256": {"type": "string"}}}},
            "x-authority": "displayed and controls are validated client-carried input; confirmed is canonical server-record metadata only"}

def _schema_errors(value, schema, path="proposal"):
    """Strict stdlib validation for the generated schema subset; no coercion."""
    if "oneOf" in schema:
        candidates = [_schema_errors(value, s, path) for s in schema["oneOf"]]
        return [] if sum(not e for e in candidates) == 1 else [{"field": path, "message": "must match exactly one proposal kind"}]
    errors = []
    def error(message): errors.append({"field": path, "message": message})
    typ = schema.get("type")
    if typ:
        types = typ if isinstance(typ, list) else [typ]
        checks = {"null": value is None, "object": isinstance(value, dict), "array": isinstance(value, list),
                  "string": isinstance(value, str), "integer": type(value) is int, "boolean": type(value) is bool}
        if not any(checks.get(t, False) for t in types):
            error("invalid type"); return errors
    if "const" in schema and value != schema["const"]: error("invalid kind")
    if "enum" in schema and value not in schema["enum"]: error("not a known ID")
    if value is None: return errors
    if isinstance(value, dict):
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False and set(value) - set(props): error("unknown fields")
        if set(schema.get("required", [])) - set(value): error("missing required fields")
        for k, v in value.items():
            if k in props: errors += _schema_errors(v, props[k], path + "." + k)
    if isinstance(value, list):
        if not schema.get("minItems", 0) <= len(value) <= schema.get("maxItems", 999): error("list length out of bounds")
        if schema.get("uniqueItems") and len({json.dumps(v, sort_keys=True) for v in value}) != len(value): error("duplicate candidates")
        for i, v in enumerate(value): errors += _schema_errors(v, schema.get("items", {}), f"{path}[{i}]")
    if isinstance(value, str):
        import re
        if schema.get("pattern") and not re.fullmatch(schema["pattern"], value): error("malformed identifier")
        if len(value) > schema.get("maxLength", 999999): error("string length out of bounds")
    return errors


def supplied_fields(fields):
    """Keep meaningful top-level metadata after raw transport validation."""
    return {key: value for key, value in fields.items()
            if value not in (None, [], {}) and
            not (key == "district" and all(v is None for v in value.values()))}


def canonical_proposal(core, proposal):
    """Return (canonical metadata-only proposal, errors); never interpret language."""
    errors = _schema_errors(proposal, proposal_schema(core))
    if errors: return None, errors
    p = copy.deepcopy(proposal)
    task = p.get("task")
    fields = p.get("fields", {})
    # Canonical transport types/list normalization are shared with the HTTP contract.
    if "fields" in p:
        raw = {"request_id": "proposal", "snapshot_id": core.snapshot_id, "input_mode": "guided",
               "task": task or "profile", **fields}
        validated, validation = validate_request(raw, core.snapshot_id)
        if validation: return None, validation
        fields = supplied_fields({k: validated[k] for k in fields})
        p["fields"] = fields
    if task:
        applicable = set(APPLICABLE_FIELDS[task]) & set(PROPOSAL_FIELDS)
        for key in fields:
            if key not in applicable:
                errors.append({"field": "proposal.fields." + key, "message": "not applicable to task"})
    candidates = p.get("candidates", {})
    field = p.get("field")
    field_tasks = {"metric": {"profile", "compare"}, "comparison": {"compare"},
                   "program": {"program_relevance", "outreach"}, "finding_selection": {"brief"},
                   **{f: {"administrative_context"} for f in ("admin_row", "admin_series", "admin_period", "admin_unit")},
                   **{f: set(TASKS) - {"administrative_context"} for f in ("district", "chamber", "session")}}
    if task is not None and field in field_tasks and task not in field_tasks[field]:
        errors.append({"field": "proposal.field", "message": "clarification field not applicable to task"})
    unresolved_key = CLARIFY_TO_RESOLVER.get(field)
    if unresolved_key in PROPOSAL_FIELDS and fields.get(unresolved_key):
        errors.append({"field": "proposal.fields." + unresolved_key, "message": "unresolved field must use candidates, not selected values"})
    for key in candidates:
        if fields.get(key):
            errors.append({"field": "proposal.candidates." + key, "message": "cannot accompany a selected value of the same field"})
    allowed_candidates = {"metric": {"metric_ids"}, "comparison": {"comparison_geography"},
                          "program": {"program_ids"}, "admin_row": {"observation_ids"},
                          "admin_series": {"observation_ids"}, "admin_period": {"observation_ids"},
                          "admin_unit": {"observation_ids"}}
    # Compare may carry both still-unanswered fields, just like guided continuations.
    allowed = {"metric_ids", "comparison_geography"} if task == "compare" and field in ("metric", "comparison") else allowed_candidates.get(field, set())
    if set(candidates) - allowed:
        errors.append({"field": "proposal.candidates", "message": "candidate fields not applicable to clarification"})
    if errors: return None, errors
    return p, []


def _unresolved(task=None, *, source="router_proposal"):
    return {"resolved": False, "task": task, "template": TEMPLATES.get(task), "operation": TASK_TO_OPERATION.get(task),
            "district": None, "district_label": "No district resolved", "geography_id": None, "args": {},
            "input_source": source, "defaults_applied": [], "notes": [], "unresolved": []}


def proposal_base_fields(request, task):
    """Language-proposal defaults; a profile subset must be explicitly proposed."""
    fields = {"task": task}
    shown = request.get("displayed_context") or {}
    applicable = APPLICABLE_FIELDS.get(task, (*PROPOSAL_FIELDS, "selected_finding_ids", "edits"))
    for key in applicable:
        if task == "profile" and key == "metric_ids":
            continue
        if request.get(key): fields[key] = request[key]
        elif shown.get(key): fields[key] = shown[key]
    return fields


def validate_proposal(core, proposal, request, *, input_source="router_proposal"):
    p, errors = canonical_proposal(core, proposal)
    if errors:
        out = Outcome("unsupported", _unresolved(source=input_source), reason="The routing proposal failed shared validation.")
        out.validator_outcome = {"status": "rejected", "errors": errors}
        out.decision = {"kind": "escalate", "reason": "validation_rejected", "action_ids": ["use_guided_controls"]}
        return out
    kind = p["kind"]
    if kind in ("unsupported", "escalate"):
        reason = p["reason"]
        out = Outcome("unsupported", _unresolved(source=input_source), reason=REASON_TABLE[reason]["message"])
        out.decision = {"kind": kind, "reason": reason, "action_ids": REASON_TABLE[reason]["action_ids"]}
        out.next_actions = [{"label": ACTION_TABLE[a]["label"], "request": {"task": "profile"}}
                            for a in REASON_TABLE[reason]["action_ids"]]
    else:
        task = p.get("task") or request.get("task")
        fields = proposal_base_fields(request, task)
        for key in p.get("candidates", {}):
            fields.pop(key, None)
        fields.update(p["fields"])
        # Neither proposal nor displayed context may select findings or supply staff edits.
        fields["selected_finding_ids"] = request.get("selected_finding_ids") or []
        fields["edits"] = request.get("edits") or {}
        if kind == "call":
            out = proposal_conflicts(core, request, fields, p["fields"])
            if out is None: out = resolve_fields(core, fields, input_source=input_source)
            out.decision = decision_from_outcome(out, core=core)
        else:
            field = p["field"]
            candidates = p["candidates"]
            choices = []
            primary = CLARIFY_TO_RESOLVER[field]
            if primary in CANDIDATE_FIELDS:
                fallback = {"metric_ids": list(core.metrics), "comparison_geography": list(core.profiles),
                            "program_ids": list(core.programs), "observation_ids": list(core.administrative_rows)}
                for value in candidates.get(primary, fallback[primary]):
                    label = _candidate_label(core, primary, value)
                    chosen = value if primary == "comparison_geography" else [value]
                    continuation = dict(fields, **{primary: chosen})
                    remaining = {k: v for k, v in candidates.items() if k != primary}
                    if task == "compare" and remaining: continuation["clarification_choices"] = remaining
                    choices.append({"label": label, "request": _req(continuation)})
            if field == "session":
                district = fields.get("district") or {}
                choices = [choice for session in SESSIONS for choice in district_choices(
                    core, fields, chambers=(district["chamber"],) if district.get("chamber") else CHAMBERS,
                    code=district.get("code"), geoid=district.get("geoid") if not district.get("code") else None,
                    session=session)]
            if not choices:
                # Resolver supplies ordinary district/task choices for metadata-only clarifications.
                lookup = dict(fields)
                key = CLARIFY_TO_RESOLVER[field]
                if key.startswith("district."):
                    lookup["district"] = dict(lookup.get("district") or {})
                    lookup["district"].pop(key.split(".")[1], None)
                else: lookup.pop(key, None)
                derived = resolve_fields(core, lookup, input_source=input_source)
                choices = (derived.clarification or {}).get("choices", [])
            res = _unresolved(task, source=input_source)
            res["unresolved"] = [CLARIFY_TO_RESOLVER[field]]
            out = Outcome("clarification", res, clarification={"field": CLARIFY_TO_RESOLVER[field],
                          "semantic_field": field, "reason": p["reason"], "candidates": candidates,
                          "question": QUESTION_TABLE[field], "choices": choices})
            out.decision = {"kind": "clarify", "field": field, "candidates": candidates, "reason": p["reason"]}
    out.validator_outcome = {"status": "accepted"}
    return out


def proposal_conflicts(core, request, fields, named):
    """Preserve the existing A/B changed-control versus client-display rule."""
    from .route_a import _same_district, _district_compatible
    shown = request.get("displayed_context") or {}
    conflicts = []
    candidates = fields.get("clarification_choices") or {}
    for field in ("task",) + APPLICABLE_FIELDS.get(fields.get("task"), ()):
        if field != "task" and field not in named and field not in candidates: continue
        ctrl = request.get(field)
        if not ctrl: continue
        prior = shown.get(field)
        if field == "district":
            changed = not _same_district(ctrl, prior)
            same = _district_compatible(core, fields.get(field) or {}, ctrl)
        else:
            changed = ctrl != prior
            if field in candidates:
                same = ctrl in candidates[field] if field == "comparison_geography" else len(ctrl) == 1 and ctrl[0] in candidates[field]
            else: same = ctrl == fields.get(field)
        if changed and not same: conflicts.append(field)
    if not conflicts: return None
    kept = dict(fields, **{f: request[f] for f in conflicts})
    res = _unresolved(fields.get("task"))
    res["unresolved"] = conflicts
    return Outcome("clarification", res, clarification={"field": ",".join(conflicts), "reason": "control_conflict",
        "candidates": candidates,
        "question": "The typed request and changed controls disagree on " + ", ".join(conflicts) + ". Which should be used?",
        "choices": [{"label": "Use the typed request", "request": _req(fields)},
                    {"label": "Use the current controls", "request": _req(kept)}]})


def _candidate_label(core, field, value):
    if field == "metric_ids": return core.metrics[value]["label"]
    if field == "program_ids": return core.programs[value]["name"]
    if field == "observation_ids": return core.admin_label(value)
    from .resolve import geography_label
    return geography_label(core, value)


def decision_from_outcome(outcome, *, core=None):
    """Preserve explicit decisions; derive only classified, validated producer metadata.

    Nonempty candidate restrictions need the core's accepted-ID catalog. All
    production derivation callers supply it; catalog-free callers fail closed.
    """
    explicit = getattr(outcome, "decision", None)
    if explicit is not None:
        return explicit
    if outcome.resolution.get("decision") is not None:
        return outcome.resolution["decision"]
    if outcome.status == "resolved":
        return {"kind": "call", "operation": outcome.resolution["operation"], "args": outcome.resolution["args"]}
    if outcome.status == "error":
        return {"kind": "error", "reason": outcome.reason}
    decision = None
    if outcome.status == "clarification" and isinstance(outcome.clarification, dict):
        clarification = outcome.clarification or {}
        paths = clarification.get("field")
        paths = paths.split(",") if isinstance(paths, str) else []
        semantic = clarification.get("semantic_field", RESOLVER_TO_CLARIFY.get(paths[0]) if paths else None)
        if paths and all(path in RESOLVER_TO_CLARIFY for path in paths):
            decision = {"kind": "clarify", "field": semantic, "reason": clarification.get("reason"),
                        "candidates": copy.deepcopy(clarification.get("candidates"))}
    elif outcome.status == "unsupported":
        decision = {"kind": "unsupported", "reason": outcome.reason_id, "action_ids": ["use_guided_controls"]}
    catalog_available = core is not None or not (decision or {}).get("candidates")
    if decision is not None and catalog_available and not _schema_errors(decision, decision_schema(core), "decision"):
        return decision
    # Mutate the existing resolution so aliases already held by Service stay coherent.
    outcome.status = "error"
    outcome.resolution["resolved"] = False
    outcome.clarification = None
    outcome.reason = "invalid_derived_decision"
    outcome.decision = {"kind": "error", "reason": "invalid_derived_decision"}
    return outcome.decision


def scoring_record(core, envelope):
    """Revision 1: semantic decisions and resolve-only guided continuation trees.

    Raw-proposal metrics separately honor each arm's existing guard trace (B's
    guard.decision == 'return'; C's guard.preempted). No core operation runs here.
    """
    def normalize(value, key=None, candidate_values=False):
        if isinstance(value, dict):
            return {k: normalize(v, k, key == "candidates") for k, v in value.items()}
        if isinstance(value, list):
            items = [normalize(v) for v in value]
            if key in (*CANDIDATE_FIELDS, "action_ids"):
                # Valid candidate lists are already unique. Preserve invalid
                # duplicates rather than repairing them into an accepted set.
                return sorted(items if candidate_values else set(items))
            return items
        return value

    def node(outcome):
        decision = decision_from_outcome(outcome, core=core)
        clarification = outcome.clarification or {}
        paths = clarification.get("field", "") if outcome.status == "clarification" else ""
        fields = paths.split(",") if paths else []
        children = {}
        if outcome.status == "clarification":
            for choice in clarification.get("choices", []):
                raw = choice.get("request") if isinstance(choice, dict) else None
                if isinstance(raw, dict):
                    raw = dict(raw, request_id="scoring-continuation", snapshot_id=core.snapshot_id,
                               input_mode="guided", action={"kind": "clarification_response"})
                request, errors = validate_request(raw, core.snapshot_id)
                if errors:
                    child = {"status": "error", "decision": {"kind": "error", "reason": "invalid_continuation"},
                             "clarification_fields": [], "continuations": []}
                else:
                    child = node(resolve_fields(core, request, input_source="scoring_continuation"))
                children[json.dumps(child, sort_keys=True, ensure_ascii=False, separators=(",", ":"))] = child
        return {"status": outcome.status, "decision": normalize(decision), "clarification_fields": fields,
                "continuations": [children[key] for key in sorted(children)]}

    resolution = envelope.get("resolution") or {}
    outcome = Outcome("resolved" if envelope["status"] == "ok" else envelope["status"], resolution,
                      clarification=envelope.get("clarification"), reason=envelope.get("reason"))
    if envelope.get("decision") is not None:
        outcome.decision = envelope["decision"]
    result = node(outcome)
    return {"revision": 1, "terminal_status": envelope["status"],
            **{k: result[k] for k in ("decision", "clarification_fields", "continuations")}}


def catalog_metadata(core):
    """The routing catalog contains no published fact values, prose evidence or URLs."""
    cat = core.catalog()
    return {"templates": [{"task": t, "label": TEMPLATES[t], "operation": TASK_TO_OPERATION[t]} for t in TASKS],
            "metrics": [{k: m[k] for k in ("metric_id", "label", "group", "unit", "period", "universe")} for m in core.metrics.values()],
            "programs": [{"program_id": pid, "name": p["name"]} for pid, p in core.programs.items()],
            "districts": [{k: d[k] for k in ("chamber", "code", "boundary_session", "geoid", "has_statistics")} for d in cat["districts"]],
            "normalized_geographies": [{"geography_id": pid, "label": p["label"]} for pid, p in core.profiles.items()],
            "comparison_geographies": sorted({p for p in core.profiles} | {r["geography_id"] for r in cat["unavailable_geographies"]} |
                {core.profile_id_for(d["chamber"], d["code"], d["boundary_session"]) for d in cat["districts"]}),
            "administrative_rows": [{"observation_id": oid, "program_id": r["program_id"],
                **admin_labels.metadata(r),
                **{k: r[k] for k in ("geography", "period", "unit", "status", "source_id")}} for oid, r in core.administrative_rows.items()],
            "source_ids": sorted(core.packet.sources), "boundary_sessions": list(SESSIONS),
            "statistics_boundary_session": 2024, "no_measured_district_participation_gap": True}


def panel_metadata(core=None):
    return {"version": PANEL_VERSION, "district_ids": ["HI-HOUSE-001-2024", "HI-SENATE-001-2024", "HI-HOUSE-009-2024"],
            "boundary_sessions": [2024], "comparison_ids": ["HI-STATE-2024", "HI-COUNTY-009-2024", "HI-HOUSE-001-2024", "HI-SENATE-001-2024", "HI-HOUSE-009-2024"],
            "metric_ids": ["total_population", "population_65_plus", "total_households", "median_household_income",
                           "poverty_rate_all_people", "median_gross_rent", "rent_35_plus_percent_income", "unemployment_rate"],
            "program_ids": ["snap_hi"], "observation_ids": [f"hi_snap_sfy2027_{n:03}" for n in (5, 6, 7)],
            "workflow": ["source", "selection", "edits", "brief", "print"],
            "outside_panel": "evaluation tag only; no runtime refusal"}


def _context(value):
    if value is None: return None
    return {k: copy.deepcopy(value.get(k)) if k not in ("metric_ids", "program_ids", "observation_ids")
            else list(value.get(k) or []) for k in METADATA_FIELDS}


def finding_descriptor(core, finding_id):
    """Metadata for validation, never evidence values or factual prose."""
    if not isinstance(finding_id, str) or not RE_FINDING_ID.fullmatch(finding_id):
        return {"finding_id": finding_id, "valid": False}
    from .core import Unsupported
    try: f = core.finding(finding_id)
    except (Unsupported, ValueError, KeyError): return {"finding_id": finding_id, "valid": False}
    d = {"finding_id": finding_id, "kind": f["kind"], "valid": True,
         "profile_id": core.finding_profile(finding_id)}
    for k in ("observation_id", "series_id", "unit", "period", "status"):
        if k in f: d[k] = copy.deepcopy(f[k])
    return d


def build_router_input(core, request, *, confirmed_context=None):
    catalog = catalog_metadata(core)
    record = confirmed_context if isinstance(confirmed_context, dict) and "canonical" in confirmed_context else None
    canonical = record.get("canonical") if record is not None else confirmed_context
    server_context = None
    if record is not None:
        provenance = record.get("provenance", "server_issued_in_this_process")
        if provenance not in ("server_issued_in_this_process", "reviewed_offline_result_record"):
            raise ValueError("unknown result-context provenance")
        descriptor_keys = {"finding_id", "kind", "profile_id", "observation_id", "metric_id", "program_id", "series_id", "unit", "period", "status"}
        server_context = {
            "submitted_controls": _context(record.get("submitted_controls")),
            "finding_descriptors": [{k: copy.deepcopy(v) for k, v in d.items() if k in descriptor_keys}
                                    for d in record.get("finding_descriptors", [])],
            "cited_pairs": [{k: pair[k] for k in ("source_id", "finding_id")} for pair in record.get("cited_pairs", [])],
            "provenance": provenance,
        }
    return {"version": INPUT_VERSION, "utterance": request.get("utterance"), "controls": _context(request),
            "displayed": _context(request.get("displayed_context")), "confirmed": _context(canonical),
            "server_context": server_context,
            "selected_finding_ids": list(request.get("selected_finding_ids") or []),
            "selected_findings": [finding_descriptor(core, fid) for fid in request.get("selected_finding_ids") or []],
            "value_free_catalog": catalog, "bindings": {"contract": CONTRACT_VERSION, "proposal": PROPOSAL_VERSION,
            "router_input": INPUT_VERSION, "snapshot_id": core.snapshot_id, "catalog_sha256": digest(catalog),
            "panel_sha256": digest(panel_metadata(core))}}


def export_contract(core):
    return {"request_schema": request_schema(), "proposal_schema": proposal_schema(core),
            "router_input_schema": router_input_schema(core), "decision_schema": decision_schema(core),
            "catalog": catalog_metadata(core), "panel": panel_metadata(core),
            "reasons": REASON_TABLE, "runtime_reasons": RUNTIME_REASON_TABLE, "actions": ACTION_TABLE, "questions": QUESTION_TABLE,
            "clarify_to_resolver": CLARIFY_TO_RESOLVER, "task_to_operation": TASK_TO_OPERATION,
            "applicability": {k: list(v) for k, v in APPLICABLE_FIELDS.items()}}
