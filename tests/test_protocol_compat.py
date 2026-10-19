"""The streamable-HTTP transport must accept the 2026-07-28 protocol header.

Anthropic's hosted connector client (claude.ai / Claude Desktop custom
connectors / Cowork) sends ``MCP-Protocol-Version: 2026-07-28`` on follow-up
requests. The 1.x SDK answers 400 to that, which surfaces as an unreachable or
flaky connector. Upstream's ``install_protocol_compatibility()`` (run when
``telegram_mcp.runtime`` is imported) patches the SDK's version list.

These tests exercise the *bare* Starlette app, the way
``telegram_mcp.runner_http`` serves it (it unwraps upstream's
ProtocolNegotiationMiddleware so the OAuth routes stay reachable), so the
SDK-level patch alone must be enough.
"""

import json

import httpx
import pytest
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from telegram_mcp import runtime  # noqa: F401 - importing installs the patch
from telegram_mcp.transport.http import ProtocolNegotiationMiddleware

TOOLS_LIST = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}


async def _post_tools_list(version: str) -> httpx.Response:
    """POST tools/list to a fresh stateless server with the given version header.

    A fresh FastMCP per call because a session manager can only be started
    once; the patch mutates SDK module globals, so every instance sees it.
    """
    server = FastMCP(
        "compat-test",
        stateless_http=True,
        # The test client has no real Host; the guard under test is the
        # protocol-version check, not DNS-rebinding protection.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    app = server.streamable_http_app()
    if isinstance(app, ProtocolNegotiationMiddleware):
        app = app.app
    async with server.session_manager.run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            return await client.post(
                "/mcp",
                content=json.dumps(TOOLS_LIST),
                headers={**HEADERS, "MCP-Protocol-Version": version},
            )


@pytest.mark.asyncio
@pytest.mark.parametrize("version", ["2026-07-28", "2025-11-25"])
async def test_streamable_http_accepts_supported_and_forward_versions(version):
    """tools/list with the given header must not be rejected as unsupported."""
    resp = await _post_tools_list(version)
    assert resp.status_code == 200, resp.text
    assert "Unsupported protocol version" not in resp.text


@pytest.mark.asyncio
async def test_streamable_http_still_rejects_unknown_versions():
    resp = await _post_tools_list("1999-01-01")
    assert resp.status_code == 400
    assert "Unsupported protocol version" in resp.text
