from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List

import httpx
from jinja2 import Template
from mcp.logging import setup_logging
from mcp.server import Server


TOOLS_FILE = Path(__file__).resolve().parent / "_mcp_tools.json"
CLAUDE_CODE_URL = os.getenv("CLAUDE_CODE_URL", "http://127.0.0.1:8300").rstrip("/")
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")


def _render_template(tpl: str, ctx: Dict[str, Any]) -> str:
    return Template(tpl).render(**ctx)


def _claude_complete_sync(prompt: str, system: str | None = None) -> str:
    headers = {"Content-Type": "application/json"}
    if ADMIN_TOKEN:
        headers["X-Admin-Token"] = ADMIN_TOKEN
    body = {"prompt": prompt, "system": system, "max_tokens": 2000, "temperature": 0.1}
    with httpx.Client(timeout=600) as client:
        r = client.post(f"{CLAUDE_CODE_URL}/complete", json=body, headers=headers)
        r.raise_for_status()
        data = r.json()
        return (data.get("text") or "").strip()


def _load_tools() -> List[Dict[str, Any]]:
    if not TOOLS_FILE.exists():
        return []
    try:
        return json.loads(TOOLS_FILE.read_text("utf-8"))
    except Exception:
        return []


def build_server() -> Server:
    setup_logging()
    server = Server("generated-api-mcp")

    for spec in _load_tools():
        name = spec.get("name")
        desc = spec.get("description", "")
        schema = spec.get("inputSchema") or {"type": "object"}
        backend = (spec.get("backend") or "static").lower()

        if backend == "static":
            payload = spec.get("static") or {}

            @server.tool(name=name, description=desc, inputSchema=schema)
            async def _static_tool(**kwargs):  # type: ignore[no-redef]
                content = payload.get("text")
                if content is None and "json" in payload:
                    content = json.dumps(payload.get("json"), indent=2)
                if content is None:
                    content = json.dumps({"inputs": kwargs}, indent=2)
                return [{"type": "text", "text": str(content)}]

        elif backend == "claude":
            c = spec.get("claude") or {}
            tpl = c.get("template") or c.get("prompt_template") or "{{ inputs | tojson }}"
            system = c.get("system")
            parse_json = bool(c.get("parse_json"))

            @server.tool(name=name, description=desc, inputSchema=schema)
            async def _claude_tool(**kwargs):  # type: ignore[no-redef]
                prompt = _render_template(tpl, {"inputs": kwargs})
                out = _claude_complete_sync(prompt, system)
                if parse_json:
                    try:
                        data = json.loads(out)
                        out = json.dumps(data, indent=2)
                    except Exception:
                        pass
                return [{"type": "text", "text": out}]

        else:
            # Unknown backend; expose a stub that reports the error so it's visible
            @server.tool(name=name or "invalid_tool", description=desc or "invalid", inputSchema=schema)
            async def _invalid_tool(**kwargs):  # type: ignore[no-redef]
                return [
                    {
                        "type": "text",
                        "text": f"Invalid backend '{backend}' for tool '{name}'.",
                    }
                ]

    return server

