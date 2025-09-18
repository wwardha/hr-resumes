import os
import logging
from starlette.responses import JSONResponse


TOKEN = os.getenv("MCP_TOKEN", "").strip()


class MCPAuthASGI:
    """Protects /mcp over HTTP, SSE, and WebSocket with a static Bearer token."""

    def __init__(self, app, token: str | None = None):
        self.app = app
        self.token = token or TOKEN

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        typ = scope.get("type", "")
        if path.startswith("/mcp"):
            headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
            supplied = headers.get("authorization", "").removeprefix("Bearer ").strip() \
                or headers.get("x-mcp-token", "")
            if not self.token or supplied != self.token:
                redacted = supplied[:4] + "***" if supplied else "<missing>"
                logging.warning("Unauthorized /mcp request: token mismatch (%s)", redacted)
                if typ == "websocket":
                    await send({"type": "websocket.close", "code": 4401})
                else:
                    await JSONResponse({"detail": "unauthorized"}, status_code=401)(scope, receive, send)
                return
        await self.app(scope, receive, send)
