from __future__ import annotations

from fastapi import APIRouter


def create_minimal_mcp_router(_server) -> APIRouter:  # _server kept for signature parity
    router = APIRouter()

    @router.get("/")
    async def info_root():
        return {
            "ok": True,
            "message": "MCP FastAPI adapter not installed; minimal /mcp stub active.",
            "capabilities": [],
        }

    @router.get("/health")
    async def health():
        return {"ok": True}

    return router

