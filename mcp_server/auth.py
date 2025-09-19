import os
import logging
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware

class MCPAuthMiddleware(BaseHTTPMiddleware):
    """Simple Bearer token authentication for MCP endpoints."""
    
    def __init__(self, app):
        super().__init__(app)
        self.mcp_token = os.getenv("MCP_TOKEN", "dev-token")
        logging.info(f"MCP Bearer auth enabled with token: {self.mcp_token[:8]}...")

    async def dispatch(self, request: Request, call_next):
        # Only protect /mcp paths
        if request.url.path.startswith("/mcp"):
            auth_header = request.headers.get("authorization")
            expected_auth = f"Bearer {self.mcp_token}"
            
            if auth_header != expected_auth:
                logging.warning(f"Unauthorized MCP access: {request.url.path}")
                raise HTTPException(status_code=401, detail="Unauthorized")
        
        return await call_next(request)

# Legacy ASGI wrapper for backward compatibility
class MCPAuthASGI:
    def __init__(self, app):
        from fastapi import FastAPI
        if isinstance(app, FastAPI):
            # Add the middleware to the FastAPI app
            app.add_middleware(MCPAuthMiddleware)
            self.app = app
        else:
            # Wrap non-FastAPI ASGI apps
            self.app = app
            self.mcp_token = os.getenv("MCP_TOKEN", "dev-token")

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope.get("path", "").startswith("/mcp"):
            # Check authorization for MCP paths
            headers = dict(scope.get("headers", []))
            auth_header = headers.get(b"authorization", b"").decode()
            expected_auth = f"Bearer {self.mcp_token}"
            
            if auth_header != expected_auth:
                # Send 401 Unauthorized
                await send({
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [[b"content-type", b"application/json"]],
                })
                await send({
                    "type": "http.response.body",
                    "body": b'{"detail":"Unauthorized"}',
                })
                return
        
        await self.app(scope, receive, send)
