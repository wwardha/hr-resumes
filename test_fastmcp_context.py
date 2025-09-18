#!/usr/bin/env python3
"""Test FastMCP HTTP app within proper server context"""

import asyncio
import json
from mcp_server.tools import server

async def test_with_server_context():
    print("Testing FastMCP HTTP app with server context...")
    
    try:
        # Check if server has a run method or needs initialization
        print(f"Server type: {type(server)}")
        print(f"Server methods: {[m for m in dir(server) if not m.startswith('_') and callable(getattr(server, m))]}")
        
        # Try to start/initialize the server if needed
        if hasattr(server, 'run'):
            print("Server has run() method")
        if hasattr(server, 'start'):
            print("Server has start() method")
        if hasattr(server, '__aenter__'):
            print("Server supports async context manager")
            
        # Try using the server as async context manager
        try:
            async with server:
                print("✅ Server context manager works")
                http_app = server.streamable_http_app()
                await test_http_in_context(http_app)
        except Exception as ctx_err:
            print(f"❌ Context manager failed: {ctx_err}")
            
            # Try direct initialization
            try:
                print("Trying direct HTTP app test...")
                http_app = server.streamable_http_app()
                
                # Check if HTTP app has any initialization methods
                print(f"HTTP app methods: {[m for m in dir(http_app) if not m.startswith('_')]}")
                
                # Try to call it with minimal scope
                await test_minimal_http(http_app)
                
            except Exception as direct_err:
                print(f"❌ Direct test failed: {direct_err}")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

async def test_http_in_context(http_app):
    print("Testing HTTP app within server context...")
    
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
    
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/mcp",
        "headers": [(b"content-type", b"application/json")],
        "query_string": b"",
    }
    
    response_status = None
    
    async def receive():
        return {
            "type": "http.request",
            "body": json.dumps(test_message).encode(),
            "more_body": False
        }
    
    async def send(message):
        nonlocal response_status
        if message["type"] == "http.response.start":
            response_status = message.get("status", 0)
            print(f"  Status: {response_status}")
    
    await http_app(scope, receive, send)

async def test_minimal_http(http_app):
    print("Testing with minimal HTTP scope...")
    
    # Try the simplest possible request
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/mcp",
        "headers": [],
        "query_string": b"",
    }
    
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}
    
    async def send(message):
        print(f"  Response: {message}")
    
    try:
        await http_app(scope, receive, send)
        print("✅ Minimal HTTP test succeeded")
    except Exception as e:
        print(f"❌ Minimal HTTP test failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_with_server_context())
