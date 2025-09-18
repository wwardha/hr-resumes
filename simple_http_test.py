#!/usr/bin/env python3
"""Simple test for FastMCP HTTP app"""

import asyncio
from mcp_server.tools import server

async def simple_test():
    print("Testing FastMCP HTTP app...")
    
    if hasattr(server, "streamable_http_app"):
        print("✅ streamable_http_app exists")
        try:
            http_app = server.streamable_http_app()
            print(f"✅ HTTP app created: {type(http_app)}")
            print(f"HTTP app: {http_app}")
        except Exception as e:
            print(f"❌ Error creating HTTP app: {e}")
    else:
        print("❌ No streamable_http_app")
    
    if hasattr(server, "sse_app"):
        print("✅ sse_app exists")
        try:
            sse_app = server.sse_app()
            print(f"✅ SSE app created: {type(sse_app)}")
        except Exception as e:
            print(f"❌ Error creating SSE app: {e}")
    else:
        print("❌ No sse_app")

if __name__ == "__main__":
    asyncio.run(simple_test())
