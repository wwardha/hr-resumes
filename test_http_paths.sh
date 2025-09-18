#!/bin/bash

echo "Testing different paths for FastMCP HTTP app..."
echo

# Test various paths to see what the HTTP app responds to
paths=("/" "/mcp" "/http" "/api" "/rpc")

for path in "${paths[@]}"; do
    echo "Testing POST $path:"
    docker exec hr-resumes-mcp curl -s -X POST \
        -H "Content-Type: application/json" \
        -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}' \
        -w "Status: %{http_code}\n" \
        "http://localhost:8000$path" | head -2
    echo
done

echo "Done!"
