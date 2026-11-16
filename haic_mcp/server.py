"""MCP registration and Streamable HTTP runtime (official Python SDK, low-level Server)."""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time

import anyio
import mcp_types as types
from mcp.server import Server
from mcp.server.transport_security import TransportSecuritySettings

from .engine import CONNECTOR_NAME, CONNECTOR_VERSION, Engine, StartupError
from .tools import CONTEXT, HASH, INPUT_SCHEMAS, REQUEST, Connector, ToolError

MAX_HTTP_BODY = 131072
MAX_RESULT_BYTES = 262144  # frozen above the largest measured legitimate eight-step run (8 selections): see README
LOOPBACK = ('127.0.0.1', '::1', 'localhost')
log = logging.getLogger('haic_mcp')

INSTRUCTIONS = (
    "HAIC public Hawaii district evidence, read-only and deterministic. Flow: prepare_question -> validate_proposal -> "
    "run_plan -> inspect_source or build_brief. Copy request, identity, next_context, decision and proposal_digest exactly "
    "as returned; never invent IDs, districts, plans or claim refs. Pass the user's question verbatim. Never rewrite it to "
    "get past a clarification or refusal; ask the user. Show the normalized plan before run_plan. "
    "State facts only from run_plan, inspect_source or build_brief results, with their MOEs and caveat IDs (C1, C2...) or "
    "citation numbers. interpretation_rules govern only the decision step. Follow-ups: call prepare_question with the "
    "latest next_context and identity; select only claim refs the user points to (at most eight). Programs are "
    "informational; outreach items are hypotheses, not eligibility or measured gaps. Sources are bundled normalized "
    "projections; no URL is fetched.")

ERROR_SCHEMA = {'type': 'object', 'required': ['status', 'error'], 'properties': {
    'status': {'const': 'tool_error'},
    'error': {'type': 'object', 'required': ['code', 'message', 'retry_action'],
              'properties': {'code': {'type': 'string'}, 'message': {'type': 'string'}, 'retry_action': {'type': 'string'}}}}}


def _out(required, properties):
    # MCP requires a top-level object schema; a result is either the tool's success shape or a typed tool error.
    return {'type': 'object', 'anyOf': [{'type': 'object', 'required': required, 'properties': properties}, ERROR_SCHEMA]}


OBJ, ARR, STR = {'type': 'object'}, {'type': 'array'}, {'type': 'string'}
NULL_CONTEXT = {'anyOf': [CONTEXT, {'type': 'null'}]}
CLAIM_OUT = {'type': 'object', 'required': ['finding_id', 'kind', 'claim_ref', 'text', 'caveat_ids', 'source_ids'],
             'properties': {'text': STR, 'caveat_ids': ARR, 'source_ids': ARR}}
OUTPUT_SCHEMAS = {
    'prepare_question': _out(['status', 'identity', 'request', 'next_context', 'provider_context', 'decision_schema',
                              'interpretation_rules', 'interpretation_rules_sha256'],
                             {'status': {'const': 'prepared'}, 'identity': OBJ, 'request': REQUEST, 'next_context': CONTEXT,
                              'provider_context': OBJ, 'decision_schema': OBJ, 'interpretation_rules': STR, 'interpretation_rules_sha256': HASH}),
    'validate_proposal': _out(['status', 'intent', 'message', 'reason_code', 'normalized_plan', 'typed_diff', 'inherited_fields',
                               'source_inspection_refs', 'choices', 'clarify_field', 'recovery', 'rejection_code', 'identity',
                               'request', 'decision', 'proposal_digest', 'next_context'],
                              {'status': {'enum': ['propose', 'clarify', 'unsupported', 'uncertain']}, 'identity': OBJ,
                               'request': REQUEST, 'decision': OBJ, 'proposal_digest': {'anyOf': [HASH, {'type': 'null'}]},
                               'next_context': CONTEXT}),
    'run_plan': _out(['status', 'identity', 'run_status', 'normalized_plan', 'steps', 'claims', 'responses', 'selection_review',
                      'action_review', 'limitation_ids', 'caveats', 'next_context'],
                     {'status': {'const': 'ok'}, 'run_status': {'enum': ['ok', 'partial', 'unsupported', 'error']},
                      'claims': {'type': 'array', 'items': CLAIM_OUT}, 'caveats': ARR, 'next_context': CONTEXT}),
    'inspect_source': _out(['status', 'mode', 'identity', 'sources', 'leaves', 'normalized_findings', 'fetch_policy', 'next_context'],
                           {'status': {'const': 'ok'}, 'mode': {'enum': ['catalog', 'claim', 'source_intent']},
                            'sources': OBJ, 'leaves': ARR, 'normalized_findings': OBJ, 'fetch_policy': STR, 'next_context': NULL_CONTEXT}),
    'build_brief': _out(['status', 'identity', 'run_status', 'brief', 'next_context'],
                        {'status': {'const': 'ok'}, 'brief': {'type': 'object', 'required': ['entries', 'citations', 'limitations']},
                         'next_context': CONTEXT}),
}
DESCRIPTIONS = {
    'prepare_question': "Start or continue a question. First call: the user's question alone. Follow-up: add the latest "
                        "next_context and identity. Returns the canonical request, interpretation_rules, provider_context and "
                        "the request-specific decision_schema. No facts are returned here.",
    'validate_proposal': "Check one complete decision for the exact prepared request. Returns the normalized plan and changes, "
                         "a clarification, or a refusal, plus a proposal_digest for copy consistency (not authorization).",
    'run_plan': "Run a validated plan on the public evidence snapshot. Requires request, decision, expected_identity and "
                "proposal_digest exactly as validated. Returns canonical claims with MOEs, caveats and source IDs.",
    'inspect_source': "Look up bundled source provenance. mode=catalog needs source_id only. mode=claim needs a validated "
                      "executable bundle and an exact current claim_ref. mode=source_intent needs a validated inspect_source "
                      "bundle. Returns normalized projections; original bytes are not re-read and no URL is fetched.",
    'build_brief': "Build the deterministic one-page brief from a validated plan and up to eight exact claim refs, with an "
                   "optional action ref. Returns structured data and a readable text projection with numbered citations.",
}
TITLES = {'prepare_question': 'Prepare a question', 'validate_proposal': 'Validate a proposal', 'run_plan': 'Run a validated plan',
          'inspect_source': 'Inspect a source', 'build_brief': 'Build a brief'}


def tool_list():
    return [types.Tool(name=name, title=TITLES[name], description=DESCRIPTIONS[name], input_schema=INPUT_SCHEMAS[name],
                       output_schema=OUTPUT_SCHEMAS[name],
                       annotations=types.ToolAnnotations(title=TITLES[name], read_only_hint=True, destructive_hint=False,
                                                         open_world_hint=False, idempotent_hint=name != 'prepare_question'))
            for name in INPUT_SCHEMAS]


def envelope_bytes(result: types.CallToolResult) -> int:
    """Serialized JSON-RPC response size across BOTH channels (text content and structuredContent)."""
    body = result.model_dump(by_alias=True, mode='json', exclude_none=True)
    return len(json.dumps({'jsonrpc': '2.0', 'id': 2147483647, 'result': body}, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))


def _error_result(err: ToolError) -> types.CallToolResult:
    content = err.content()
    return types.CallToolResult(content=[types.TextContent(type='text', text=f"{err.code}: {err.message} Retry: {err.retry_action}.")],
                                structured_content=content, is_error=True)


def build_server(connector: Connector) -> Server:
    tools = tool_list()

    async def list_tools(ctx, params):
        return types.ListToolsResult(tools=tools)

    async def call_tool(ctx, params):
        started = time.monotonic()
        status = 'ok'
        try:
            structured, text = await anyio.to_thread.run_sync(connector.call, params.name, params.arguments)
            result = types.CallToolResult(content=[types.TextContent(type='text', text=text)], structured_content=structured)
            if envelope_bytes(result) > MAX_RESULT_BYTES:
                raise ToolError('result_too_large', f'The complete result exceeds {MAX_RESULT_BYTES} bytes; nothing was clipped.',
                                'reduce_plan_or_use_source_id_filter')
        except ToolError as err:
            status, result = err.code, _error_result(err)
        except Exception:
            status = 'internal_error'
            result = _error_result(ToolError('internal_error', 'The tool failed safely.', 'retry'))
        # Operational metadata only: no question, context, arguments or results are logged or retained.
        log.info(json.dumps({'tool': params.name if params.name in INPUT_SCHEMAS else 'unknown', 'status': status,
                             'ms': round((time.monotonic() - started) * 1000)}))
        return result

    return Server(CONNECTOR_NAME, version=CONNECTOR_VERSION, title='HAIC district evidence', instructions=INSTRUCTIONS,
                  on_list_tools=list_tools, on_call_tool=call_tool)


def build_app(connector: Connector, *, host: str, port: int, allowed_hosts=(), allowed_origins=()):
    security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[f'127.0.0.1:{port}', f'localhost:{port}', f'[::1]:{port}', *allowed_hosts],
        allowed_origins=[f'http://127.0.0.1:{port}', f'http://localhost:{port}', *allowed_origins])
    return build_server(connector).streamable_http_app(
        streamable_http_path='/mcp', json_response=True, stateless_http=True, max_request_body_size=MAX_HTTP_BODY,
        transport_security=security, host=host)


def main(argv=None):
    parser = argparse.ArgumentParser(prog='python -m haic_mcp', description='HAIC public MCP server (loopback by default).')
    parser.add_argument('--host', default='127.0.0.1', choices=LOOPBACK)
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--engine-root', default=None, help='Engine checkout (default: the directory containing haic_mcp).')
    parser.add_argument('--expected-manifest-sha256', default=None, help='Override the pinned RELEASE-MANIFEST.json SHA-256.')
    parser.add_argument('--allowed-host', action='append', default=[], help='Extra exact Host header value (e.g. a tunnel name).')
    parser.add_argument('--allowed-origin', action='append', default=[], help='Extra exact Origin header value.')
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format='%(message)s', stream=sys.stderr)
    logging.getLogger('mcp').setLevel(logging.ERROR)  # SDK transport lines can carry caller-chosen header values
    try:
        engine = Engine(args.engine_root, args.expected_manifest_sha256)
    except (StartupError, Exception) as exc:  # startup is fail-closed; the reason is a fixed message
        print(json.dumps({'startup': 'failed', 'reason': str(exc) if isinstance(exc, StartupError) else type(exc).__name__}), file=sys.stderr)
        return 2
    import uvicorn
    app = build_app(Connector(engine), host=args.host, port=args.port, allowed_hosts=args.allowed_host,
                    allowed_origins=args.allowed_origin)
    print(json.dumps({'startup': 'ok', 'url': f'http://{args.host}:{args.port}/mcp', 'identity': engine.identity,
                      'engine_modules': len(engine.loaded_modules)}), file=sys.stderr, flush=True)
    uvicorn.run(app, host=args.host, port=args.port, log_level='warning', access_log=False, lifespan='on')
    return 0
