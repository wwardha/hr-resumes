#!/usr/bin/env python3
"""Test FastMCP HTTP app with different methods"""

import asyncio
import json
from mcp_server.tools import server

async def test_http_methods():
    print("Testing FastMCP HTTP app with different methods...")
    
    try:
        http_app = server.streamable_http_app()
        
        # Test message
        test_message = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1.0"}
            }
        }
        
        # Test different HTTP methods
        methods = ["GET", "POST", "PUT", "PATCH", "OPTIONS"]
        
        for method in methods:
            print(f"\n--- Testing {method} /mcp ---")
            await test_method(http_app, "/mcp", method, test_message if method != "GET" else None)
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

async def test_method(app, path, method, body):
    try:
        scope = {
            "type": "http",
            "method": method,
            "path": path,
            "headers": [(b"content-type", b"application/json")] if body else [],
            "query_string": b"",
        }
        
        response_status = None
        response_body = b""
        
        async def receive():
            if body:
                return {
                    "type": "http.request",
                    "body": json.dumps(body).encode(),
                    "more_body": False
                }
            else:
                return {"type": "http.request", "body": b"", "more_body": False}
        
        async def send(message):
            nonlocal response_status, response_body
            if message["type"] == "http.response.start":
                response_status = message.get("status", 0)
            elif message["type"] == "http.response.body":
                response_body += message.get("body", b"")
        
        await app(scope, receive, send)
        
        print(f"  Status: {response_status}")
        if response_status == 200:
            print("  ✅ Success!")
            if response_body:
                try:
                    decoded = response_body.decode()[:200]
                    print(f"  Response: {decoded}...")
                except:
                    print(f"  Response: {len(response_body)} bytes")
        elif response_status == 405:
            print("  ⚠️  Method Not Allowed")
        else:
            print(f"  ❌ Failed")
            if response_body:
                try:
                    decoded = response_body.decode()[:100]
                    print(f"  Error: {decoded}")
                except:
                    pass
        
    except Exception as e:
        print(f"  ❌ Exception: {e}")

if __name__ == "__main__":
    asyncio.run(test_http_methods())
