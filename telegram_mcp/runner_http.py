"""HTTP (streamable-http + OAuth) entrypoint for the Telegram MCP server.

Selected when ``TELEGRAM_MCP_TRANSPORT=http``. Mirrors ``runner.py`` but
serves the MCP endpoint over HTTP through uvicorn, with the OAuth 2.1
provider wired into FastMCP. The Telegram clients are connected and their
entity caches warmed once at startup, exactly like the stdio path.
"""

from __future__ import annotations

import asyncio
import os
import sys

import uvicorn

from telegram_mcp import runtime as _runtime
from telegram_mcp import transcription as _transcription
from telegram_mcp.runtime import (
    _configure_allowed_roots_from_cli,
    clients,
    mcp,
)
from telegram_mcp.runner import (
    _configure_transport_security,
    _session_lock_shared,
    _session_locks,
    connect_clients,
)


async def _serve_http() -> None:
    """Connect Telegram clients, warm caches, then serve the ASGI app."""
    labels = ", ".join(clients.keys())
    print(
        f"Starting {len(clients)} Telegram client(s) ({labels})...",
        file=sys.stderr,
    )
    await connect_clients()

    # Build the Starlette app and attach the OAuth login routes. We import
    # here (after the package is fully initialized) so that the FastMCP
    # session manager is created in the right order.
    from telegram_mcp.auth import SingleUserOAuthProvider

    app = mcp.streamable_http_app()
    provider = mcp._auth_server_provider  # type: ignore[attr-defined]
    if isinstance(provider, SingleUserOAuthProvider):
        for route in provider.routes():
            app.routes.append(route)

    # Optional DNS-rebinding protection (MCP_ALLOWED_HOSTS / MCP_ALLOWED_ORIGINS),
    # same knobs as the upstream MCP_TRANSPORT=http path.
    _configure_transport_security()

    host = os.getenv("TELEGRAM_MCP_HOST", "0.0.0.0")
    port = int(os.getenv("TELEGRAM_MCP_PORT", "8000"))
    public_url = os.getenv("TELEGRAM_MCP_PUBLIC_URL", "(unset)")

    print(
        f"Telegram client(s) ready ({labels}). Serving MCP over HTTP on "
        f"{host}:{port}  (public URL: {public_url})",
        file=sys.stderr,
    )

    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level=os.getenv("TELEGRAM_MCP_LOG_LEVEL", "info"),
        access_log=False,
        # Trust X-Forwarded-* headers from the reverse proxy / Cloudflare
        # tunnel so issued redirect URIs stay on HTTPS.
        proxy_headers=True,
        forwarded_allow_ips="*",
    )
    server = uvicorn.Server(config)
    try:
        await server.serve()
    finally:
        await asyncio.gather(
            *(cl.disconnect() for cl in clients.values()),
            return_exceptions=True,
        )
        for lock in _session_locks.values():
            lock.release()
        _session_locks.clear()


def main() -> None:
    # Same startup validation as the stdio path in ``runner.main``.
    _configure_allowed_roots_from_cli(sys.argv[1:])
    _runtime._apply_exposed_tools_mode()
    _transcription.validate_transcription_config()
    _session_lock_shared()  # fail loudly at startup on a bad toggle
    asyncio.run(_serve_http())


if __name__ == "__main__":
    main()
