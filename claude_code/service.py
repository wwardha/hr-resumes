from fastapi import FastAPI, HTTPException, Body, Header
from pydantic import BaseModel, Field
from typing import Dict, List, Optional
from pathlib import Path
import json, os, subprocess, time, shlex


WORKSPACE = Path(os.getenv("WORKSPACE_DIR", "/workspace")).resolve()
GENERATED = Path(os.getenv("GENERATED_DIR", "/workspace/generated_api")).resolve()
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")
CLAUDE_CLI_PATH = os.getenv("CLAUDE_CLI_PATH", "claude")


app = FastAPI(title="Claude Code (local CLI)")


class GenerateReq(BaseModel):
    brief: str
    install: bool = True
    return_plan: bool = True


class ApplyFilesReq(BaseModel):
    files: Dict[str, str]
    install: bool = False
    packages: List[str] = Field(default_factory=list)


class PipReq(BaseModel):
    packages: List[str]


class CompleteReq(BaseModel):
    prompt: str
    system: Optional[str] = None
    max_tokens: int = 1500
    temperature: float = 0.1


class AllowedCmdReq(BaseModel):
    cmd: str


ALLOWED_CMDS = [
    "alembic upgrade head",
    "alembic downgrade -1",
    "alembic revision --autogenerate -m ",
    "pytest -q",
]


def _require_admin(x_admin_token: Optional[str]):
    if not ADMIN_TOKEN:
        raise HTTPException(status_code=500, detail="ADMIN_TOKEN not configured")
    if (x_admin_token or "") != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="invalid admin token")


def _safe_rel_path(p: str) -> Path:
    pth = (WORKSPACE / p).resolve()
    if not str(pth).startswith(str(WORKSPACE)):
        raise HTTPException(status_code=400, detail=f"path escapes workspace: {p}")
    return pth


def _write_files(files: Dict[str, str]):
    written = []
    for rel, content in files.items():
        rel = rel.lstrip("/").replace("\\", "/")
        dst = _safe_rel_path(rel)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(content, "utf-8")
        written.append(str(dst))
    return written


def _pip_install(pkgs: List[str]) -> str:
    if not pkgs:
        return "no packages"
    cmd = ["python", "-m", "pip", "install", "--no-cache-dir", *pkgs]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return (
        f"cmd: {' '.join(cmd)}\nexit:{proc.returncode}\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )


def _call_cli(prompt: str, system: Optional[str], max_tokens: int, temperature: float) -> str:
    if system:
        prompt = f"[SYSTEM]\n{system}\n[/SYSTEM]\n\n{prompt}"
    cmd = [
        CLAUDE_CLI_PATH,
        "-y",
        "-p",
        "--output-format",
        "json",
        "--max-tokens",
        str(max_tokens),
        "--temperature",
        str(temperature),
    ]
    proc = subprocess.run(cmd, input=prompt, text=True, capture_output=True)
    if proc.returncode != 0:
        raise HTTPException(status_code=500, detail=f"claude CLI failed: {proc.stderr[-2000:]}")
    out = (proc.stdout or "").strip()
    try:
        data = json.loads(out)
        text = (
            data.get("text")
            or data.get("output")
            or data.get("content")
            or data.get("message")
            or data.get("completion")
        )
        return (text or out).strip()
    except Exception:
        return out


@app.get("/health")
async def health():
    return {"ok": True, "generated": GENERATED.exists()}


@app.get("/list")
async def list_files(x_admin_token: Optional[str] = Header(None)):
    _require_admin(x_admin_token)
    files = []
    for p in GENERATED.rglob("*"):
        if p.is_file():
            files.append(str(p.relative_to(WORKSPACE)))
    return {"files": files}


@app.post("/pip_install")
async def pip_install(req: PipReq, x_admin_token: Optional[str] = Header(None)):
    _require_admin(x_admin_token)
    return {"result": _pip_install(req.packages)}


@app.post("/apply_files")
async def apply_files(req: ApplyFilesReq, x_admin_token: Optional[str] = Header(None)):
    _require_admin(x_admin_token)
    written = _write_files(req.files)
    result = ""
    if req.install and req.packages:
        result = _pip_install(req.packages)
    # trigger reload
    (GENERATED / "__reload__.txt").write_text(str(time.time()), "utf-8")
    return {"written": written, "pip": result}


@app.post("/generate")
async def generate(req: GenerateReq, x_admin_token: Optional[str] = Header(None)):
    _require_admin(x_admin_token)
    system = (
        "You generate a working FastAPI project INSIDE an existing container.\n"
        "Return ONLY JSON (no fences) with keys: packages, files, notes.\n"
        "Main ASGI app at 'generated_api/app.py' exporting app = FastAPI().\n"
        "Create all referenced modules. Include a /health route. Use env vars for secrets."
    )
    user = (
        f"Build/modify a FastAPI app per this brief:\n{req.brief}\n"
        f"Return files under /workspace (relative paths)."
    )

    text = _call_cli(user, system=system, max_tokens=4000, temperature=0.1)
    try:
        plan = json.loads(text)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Model did not return valid JSON:\n{e}\n{text[:1200]}"
        )

    packages = plan.get("packages", [])
    files = {f["path"]: f["content"] for f in plan.get("files", [])}
    if "generated_api/app.py" not in files:
        raise HTTPException(status_code=400, detail="Output must include generated_api/app.py")

    written = _write_files(files)
    pip_res = _pip_install(packages) if (req.install and packages) else ""

    (GENERATED / "__reload__.txt").write_text(str(time.time()), "utf-8")

    res = {"written": written, "packages": packages, "notes": plan.get("notes", "")}
    if req.return_plan:
        res["plan"] = plan
    if pip_res:
        res["pip"] = pip_res
    return res


@app.post("/complete")
async def complete(req: CompleteReq, x_admin_token: Optional[str] = Header(None)):
    _require_admin(x_admin_token)
    out = _call_cli(req.prompt, req.system, req.max_tokens, req.temperature)
    return {"text": out}


@app.post("/run_allowed")
async def run_allowed(req: AllowedCmdReq, x_admin_token: Optional[str] = Header(None)):
    _require_admin(x_admin_token)
    cmd = req.cmd.strip()
    if not any(cmd.startswith(p) for p in ALLOWED_CMDS):
        raise HTTPException(status_code=400, detail=f"Command not allowed: {cmd}")
    # Run through shell to allow quoted args; restricted by prefix allowlist
    proc = subprocess.run(cmd, shell=True, text=True, capture_output=True)
    return {
        "cmd": cmd,
        "exit": proc.returncode,
        "stdout": proc.stdout[-4000:],
        "stderr": proc.stderr[-4000:],
    }
