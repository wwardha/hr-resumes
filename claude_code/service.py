from fastapi import FastAPI, HTTPException, Body, Header
from pydantic import BaseModel, Field
from typing import Dict, List, Optional
from pathlib import Path
import json, os, subprocess, time, shlex, logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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
    logger.info(f"_call_cli called with max_tokens={max_tokens}, temperature={temperature}")
    
    if system:
        prompt = f"[SYSTEM]\n{system}\n[/SYSTEM]\n\n{prompt}"
        logger.info(f"System prompt added, total prompt length: {len(prompt)} chars")
    
    cmd = [
        CLAUDE_CLI_PATH,
        "-p",
        "--output-format",
        "json",
    ]
    
    logger.info(f"Executing Claude CLI command: {' '.join(cmd)}")
    logger.info(f"Input prompt preview: {prompt[:200]}..." if len(prompt) > 200 else f"Input prompt: {prompt}")
    
    try:
        # Use Popen for streaming to monitor progress in real-time
        logger.info("Starting Claude CLI with streaming...")
        proc = subprocess.Popen(
            cmd, 
            stdin=subprocess.PIPE, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE,
            text=True
        )
        
        # Send input and close stdin
        stdout_data, stderr_data = proc.communicate(input=prompt, timeout=120)
        
        logger.info(f"Claude CLI finished with return code: {proc.returncode}")
        logger.info(f"stdout length: {len(stdout_data or '')} chars")
        logger.info(f"stderr length: {len(stderr_data or '')} chars")
        
        if stdout_data:
            logger.info(f"stdout preview: {(stdout_data[:500] + '...') if len(stdout_data) > 500 else stdout_data}")
        if stderr_data:
            logger.warning(f"stderr content: {stderr_data}")
            
        if proc.returncode != 0:
            logger.error(f"Claude CLI failed with exit code {proc.returncode}")
            logger.error(f"Full stderr: {stderr_data}")
            raise HTTPException(status_code=500, detail=f"claude CLI failed: {stderr_data[-2000:] if stderr_data else 'Unknown error'}")
        
        # Set the output for further processing
        proc.stdout = stdout_data
        proc.stderr = stderr_data
        
        out = (proc.stdout or "").strip()
        logger.info(f"Processing output, length: {len(out)} chars")
        
        try:
            # Parse the outer wrapper JSON from Claude CLI
            cli_response = json.loads(out)
            logger.info(f"Successfully parsed CLI wrapper JSON, keys: {list(cli_response.keys()) if isinstance(cli_response, dict) else 'not dict'}")
            
            # Extract the actual result content
            if isinstance(cli_response, dict) and "result" in cli_response:
                result_content = cli_response["result"]
                logger.info(f"Extracted result field, type: {type(result_content)}, length: {len(str(result_content))}")
                
                # If result is a string, try to parse it as JSON
                if isinstance(result_content, str):
                    try:
                        # Strip markdown code fences if present
                        cleaned_result = result_content.strip()
                        if cleaned_result.startswith('```json\n'):
                            cleaned_result = cleaned_result[8:]  # Remove ```json\n
                        elif cleaned_result.startswith('```\n'):
                            cleaned_result = cleaned_result[4:]  # Remove ```\n
                        if cleaned_result.endswith('\n```'):
                            cleaned_result = cleaned_result[:-4]  # Remove \n```
                        elif cleaned_result.endswith('```'):
                            cleaned_result = cleaned_result[:-3]  # Remove ```
                        
                        logger.info(f"Cleaned result for JSON parsing, length: {len(cleaned_result)}")
                        data = json.loads(cleaned_result)
                        logger.info(f"Successfully parsed result JSON, keys: {list(data.keys()) if isinstance(data, dict) else 'not dict'}")
                    except json.JSONDecodeError as json_err:
                        logger.warning(f"Result field is not valid JSON after cleaning: {json_err}")
                        data = {"text": result_content}
                else:
                    # Result is already parsed JSON
                    data = result_content
                    logger.info(f"Result field is already parsed JSON")
            else:
                # Fallback to original parsing logic
                logger.info("No 'result' field found, using original parsing logic")
                data = cli_response
                
            # Extract text content from the parsed data
            text = (
                data.get("text")
                or data.get("output") 
                or data.get("content")
                or data.get("message")
                or data.get("completion")
            )
            
            # If no text field found, return the entire data as JSON string
            if text is None:
                result = json.dumps(data, indent=2)
                logger.info(f"No text field found, returning full JSON structure, length: {len(result)} chars")
            else:
                result = str(text).strip()
                logger.info(f"Extracted text result, length: {len(result)} chars")
                
            return result
        except Exception as e:
            logger.warning(f"Failed to parse JSON output: {str(e)}")
            logger.info(f"Returning raw output instead")
            return out
    except Exception as e:
        logger.error(f"Exception during Claude CLI execution: {str(e)}")
        raise


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
    
    # Step 1: Ask Claude to create a TODO list and return immediate feedback
    logger.info("=== BRIEF TOOL STARTED ===")
    logger.info("Step 1: Creating TODO list for the task")
    
    todo_system = (
        "You are a project planner. Create a TODO list for building a FastAPI project.\n"
        "Respond with ONLY a JSON object: {\"todos\": [\"task1\", \"task2\", \"task3\"]}\n"
        "Keep tasks small and specific. Maximum 5 tasks.\n"
        "Include: analyze requirements, create main app, add health endpoint, define packages."
    )
    todo_prompt = f"Create a TODO list for: {req.brief}\nReturn JSON with todos array."
    
    # Create TODO list with 15-minute timeout
    try:
        logger.info("🚀 Starting TODO list creation (15 min timeout)...")
        todo_text = _call_cli_with_long_timeout(todo_prompt, system=todo_system, max_tokens=1000, temperature=0.1)
        todo_data = json.loads(todo_text)
        todos = todo_data.get("todos", [])
        logger.info(f"✅ TODO list created successfully: {len(todos)} items")
        logger.info(f"📋 TODO LIST: {todos}")
        
        # Log temporary result for client visibility
        logger.info(f"🔄 TEMPORARY RESULT: Created {len(todos)} TODO items - Brief tool still processing...")
        
    except Exception as e:
        logger.error(f"❌ Failed to create TODO list: {e}")
        todos = [
            "Analyze the brief requirements",
            "Create FastAPI app structure", 
            "Add health endpoint",
            "Define required packages",
            "Generate final response"
        ]
        logger.info(f"📋 Using fallback TODO list: {len(todos)} items")
    
    # Step 2: Execute each TODO item with separate subprocess calls
    results = {"packages": [], "files": {}, "notes": ""}
    all_notes = []
    
    logger.info(f"🔄 STARTING TODO EXECUTION: {len(todos)} items to process")
    
    for i, todo in enumerate(todos, 1):
        logger.info(f"=== TODO {i}/{len(todos)} STARTED ===")
        logger.info(f"📝 Current task: {todo}")
        
        execution_system = (
            "You are a code executor. Complete ONE specific task for a FastAPI project.\n"
            "Respond with ONLY JSON: {\"packages\": [], \"files\": {\"path\": \"content\"}, \"notes\": \"what I did\"}\n"
            "Be specific and focused. Complete only the requested task.\n"
            "Main app must be at 'generated_api/app.py' if creating files.\n"
            "Keep response concise and focused."
        )
        
        execution_prompt = (
            f"Complete this specific task: {todo}\n"
            f"Project brief: {req.brief}\n"
            f"Current progress: Completed {i-1}/{len(todos)} tasks\n"
            f"Previous files: {list(results['files'].keys())}\n"
            "Return JSON with your contribution."
        )
        
        try:
            logger.info(f"🚀 Starting TODO {i} execution (15 min timeout)...")
            step_text = _call_cli_with_long_timeout(execution_prompt, system=execution_system, max_tokens=2000, temperature=0.1)
            step_data = json.loads(step_text)
            
            # Merge results
            step_packages = step_data.get("packages", [])
            step_files = step_data.get("files", {})
            step_notes = step_data.get("notes", "")
            
            # Add unique packages
            for pkg in step_packages:
                if pkg not in results["packages"]:
                    results["packages"].append(pkg)
            
            # Add/update files
            results["files"].update(step_files)
            
            # Collect notes
            if step_notes:
                all_notes.append(f"Step {i}: {step_notes}")
            
            logger.info(f"✅ TODO {i}/{len(todos)} COMPLETED")
            logger.info(f"📦 Added {len(step_packages)} packages, {len(step_files)} files")
            logger.info(f"🔄 TEMPORARY RESULT: Completed {i}/{len(todos)} TODOs - Brief tool still processing...")
            
        except Exception as e:
            logger.error(f"❌ TODO {i}/{len(todos)} FAILED: {str(e)}")
            all_notes.append(f"Step {i}: Failed - {str(e)}")
            logger.info(f"🔄 TEMPORARY RESULT: TODO {i} failed, continuing with remaining {len(todos)-i} items...")
    
    # Step 3: Finalize and return complete result
    logger.info("=== FINALIZING RESULTS ===")
    results["notes"] = "; ".join(all_notes)
    
    if "generated_api/app.py" not in results["files"]:
        logger.warning("No app.py generated, creating minimal one")
        results["files"]["generated_api/app.py"] = (
            "from fastapi import FastAPI\n\n"
            "app = FastAPI()\n\n"
            "@app.get('/health')\n"
            "def health():\n"
            "    return {'status': 'ok'}\n"
        )
        if "fastapi" not in results["packages"]:
            results["packages"].append("fastapi")
        if "uvicorn" not in results["packages"]:
            results["packages"].append("uvicorn")
    
    # Handle file writing and response
    packages = results["packages"]
    files = results["files"]
    
    # Handle both file formats: dict or list of objects
    files_data = files
    if isinstance(files_data, dict):
        files = files_data
        logger.info(f"Files in dict format, {len(files)} files found")
    elif isinstance(files_data, list):
        files = {f["path"]: f["content"] for f in files_data}
        logger.info(f"Files in list format, {len(files)} files found")
    else:
        files = {}
        logger.warning(f"Unexpected files format: {type(files_data)}")
    
    written = _write_files(files)
    pip_res = _pip_install(packages) if (req.install and packages) else ""

    (GENERATED / "__reload__.txt").write_text(str(time.time()), "utf-8")

    response = {"written": written, "packages": packages, "notes": results["notes"]}
    if req.return_plan:
        response["plan"] = results
    if pip_res:
        response["pip"] = pip_res
        
    logger.info(f"✅ BRIEF TOOL COMPLETED: {len(todos)} TODO items processed")
    logger.info("=== BRIEF TOOL FINISHED ===")
    return response


def _call_cli_with_long_timeout(prompt: str, system: Optional[str], max_tokens: int, temperature: float) -> str:
    """Call CLI with 15-minute timeout for long-running tasks"""
    logger.info(f"_call_cli_with_long_timeout called with max_tokens={max_tokens}, temperature={temperature}")
    
    if system:
        prompt = f"[SYSTEM]\n{system}\n[/SYSTEM]\n\n{prompt}"
        logger.info(f"System prompt added, total prompt length: {len(prompt)} chars")
    
    cmd = [
        CLAUDE_CLI_PATH,
        "-p",
        "--output-format",
        "json",
    ]
    
    logger.info(f"Executing Claude CLI command: {' '.join(cmd)}")
    logger.info(f"Input prompt preview: {prompt[:200]}..." if len(prompt) > 200 else f"Input prompt: {prompt}")
    
    try:
        logger.info("Starting Claude CLI subprocess (15 minute timeout)...")
        proc = subprocess.Popen(
            cmd, 
            stdin=subprocess.PIPE, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE,
            text=True
        )
        
        # 15 minute timeout = 900 seconds
        try:
            stdout_data, stderr_data = proc.communicate(input=prompt, timeout=900)
        except subprocess.TimeoutExpired:
            logger.error("Claude CLI timed out after 15 minutes")
            proc.kill()
            raise HTTPException(status_code=500, detail="Claude CLI timed out after 15 minutes")
        
        logger.info(f"Claude CLI finished with return code: {proc.returncode}")
        logger.info(f"stdout length: {len(stdout_data or '')} chars")
        logger.info(f"stderr length: {len(stderr_data or '')} chars")
        
        if stdout_data:
            logger.info(f"stdout preview: {(stdout_data[:500] + '...') if len(stdout_data) > 500 else stdout_data}")
        if stderr_data:
            logger.warning(f"stderr content: {stderr_data}")
            
        if proc.returncode != 0:
            logger.error(f"Claude CLI failed with exit code {proc.returncode}")
            logger.error(f"Full stderr: {stderr_data}")
            raise HTTPException(status_code=500, detail=f"claude CLI failed: {stderr_data[-2000:] if stderr_data else 'Unknown error'}")
        
        # Process the output using existing parsing logic
        out = (stdout_data or "").strip()
        logger.info(f"Processing output, length: {len(out)} chars")
        
        try:
            # Parse the outer wrapper JSON from Claude CLI
            cli_response = json.loads(out)
            logger.info(f"Successfully parsed CLI wrapper JSON, keys: {list(cli_response.keys()) if isinstance(cli_response, dict) else 'not dict'}")
            
            # Extract the actual result content
            if isinstance(cli_response, dict) and "result" in cli_response:
                result_content = cli_response["result"]
                logger.info(f"Extracted result field, type: {type(result_content)}, length: {len(str(result_content))}")
                
                # If result is a string, try to parse it as JSON
                if isinstance(result_content, str):
                    try:
                        # Strip markdown code fences if present
                        cleaned_result = result_content.strip()
                        if cleaned_result.startswith('```json\n'):
                            cleaned_result = cleaned_result[8:]  # Remove ```json\n
                        elif cleaned_result.startswith('```\n'):
                            cleaned_result = cleaned_result[4:]  # Remove ```\n
                        if cleaned_result.endswith('\n```'):
                            cleaned_result = cleaned_result[:-4]  # Remove \n```
                        elif cleaned_result.endswith('```'):
                            cleaned_result = cleaned_result[:-3]  # Remove ```
                        
                        logger.info(f"Cleaned result for JSON parsing, length: {len(cleaned_result)}")
                        data = json.loads(cleaned_result)
                        logger.info(f"Successfully parsed result JSON, keys: {list(data.keys()) if isinstance(data, dict) else 'not dict'}")
                    except json.JSONDecodeError as json_err:
                        logger.warning(f"Result field is not valid JSON after cleaning: {json_err}")
                        data = {"text": result_content}
                else:
                    # Result is already parsed JSON
                    data = result_content
                    logger.info(f"Result field is already parsed JSON")
            else:
                # Fallback to original parsing logic
                logger.info("No 'result' field found, using original parsing logic")
                data = cli_response
                
            # Extract text content from the parsed data
            text = (
                data.get("text")
                or data.get("output") 
                or data.get("content")
                or data.get("message")
                or data.get("completion")
            )
            
            # If no text field found, return the entire data as JSON string
            if text is None:
                result = json.dumps(data, indent=2)
                logger.info(f"No text field found, returning full JSON structure, length: {len(result)} chars")
            else:
                result = str(text).strip()
                logger.info(f"Extracted text result, length: {len(result)} chars")
                
            return result
        except Exception as e:
            logger.warning(f"Failed to parse JSON output: {str(e)}")
            logger.info(f"Returning raw output instead")
            return out
            
    except Exception as e:
        logger.error(f"Exception during Claude CLI execution: {str(e)}")
        raise


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
