# =============================================================================
# Base stage: official minimal Alpine Python runtime
# =============================================================================
FROM python:3.13-alpine AS base

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# =============================================================================
# Builder stage: build wheels / dependencies
# =============================================================================
FROM base AS builder

COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir --prefix=/install -r requirements.txt

# =============================================================================
# Development / Test stage: includes dev tooling from pyproject.toml
# =============================================================================
FROM base AS development

# Copy installed production packages
COPY --from=builder /install /usr/local

# Copy dev dependencies and install test/lint tools
COPY pyproject.toml ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir black flake8 pytest pytest-asyncio pytest-cov

# Copy application source and tests
COPY main.py sanitize.py ./
COPY telegram_mcp ./telegram_mcp
COPY tests ./tests

CMD ["pytest", "--cov", "--cov-report=term-missing"]

# =============================================================================
# Production stage: slim runtime container with non-root appuser
# =============================================================================
FROM base AS production

# Copy only installed dependencies from builder
COPY --from=builder /install /usr/local

# Copy application source code
COPY main.py sanitize.py ./
COPY telegram_mcp ./telegram_mcp

# Create non-root user and setup directories. /data is pre-created with the
# right ownership so a Docker named volume mounted there (used by the http
# compose profile for OAuth state, TELEGRAM_MCP_OAUTH_DB) inherits these perms
# when it's first created. Without it the volume comes up as root:root and the
# server crashes with "unable to open database file".
RUN adduser --disabled-password --gecos "" appuser && \
    mkdir -p /app/data/transcripts /data && \
    chown -R appuser:appuser /app /data

USER appuser

# Runtime environment variables (to be supplied at run/container start)
ENV TELEGRAM_API_ID="" \
    TELEGRAM_API_HASH="" \
    TELEGRAM_SESSION_NAME="telegram_mcp_session" \
    TELEGRAM_SESSION_STRING=""

# --- Transport selection ----------------------------------------------------
# TELEGRAM_MCP_TRANSPORT: "stdio" (default, local Claude Desktop / Claude
#   Code) or "http" (remote streamable-http + OAuth 2.1 for Claude Desktop's
#   "Add custom connector" dialog).
# When TELEGRAM_MCP_TRANSPORT=http these additional vars are required:
#   TELEGRAM_MCP_PUBLIC_URL   - externally reachable HTTPS base URL
#                               (e.g. https://tg-mcp.example.com). Used as
#                               the OAuth issuer + resource identifier.
#   TELEGRAM_MCP_AUTH_PASSWORD - password the single user enters in the
#                                login form to complete the OAuth flow.
# Optional:
#   TELEGRAM_MCP_AUTH_USERNAME (default "admin")
#   TELEGRAM_MCP_HOST          (default "0.0.0.0")
#   TELEGRAM_MCP_PORT          (default 8000)
ENV TELEGRAM_MCP_TRANSPORT="stdio"

# HTTP transport listens on 8000 inside the container; expose it so a host
# reverse proxy / Cloudflare Tunnel can reach it. No-op in stdio mode.
EXPOSE 8000

CMD ["python", "main.py"]
