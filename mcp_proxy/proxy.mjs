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

// Custom SSE transport that supports Authorization headers (Node only)
class SSEAuthClientTransport {
  constructor(url, opts = {}) {
    this._url = new URL(url);
    this._headers = opts.headers || {};
    this.onclose = undefined;
    this.onerror = undefined;
    this.onmessage = undefined;
  }

  start() {
    if (this._es) throw new Error("Already started");
    return new Promise((resolve, reject) => {
      this._ac = new AbortController();
      this._es = new EventSource(this._url.href, { headers: this._headers });
      this._es.onerror = (event) => {
        const err = new Error(`SSE error: ${JSON.stringify(event)}`);
        reject(err);
        this.onerror?.(err);
      };
      this._es.addEventListener("endpoint", (event) => {
        try {
          const data = event?.data;
          // Handle both absolute and relative endpoint URLs properly
          if (data.startsWith('http://') || data.startsWith('https://')) {
            // Absolute URL - use as is
            this._endpoint = new URL(data);
          } else if (data.startsWith('/')) {
            // Absolute path - use origin from base URL
            this._endpoint = new URL(data, this._url.origin);
          } else {
            // Relative path - resolve against parent directory of base URL
            const base = new URL(this._url);
            // Compute directory of base path (drop last segment like 'sse')
            const lastSlash = base.pathname.lastIndexOf('/');
            const dirPath = lastSlash >= 0 ? base.pathname.slice(0, lastSlash + 1) : '/';
            let rel = data;
            // If server returns 'mcp/...' and dirPath already ends with '/mcp/', avoid duplicating
            if (dirPath.endsWith('/mcp/') && rel.startsWith('mcp/')) {
              rel = rel.slice(4);
            }
            this._endpoint = new URL(dirPath + rel, this._url.origin);
          }
          // Normalize accidental double segments like '/mcp/mcp/' if any
          if (this._endpoint.pathname.includes('/mcp/mcp/')) {
            const normalized = this._endpoint.pathname.replace('/mcp/mcp/', '/mcp/');
            this._endpoint = new URL(`${this._endpoint.origin}${normalized}${this._endpoint.search}`);
          }
          console.error(`[proxy] endpoint event: data="${data}", resolved_endpoint="${this._endpoint.href}"`);
          
          if (this._endpoint.origin !== this._url.origin) {
            throw new Error(`Endpoint origin mismatch: ${this._endpoint.origin}`);
          }
        } catch (e) {
          reject(e);
          this.onerror?.(e);
          void this.close();
          return;
        }
        resolve();
      });
      this._es.onmessage = (event) => {
        let msg;
        try {
          msg = JSON.parse(event.data);
        } catch (e) {
          this.onerror?.(e);
          return;
        }
        this.onmessage?.(msg);
      };
    });
  }

  async close() {
    this._ac?.abort();
    this._es?.close();
    this.onclose?.();
  }

  async send(message) {
    if (!this._endpoint) throw new Error("Not connected");
    console.error(`[proxy] sending to ${this._endpoint.href}`);
    const res = await fetch(this._endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...this._headers },
      body: JSON.stringify(message),
      signal: this._ac?.signal,
    });
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      throw new Error(`POST ${this._endpoint} failed (${res.status}): ${text}`);
    }
  }
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
  // Prefer our auth-capable transport; fall back to SDK SSE if needed
  const transport = new SSEAuthClientTransport(REMOTE_URL, { headers });
  await client.connect(transport);

  // Initialize remote and fetch tools list
  const tools = await client.listTools();
  return { client, tools };
}

// Start local stdio MCP server and forward calls
async function main() {
  const { client, tools } = await connectRemote();

  const server = new Server(
    { name: "hr-resumes-stdio-proxy", version: "1.0.0" },
    // Mirror remote capabilities where reasonable; ensure tools are enabled
    { capabilities: { tools: {} } }
  );

  server.setRequestHandler("tools/list", async () => {
    return await client.listTools();
  });
  server.setRequestHandler("tools/call", async (req) => {
    const { name, arguments: args } = req.params || {};
    if (!name) throw new Error("tools/call missing 'name' parameter");
    return await client.callTool(name, args ?? {});
  });

  // Optional: light bridging for resources/prompts; errors will bubble if unsupported by remote
  server.setRequestHandler("resources/list", async () => {
    return await client.listResources();
  });
  server.setRequestHandler("resources/read", async (req) => {
    return await client.readResource(req);
  });
  server.setRequestHandler("prompts/list", async () => {
    return await client.listPrompts();
  });
  server.setRequestHandler("prompts/get", async (req) => {
    return await client.getPrompt(req);
  });

  const transport = new StdioServerTransport();
  await server.connect(transport);
}

main().catch((err) => {
  console.error("Proxy crashed:", err?.stack || err);
  process.exit(1);
});
