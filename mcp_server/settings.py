from pydantic import BaseModel, Field
import os
from pathlib import Path


class Settings(BaseModel):
    admin_token: str | None = Field(default=os.getenv("ADMIN_TOKEN"))
    mcp_token: str | None = Field(default=os.getenv("MCP_TOKEN"))

    # Local services
    claude_code_url: str = Field(default=os.getenv("CLAUDE_CODE_URL", "http://127.0.0.1:8300"))

    # Paths
    workspace_dir: Path = Field(default=Path(os.getenv("WORKSPACE_DIR", "/workspace")))
    generated_dir: Path = Field(default=Path(os.getenv("GENERATED_DIR", "/workspace/generated_api")))


settings = Settings()
settings.workspace_dir.mkdir(parents=True, exist_ok=True)
settings.generated_dir.mkdir(parents=True, exist_ok=True)
