from fastapi import FastAPI
import logging
from .auth_asgi import MCPAuthASGI
from .minimal_mcp_router import create_minimal_mcp_router as _create_minimal

# Optional MCP integration: import only if available
create_fastapi_router = None
server = None
try:
    import importlib.util as _iu
    if _iu.find_spec("mcp.server.fastapi") and _iu.find_spec("mcp.server"):
        from mcp.server.fastapi import create_fastapi_router  # type: ignore
        from .tools import server  # type: ignore
    else:
        raise ImportError("mcp.server not found")
except Exception as e:
    logging.warning("MCP FastAPI adapter unavailable; /mcp routes disabled: %s", e)


logging.basicConfig(level=logging.INFO)
inner = FastAPI(title="Living FastAPI - MCP Server")
# Prefer real adapter if present; otherwise use minimal stub
if create_fastapi_router is not None and server is not None:
    inner.include_router(create_fastapi_router(server), prefix="/mcp")
else:
    inner.include_router(_create_minimal(None), prefix="/mcp")


@inner.get("/health")
async def health():
    return {"ok": True}


# Protect /mcp with Bearer token
app = MCPAuthASGI(inner)
