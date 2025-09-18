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
        if hasattr(server, "http_app"):
            try:
                http_app = server.http_app(mount_path="/mcp")
                http_enabled = True
                logging.info("FastMCP Streamable HTTP transport available")
            except Exception as http_err:
                logging.warning("FastMCP HTTP app unavailable: %s", http_err)

        sse_app = server.sse_app(mount_path="/mcp")

        if http_enabled and http_app is not None:
            inner.mount("/mcp", http_app)
            if hasattr(http_app, "mount"):
                try:
                    http_app.mount("/sse", sse_app)
                    logging.info("Mounted SSE fallback beneath HTTP app")
                except Exception as mount_err:
                    logging.warning("Failed to mount SSE fallback under HTTP app: %s", mount_err)
            else:
                logging.warning("HTTP app does not support .mount; SSE fallback unavailable")
        else:
            inner.mount("/mcp", sse_app)
            logging.info("Mounted FastMCP SSE app at /mcp")

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
