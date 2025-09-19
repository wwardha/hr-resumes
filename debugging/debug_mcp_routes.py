#!/usr/bin/env python3
"""Debug script to inspect FastMCP HTTP app routes and behavior"""

import asyncio
import json
from mcp_server.tools import server

async def debug_mcp_routes():
    print("=== Debugging FastMCP HTTP App Routes ===")
    
    try:
        # Get the HTTP app
        http_app = server.streamable_http_app()
        print(f"✅ HTTP app created: {type(http_app)}")
        
        # Try to inspect the app's routes if it's a Starlette/FastAPI app
        if hasattr(http_app, 'routes'):
            print(f"\n📋 HTTP app routes ({len(http_app.routes)} total):")
            for i, route in enumerate(http_app.routes):
                print(f"  {i+1}. {route}")
                if hasattr(route, 'path'):
                    print(f"     Path: {route.path}")
                if hasattr(route, 'methods'):
                    print(f"     Methods: {route.methods}")
        elif hasattr(http_app, 'router') and hasattr(http_app.router, 'routes'):
            print(f"\n📋 HTTP app router routes ({len(http_app.router.routes)} total):")
            for i, route in enumerate(http_app.router.routes):
                print(f"  {i+1}. {route}")
                if hasattr(route, 'path'):
                    print(f"     Path: {route.path}")
                if hasattr(route, 'methods'):
                    print(f"     Methods: {route.methods}")
        else:
            print("\n⚠️ Cannot inspect routes - not a Starlette app")
            
        # Test different paths and methods
        test_cases = [
            ("GET", "/"),
            ("POST", "/"),
            ("GET", "/docs"), 
            ("POST", "/initialize"),
            ("POST", "/tools/list"),
        ]
        
        print(f"\n🧪 Testing HTTP app directly:")
        for method, path in test_cases:
            print(f"\n--- Testing {method} {path} ---")
            await test_http_app_direct(http_app, method, path)
            
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

async def test_http_app_direct(app, method, path):
    """Test the HTTP app directly with different methods and paths"""
    
    test_body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "debug", "version": "1.0"}
        }
    }
    
    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "headers": [
            (b"content-type", b"application/json"),
            (b"user-agent", b"debug-script"),
        ],
        "query_string": b"",
        "root_path": "",
    }
    
    response_status = None
    response_headers = []
    response_body = b""
    
    async def receive():
        if method in ("POST", "PUT", "PATCH"):
            return {
                "type": "http.request",
                "body": json.dumps(test_body).encode(),
                "more_body": False
            }
        else:
            return {"type": "http.request", "body": b"", "more_body": False}
    
    async def send(message):
        nonlocal response_status, response_headers, response_body
        if message["type"] == "http.response.start":
            response_status = message.get("status", 0)
            response_headers = message.get("headers", [])
        elif message["type"] == "http.response.body":
            response_body += message.get("body", b"")
    
    try:
        await app(scope, receive, send)
        print(f"  Status: {response_status}")
        
        if response_status == 200:
            print("  ✅ Success!")
            if response_body:
                try:
                    decoded = response_body.decode()[:300]
                    print(f"  Response: {decoded}...")
                except:
                    print(f"  Response: {len(response_body)} bytes")
        elif response_status == 404:
            print("  ❌ 404 Not Found")
        elif response_status == 405:
            print("  ⚠️ 405 Method Not Allowed")
        else:
            print(f"  ⚠️ Status {response_status}")
            
        if response_headers:
            print(f"  Headers: {dict(response_headers)}")
            
    except Exception as e:
        print(f"  ❌ Exception: {e}")

if __name__ == "__main__":
    asyncio.run(debug_mcp_routes())
