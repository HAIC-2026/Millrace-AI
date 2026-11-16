"""The five HAIC MCP tools over one verified engine. Transport-free: server.py adds MCP and HTTP.

Every tool call: size check -> one static validation routine -> bounded admission -> engine work under one
lock -> projection. Nothing about a caller is retained between calls.
"""
from __future__ import annotations

import copy
import hashlib
import json
import threading
import uuid
from types import SimpleNamespace

from jsonschema import Draft202012Validator
from jsonschema.exceptions import best_match

MAX_ARGUMENT_BYTES = 65536
MAX_REVISION = 2147483647
DIGEST_VERSION = 'haic-mcp-proposal/1'
EXECUTABLE_INTENTS = ('create_plan', 'replace_plan')


class ToolError(Exception):
    """A typed, sanitized tool failure. Messages never echo caller values or internal exceptions."""

    def __init__(self, code, message, retry_action, **extra):
        super().__init__(code)
        self.code, self.message, self.retry_action, self.extra = code, message, retry_action, extra

    def content(self):
        return {'status': 'tool_error', 'error': {'code': self.code, 'message': self.message,
                                                   'retry_action': self.retry_action, **self.extra}}


def dumps(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8')


def proposal_digest(request, decision, validated, identity) -> str:
    """Unkeyed copy-consistency digest. It is not authentication, consent or proof that a preview was shown."""
    named = {'proposal_digest_version': DIGEST_VERSION, 'request': request, 'decision': decision,
             'validated': validated, 'expected_identity': identity}
    return 'sha256:' + hashlib.sha256(dumps(named)).hexdigest()


def canonical_decision(decision):
    """Boundary rule: a whole-number float map_session (2024.0) becomes the integer (2024) before validation and
    digest, so a copied decision hashes the same either way. Nothing else is rewritten."""
    decision = copy.deepcopy(decision)
    plan = decision.get('plan') if isinstance(decision, dict) else None
    value = plan.get('map_session') if isinstance(plan, dict) else None
    if type(value) is float and value.is_integer():
        plan['map_session'] = int(value)
    return decision


# ----------------------------------------------------------------------------- static schemas
UUID4 = {'type': 'string', 'pattern': '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'}
HASH = {'type': 'string', 'pattern': '^sha256:[0-9a-f]{64}$'}


def closed(properties, required=None):
    return {'type': 'object', 'properties': properties, 'required': list(properties if required is None else required),
            'additionalProperties': False}


def nullable(schema):
    return {'anyOf': [schema, {'type': 'null'}]}


CLAIM_REF = closed({'snapshot_id': HASH, 'finding_id': {'type': 'string', 'minLength': 1, 'maxLength': 500},
                    'semantic_hash': HASH})
ACTION_REF = closed({'action_id': {'type': 'string', 'minLength': 1, 'maxLength': 64}, 'semantic_hash': HASH})
PLAN = {'type': 'object', 'description': 'An engine plan copied exactly from a previous tool result.'}
CONTEXT = closed({
    'case_id': UUID4, 'branch_id': UUID4,
    'revision': {'type': 'integer', 'minimum': 0, 'maximum': MAX_REVISION},
    'snapshot_id': HASH, 'operation_version': {'type': 'string', 'maxLength': 40},
    'recipe_version': {'type': 'string', 'maxLength': 80},
    'confirmed_plan': nullable(PLAN), 'draft_plan': nullable(PLAN),
    'focused_step_id': nullable({'type': 'string', 'maxLength': 8}),
    'selected_claim_refs': {'type': 'array', 'items': CLAIM_REF, 'maxItems': 8}})
REQUEST = closed({'schema_version': {'const': 'ia-language/1'}, 'request_id': UUID4,
                  'utterance': {'type': 'string', 'minLength': 1, 'maxLength': 500}, 'context': CONTEXT})
IDENTITY = {'type': 'object', 'description': 'The identity object returned by prepare_question, copied exactly.'}
DECISION = {'type': 'object', 'description': 'One decision object matching the request-specific decision_schema.'}
UTTERANCE = {'type': 'string', 'minLength': 1, 'maxLength': 500,
             'description': "The user's question, verbatim. Never rewrite it to avoid a clarification or refusal."}
SOURCE_ID = {'type': 'string', 'pattern': '^[A-Za-z0-9_]{1,64}$'}

INPUT_SCHEMAS = {
    'prepare_question': closed({'utterance': UTTERANCE,
                                'context': nullable(CONTEXT),
                                'expected_identity': nullable(IDENTITY)}, required=['utterance']),
    'validate_proposal': closed({'request': REQUEST, 'decision': DECISION, 'expected_identity': IDENTITY}),
    'run_plan': closed({'request': REQUEST, 'decision': DECISION, 'expected_identity': IDENTITY, 'proposal_digest': HASH}),
    'inspect_source': closed({'mode': {'type': 'string', 'enum': ['catalog', 'claim', 'source_intent']},
                              'expected_identity': IDENTITY, 'source_id': SOURCE_ID, 'request': REQUEST,
                              'decision': DECISION, 'proposal_digest': HASH, 'claim_ref': CLAIM_REF},
                             required=['mode', 'expected_identity']),
    'build_brief': closed({'request': REQUEST, 'decision': DECISION, 'expected_identity': IDENTITY, 'proposal_digest': HASH,
                           'selected_claim_refs': {'type': 'array', 'items': CLAIM_REF, 'minItems': 1, 'maxItems': 8},
                           'selected_action_ref': nullable(ACTION_REF)},
                          required=['request', 'decision', 'expected_identity', 'proposal_digest', 'selected_claim_refs']),
}
# inspect_source is one closed object for clients; each mode is a closed variant checked by the same routine.
SOURCE_MODES = {
    'catalog': closed({'mode': {}, 'expected_identity': {}, 'source_id': {}}),
    'claim': closed({k: {} for k in ('mode', 'expected_identity', 'request', 'decision', 'proposal_digest', 'claim_ref', 'source_id')},
                    required=['mode', 'expected_identity', 'request', 'decision', 'proposal_digest', 'claim_ref']),
    'source_intent': closed({k: {} for k in ('mode', 'expected_identity', 'request', 'decision', 'proposal_digest', 'source_id')},
                            required=['mode', 'expected_identity', 'request', 'decision', 'proposal_digest']),
}
VALIDATORS = {name: Draft202012Validator(schema) for name, schema in {**INPUT_SCHEMAS, **{'inspect_source:' + k: v for k, v in SOURCE_MODES.items()}}.items()}


def check(name, value):
    """The one static validation routine. Reports path and failed keyword only, never the rejected value."""
    error = best_match(VALIDATORS[name].iter_errors(value))
    if error is not None:
        path = '.'.join(str(p) for p in error.absolute_path) or 'arguments'
        raise ToolError('invalid_arguments', f'{path} failed schema keyword "{error.validator}".', 'correct_arguments', path=path)


# ----------------------------------------------------------------------------- projections
class Caveats:
    """Each distinct limitation once, with a stable C-number inside one result."""

    def __init__(self):
        self.rows = []

    def ids(self, texts):
        out = []
        for text in texts or []:
            if text not in self.rows:
                self.rows.append(text)
            out.append('C%d' % (self.rows.index(text) + 1))
        return out

    def table(self):
        return [{'id': 'C%d' % (i + 1), 'text': t} for i, t in enumerate(self.rows)]


def _pick(src, keys):
    return {k: copy.deepcopy(src.get(k)) for k in keys}


def _geo(g):
    g = g or {}
    return {'geography_id': g.get('geography_id'), 'label': g.get('label'), 'boundary_session': g.get('boundary_session')}


def project_claim(c, caveats):
    """Compact canonical claim: engine text, claim_ref and every value/MOE/unit/universe/period/caveat it carries.
    Nested operand findings become finding-ID references to their own claims in the same result."""
    out = _pick(c, ('finding_id', 'kind', 'claim_ref', 'text', 'verified'))
    kind = c['kind']
    metric = c.get('metric') or {}
    if kind == 'statistic':
        out.update(_pick(c, ('observation_id', 'estimate', 'estimate_display', 'margin_of_error', 'moe_display',
                              'moe_confidence_level', 'annotation', 'moe_annotation', 'annotation_meaning', 'unit',
                              'universe', 'transformation')))
        out.update(metric_id=metric.get('metric_id'), metric_label=metric.get('label'), geography=_geo(c.get('geography')),
                   period_label=(c.get('period') or {}).get('label'),
                   source={'source_id': c['source']['source_id'], 'locator': copy.deepcopy(c['source']['locator'])})
    elif kind == 'comparison':
        out.update(_pick(c, ('difference', 'not_differenced_reason', 'compatibility', 'unit', 'universe', 'transformation')))
        out.update(metric_id=metric.get('metric_id'), metric_label=metric.get('label'),
                   left_finding_id=c['left']['finding_id'], right_finding_id=c['right']['finding_id'],
                   period_label=(c.get('period') or {}).get('label'))
    elif kind == 'administrative_context':
        out.update(_pick(c, ('observation_id', 'program_id', 'series_id', 'series_label', 'geography', 'period', 'unit',
                              'value', 'status', 'coverage', 'coverage_label', 'revision_status', 'suppression',
                              'missing_reason', 'district_gap_usable')))
        out['source'] = {'source_id': c['source']['source_id'], 'locator': copy.deepcopy(c['source']['locator'])}
    elif kind == 'program_relevance':
        program = c.get('program') or {}
        out.update(_pick(c, ('informational_only', 'eligibility_area', 'access', 'jurisdiction_check', 'scope_questions',
                              'status_notes', 'effective_text')))
        out.update(program_id=program.get('program_id'), program_name=program.get('name'), agency=program.get('agency'),
                   program_jurisdiction=program.get('jurisdiction'), referral=copy.deepcopy(program.get('referral')),
                   missing_facts=copy.deepcopy(program.get('missing_facts')),
                   criteria_summary=program.get('criteria_summary'),
                   relevance_connection=(c.get('relevance') or {}).get('connection'),
                   related_observations=copy.deepcopy((c.get('relevance') or {}).get('related_observations')),
                   geography=_geo(c.get('geography')),
                   evidence=[{k: copy.deepcopy(e.get(k)) for k in ('source_id', 'claim', 'verification_kind', 'locator')}
                             for e in c.get('evidence') or []])
    elif kind == 'outreach_hypothesis':
        program = c.get('program') or {}
        need = []
        for o in c.get('observed_need') or []:
            need.append(o['finding_id'])
            if o.get('state_reference'):
                need.append(o['state_reference']['finding_id'])
        out.update(_pick(c, ('label', 'hypothesis', 'measure_ids', 'unknowns', 'next_step', 'referral')))
        out.update(program_id=program.get('program_id'), program_name=program.get('name'), observed_need_finding_ids=need,
                   program_connection=(c.get('program_connection') or {}).get('text'), geography=_geo(c.get('geography')))
    out['dependency_finding_ids'] = [d['finding_id'] for d in c.get('dependencies') or []]
    out['source_ids'] = list(dict.fromkeys(r['source_id'] for r in c.get('source_inspection_refs') or []))
    out['caveat_ids'] = caveats.ids(c.get('limitations'))
    return out


def project_run(out, caveats):
    steps = [{'step_id': s['step_id'], 'operation': s['operation'], 'status': s['status'],
              'finding_ids': [r['finding_id'] for r in s['claim_refs']], 'reason_code': s['reason_code'],
              'message': s['message'], 'next_actions': [a.get('label') for a in s.get('next_actions') or [] if isinstance(a, dict)]}
             for s in out['steps']]
    responses = [{**_pick(r, ('program_id', 'tier', 'action_ref', 'jurisdiction', 'access', 'eligibility_area',
                              'weakening_facts', 'facts_to_verify', 'template_checklist')),
                  'program_finding_id': (r.get('program_claim_ref') or {}).get('finding_id'),
                  'hypothesis_finding_id': (r.get('hypothesis_claim_ref') or {}).get('finding_id'),
                  'support_finding_ids': [x['finding_id'] for x in r.get('support_claim_refs') or []]}
                 for r in out['responses']]
    return {'run_status': out['status'], 'normalized_plan': copy.deepcopy(out['normalized_plan']), 'steps': steps,
            'claims': [project_claim(c, caveats) for c in out['claims']], 'responses': responses,
            'selection_review': copy.deepcopy(out['selection_review']), 'action_review': copy.deepcopy(out['action_review']),
            'limitation_ids': caveats.ids(out['limitations'])}


def run_text(projected, caveats):
    plan = projected['normalized_plan']
    d = plan['district']
    lines = [f"Run status: {projected['run_status']}. Plan: {d['chamber'].title()} {d['code']}, issue {plan['issue_id']}, "
             f"map {plan['map_session']}, {len(plan['steps'])} step(s)."]
    for s in projected['steps']:
        lines.append(f"Step {s['step_id']} {s['operation']}: {s['status']} ({len(s['finding_ids'])} finding(s))"
                     + (f" — {s['message']}" if s['message'] else ''))
    lines.append('Findings (finding_id — canonical text [caveats]):')
    for c in projected['claims']:
        lines.append(f"- {c['finding_id']} — {c['text']} [{', '.join(c['caveat_ids'])}]")
    for r in projected['responses']:
        lines.append(f"Response {r['program_id']}: {r['tier']}" + (f", action {r['action_ref']['action_id']}" if r['action_ref'] else ''))
    for r in projected['selection_review']:
        lines.append(f"Selection {r['claim_ref']['finding_id']}: {r['state']} ({r['reason_code']})")
    lines.append('Run limitations: ' + ', '.join(projected['limitation_ids']))
    lines += [f"{row['id']}: {row['text']}" for row in caveats.table()]
    return '\n'.join(lines)


def brief_text(brief, render):
    """Deterministic readable brief: displays, numbered citations, action, checklist and every limitation."""
    kinds = {'statistic': 'Statistic', 'comparison': 'Comparison', 'program_relevance': 'Program (informational)',
             'outreach_hypothesis': 'Outreach hypothesis', 'administrative_context': 'Administrative context (not district data)'}
    cite = lambda ns: ''.join(f'[{n}]' for n in sorted(ns))
    issue = render._ISSUE_NAMES.get(brief.get('recipe_version'))
    lines = [brief['title'], f"{brief['geography']['label']}" + (f' · Issue: {issue}' if issue else '')
             + ' · Statistics use 2024 district boundaries'
             + (f"; map shows the {brief['map_session']} boundary" if brief.get('map_session') != 2024 else ''),
             'Selected findings:']
    for i, en in enumerate(brief['entries'], 1):
        lines.append(f"{i}. {kinds.get(en['kind'], en['kind'])}: {en['text']} {cite(en['citations'])}")
    action = brief.get('action')
    if action:
        program = brief.get('action_program') or {}
        lines.append(f"Agency action: {program.get('name', action['program_id'])} · {program.get('agency', '')} · "
                     f"recorded status {action['access']['recorded_status']} ({action['access']['checked_at']}) "
                     f"{cite(brief.get('action_citations', []))}")
        next_step = (program.get('referral') or {}).get('next_step')
        if next_step:
            lines.append('Recorded next step: ' + next_step)
        referral = brief.get('action_referral') or {}
        if referral.get('url') or referral.get('phone'):
            lines.append('Referral: ' + ', '.join(x for x in (referral.get('url'), referral.get('phone')) if x))
        lines.append('Open questions to verify (not verified facts):')
        lines += [f'- {x}' for x in action['facts_to_verify']]
    if brief.get('checklist'):
        lines.append('Office checklist (template items; staff work, not verified facts):')
        lines += [f"- {row['text']} ({'done' if row.get('completed') else 'to do'})" for row in brief['checklist']]
    indicator = render.indicator_context_text(brief)
    if indicator:
        lines.append(indicator + ' ' + cite(brief.get('indicator_citations', [])))
    lines.append('Limitations:')
    lines += [f'- {x}' for x in render.printed_limitations(brief)]  # the engine's canonical printed list
    lines.append('Sources:')
    for c in brief['citations']:
        lines.append(f"[{c['n']}] {c['publisher']} — {c['source_id']}. {c['url']} · retrieved {c.get('retrieved_at_utc')} · "
                     f"recorded sha256 {c.get('sha256')} · " + '; '.join(c['locators']))
    lines.append('Facts come from bundled normalized public projections; original source bytes are not re-read here.')
    return '\n'.join(lines)


# ----------------------------------------------------------------------------- connector
class Connector:
    def __init__(self, engine, *, max_waiting=2, wait_seconds=15.0):
        from districtbrief import render
        from districtbrief.case_contract import InvestigationError
        from districtbrief.core import Unsupported
        self.e = engine
        self.L = engine.language
        self.render = render
        self.InvestigationError = InvestigationError
        self.Unsupported = Unsupported
        self.lock = threading.Lock()  # one scope for ALL engine work, including shared Core caches
        self.admission = threading.BoundedSemaphore(1 + max_waiting)  # no unbounded queue
        self.wait_seconds = wait_seconds
        self.rules_sha256 = 'sha256:' + hashlib.sha256(engine.rules.encode('utf-8')).hexdigest()

    # -- entry point
    def call(self, name, arguments):
        """Return (structured_content, text). Raises ToolError for every typed failure."""
        if name not in INPUT_SCHEMAS:
            raise ToolError('unknown_tool', 'Use one of the five listed HAIC tools.', 'list_tools')
        arguments = {} if arguments is None else arguments
        try:
            size = len(dumps(arguments))
        except (TypeError, ValueError):
            raise ToolError('invalid_arguments', 'Arguments must be finite JSON.', 'correct_arguments') from None
        if size > MAX_ARGUMENT_BYTES:
            raise ToolError('arguments_too_large', f'Tool arguments exceed {MAX_ARGUMENT_BYTES} bytes.', 'reduce_arguments')
        check(name, arguments)
        if name == 'inspect_source':
            check('inspect_source:' + arguments['mode'], arguments)
        if not self.admission.acquire(blocking=False):
            raise ToolError('busy', 'The engine is busy with other requests.', 'retry_in_a_few_seconds')
        try:
            if not self.lock.acquire(timeout=self.wait_seconds):
                raise ToolError('busy', 'The engine is busy with other requests.', 'retry_in_a_few_seconds')
            try:
                if not self.e.still_pinned():
                    raise ToolError('engine_changed', 'The engine release changed after startup.', 'restart_server')
                return getattr(self, name)(arguments)
            finally:
                self.lock.release()
        finally:
            self.admission.release()

    # -- shared steps
    def _identity(self, expected):
        if expected != self.e.identity:
            raise ToolError('identity_mismatch', 'expected_identity does not match this server release and build. '
                            'Start a new question with prepare_question and no context.', 'start_new_question')

    def _prepare(self, request):
        try:
            return self.L.prepare_request(copy.deepcopy(request), self.e.investigation, 'haic-mcp-stateless')
        except self.L.LanguageError as exc:
            retry = {'stale_selection': 'clear_selected_claim_refs_or_start_new_question',
                     'snapshot_unavailable': 'start_new_question', 'version_mismatch': 'start_new_question',
                     }.get(exc.code, 'correct_context_or_start_new_question')
            raise ToolError('context_rejected', 'The engine rejected this request or context; earlier results stay valid.',
                            retry, engine_code=exc.code) from None

    def _validated(self, args):
        """Re-prepare the exact request server-side and convert the full decision, like the website worker."""
        self._identity(args['expected_identity'])
        request = args['request']
        decision = canonical_decision(args['decision'])
        prepared = self._prepare(request)
        cat = prepared['provider_context']['catalog']
        validation = SimpleNamespace(metrics={x['metric_id']: None for x in cat['metrics']},
                                     programs={x['program_id']: None for x in cat['programs']},
                                     administrative_rows={x['observation_id']: None for x in cat['administrative_observations']},
                                     profiles={g: None for g in cat['geographies']},
                                     admitted_recipe_versions=tuple(cat['recipes']))
        refused = None
        try:
            result = self.L.convert_decision(copy.deepcopy(prepared), copy.deepcopy(decision), validation)
        except self.L.LanguageError as exc:
            if getattr(exc, 'stage', None) == 'wire_schema':
                raise ToolError('decision_schema_mismatch', 'The decision does not match decision_schema exactly.',
                                'return_one_complete_decision_matching_decision_schema', engine_code=exc.code) from None
            if exc.status == 503:
                raise ToolError('engine_error', 'Validation failed safely.', 'retry') from None
            refused = exc.code
            result = {'status': 'uncertain', 'intent': 'none', 'message': self.L.MESSAGES['uncertain'],
                      'reason_code': 'uncertain_interpretation', 'normalized_plan': None, 'typed_diff': [],
                      'inherited_fields': [], 'source_inspection_refs': [], 'choices': [], 'clarify_field': ''}
        recovered = result.pop('recovered_from', None)
        category = result.pop('recovery_category', None)
        result['recovery'] = {'code': recovered, 'category': category} if recovered else None
        result['rejection_code'] = refused
        digest = None if refused else proposal_digest(request, decision, result, self.e.identity)
        return request, decision, result, digest

    def _require(self, args, intents):
        request, decision, result, digest = self._validated(args)
        if digest is None or args['proposal_digest'] != digest:
            raise ToolError('proposal_digest_mismatch', 'The request, decision or identity differs from the validated proposal. '
                            'Call validate_proposal again and show the user the new result.', 'revalidate')
        if result['status'] != 'propose' or result['intent'] not in intents:
            raise ToolError('not_applicable', 'This validated proposal does not support this tool.',
                            'use_the_tool_matching_the_validated_intent', intent=result['intent'], validated_status=result['status'])
        return request, decision, result

    def _execute(self, request, plan, mode, selected, action=None):
        ctx = request['context']
        envelope = {'schema_version': 'haic-investigation/1', 'operation_version': 'ia-core/1',
                    'recipe_version': plan['issue_id'] + '/1', 'snapshot_id': self.e.investigation.snapshot_id,
                    'request_id': request['request_id'], 'case_id': ctx['case_id'], 'branch_id': ctx['branch_id'],
                    'revision': ctx['revision'], 'mode': mode, 'plan': copy.deepcopy(plan),
                    'selected_claim_refs': copy.deepcopy(selected), 'selected_action_ref': copy.deepcopy(action)}
        if mode == 'brief':
            # Internal only: no staff edits, checklist edits or tracking are accepted from tool callers.
            envelope.update(staff_edits={}, checklist_edits=[], tracking=None, edits_reviewed_for=None)
        try:
            return self.e.investigation.handle(envelope)
        except self.InvestigationError as exc:
            raise ToolError(exc.code, exc.message, exc.retry_action, issues=exc.issues) from None
        except Exception:
            raise ToolError('engine_error', 'The engine failed safely. Earlier results stay valid.', 'retry') from None

    @staticmethod
    def next_after_run(ctx, plan, out):
        """Context continuation after an execution (see README: next_context rules)."""
        nxt = copy.deepcopy(ctx)
        if out['status'] == 'ok':
            nxt['confirmed_plan'] = copy.deepcopy(plan)
            nxt['draft_plan'] = copy.deepcopy(plan)
            nxt['recipe_version'] = plan['issue_id'] + '/1'
            if nxt['focused_step_id'] not in [s['step_id'] for s in plan['steps']]:
                nxt['focused_step_id'] = None
            nxt['selected_claim_refs'] = [copy.deepcopy(r['claim_ref']) for r in out['selection_review'] if r['state'] == 'retained']
        else:
            # A partial/unsupported/error attempt is never promoted: keep the confirmed plan and its selections.
            nxt['draft_plan'] = copy.deepcopy(plan)
            active = nxt['confirmed_plan'] or plan
            if nxt['focused_step_id'] not in [s['step_id'] for s in active['steps']]:
                nxt['focused_step_id'] = None
        return nxt

    def _sources(self, refs):
        sources, leaves, findings = {}, [], {}
        for ref in refs:
            sid, fid = ref['source_id'], ref.get('finding_id')
            try:
                res = self.e.core.source(sid, fid)
            except self.Unsupported:
                raise ToolError('source_unavailable', 'This source reference is not available in the bundled packet.', 'choose_listed_source') from None
            if sid not in sources:
                sources[sid] = {'source': copy.deepcopy(res['source']), 'retained_file': copy.deepcopy(res['retained_file']),
                                'cited_by_counts': {k: len(v) for k, v in res['cited_by'].items()}, 'not_cited': res['not_cited']}
            detail = copy.deepcopy(res['detail'])
            if isinstance(detail, dict) and 'normalized_reference' in detail:
                findings.setdefault(fid, detail.pop('normalized_reference'))
            leaves.append({'source_id': sid, 'finding_id': fid, 'detail': detail})
        fetch = self.e.core.packet.fetch_policy
        return {'sources': sources, 'leaves': leaves, 'normalized_findings': findings, 'fetch_policy': fetch}

    @staticmethod
    def _filter(refs, source_id):
        if source_id is None:
            return refs
        chosen = [r for r in refs if r['source_id'] == source_id]
        if not chosen:
            raise ToolError('source_not_in_reference', 'source_id is not one of the canonical references for this request.',
                            'omit_source_id_or_choose_a_listed_reference')
        return chosen

    @staticmethod
    def _source_text(bundle):
        lines = []
        for leaf in bundle['leaves']:
            detail = leaf['detail'] or {}
            lines.append(f"- {leaf['source_id']}" + (f" for {leaf['finding_id']}" if leaf['finding_id'] else '')
                         + (f": locator {json.dumps(detail.get('locator'), ensure_ascii=False, sort_keys=True)}" if detail.get('locator') else '')
                         + (f"; verification {detail.get('verification_kind')}, cell verified {detail.get('cell_verified')}" if detail else ''))
        for sid, s in bundle['sources'].items():
            rf = s['retained_file']
            lines.append(f"Source {sid}: {s['source'].get('publisher')} {s['source'].get('url')}; original bytes bundled: "
                         f"{rf.get('available')}; scope {rf.get('verification_scope')}. {rf.get('reason') or ''}".rstrip())
        lines.append('Policy: ' + bundle['fetch_policy'])
        return '\n'.join(lines)

    # -- tools
    def prepare_question(self, args):
        ctx = args.get('context')
        if ctx is None:
            if args.get('expected_identity') is not None:
                self._identity(args['expected_identity'])
            ctx = {'case_id': str(uuid.uuid4()), 'branch_id': str(uuid.uuid4()), 'revision': 0,
                   'snapshot_id': self.e.investigation.snapshot_id, 'operation_version': 'ia-core/1',
                   'recipe_version': 'custom/1', 'confirmed_plan': None, 'draft_plan': None,
                   'focused_step_id': None, 'selected_claim_refs': []}
        else:
            if args.get('expected_identity') is None:
                raise ToolError('identity_required', 'A follow-up with context needs the expected_identity returned with it.', 'copy_expected_identity')
            self._identity(args['expected_identity'])
            if ctx['revision'] >= MAX_REVISION:
                raise ToolError('revision_exhausted', 'This conversation chain reached its last revision.', 'start_new_question')
            ctx = copy.deepcopy(ctx)
            ctx['revision'] += 1
        request = {'schema_version': 'ia-language/1', 'request_id': str(uuid.uuid4()), 'utterance': args['utterance'], 'context': ctx}
        prepared = self._prepare(request)
        structured = {'status': 'prepared', 'identity': copy.deepcopy(self.e.identity), 'request': request,
                      'next_context': copy.deepcopy(ctx), 'provider_context': prepared['provider_context'],
                      'decision_schema': prepared['schema'], 'interpretation_rules': self.e.rules,
                      'interpretation_rules_sha256': self.rules_sha256,
                      'next_step': 'Interpret the question using interpretation_rules and provider_context, then call '
                                   'validate_proposal with request and identity (as expected_identity) copied exactly and one complete decision.'}
        text = (f"Prepared request {request['request_id']} (revision {ctx['revision']}). Interpretation phase only: produce one "
                "decision object matching decision_schema under interpretation_rules, then call validate_proposal with this "
                "request and identity copied exactly. Do not answer facts before running the validated plan.")
        return structured, text

    def validate_proposal(self, args):
        request, decision, result, digest = self._validated(args)
        structured = {**result, 'identity': copy.deepcopy(self.e.identity), 'request': request, 'decision': decision,
                      'proposal_digest': digest, 'next_context': copy.deepcopy(request['context'])}
        lines = [f"Validation: {result['status']} (intent {result['intent']})."]
        if result['normalized_plan']:
            plan = result['normalized_plan']
            lines.append(f"Normalized plan: {plan['district']['chamber'].title()} {plan['district']['code']}, issue {plan['issue_id']}, "
                         f"map {plan['map_session']}; steps: " + '; '.join(f"{s['step_id']} {s['operation']} {json.dumps(s['args'], ensure_ascii=False, sort_keys=True)}" for s in plan['steps']))
            lines.append(f"Changes: {len(result['typed_diff'])}; inherited fields: {', '.join(result['inherited_fields']) or 'none'}.")
            lines.append('Show this plan to the user; run_plan only with request, decision, expected_identity and proposal_digest copied exactly.')
        if result['source_inspection_refs']:
            lines.append('Source references: ' + '; '.join(f"{r['source_id']}" + (f" for {r['finding_id']}" if r.get('finding_id') else '') for r in result['source_inspection_refs'])
                         + '. Next: inspect_source mode source_intent with the same request, decision and proposal_digest.')
        if result['choices']:
            lines.append(f"Clarify {result['clarify_field']}: " + '; '.join(f"{c['alias']} = {c['label']}" for c in result['choices'])
                         + '. Ask the user; do not choose for them.')
        if result['rejection_code']:
            lines.append(f"Refused by deterministic check {result['rejection_code']}. Ask the user to clarify; never rewrite their question to bypass it.")
        return structured, '\n'.join(lines)

    def run_plan(self, args):
        request, decision, result = self._require(args, EXECUTABLE_INTENTS)
        plan = result['normalized_plan']
        out = self._execute(request, plan, 'run', request['context']['selected_claim_refs'])
        caveats = Caveats()
        projected = project_run(out, caveats)
        structured = {'status': 'ok', 'identity': copy.deepcopy(self.e.identity), **projected, 'caveats': caveats.table(),
                      'next_context': self.next_after_run(request['context'], plan, out),
                      'projection': 'Compact canonical projection: engine text, claim_ref, values, MOEs, units, universes, periods, '
                                    'caveats and source IDs per claim; operands and dependencies are finding IDs of claims in this '
                                    'result. Full normalized findings and locators: inspect_source mode claim.'}
        return structured, run_text(projected, caveats)

    def inspect_source(self, args):
        mode = args['mode']
        self._identity(args['expected_identity'])
        if mode == 'catalog':
            bundle = self._sources([{'source_id': args['source_id']}])
            structured = {'status': 'ok', 'mode': mode, 'identity': copy.deepcopy(self.e.identity), **bundle, 'next_context': None}
            return structured, self._source_text(bundle)
        if mode == 'source_intent':
            request, decision, result = self._require(args, ('inspect_source',))
            refs = self._filter(result['source_inspection_refs'], args.get('source_id'))
            bundle = self._sources(refs)
            structured = {'status': 'ok', 'mode': mode, 'identity': copy.deepcopy(self.e.identity), 'references': copy.deepcopy(refs),
                          **bundle, 'next_context': copy.deepcopy(request['context'])}
            return structured, self._source_text(bundle)
        request, decision, result = self._require(args, EXECUTABLE_INTENTS)
        plan = result['normalized_plan']
        out = self._execute(request, plan, 'run', request['context']['selected_claim_refs'])
        claim = next((c for c in out['claims'] if c['claim_ref'] == args['claim_ref']), None)
        if claim is None:
            raise ToolError('claim_not_current', 'claim_ref is not an exact current claim of this validated plan.', 'use_a_claim_ref_from_run_plan')
        refs = self._filter(claim['source_inspection_refs'], args.get('source_id'))
        bundle = self._sources(refs)
        caveats = Caveats()
        structured = {'status': 'ok', 'mode': mode, 'identity': copy.deepcopy(self.e.identity),
                      'claim': project_claim(claim, caveats), 'caveats': caveats.table(), 'references': copy.deepcopy(refs),
                      **bundle, 'next_context': self.next_after_run(request['context'], plan, out)}
        return structured, f"Claim {claim['finding_id']}: {claim['text']}\n" + self._source_text(bundle)

    def build_brief(self, args):
        request, decision, result = self._require(args, EXECUTABLE_INTENTS)
        plan = result['normalized_plan']
        out = self._execute(request, plan, 'brief', args['selected_claim_refs'], args.get('selected_action_ref'))
        brief = {k: v for k, v in out['brief'].items() if k != 'html'}
        structured = {'status': 'ok', 'identity': copy.deepcopy(self.e.identity), 'run_status': out['status'], 'brief': brief,
                      'next_context': self.next_after_run(request['context'], plan, out)}
        return structured, brief_text(brief, self.render)
