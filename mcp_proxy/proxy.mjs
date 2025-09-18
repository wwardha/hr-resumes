#!/usr/bin/env node
// Minimal stdio→HTTP MCP proxy for Claude Desktop.
// Prefers Streamable HTTP (/mcp) and falls back to SSE when necessary.
//
// Env vars:
//   MCP_REMOTE_URL            (e.g. https://hr-resumes-mcp.your-domain/mcp)
//   MCP_REMOTE_BEARER         (optional Bearer token for remote /mcp)
//   MCP_REMOTE_HEADERS_JSON   (optional JSON object of extra headers)
//   MCP_TOKEN                 (legacy Bearer token env; still supported)
//
// Usage (manual):
//   MCP_REMOTE_URL=... node proxy.mjs
//   node proxy.mjs https://host/mcp  # URL can also be passed as first arg
//
// Claude Desktop config example (Windows paths escaped):
// {
//   "mcpServers": {
//     "hr-resumes-proxy": {
//       "command": "node",
//       "args": ["C:\\path\\to\\repo\\hr-resumes\\mcp_proxy\\proxy.mjs"],
//       "env": {
//         "MCP_REMOTE_URL": "https://hr-resumes-mcp.<your-domain>/mcp",
//         "MCP_REMOTE_BEARER": "<your-mcp-token>"
//       }
//     }
//   }
// }

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  ListToolsRequestSchema,
  CallToolRequestSchema,
  ListResourcesRequestSchema,
  ReadResourceRequestSchema,
  ListPromptsRequestSchema,
  GetPromptRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";

import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";
import { SSEClientTransport } from "@modelcontextprotocol/sdk/client/sse.js";

function headersFromEnv() {
  const headers = {};
  const bearer = process.env.MCP_REMOTE_BEARER || process.env.MCP_TOKEN;
  if (bearer) {
    headers["Authorization"] = `Bearer ${bearer}`;
  }
  const extra = process.env.MCP_REMOTE_HEADERS_JSON;
  if (extra) {
    try {
      Object.assign(headers, JSON.parse(extra));
    } catch (err) {
      console.error("[proxy] Failed to parse MCP_REMOTE_HEADERS_JSON:", err);
      process.exit(1);
    }
  }
  return headers;
}

const argvUrl = process.argv
  .slice(2)
  .find((arg) => typeof arg === "string" && arg.length && !arg.startsWith("-"));

const remoteUrl = process.env.MCP_REMOTE_URL || argvUrl;
if (!remoteUrl) {
  console.error(
    "MCP_REMOTE_URL is required (e.g. https://host/mcp). Set it via env or pass as the first non-flag argument."
  );
  process.exit(1);
}

if (argvUrl && argvUrl !== remoteUrl) {
  console.error(`[proxy] Ignoring CLI flag; using MCP_REMOTE_URL from env: ${remoteUrl}`);
}

const client = new Client({ name: "hr-resumes-proxy-client", version: "1.1.0" });
const headers = headersFromEnv();

async function connectClient() {
  try {
    const shttp = new StreamableHTTPClientTransport(new URL(remoteUrl), { headers });
    await client.connect(shttp);
    console.error(`[proxy] Connected to ${remoteUrl} via Streamable HTTP`);
  } catch (err) {
    console.error("[proxy] Streamable HTTP failed, falling back to SSE:", err?.message || err);
    const sse = new SSEClientTransport(new URL(remoteUrl), { headers });
    await client.connect(sse);
    console.error(`[proxy] Connected to ${remoteUrl} via SSE`);
  }
}

await connectClient();

const server = new Server(
  { name: "hr-resumes-stdio-proxy", version: "1.1.0" },
  { capabilities: { tools: {}, resources: {}, prompts: {} } }
);

// ---- TOOLS ----
server.setRequestHandler(ListToolsRequestSchema, async () => {
  return await client.listTools();
});

server.setRequestHandler(CallToolRequestSchema, async (req) => {
  return await client.callTool(req.params);
});

// ---- RESOURCES ----
server.setRequestHandler(ListResourcesRequestSchema, async () => {
  return await client.listResources();
});

server.setRequestHandler(ReadResourceRequestSchema, async (req) => {
  return await client.readResource(req.params);
});

// ---- PROMPTS ----
server.setRequestHandler(ListPromptsRequestSchema, async () => {
  return await client.listPrompts();
});

server.setRequestHandler(GetPromptRequestSchema, async (req) => {
  return await client.getPrompt(req.params);
});

const transport = new StdioServerTransport();
await server.connect(transport);
console.error("[proxy] Ready: local stdio server running");

process.on("SIGINT", () => process.exit(0));
process.on("SIGTERM", () => process.exit(0));
