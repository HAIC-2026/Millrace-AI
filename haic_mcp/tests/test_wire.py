"""Real loopback MCP over Streamable HTTP with the official SDK client: no in-process stand-ins for the wire."""
from __future__ import annotations

import copy
import json
import os
import unittest
from contextlib import asynccontextmanager
from pathlib import Path

import anyio
import httpx2
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

from haic_mcp.server import INSTRUCTIONS, MAX_HTTP_BODY, MAX_RESULT_BYTES
from haic_mcp.tests.support import (EIGHT_STEPS, MAXIMAL_Q, MAXIMAL_STEPS, RECIPE_LABEL, Flow, ServerProcess, connector, engine, local_call,
                                    recipe_steps, size, step, synthetic_decision)
from haic_mcp.tools import MAX_ARGUMENT_BYTES

TOOLS = ['prepare_question', 'validate_proposal', 'run_plan', 'inspect_source', 'build_brief']
EIGHT_Q = ('House 28 full profile, then compare senior poverty, all-people poverty, median household income and senior population '
           'against the State, against Honolulu County and against Senate 25, plus program evidence for SNAP, Med-QUEST, Section 8, '
           'Kupuna Care and WIC, Kupuna Care and SNAP outreach leads, and administrative evidence.')
MEASURED = {}
TRANSCRIPT = []


class WireError(Exception):
    def __init__(self, result):
        super().__init__(result.structured_content)
        self.result = result
        self.code = (result.structured_content or {}).get('error', {}).get('code')


@asynccontextmanager
async def mcp_client(url, record=None):
    async def on_response(response):
        if record is None:
            return
        try:
            body = json.loads(response.request.content)
        except ValueError:
            return
        if body.get('method') == 'tools/call':
            record.append({'tool': body['params']['name'], 'request_bytes': len(response.request.content),
                           'response_bytes': int(response.headers.get('content-length', -1)), 'http_status': response.status_code})
    async with httpx2.AsyncClient(timeout=httpx2.Timeout(60), event_hooks={'response': [on_response]}) as http:
        async with streamable_http_client(url, http_client=http) as (read, write):
            async with ClientSession(read, write) as session:
                init = await session.initialize()

                async def call(name, args):
                    result = await session.call_tool(name, args)  # the SDK validates structuredContent against outputSchema
                    if result.is_error:
                        raise WireError(result)
                    return result
                yield session, init, call


def structured(call):
    async def inner(name, args):
        return (await call(name, args)).structured_content
    return inner


class AsyncFlow(Flow):
    async def prepare(self, utterance, context=None, identity=None):
        args = {'utterance': utterance}
        if context is not None:
            args.update(context=context, expected_identity=identity)
        return await self.call('prepare_question', args)

    async def validate(self, prepared, decision):
        return await self.call('validate_proposal', {'request': prepared['request'], 'decision': decision, 'expected_identity': prepared['identity']})

    async def run(self, validated):
        return await self.call('run_plan', Flow.bundle(validated))

    async def ask_and_run(self, utterance, decision, context=None, identity=None):
        p = await self.prepare(utterance, context, identity)
        v = await self.validate(p, decision)
        assert v['status'] == 'propose', v
        return p, v, await self.run(v)


def eight_step_decision():
    return synthetic_decision(chamber='house', code='028', issue='custom', steps=EIGHT_STEPS + [
        step('s8', 'administrative_evidence', observations=sorted(engine().core.administrative_rows)[:8])])


class WireTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ServerProcess()
        cls.local = Flow(local_call(connector()))

    @classmethod
    def tearDownClass(cls):
        log = cls.server.stop()
        cls.server_log = log
        evidence = os.environ.get('HAIC_MCP_EVIDENCE_DIR')
        if evidence:
            Path(evidence).mkdir(parents=True, exist_ok=True)
            (Path(evidence) / 'wire-measurements.json').write_text(json.dumps(MEASURED, indent=1, ensure_ascii=False), encoding='utf-8')
            (Path(evidence) / 'wire-transcript.json').write_text(json.dumps(TRANSCRIPT, indent=1, ensure_ascii=False), encoding='utf-8')
        assert cls.server.proc.poll() is not None

    def wire(self, fn):
        async def bounded():
            with anyio.fail_after(180):  # a hung wire call fails the test instead of blocking the suite
                return await fn()
        return anyio.run(bounded)

    def test_initialize_and_list_tools(self):
        async def go():
            async with mcp_client(self.server.url) as (session, init, call):
                tools = (await session.list_tools()).tools
                return init, tools
        init, tools = self.wire(go)
        self.assertEqual((init.server_info.name, init.server_info.version), ('haic-mcp', engine().identity['connector']['version']))
        self.assertEqual(init.instructions, INSTRUCTIONS)
        head = INSTRUCTIONS[:512]
        for phrase in ('read-only', 'prepare_question -> validate_proposal', 'exactly', 'Never rewrite it'):
            self.assertIn(phrase, head)
        self.assertEqual([t.name for t in tools], TOOLS)
        for t in tools:
            a = t.annotations
            self.assertEqual((a.read_only_hint, a.destructive_hint, a.open_world_hint, a.idempotent_hint),
                             (True, False, False, t.name != 'prepare_question'), t.name)
            self.assertIs(t.input_schema['additionalProperties'], False)
            self.assertIn('anyOf', t.output_schema)
        TRANSCRIPT.append({'step': 'initialize+tools/list', 'protocol_version': init.protocol_version, 'tools': [t.name for t in tools]})

    def test_all_tools_flow_source_and_brief_demo(self):
        record = []

        async def go():
            async with mcp_client(self.server.url, record) as (session, init, raw):
                call = structured(raw)
                flow = AsyncFlow(call)
                u = f'Run the {RECIPE_LABEL["aging_at_home"]} recipe for House 28.'
                d = synthetic_decision(chamber='house', code='028', issue='aging_at_home', steps=recipe_steps('aging_at_home'))
                p, v, r = await flow.ask_and_run(u, d)
                out = {'p': p, 'v': v, 'r': r, 'sources': {}}
                for kind in ('comparison', 'outreach_hypothesis'):
                    claim = next(c for c in r['claims'] if c['kind'] == kind)
                    ctx = dict(r['next_context'], selected_claim_refs=[claim['claim_ref']])
                    f = await flow.prepare('Why that figure?', ctx, p['identity'])
                    sv = await flow.validate(f, synthetic_decision(intent='inspect_source', focus='selected_1'))
                    si = await raw('inspect_source', dict(Flow.bundle(sv), mode='source_intent'))
                    cm = await raw('inspect_source', dict(Flow.bundle(v), mode='claim', claim_ref=claim['claim_ref']))
                    out['sources'][kind] = (f, sv, si, cm)
                out['catalog'] = await raw('inspect_source', {'mode': 'catalog', 'expected_identity': p['identity'], 'source_id': 'hi_eoa_referral'})
                picks = [c['claim_ref'] for c in r['claims'] if c['kind'] in ('comparison', 'outreach_hypothesis')]
                out['brief'] = await raw('build_brief', dict(Flow.bundle(v), selected_claim_refs=picks, selected_action_ref=r['responses'][0]['action_ref']))
                return out
        out = self.wire(go)
        p, v, r = out['p'], out['v'], out['r']
        self.assertEqual(r['run_status'], 'ok')
        # Wire results equal the in-process results for the same deterministic inputs.
        self.assertEqual(self.local.call('validate_proposal', {'request': p['request'], 'decision': v['decision'], 'expected_identity': p['identity']}), v)
        self.assertEqual(self.local.call('run_plan', Flow.bundle(v)), r)
        for kind, (f, sv, si, cm) in out['sources'].items():
            self.assertEqual((sv['status'], sv['intent']), ('propose', 'inspect_source'))
            refs = sv['source_inspection_refs']
            self.assertEqual(si.structured_content['references'], refs)
            self.assertEqual(cm.structured_content['references'], refs)
            self.assertTrue(all(not x['finding_id'].startswith(('cmp:', 'lead:')) for x in refs))
            self.assertIn('normalized_projection', si.content[0].text)
            TRANSCRIPT.append({'step': f'source wire scenario ({kind})', 'selected': f['provider_context']['selected']['selected_1']['kind'],
                               'validated': [sv['status'], sv['intent']], 'leaf_refs': refs, 'text': si.content[0].text})
        self.assertIsNone(out['catalog'].structured_content['next_context'])
        brief = out['brief']
        self.assertTrue(brief.structured_content['brief']['citations'])
        self.assertIn('[1]', brief.content[0].text)
        TRANSCRIPT.append({'step': 'build_brief', 'text': brief.content[0].text})
        self.assertEqual({x['tool'] for x in record}, set(TOOLS))
        self.assertTrue(all(x['http_status'] == 200 for x in record))

    def test_tool_errors_are_typed_and_sanitized(self):
        async def go():
            async with mcp_client(self.server.url) as (session, init, raw):
                results = {}
                for name, args in (('prepare_question', {'utterance': ''}), ('prepare_question', {'utterance': 'x', 'evil': 1}),
                                   ('no_such_tool', {}), ('run_plan', {'request': {}, 'decision': {}, 'expected_identity': {}, 'proposal_digest': 'x'})):
                    results[(name, json.dumps(args))] = await session.call_tool(name, args)
                p = await structured(raw)('prepare_question', {'utterance': 'Compare senior poverty in House 4 with the State.'})
                d = synthetic_decision(chamber='house', code='004', issue='custom', steps=[step('s1', 'compare', ['poverty_rate_65_plus'], 'HI-STATE-2024')])
                v = await structured(raw)('validate_proposal', {'request': p['request'], 'decision': d, 'expected_identity': p['identity']})
                changed = copy.deepcopy(Flow.bundle(v))
                changed['request']['utterance'] = 'Compare senior poverty in House 5 with the State.'
                results['digest'] = await session.call_tool('run_plan', changed)
                return results
        results = self.wire(go)
        codes = {k: (r.is_error, r.structured_content['error']['code']) for k, r in results.items()}
        self.assertEqual(sorted(set(codes.values())), [(True, 'invalid_arguments'), (True, 'proposal_digest_mismatch'), (True, 'unknown_tool')])
        for r in results.values():
            text = r.content[0].text
            self.assertNotIn('Traceback', text)
            self.assertNotIn('House 5', json.dumps(r.structured_content))

    def test_payload_measurements_and_limits(self):
        record = []

        async def go():
            async with mcp_client(self.server.url, record) as (session, init, raw):
                call = structured(raw)
                flow = AsyncFlow(call)
                p = await flow.prepare(EIGHT_Q)
                v = await flow.validate(p, eight_step_decision())
                r = await flow.run(v)
                # Largest legitimate context: a confirmed eight-step plan, a different draft and eight selections.
                draft = copy.deepcopy(r['next_context']['confirmed_plan'])
                draft['steps'][0]['args'] = {'metric_ids': ['poverty_rate_65_plus']}
                picks = [c['claim_ref'] for c in r['claims'] if c['kind'] in ('outreach_hypothesis', 'comparison', 'program_relevance')][:8]
                ctx = dict(r['next_context'], draft_plan=draft, selected_claim_refs=picks, focused_step_id='s2')
                big = await flow.prepare('Use the confirmed plan and compare senior poverty against the State.', ctx, p['identity'])
                biggest_source = None
                for c in r['claims']:
                    if c['kind'] in ('outreach_hypothesis', 'program_relevance'):
                        res = await raw('inspect_source', dict(Flow.bundle(v), mode='claim', claim_ref=c['claim_ref']))
                        n = len(res.model_dump_json(by_alias=True, exclude_none=True))
                        if biggest_source is None or n > biggest_source[0]:
                            biggest_source = (n, c['finding_id'])
                aging = await flow.ask_and_run(f'Run the {RECIPE_LABEL["aging_at_home"]} recipe for Senate 16.',
                                               synthetic_decision(chamber='senate', code='016', issue='aging_at_home', steps=recipe_steps('aging_at_home')))
                sel = [c['claim_ref'] for c in aging[2]['claims'] if 'HI-SENATE-016-2024' in c['finding_id']]  # primary-district claims only
                brief = None
                for n in range(len(sel), 0, -1):  # the largest selection that fits one printed page
                    try:
                        brief = await raw('build_brief', dict(Flow.bundle(aging[1]), selected_claim_refs=sel[:min(n, 8)],
                                                              selected_action_ref=aging[2]['responses'][0]['action_ref']))
                        break
                    except WireError as exc:
                        assert exc.code == 'brief_overflow', exc.code
                # A >64 KiB argument within the 128 KiB HTTP body is a typed tool error.
                padded = {'utterance': 'Compare.', 'expected_identity': {'pad': 'y' * (MAX_ARGUMENT_BYTES + 10)}}
                too_big = await session.call_tool('prepare_question', padded)
                return {'prepare_first': p, 'prepare_full_context': big, 'run8': r, 'biggest_source': biggest_source, 'brief': brief,
                        'too_big': too_big, 'ctx': ctx}
        out = self.wire(go)
        self.assertEqual(out['run8']['run_status'], 'ok')
        self.assertEqual(len(out['run8']['steps']), 8)
        self.assertEqual(out['too_big'].structured_content['error']['code'], 'arguments_too_large')
        by_tool = {}
        for row in record:
            by_tool.setdefault(row['tool'], []).append(row)
        largest = {tool: max(rows, key=lambda x: x['response_bytes']) for tool, rows in by_tool.items()}
        for tool, row in largest.items():
            self.assertLess(row['response_bytes'], MAX_RESULT_BYTES, tool)
            self.assertLess(row['request_bytes'], MAX_HTTP_BODY, tool)
        legit_requests = [x['request_bytes'] for x in record if x['http_status'] == 200 and x['tool'] != 'prepare_question' or x['request_bytes'] < MAX_ARGUMENT_BYTES]
        MEASURED.update({
            'caps': {'http_body_bytes': MAX_HTTP_BODY, 'tool_arguments_bytes': MAX_ARGUMENT_BYTES, 'complete_result_bytes': MAX_RESULT_BYTES},
            'largest_http_response_bytes_by_tool': {t: r['response_bytes'] for t, r in largest.items()},
            'largest_http_request_bytes_by_tool': {t: max(x['request_bytes'] for x in rows if x['request_bytes'] < MAX_ARGUMENT_BYTES) for t, rows in by_tool.items()},
            'prepare_first_structured_bytes': size(out['prepare_first']),
            'prepare_full_context_structured_bytes': size(out['prepare_full_context']),
            'full_context_object_bytes': size(out['ctx']),
            'run_eight_step_structured_bytes': size(out['run8']),
            'run_eight_step_raw_engine_bytes': size(engine().investigation.handle({
                'schema_version': 'haic-investigation/1', 'operation_version': 'ia-core/1', 'recipe_version': 'custom/1',
                'snapshot_id': engine().investigation.snapshot_id, 'request_id': out['prepare_first']['request']['request_id'],
                **{k: out['prepare_first']['request']['context'][k] for k in ('case_id', 'branch_id', 'revision')}, 'mode': 'run',
                'plan': out['run8']['normalized_plan'], 'selected_claim_refs': [], 'selected_action_ref': None})),
            'largest_claim_source_lookup': {'finding_id': out['biggest_source'][1], 'result_json_bytes': out['biggest_source'][0]},
            'brief_entries': len(out['brief'].structured_content['brief']['entries']),
            'brief_result_json_bytes': len(out['brief'].model_dump_json(by_alias=True, exclude_none=True)),
            'calls_measured': len(record),
        })
        self.assertTrue(legit_requests)

    def test_maximal_eight_step_run_with_eight_selections_is_complete(self):
        record = []

        async def go():
            async with mcp_client(self.server.url, record) as (session, init, raw):
                flow = AsyncFlow(structured(raw))
                d = synthetic_decision(chamber='house', code='028', issue='custom', steps=MAXIMAL_STEPS)
                p, v, first = await flow.ask_and_run(MAXIMAL_Q, d)
                picks = [c['claim_ref'] for c in first['claims'] if 'HI-HOUSE-028-2024' in c['finding_id']][:8]
                ctx = dict(first['next_context'], selected_claim_refs=picks)
                f = await flow.prepare(MAXIMAL_Q, ctx, p['identity'])
                v2 = await flow.validate(f, dict(d, intent='replace_plan'))
                return v2, await flow.run(v2), picks
        v2, run, picks = self.wire(go)
        self.assertEqual(v2['status'], 'propose')
        oracle = engine().investigation.handle({'schema_version': 'haic-investigation/1', 'operation_version': 'ia-core/1', 'recipe_version': 'custom/1',
                                                'snapshot_id': engine().investigation.snapshot_id, 'request_id': v2['request']['request_id'],
                                                **{k: v2['request']['context'][k] for k in ('case_id', 'branch_id', 'revision')}, 'mode': 'run',
                                                'plan': v2['normalized_plan'], 'selected_claim_refs': picks, 'selected_action_ref': None})
        self.assertEqual((run['run_status'], oracle['status']), ('ok', 'ok'))
        self.assertEqual(len(run['claims']), 80)
        self.assertEqual([c['claim_ref'] for c in run['claims']], [c['claim_ref'] for c in oracle['claims']])
        self.assertEqual([c['text'] for c in run['claims']], [c['text'] for c in oracle['claims']])
        self.assertEqual([x['state'] for x in run['selection_review']], ['retained'] * 8)
        self.assertEqual(run['next_context']['selected_claim_refs'], picks)
        runs = [x for x in record if x['tool'] == 'run_plan']
        largest = max(x['response_bytes'] for x in runs)
        self.assertLess(largest, MAX_RESULT_BYTES)
        self.assertGreater(largest, 196608)  # the previous cap refused this complete legitimate result
        MEASURED['maximal_eight_step_run'] = {'claims': len(run['claims']), 'raw_engine_bytes': size(oracle),
                                              'wire_response_bytes_without_selections': runs[0]['response_bytes'],
                                              'wire_response_bytes_with_8_selections': runs[-1]['response_bytes'],
                                              'program_claims_with_related_observations': sum(1 for c in run['claims'] if c['kind'] == 'program_relevance' and c['related_observations'])}

    def test_sdk_transport_lines_and_rejected_headers_are_not_logged(self):
        canary = 'canary-7f3a91.example'
        headers = {'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream'}
        listing = json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list', 'params': {}}).encode()
        with httpx2.Client(timeout=30) as http:
            self.assertEqual(http.post(self.server.url, headers={**headers, 'Host': canary}, content=listing).status_code, 421)
            self.assertEqual(http.post(self.server.url, headers={**headers, 'Origin': 'http://' + canary}, content=listing).status_code, 403)
            self.assertEqual(http.post(self.server.url, headers=headers, content=listing).status_code, 200)

        async def go():
            async with mcp_client(self.server.url) as (session, init, raw):
                await raw('prepare_question', {'utterance': f'Compare senior poverty in House 9 with the State {canary}.'})
        self.wire(go)
        anyio.run(anyio.sleep, 0.5)
        lines = list(self.server.log)
        self.assertTrue(any(x.startswith('{"tool"') for x in lines))
        self.assertFalse([x for x in lines if canary in x])
        self.assertFalse([x for x in lines if 'Terminating session' in x or 'Invalid Host' in x or 'Invalid Origin' in x])
        self.assertTrue(all(set(json.loads(x)) == {'tool', 'status', 'ms'} for x in lines if x.startswith('{"tool"')))

    def test_http_bounds_host_origin_and_malformed(self):
        url = self.server.url
        headers = {'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream'}
        listing = json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list', 'params': {}}).encode()
        with httpx2.Client(timeout=30) as http:
            results = {
                'oversize_body': http.post(url, headers=headers, content=b'{"x":"' + b'a' * (MAX_HTTP_BODY + 1) + b'"}').status_code,
                'malformed_json': http.post(url, headers=headers, content=b'{"jsonrpc":').status_code,
                'foreign_host': http.post(url, headers={**headers, 'Host': 'attacker.example'}, content=listing).status_code,
                'foreign_origin': http.post(url, headers={**headers, 'Origin': 'https://attacker.example'}, content=listing).status_code,
                'wrong_content_type': http.post(url, headers={**headers, 'Content-Type': 'text/plain'}, content=listing).status_code,
                'local_origin': http.post(url, headers={**headers, 'Origin': f'http://127.0.0.1:{self.server.port}'}, content=listing).status_code,
                'other_path': http.post(url.replace('/mcp', '/other'), headers=headers, content=listing).status_code,
            }
            # GET opens a server-to-client SSE stream (kept alive by pings): read headers only, then close it.
            with http.stream('GET', url, headers={'Accept': 'text/event-stream'}, timeout=10) as response:
                results['get_stream'] = response.status_code
                results['get_stream_content_type'] = response.headers.get('content-type', '').split(';')[0]
        self.assertIn(results['get_stream'], (200, 405))
        self.assertEqual((results['oversize_body'], results['malformed_json'], results['foreign_host'], results['foreign_origin'],
                          results['wrong_content_type']), (413, 400, 421, 403, 400))
        self.assertNotEqual(results['local_origin'], 403)
        self.assertEqual(results['other_path'], 404)
        MEASURED['http_bounds_status_codes'] = results

    def test_concurrent_independent_clients(self):
        cases = [('house', '007'), ('house', '019'), ('house', '044'), ('senate', '002'), ('senate', '021'), ('house', '051')]

        async def one(chamber, code, results):
            async with mcp_client(self.server.url) as (session, init, raw):
                flow = AsyncFlow(structured(raw))
                u = f'Run the {RECIPE_LABEL["food_assistance_outreach"]} recipe for {chamber.title()} {int(code)}.'
                d = synthetic_decision(chamber=chamber, code=code, issue='food_assistance_outreach', steps=recipe_steps('food_assistance_outreach'))
                for attempt in range(20):
                    try:
                        results[(chamber, code)] = (await flow.ask_and_run(u, d))[2]
                        return
                    except WireError as exc:
                        if exc.code != 'busy':
                            raise
                        await anyio.sleep(0.2)

        async def go():
            results = {}
            async with anyio.create_task_group() as tg:
                for chamber, code in cases:
                    tg.start_soon(one, chamber, code, results)
            return results
        results = self.wire(go)
        self.assertEqual(set(results), set(cases))
        for (chamber, code), r in results.items():
            self.assertEqual(r['normalized_plan']['district'], {'state_fips': '15', 'chamber': chamber, 'code': code, 'boundary_session': 2024})
            self.assertTrue(all(c['finding_id'].count(f'HI-{chamber.upper()}-{code}-2024') or c['kind'] == 'program_relevance' and code in c['finding_id']
                                or c['finding_id'].startswith(('stat:HI-STATE', 'admin:')) for c in r['claims']))

    def test_restart_is_stateless(self):
        async def validate(url):
            async with mcp_client(url) as (session, init, raw):
                flow = AsyncFlow(structured(raw))
                p = await flow.prepare('Compare median household income in Senate 8 with Maui County.')
                d = synthetic_decision(chamber='senate', code='008', issue='custom', steps=[step('s1', 'compare', ['median_household_income'], 'HI-COUNTY-009-2024')])
                v = await flow.validate(p, d)
                return v, await flow.run(v)

        async def rerun(url, v):
            async with mcp_client(url) as (session, init, raw):
                return await structured(raw)('run_plan', Flow.bundle(v))
        first = ServerProcess()
        try:
            v, r1 = self.wire(lambda: validate(first.url))
        finally:
            first.stop()
        self.assertIsNotNone(first.proc.poll())
        second = ServerProcess(port=first.port)
        try:
            r2 = self.wire(lambda: rerun(second.url, v))
            self.assertEqual(second.startup['identity'], first.startup['identity'])
        finally:
            log = second.stop()
        self.assertEqual(r1, r2)
        # Operational logs carry tool, status and duration only; questions and contexts are never logged.
        tool_lines = [json.loads(x) for x in first.log + log if x.startswith('{"tool"')]
        self.assertTrue(tool_lines)
        self.assertTrue(all(set(x) == {'tool', 'status', 'ms'} for x in tool_lines))
        self.assertFalse(any('Senate 8' in x or 'median household income' in x for x in first.log + log))


if __name__ == '__main__':
    unittest.main()
