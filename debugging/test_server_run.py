#!/usr/bin/env python3
"""Test if FastMCP server needs to be run"""

import asyncio
import json
from mcp_server.tools import server

async def test_server_run():
    print("Testing FastMCP server run...")
    
    try:
        print(f"Server type: {type(server)}")
        
        # Check if server has run method
        if hasattr(server, 'run'):
            print("✅ Server has run() method")
            
            # Try to run the server briefly to initialize it
            print("Attempting to initialize server...")
            
            # Create a task to run the server
            server_task = asyncio.create_task(server.run())
            
            # Give it a moment to initialize
            await asyncio.sleep(0.1)
            
            # Now try to get the HTTP app
            try:
                http_app = server.streamable_http_app()
                print("✅ HTTP app created after server.run()")
                
                # Test the HTTP app
                await test_http_app(http_app)
                
            except Exception as http_err:
                print(f"❌ HTTP app still failed: {http_err}")
            
            # Cancel the server task
            server_task.cancel()
            try:
                await server_task
            except asyncio.CancelledError:
                pass
            
        else:
            print("❌ Server has no run() method")
            
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

async def test_http_app(http_app):
    print("Testing HTTP app after server initialization...")
    
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
    response_body = b""
    
    async def receive():
        return {
            "type": "http.request",
            "body": json.dumps(test_message).encode(),
            "more_body": False
        }
    
    async def send(message):
        nonlocal response_status, response_body
        if message["type"] == "http.response.start":
            response_status = message.get("status", 0)
        elif message["type"] == "http.response.body":
            response_body += message.get("body", b"")
    
    try:
        await http_app(scope, receive, send)
        print(f"  Status: {response_status}")
        if response_status == 200:
            print("  ✅ HTTP app works!")
            if response_body:
                print(f"  Response: {response_body.decode()[:200]}...")
        else:
            print(f"  ❌ HTTP app returned {response_status}")
    except Exception as e:
        print(f"  ❌ HTTP app failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_server_run())
