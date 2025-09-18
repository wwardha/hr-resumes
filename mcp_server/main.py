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
        # Mount FastMCP's Starlette app that serves `/mcp/sse` and `/mcp/messages/`
        # using the SDK's SSE transport. Mount at root; app itself is configured
        # with mount_path "/mcp" so routes resolve to /mcp/sse etc.
        inner.mount("/mcp", server.sse_app(mount_path="/mcp"))

        @inner.get("/mcp/health")
        async def mcp_health():
            return {"ok": True}
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
