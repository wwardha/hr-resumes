#!/usr/bin/env python3
"""Test FastMCP server async methods"""

import asyncio
import json
from mcp_server.tools import server

async def test_async_methods():
    print("Testing FastMCP server async methods...")
    
    try:
        print(f"Server type: {type(server)}")
        
        # Check all methods that might be async versions
        methods = [m for m in dir(server) if not m.startswith('_')]
        print(f"Available methods: {methods}")
        
        # Look for async run methods
        async_methods = [m for m in methods if 'run' in m.lower() or 'start' in m.lower() or 'async' in m.lower()]
        print(f"Potential async methods: {async_methods}")
        
        # Check if there's a run_async or similar method
        if hasattr(server, 'run_stdio_async'):
            print("✅ Found run_stdio_async method")
            try:
                # Try to call it directly
                print("Attempting to call run_stdio_async...")
                task = asyncio.create_task(server.run_stdio_async())
                
                # Give it a moment to initialize
                await asyncio.sleep(0.1)
                
                # Now try to get the HTTP app
                http_app = server.streamable_http_app()
                print("✅ HTTP app created after run_stdio_async")
                
                # Test the HTTP app
                await test_http_app(http_app)
                
                # Cancel the task
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                    
            except Exception as e:
                print(f"❌ run_stdio_async failed: {e}")
        
        # Try other potential methods
        for method_name in ['start', 'initialize', 'setup']:
            if hasattr(server, method_name):
                print(f"✅ Found {method_name} method")
                try:
                    method = getattr(server, method_name)
                    if asyncio.iscoroutinefunction(method):
                        await method()
                        print(f"✅ Called async {method_name}")
                    else:
                        method()
                        print(f"✅ Called sync {method_name}")
                except Exception as e:
                    print(f"❌ {method_name} failed: {e}")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

async def test_http_app(http_app):
    print("Testing HTTP app...")
    
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
    
    try:
        await http_app(scope, receive, send)
        print(f"  Status: {response_status}")
        if response_status == 200:
            print("  ✅ HTTP app works!")
        else:
            print(f"  ❌ HTTP app returned {response_status}")
    except Exception as e:
        print(f"  ❌ HTTP app failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_async_methods())
