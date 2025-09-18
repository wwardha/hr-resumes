#!/usr/bin/env python3
"""Inspect FastMCP HTTP app routes"""

import asyncio
from mcp_server.tools import server

async def inspect_routes():
    print("Inspecting FastMCP HTTP app routes...")
    
    try:
        http_app = server.streamable_http_app()
        sse_app = server.sse_app()
        
        print(f"\n=== HTTP App ({type(http_app)}) ===")
        if hasattr(http_app, 'routes'):
            print(f"Routes: {len(http_app.routes)}")
            for i, route in enumerate(http_app.routes):
                print(f"  {i}: {route}")
                if hasattr(route, 'path'):
                    print(f"      Path: {route.path}")
                if hasattr(route, 'methods'):
                    print(f"      Methods: {route.methods}")
        else:
            print("No routes attribute found")
        
        if hasattr(http_app, 'router'):
            print(f"Router: {http_app.router}")
            if hasattr(http_app.router, 'routes'):
                print(f"Router routes: {len(http_app.router.routes)}")
                for i, route in enumerate(http_app.router.routes):
                    print(f"  {i}: {route}")
        
        print(f"\n=== SSE App ({type(sse_app)}) ===")
        if hasattr(sse_app, 'routes'):
            print(f"Routes: {len(sse_app.routes)}")
            for i, route in enumerate(sse_app.routes):
                print(f"  {i}: {route}")
                if hasattr(route, 'path'):
                    print(f"      Path: {route.path}")
                if hasattr(route, 'methods'):
                    print(f"      Methods: {route.methods}")
        
        print(f"\n=== App Attributes ===")
        print(f"HTTP app dir: {[attr for attr in dir(http_app) if not attr.startswith('_')]}")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(inspect_routes())
