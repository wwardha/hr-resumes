#!/usr/bin/env python3
"""Test FastMCP HTTP app with /mcp path"""

import asyncio
import json
from mcp_server.tools import server

async def test_mcp_path():
    print("=== Testing FastMCP HTTP App with /mcp path ===")
    
    http_app = server.streamable_http_app()
    
    test_body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/list",
        "params": {}
    }
    
    # Test with /mcp path (what the route expects)
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/mcp",  # ✅ Using /mcp instead of /
        "headers": [(b"content-type", b"application/json")],
        "query_string": b"",
    }
    
    response_status = None
    response_body = b""
    
    async def receive():
        return {
            "type": "http.request",
            "body": json.dumps(test_body).encode(),
            "more_body": False
        }
    
    async def send(message):
        nonlocal response_status, response_body
        if message["type"] == "http.response.start":
            response_status = message.get("status", 0)
        elif message["type"] == "http.response.body":
            response_body += message.get("body", b"")
    
    await http_app(scope, receive, send)
    
    print(f"Status: {response_status}")
    if response_status == 200:
        print("✅ SUCCESS! HTTP app works with /mcp path")
        if response_body:
            try:
                decoded = response_body.decode()
                print(f"Response: {decoded}")
            except:
                print(f"Response: {len(response_body)} bytes")
    else:
        print(f"❌ Still failed with status {response_status}")

if __name__ == "__main__":
    asyncio.run(test_mcp_path())
