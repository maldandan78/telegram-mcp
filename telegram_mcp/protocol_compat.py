"""Accept newer ``MCP-Protocol-Version`` headers on the streamable-HTTP transport.

Anthropic's hosted connector client (``User-Agent: Claude-User``, used by
claude.ai, Claude Desktop custom connectors and Cowork) negotiates the
2026-07-28 MCP revision and keeps sending ``MCP-Protocol-Version:
2026-07-28`` on follow-up requests even when the server answered the
``initialize`` request with an older version. The 1.x Python SDK only knows
revisions up to 2025-11-25 and rejects every such request with ``400 Bad
Request: Unsupported protocol version``, so the connector shows up as
"unreachable" or fails intermittently.

The 2.x SDK implements 2026-07-28 natively, but upstream pins ``mcp<2``
because the FastMCP API changed. Until that upgrade lands, this shim makes
the transport's header check tolerate the newer revision. Everything else
(negotiation in ``initialize``, session handling, SSE priming) is left to the
SDK: the client is already operating in the legacy, session-based mode, it
merely echoes the wrong version string.
"""

from __future__ import annotations

from mcp.server.streamable_http import (
    MCP_PROTOCOL_VERSION_HEADER,
    StreamableHTTPServerTransport,
)
from mcp.shared.version import SUPPORTED_PROTOCOL_VERSIONS

# Revisions newer than the SDK's SUPPORTED_PROTOCOL_VERSIONS that we accept on
# the wire. Extend when Anthropic's client moves to the next revision.
FORWARD_COMPATIBLE_VERSIONS: frozenset[str] = frozenset({"2026-07-28"})

_ORIGINAL_VALIDATE = StreamableHTTPServerTransport._validate_protocol_version
_INSTALLED = False


def accepted_protocol_versions() -> frozenset[str]:
    """Every protocol version the patched transport accepts in the header."""
    return frozenset(SUPPORTED_PROTOCOL_VERSIONS) | FORWARD_COMPATIBLE_VERSIONS


async def _validate_protocol_version(self, request, send) -> bool:  # type: ignore[no-untyped-def]
    version = request.headers.get(MCP_PROTOCOL_VERSION_HEADER)
    if version in FORWARD_COMPATIBLE_VERSIONS:
        return True
    return await _ORIGINAL_VALIDATE(self, request, send)


def install() -> None:
    """Patch the SDK transport once. Safe to call repeatedly."""
    global _INSTALLED
    if _INSTALLED:
        return
    StreamableHTTPServerTransport._validate_protocol_version = _validate_protocol_version  # type: ignore[method-assign]
    _INSTALLED = True
