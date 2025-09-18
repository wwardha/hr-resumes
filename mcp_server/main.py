from fastapi import FastAPI, Request
from starlette.responses import Response
import logging
from .auth_asgi import MCPAuthASGI
from .minimal_mcp_router import create_minimal_mcp_router as _create_minimal

logging.basicConfig(level=logging.INFO)
inner = FastAPI(title="Living FastAPI - MCP Server")

# Try to expose real MCP SSE routes using the SDK available in newer versions
try:
    import importlib.util as _iu
    if _iu.find_spec("mcp.server") and _iu.find_spec("mcp.server.sse"):
        from .tools import server  # FastMCP instance with tools registered

        http_enabled = False
        http_app = None
        if hasattr(server, "streamable_http_app"):
            logging.info("FastMCP server exposes streamable_http_app callable")
            try:
                http_app = server.streamable_http_app()
                http_enabled = True
                logging.info("FastMCP Streamable HTTP transport available")
            except Exception as http_err:
                logging.warning("FastMCP HTTP app unavailable: %s", http_err)
        else:
            logging.info("FastMCP server missing streamable_http_app; using SSE only")

        sse_app = server.sse_app()

        class MCPMux:
            def __init__(self, http_app, sse_app):
                self._http_app = http_app
                self._sse_app = sse_app

            async def __call__(self, scope, receive, send):
                target = self._http_app
                routed_scope = scope
                if scope.get("type") in {"http", "websocket"}:
                    suffix = scope.get("path", "") or ""
                    routed_scope = dict(scope)
                    if suffix in ("", "/"):
                        routed_scope["path"] = "/mcp"
                        target = self._http_app
                    elif suffix.startswith("/sse") or suffix.startswith("/messages"):
                        routed_scope["path"] = suffix
                        target = self._sse_app
                    else:
                        routed_scope["path"] = "/mcp" + suffix
                        target = self._http_app
                await target(routed_scope, receive, send)

        if http_enabled and http_app is not None:
            inner.mount("/mcp", MCPMux(http_app, sse_app))
        else:
            inner.mount("/mcp", sse_app)

        @inner.get("/mcp/health")
        async def mcp_health():
            return {"ok": True, "http": http_enabled}
    else:
        raise ImportError("mcp.server.sse not found")
except Exception as e:
    logging.warning("MCP SSE adapter unavailable; using minimal /mcp stub: %s", e)
    inner.include_router(_create_minimal(None), prefix="/mcp")


@inner.get("/health")
async def health():
    return {"ok": True}


# Protect /mcp with Bearer token
app = MCPAuthASGI(inner)
