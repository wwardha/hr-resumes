from mcp.server import Server
from mcp.logging import setup_logging
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field
import httpx, os
from .settings import settings


setup_logging()
server = Server("living-fastapi-mcp")


def _headers():
    h = {"Content-Type": "application/json"}
    if settings.admin_token:
        h["X-Admin-Token"] = settings.admin_token
    return h


class BriefReq(BaseModel):
    brief: str
    install: bool = True
    return_plan: bool = True


class FilesReq(BaseModel):
    files: Dict[str, str]
    install: bool = False
    packages: List[str] = Field(default_factory=list)


class PipReq(BaseModel):
    packages: List[str]


class AllowedCmdReq(BaseModel):
    cmd: str


class RegisterGenMcpToolReq(BaseModel):
    name: str
    description: str
    inputSchema: Dict[str, Any]
    backend: str  # "static" | "claude"
    static: Optional[Dict[str, Any]] = None
    claude: Optional[Dict[str, Any]] = None


@server.tool(
    name="build_from_brief",
    description=(
        "Generate or modify the separate FastAPI app (port 9000) from a natural-language brief. "
        "Writes files under /workspace/generated_api, installs packages if needed, and hot-reloads."
    ),
    inputSchema={
        "type": "object",
        "properties": {"brief": {"type": "string"}},
        "required": ["brief"],
    },
)
async def build_from_brief(brief: str):
    async with httpx.AsyncClient(timeout=600) as client:
        r = await client.post(
            f"{settings.claude_code_url}/generate",
            headers=_headers(),
            json={"brief": brief, "install": True, "return_plan": True},
        )
        return [{"type": "text", "text": r.text}]


@server.tool(
    name="apply_files_to_generated_api",
    description="Write/overwrite specific files in the generated API; optional pip install.",
    inputSchema={
        "type": "object",
        "properties": {
            "files": {"type": "object"},
            "install": {"type": "boolean", "default": False},
            "packages": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["files"],
    },
)
async def apply_files_to_generated_api(
    files: Dict[str, str], install: bool = False, packages: Optional[List[str]] = None
):
    payload = {"files": files, "install": install, "packages": packages or []}
    async with httpx.AsyncClient(timeout=600) as client:
        r = await client.post(
            f"{settings.claude_code_url}/apply_files", headers=_headers(), json=payload
        )
        return [{"type": "text", "text": r.text}]


@server.tool(
    name="pip_install_in_container",
    description="Install extra Python packages inside the container.",
    inputSchema={
        "type": "object",
        "properties": {"packages": {"type": "array", "items": {"type": "string"}}},
        "required": ["packages"],
    },
)
async def pip_install_in_container(packages: List[str]):
    async with httpx.AsyncClient(timeout=1200) as client:
        r = await client.post(
            f"{settings.claude_code_url}/pip_install",
            headers=_headers(),
            json={"packages": packages},
        )
        return [{"type": "text", "text": r.text}]


@server.tool(
    name="run_allowed_command",
    description="Run an allow-listed shell command (e.g., alembic upgrade head).",
    inputSchema={
        "type": "object",
        "properties": {"cmd": {"type": "string"}},
        "required": ["cmd"],
    },
)
async def run_allowed_command(cmd: str):
    async with httpx.AsyncClient(timeout=1200) as client:
        r = await client.post(
            f"{settings.claude_code_url}/run_allowed",
            headers=_headers(),
            json={"cmd": cmd},
        )
        return [{"type": "text", "text": r.text}]


@server.tool(
    name="register_mcp_tool_in_generated_api",
    description="Register a new MCP tool in the Generated API and trigger hot-reload.",
    inputSchema={
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "description": {"type": "string"},
            "inputSchema": {"type": "object"},
            "backend": {"type": "string", "enum": ["static", "claude"]},
            "static": {"type": "object"},
            "claude": {"type": "object"},
        },
        "required": ["name", "description", "inputSchema", "backend"],
    },
)
async def register_mcp_tool_in_generated_api(
    name: str,
    description: str,
    inputSchema: Dict[str, Any],
    backend: str,
    static: Optional[Dict[str, Any]] = None,
    claude: Optional[Dict[str, Any]] = None,
):
    payload = {
        "name": name,
        "description": description,
        "inputSchema": inputSchema,
        "backend": backend,
        "static": static,
        "claude": claude,
    }
    gen_admin = os.getenv(
        "GEN_ADMIN_URL", "http://127.0.0.1:9000/_gen_admin/mcp_tools"
    )
    async with httpx.AsyncClient(timeout=300) as client:
        r = await client.post(gen_admin, headers=_headers(), json=payload)
        return [{"type": "text", "text": r.text}]
