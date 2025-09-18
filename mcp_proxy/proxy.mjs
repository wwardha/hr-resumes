#!/usr/bin/env node
// Minimal stdio→HTTP MCP proxy for Claude Desktop.
// - Exposes a stdio MCP server locally (for Claude Desktop "command").
// - Bridges all tools to a remote HTTP/SSE MCP server.
//
// Env vars:
//   MCP_REMOTE_URL  (e.g. https://hr-resumes-mcp.your-domain/mcp/sse)
//   MCP_TOKEN       (Bearer token for remote /mcp)
//
// Usage (manual):
//   MCP_REMOTE_URL=... MCP_TOKEN=... node proxy.mjs
//
// Claude Desktop config example (Windows paths escaped):
// {
//   "mcpServers": {
//     "hr-resumes-proxy": {
//       "command": "node",
//       "args": ["C:\\path\\to\\repo\\hr-resumes\\mcp_proxy\\proxy.mjs"],
//       "env": {
//         "MCP_REMOTE_URL": "https://hr-resumes-mcp.<your-domain>/mcp/sse",
//         "MCP_TOKEN": "<your-mcp-token>"
//       }
//     }
//   }
// }

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { SSEClientTransport } from "@modelcontextprotocol/sdk/client/sse.js";
import EventSource from "eventsource";

// Polyfill EventSource for Node.js so the SDK's SSE transport works.
if (!globalThis.EventSource) {
  globalThis.EventSource = EventSource;
}

// Allow either env vars or CLI args: node proxy.mjs <REMOTE_URL> <TOKEN>
const REMOTE_URL = process.env.MCP_REMOTE_URL || process.argv[2];
const MCP_TOKEN = process.env.MCP_TOKEN || process.argv[3];

if (!REMOTE_URL || typeof REMOTE_URL !== "string" || !REMOTE_URL.startsWith("http")) {
  console.error("MCP_REMOTE_URL is required (e.g., https://host/mcp/sse). You can set it via env or first arg.");
  process.exit(2);
}

// Connect to remote HTTP MCP first to fetch tools/capabilities
async function connectRemote() {
  const headers = {};
  if (MCP_TOKEN) headers["Authorization"] = `Bearer ${MCP_TOKEN}`;

  // The JS SDK expects client capabilities in the constructor options.
  const client = new Client(
    { name: "hr-resumes-proxy-client", version: "1.0.0" },
    { capabilities: {} }
  );

  console.error(`[proxy] Connecting to ${REMOTE_URL} ...`);
  const transport = new SSEClientTransport(REMOTE_URL, { headers });
  await client.connect(transport);

  // Initialize remote and fetch tools list
  const remoteInfo = await client.initialize();
  const tools = await client.listTools();
  return { client, remoteInfo, tools };
}

// Start local stdio MCP server and forward calls
async function main() {
  const { client, remoteInfo, tools } = await connectRemote();

  const server = new Server(
    { name: "hr-resumes-stdio-proxy", version: "1.0.0" },
    // Mirror remote capabilities where reasonable; ensure tools are enabled
    { capabilities: { tools: {} } }
  );

  // Register each remote tool locally and forward calls
  for (const t of tools.tools || []) {
    const name = t.name;
    const description = t.description || "(proxied tool)";
    const inputSchema = t.inputSchema || { type: "object" };

    server.tool(
      { name, description, inputSchema },
      async (args) => {
        const result = await client.callTool(name, args ?? {});
        // result.content is already in MCP message format
        return result.content;
      }
    );
  }

  // Optional: light bridging for resources/prompts if remote supports them
  if (remoteInfo.capabilities?.resources) {
    server.setRequestHandler("resources/list", async () => {
      return await client.listResources();
    });
    server.setRequestHandler("resources/read", async (req) => {
      return await client.readResource(req);
    });
  }
  if (remoteInfo.capabilities?.prompts) {
    server.setRequestHandler("prompts/list", async () => {
      return await client.listPrompts();
    });
    server.setRequestHandler("prompts/get", async (req) => {
      return await client.getPrompt(req);
    });
  }

  const transport = new StdioServerTransport();
  await server.connect(transport);
}

main().catch((err) => {
  console.error("Proxy crashed:", err?.stack || err);
  process.exit(1);
});
