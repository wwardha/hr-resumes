#!/bin/bash

echo "Testing /mcp endpoint with authentication..."
echo

# Get the MCP_TOKEN from environment or use a test token
MCP_TOKEN=${MCP_TOKEN:-"NvcO-MwgjnU0MaklqwHEYYcKbeh8T2F3jfwbEdvB3hM"}

echo "Testing POST /mcp with Bearer token:"
docker exec hr-resumes-mcp curl -s -X POST \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $MCP_TOKEN" \
    -H "X-MCP-Token: $MCP_TOKEN" \
    -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}' \
    -w "\nStatus: %{http_code}\n" \
    "http://localhost:8000/mcp"

echo

echo "Testing POST /mcp/ with Bearer token:"
docker exec hr-resumes-mcp curl -s -X POST \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $MCP_TOKEN" \
    -H "X-MCP-Token: $MCP_TOKEN" \
    -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}' \
    -w "\nStatus: %{http_code}\n" \
    "http://localhost:8000/mcp/"

echo

echo "Done!"
