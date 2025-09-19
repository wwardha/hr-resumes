#!/usr/bin/env python3
"""Debug FastMCP HTTP app lifespan access"""

import asyncio
from mcp_server.tools import server

async def debug_lifespan():
    print("=== Debugging FastMCP HTTP App Lifespan ===")
    
    try:
        http_app = server.streamable_http_app()
        print(f"✅ HTTP app created: {type(http_app)}")
        
        # Check all attributes
        print(f"\n📋 All attributes:")
        for attr in dir(http_app):
            if not attr.startswith('_'):
                try:
                    val = getattr(http_app, attr)
                    print(f"  {attr}: {type(val)} = {str(val)[:100]}")
                except Exception as e:
                    print(f"  {attr}: <error accessing: {e}>")
        
        # Check for lifespan-related attributes
        lifespan_attrs = [attr for attr in dir(http_app) if 'life' in attr.lower()]
        print(f"\n🔍 Lifespan-related attributes: {lifespan_attrs}")
        
        # Check router attributes
        if hasattr(http_app, 'router'):
            print(f"\n📋 Router attributes:")
            for attr in dir(http_app.router):
                if not attr.startswith('_') and 'life' in attr.lower():
                    try:
                        val = getattr(http_app.router, attr)
                        print(f"  router.{attr}: {type(val)} = {str(val)[:100]}")
                    except Exception as e:
                        print(f"  router.{attr}: <error accessing: {e}>")
        
        # Try different lifespan access patterns
        patterns = [
            'lifespan',
            'lifespan_handler',
            'lifespan_context', 
            'router.lifespan_context',
            '_lifespan',
            'state'
        ]
        
        print(f"\n🧪 Testing lifespan access patterns:")
        for pattern in patterns:
            try:
                if '.' in pattern:
                    obj_path, attr = pattern.split('.', 1)
                    obj = getattr(http_app, obj_path)
                    val = getattr(obj, attr)
                else:
                    val = getattr(http_app, pattern)
                print(f"  ✅ {pattern}: {type(val)} = {str(val)[:100]}")
            except AttributeError:
                print(f"  ❌ {pattern}: not found")
            except Exception as e:
                print(f"  ⚠️ {pattern}: {e}")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(debug_lifespan())
