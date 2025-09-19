#!/usr/bin/env python3
"""Test FastMCP HTTP app directly to find correct paths"""

import asyncio
import json
import logging
from mcp_server.tools import server

logging.basicConfig(level=logging.INFO)

async def test_http_app_paths():
    print("=== Testing FastMCP HTTP App Paths ===")
    
    if not hasattr(server, "streamable_http_app"):
        print("❌ No streamable_http_app found")
        return
    
    try:
        http_app = server.streamable_http_app()
        print("✅ Got HTTP app")
        
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
        
        # Test various paths
        test_paths = ["/", "/mcp", "/http", "/api", "/rpc", "/messages", "/mcp/messages"]
        
        for path in test_paths:
            print(f"\n--- Testing HTTP app at '{path}' ---")
            await test_app(http_app, path, "POST", test_message)
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

async def test_app(app, path, method, body):
    try:
        scope = {
            "type": "http",
            "method": method,
            "path": path,
            "headers": [(b"content-type", b"application/json")],
            "query_string": b"",
        }
        
        async def receive():
            return {
                "type": "http.request",
                "body": json.dumps(body).encode(),
                "more_body": False
            }
        
        response_status = None
        response_body = b""
        
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
    asyncio.run(test_http_app_paths())
