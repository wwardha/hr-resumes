from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

import httpx
from fastapi import Body, FastAPI, Header, HTTPException
import logging
try:
    from mcp.server.fastapi import create_fastapi_router
except Exception as e:
    create_fastapi_router = None  # type: ignore
    print("[WARN] MCP FastAPI adapter unavailable; using minimal /mcp stub:", e)
from .minimal_mcp_router import create_minimal_mcp_router as _create_minimal

try:
    from .mcp_dynamic import build_server
except Exception as e:
    build_server = None  # type: ignore
    print("[WARN] MCP dynamic server unavailable; /mcp routes disabled:", e)


APP_DIR = Path(__file__).resolve().parent
TOOLS_FILE = APP_DIR / "_mcp_tools.json"
RELOAD_SENTINEL = APP_DIR / "__reload__.txt"
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")


logging.basicConfig(level=logging.INFO)
app = FastAPI(title="Generated API (+ MCP)")


@app.get("/health")
async def health():
    return {"ok": True}


# Mount MCP if available
if build_server is not None and create_fastapi_router is not None:
    _server = build_server()
    app.include_router(create_fastapi_router(_server), prefix="/mcp")
else:
    # Either the dynamic server or adapter is unavailable; mount minimal stub
    app.include_router(_create_minimal(None), prefix="/mcp")


def _require_admin(token: Optional[str]):
    if not ADMIN_TOKEN:
        raise HTTPException(status_code=500, detail="ADMIN_TOKEN not configured")
    if (token or "") != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="invalid admin token")


class RegisterToolBodyModel(BaseModel := type("RegisterToolBodyModel", (), {})):
    # Lightweight runtime model creation to avoid pydantic import here
    pass


@app.get("/_gen_admin/mcp_tools")
async def list_tools(x_admin_token: Optional[str] = Header(None)):
    _require_admin(x_admin_token)
    if not TOOLS_FILE.exists():
        return []
    return json.loads(TOOLS_FILE.read_text("utf-8"))


@app.post("/_gen_admin/mcp_tools")
async def register_tool(body: Dict[str, Any] = Body(...), x_admin_token: Optional[str] = Header(None)):
    _require_admin(x_admin_token)
    items = []
    if TOOLS_FILE.exists():
        items = json.loads(TOOLS_FILE.read_text("utf-8"))
    # replace by name
    name = body.get("name")
    if not name:
        raise HTTPException(status_code=400, detail="'name' is required")
    items = [x for x in items if x.get("name") != name] + [body]
    TOOLS_FILE.write_text(json.dumps(items, indent=2), "utf-8")
    RELOAD_SENTINEL.write_text(str(time.time()), "utf-8")
    return {"status": "ok", "message": "tool registered; server will auto-reload"}


@app.delete("/_gen_admin/mcp_tools")
async def delete_tool(name: str, x_admin_token: Optional[str] = Header(None)):
    _require_admin(x_admin_token)
    items = []
    if TOOLS_FILE.exists():
        items = json.loads(TOOLS_FILE.read_text("utf-8"))
    items = [x for x in items if x.get("name") != name]
    TOOLS_FILE.write_text(json.dumps(items, indent=2), "utf-8")
    RELOAD_SENTINEL.write_text(str(time.time()), "utf-8")
    return {"status": "ok", "message": f"tool '{name}' removed; server will auto-reload"}
