# app.py
#
# FastAPI + FastMCP (HTTP Streamable + SSE) on one port with robust Bearer auth
# and root_path-aware muxing. Fixes 404 by clearing root_path when forwarding
# to a child that expects '/mcp' internally.
#
# Start:
#   export MCP_BEARER=dev-token
#   uvicorn app:app --host 0.0.0.0 --port 8000
#
# Test HTTP Streamable:
#   curl -s -L -H "Authorization: Bearer ${MCP_BEARER:-dev-token}" \
#        -H "Content-Type: application/json" \
#        -d '{"jsonrpc":"2.0","id":"1","method":"tools/list","params":{}}' \
#        http://localhost:8000/mcp
#
# Test SSE:
#   curl -i -H "Authorization: Bearer ${MCP_BEARER:-dev-token}" http://localhost:8000/mcp/sse
#   curl -i -X POST -H "Authorization: Bearer ${MCP_BEARER:-dev-token}" \
#        -H "Content-Type: application/json" -d '{"hello":"world"}' \
#        http://localhost:8000/mcp/messages/

import os
import logging
from typing import Iterable

from fastapi import FastAPI, APIRouter
from starlette.types import Scope, Receive, Send
from starlette.responses import JSONResponse, PlainTextResponse

logging.basicConfig(level=logging.INFO)
LOG = logging.getLogger("mcp-embed")

# -----------------------------
# Robust Bearer auth wrapper (single-file)
# -----------------------------
class MCPAuthASGI:
    """
    Protects all /mcp* routes.

    Accepts:
      - Authorization: Bearer <token>      (scheme case-insensitive)
      - X-Auth-Token: <token>
      - ?auth=<token>                       (debug)

    Token source (first found):
      - MCP_BEARER env
      - MCP_TOKEN  env
      - "dev-token" default

    Optional:
      - ALLOW_CF_ACCESS=1 -> accept CF-ACCESS-JWT-ASSERTION presence.

    Lifespan scopes always pass through.
    """
    def __init__(self, app, token_env_primary="MCP_BEARER", token_env_alt="MCP_TOKEN", prefix_env="MCP_PREFIX"):
        self.app = app
        self.prefix = os.getenv(prefix_env, "/mcp").rstrip("/") or "/mcp"
        token = os.getenv(token_env_primary) or os.getenv(token_env_alt) or "dev-token"
        self.token = token.strip().strip('"').strip("'")
        self.allow_cf_access = os.getenv("ALLOW_CF_ACCESS", "0").lower() in ("1", "true", "yes")

        LOG.info("MCPAuthASGI configured: prefix=%s, token_len=%d, allow_cf_access=%s",
                 self.prefix, len(self.token), self.allow_cf_access)

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        typ = scope.get("type")

        if typ == "lifespan":
            return await self.app(scope, receive, send)

        if typ in {"http", "websocket"}:
            path = scope.get("path") or "/"
            if path == self.prefix or path.startswith(self.prefix + "/"):
                headers = {k.decode("latin1").lower(): v.decode("latin1")
                           for k, v in scope.get("headers", [])}

                if self.allow_cf_access and ("cf-access-jwt-assertion" in headers):
                    return await self.app(scope, receive, send)

                supplied = None
                auth_hdr = headers.get("authorization", "")
                if auth_hdr:
                    parts = auth_hdr.strip().split(None, 1)
                    if len(parts) == 2 and parts[0].lower() == "bearer":
                        supplied = parts[1].strip()

                if not supplied:
                    x_token = headers.get("x-auth-token", "")
                    if x_token:
                        supplied = x_token.strip()

                if not supplied:
                    q = (scope.get("query_string") or b"").decode("latin1")
                    if q:
                        for kv in q.split("&"):
                            if kv.startswith("auth="):
                                supplied = kv[5:] or None
                                break

                if supplied != self.token:
                    try:
                        LOG.warning("401 on %s - headers seen: %s", path, sorted(headers.keys()))
                    except Exception:
                        pass
                    resp = PlainTextResponse("Unauthorized", status_code=401,
                                             headers={"WWW-Authenticate": "Bearer"})
                    return await resp(scope, receive, send)

        return await self.app(scope, receive, send)


# -----------------------------
# Minimal fallback router (if MCP SDK absent)
# -----------------------------
def create_minimal_mcp_router() -> APIRouter:
    r = APIRouter()

    @r.get("/health")
    async def mcp_health():
        return {"ok": True, "transport": "none", "reason": "mcp.server not available"}

    @r.post("/")
    async def mcp_http_stub():
        return JSONResponse(
            {"error": "MCP HTTP streamable not available. Install/update mcp.server."},
            status_code=503,
        )

    @r.get("/sse")
    async def mcp_sse_stub():
        return JSONResponse(
            {"error": "MCP SSE not available. Install/update mcp.server."},
            status_code=503,
        )

    @r.post("/messages/")
    async def mcp_messages_stub():
        return JSONResponse(
            {"error": "MCP SSE messages not available. Install/update mcp.server."},
            status_code=503,
        )

    @r.get("/")
    async def mcp_root():
        return {"ok": False, "hint": "POST JSON-RPC to /mcp with Authorization header."}

    return r


# -----------------------------
# Main assembly: build real MCP HTTP+SSE; else fallback
# -----------------------------
try:
    import importlib.util as _iu

    if _iu.find_spec("mcp.server") and _iu.find_spec("mcp.server.sse"):
        # Use your project's FastMCP instance with tools registered
        try:
            from .tools import server  # type: ignore
            LOG.info("Using FastMCP instance from .tools")
        except Exception as e:
            LOG.warning("Could not import .tools.server; creating demo FastMCP: %s", e)
            from mcp.server.fastmcp import FastMCP  # type: ignore
            server = FastMCP("demo", stateless_http=True)

            @server.tool()
            def ping() -> str:
                return "pong"

        # Build transports
        http_app = server.streamable_http_app()   # Starlette app (with its own lifespan)
        sse_app  = server.sse_app()               # SSE ASGI app

        # Parent must run the child's lifespan (starts StreamableHTTP session manager)
        inner = FastAPI(
            title="Living FastAPI - MCP Server",
            lifespan=http_app.router.lifespan_context,
        )

        # Detect whether the child HTTP app expects "/mcp" internally
        child_paths: Iterable[str] = [
            getattr(r, "path", None)
            for r in getattr(http_app, "routes", [])
            if hasattr(r, "path")
        ]
        HTTP_NEEDS_INNER_PREFIX = "/mcp" in child_paths
        LOG.info("Child HTTP route expectation: %s",
                 "'/mcp' (inner prefix)" if HTTP_NEEDS_INNER_PREFIX else "'/' (root)")

        class MCPMux:
            """Dispatch to HTTP (root) and SSE (/sse, /messages) after mount.
            Normalizes path using root_path to avoid double-prefix issues.
            """
            def __init__(self, http_app, sse_app):
                self._http_app = http_app
                self._sse_app = sse_app

            async def __call__(self, scope: Scope, receive: Receive, send: Send):
                typ = scope.get("type")

                if typ in {"http", "websocket"}:
                    raw_path = scope.get("path") or "/"
                    root_path = scope.get("root_path", "") or ""

                    # Normalize to local path relative to the mount
                    local = raw_path
                    if root_path and local.startswith(root_path):
                        local = local[len(root_path):] or "/"

                    # Defensively strip '/mcp' again if it still leaks into local
                    if local in ("/mcp", "/mcp/"):
                        local = "/"
                    elif local.startswith("/mcp/"):
                        local = local[len("/mcp"):] or "/"

                    LOG.info("MCPMux: raw_path='%s' root_path='%s' -> local='%s'",
                             raw_path, root_path, local)

                    # ---- HTTP Streamable at local root ----
                    if local == "/":
                        if HTTP_NEEDS_INNER_PREFIX:
                            # IMPORTANT: clear root_path so child sees '/mcp' at its own root
                            routed = dict(scope)
                            routed["root_path"] = ""          # <--- fix for 404
                            routed["path"] = "/mcp"
                            LOG.info("MCPMux -> HTTP: root_path cleared, path '/mcp'")
                            return await self._http_app(routed, receive, send)

                        LOG.info("MCPMux -> HTTP: forwarding local '/' unchanged")
                        return await self._http_app(scope, receive, send)

                    # ---- SSE endpoints ----
                    if local.startswith("/sse") or local.startswith("/messages"):
                        if local != raw_path:
                            routed = dict(scope)
                            routed["path"] = local
                            LOG.info("MCPMux -> SSE: forwarding with normalized path '%s'", local)
                            return await self._sse_app(routed, receive, send)
                        LOG.info("MCPMux -> SSE: forwarding as-is")
                        return await self._sse_app(scope, receive, send)

                    # Fallback to HTTP app (may 404 if unknown)
                    if local != raw_path:
                        routed = dict(scope)
                        routed["path"] = local
                        LOG.info("MCPMux -> HTTP (fallback): normalized path '%s'", local)
                        return await self._http_app(routed, receive, send)
                    LOG.info("MCPMux -> HTTP (fallback): as-is")
                    return await self._http_app(scope, receive, send)

                # Other scopes (e.g., lifespan) -> pass through to HTTP app
                return await self._http_app(scope, receive, send)

        # Mount mux at /mcp
        inner.mount("/mcp", MCPMux(http_app, sse_app))
        LOG.info("MCPMux (HTTP+SSE) mounted at /mcp")

        @inner.get("/health")
        async def health():
            return {"ok": True, "transport": "http+sse"}

        # Wrap with Bearer auth
        app = MCPAuthASGI(inner)

    else:
        raise ImportError("mcp.server or mcp.server.sse not found")

except Exception as e:
    LOG.warning("MCP HTTP/SSE not available; falling back to minimal stub: %s", e)
    inner = FastAPI(title="Living FastAPI - MCP Server (fallback)")
    inner.include_router(create_minimal_mcp_router(), prefix="/mcp")

    @inner.get("/health")
    async def health():
        return {"ok": True, "transport": "none", "reason": str(e)}

    app = MCPAuthASGI(inner)
