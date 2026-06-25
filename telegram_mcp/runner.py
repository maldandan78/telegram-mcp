"""Application entrypoints for the Telegram MCP server."""

from telegram_mcp.install_guard import UnsafeInstallationError, assert_safe_distribution

try:
    assert_safe_distribution()
except UnsafeInstallationError as exc:
    raise SystemExit(str(exc)) from None

from telegram_mcp import runtime as _runtime
from telegram_mcp.runtime import *
import telegram_mcp.tools  # noqa: F401 - registers MCP tools via decorators


async def _connect_authorized_client(label, client) -> None:
    await client.connect()
    if await client.is_user_authorized():
        return

    raise RuntimeError(
        f"Telegram client '{label}' is not authorized. Interactive phone login "
        "is disabled for the MCP server because it runs over stdio. Generate a "
        "session string with `uv run session_string_generator.py`, then set "
        "TELEGRAM_SESSION_STRING or TELEGRAM_SESSION_STRING_<LABEL> in .env. "
        "For existing file sessions, run the login outside the MCP server first."
    )


# Keeps the background cache-warm task referenced so it is not garbage
# collected mid-run (asyncio holds only a weak reference to bare tasks).
_warm_task = None


async def connect_clients() -> None:
    """Connect every configured Telegram client and warm its entity cache.

    Shared by both the stdio entrypoint (:func:`_main`) and the HTTP
    entrypoint in :mod:`telegram_mcp.runner_http` so they behave identically
    at startup. Raises ``RuntimeError`` if any client is unauthorized.

    The connect/authorize step blocks — the server must not serve until every
    client is authorized — but entity-cache warming runs in the background:
    blocking startup on it (e.g. under a GetDialogsRequest flood wait) makes
    MCP clients time out, and ``resolve_entity()`` re-warms the cache on miss
    anyway.
    """
    await asyncio.gather(
        *(_connect_authorized_client(label, cl) for label, cl in clients.items())
    )

    # Warm entity caches in the background — StringSession has no persistent
    # cache, so fetch all dialogs once per client to populate them.
    print("Warming entity caches (background)...", file=sys.stderr)

    async def _warm_caches() -> None:
        try:
            await asyncio.gather(*(cl.get_dialogs() for cl in clients.values()))
            print("Entity caches warmed.", file=sys.stderr)
        except Exception as warm_exc:
            print(f"Entity cache warm failed: {warm_exc}", file=sys.stderr)

    global _warm_task
    _warm_task = asyncio.create_task(_warm_caches())


async def _main() -> None:
    try:
        labels = ", ".join(clients.keys())
        print(f"Starting {len(clients)} Telegram client(s) ({labels})...", file=sys.stderr)
        await connect_clients()

        print(f"Telegram client(s) started ({labels}). Running MCP server...", file=sys.stderr)
        # Use the asynchronous entrypoint instead of mcp.run()
        await mcp.run_stdio_async()
    except Exception as e:
        print(f"Error starting client: {e}", file=sys.stderr)
        if isinstance(e, sqlite3.OperationalError) and "database is locked" in str(e):
            print(
                "Database lock detected. Please ensure no other instances are running.",
                file=sys.stderr,
            )
        sys.exit(1)
    finally:
        try:
            await asyncio.gather(
                *(cl.disconnect() for cl in clients.values()), return_exceptions=True
            )
        except Exception:
            pass


def main() -> None:
    # Branch on transport before doing anything else so the HTTP runner's
    # uvicorn / Starlette imports stay out of the stdio code path.
    if TELEGRAM_MCP_TRANSPORT == "http":
        from telegram_mcp.runner_http import main as http_main

        http_main()
        return

    _configure_allowed_roots_from_cli(sys.argv[1:])
    _runtime._apply_exposed_tools_mode()
    nest_asyncio.apply()
    asyncio.run(_main())


if __name__ == "__main__":
    main()
