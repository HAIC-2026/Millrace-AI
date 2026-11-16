"""MCP registration checks that do not need a socket (the wire itself is covered in test_wire)."""
from __future__ import annotations

import unittest
from unittest import mock

import anyio
import mcp_types as types
from mcp_types import methods
from mcp_types.version import HANDSHAKE_PROTOCOL_VERSIONS, MODERN_PROTOCOL_VERSIONS

from haic_mcp import server
from haic_mcp.tests.support import connector


class RegistrationTests(unittest.TestCase):
    def test_tool_list_is_valid_for_every_protocol_version(self):
        listed = types.ListToolsResult(tools=server.tool_list()).model_dump(by_alias=True, mode='json', exclude_none=True)
        for version in (*HANDSHAKE_PROTOCOL_VERSIONS, *MODERN_PROTOCOL_VERSIONS):
            methods.serialize_server_result('tools/list', version, listed)  # raises on an invalid tool listing
        for tool in listed['tools']:
            self.assertEqual(tool['outputSchema']['type'], 'object')
            self.assertEqual(tool['inputSchema']['type'], 'object')

    def test_oversize_result_is_refused_not_clipped(self):
        handler = server.build_server(connector())._request_handlers['tools/call'].handler
        params = types.CallToolRequestParams(name='prepare_question', arguments={'utterance': 'Profile House 3.'})
        ok = anyio.run(handler, None, params)
        self.assertFalse(ok.is_error)
        self.assertLess(server.envelope_bytes(ok), server.MAX_RESULT_BYTES)
        with mock.patch.object(server, 'MAX_RESULT_BYTES', server.envelope_bytes(ok) - 1):
            refused = anyio.run(handler, None, params)
        self.assertTrue(refused.is_error)
        self.assertEqual(refused.structured_content['error']['code'], 'result_too_large')
        self.assertEqual(refused.structured_content['error']['retry_action'], 'reduce_plan_or_use_source_id_filter')


if __name__ == '__main__':
    unittest.main()
