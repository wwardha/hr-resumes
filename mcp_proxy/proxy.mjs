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
import EventSource from "eventsource";

// Node's built-in EventSource lacks header support; use the package version.
if (!globalThis.EventSource) {
  globalThis.EventSource = EventSource;
}

function headersFromEnv() {
  const headers = {};
  const bearer = process.env.MCP_REMOTE_BEARER || process.env.MCP_TOKEN;
  if (bearer) {
    headers["Authorization"] = `Bearer ${bearer}`;
    headers["X-MCP-Token"] = bearer;
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

class SSEAuthClientTransport {
  constructor(url, opts = {}) {
    this._url = typeof url === "string" ? new URL(url) : new URL(url.href);
    this._headers = opts.headers || {};
    this.onclose = undefined;
    this.onerror = undefined;
    this.onmessage = undefined;
  }

  start() {
    if (this._es) throw new Error("SSE transport already started");
    return new Promise((resolve, reject) => {
      this._ac = new AbortController();
      this._es = new EventSource(this._url.href, { headers: this._headers });
      this._es.onerror = (event) => {
        const status = event?.status ?? event?.code;
        const err = new Error(
          status ? `SSE error: status ${status}` : event?.message || "SSE error"
        );
        if (typeof status === "number") {
          err.code = status;
        }
        // Resolve with failure so outer connect() can decide how to handle auth errors.
        reject(err);
        this.onerror?.(err);
        void this.close();
      };
      this._es.addEventListener("endpoint", (event) => {
        try {
          const data = event?.data;
          if (!data) throw new Error("Missing endpoint event payload");
          if (data.startsWith("http://") || data.startsWith("https://")) {
            this._endpoint = new URL(data);
          } else if (data.startsWith("/")) {
            this._endpoint = new URL(data, this._url.origin);
          } else {
            const base = new URL(this._url);
            const lastSlash = base.pathname.lastIndexOf("/");
            const dirPath = lastSlash >= 0 ? base.pathname.slice(0, lastSlash + 1) : "/";
            let rel = data;
            if (dirPath.endsWith("/mcp/") && rel.startsWith("mcp/")) {
              rel = rel.slice(4);
            }
            this._endpoint = new URL(dirPath + rel, this._url.origin);
          }
          if (this._endpoint.pathname.includes("/mcp/mcp/")) {
            const normalized = this._endpoint.pathname.replace("/mcp/mcp/", "/mcp/");
            this._endpoint = new URL(`${this._endpoint.origin}${normalized}${this._endpoint.search}`);
          }
          if (this._endpoint.origin !== this._url.origin) {
            throw new Error(`Endpoint origin mismatch: ${this._endpoint.origin}`);
          }
        } catch (err) {
          reject(err);
          this.onerror?.(err);
          void this.close();
          return;
        }
        resolve();
      });
      this._es.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);
          this.onmessage?.(msg);
        } catch (err) {
          this.onerror?.(err);
        }
      };
    });
  }

  async close() {
    this._ac?.abort();
    this._es?.close();
    this.onclose?.();
  }

  async send(message) {
    if (!this._endpoint) throw new Error("SSE transport not ready");
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

async function connectClient() {
  try {
    // Ensure URL has trailing slash for HTTP transport to prevent 307 redirects
    const httpUrl = new URL(remoteUrl);
    if (!httpUrl.pathname.endsWith('/')) {
      httpUrl.pathname += '/';
    }
    const shttp = new StreamableHTTPClientTransport(httpUrl, { requestInit: { headers } });
    await client.connect(shttp);
    console.error(`[proxy] Connected to ${httpUrl} via Streamable HTTP`);
  } catch (err) {
    console.error("[proxy] Streamable HTTP failed, falling back to SSE:", err?.message || err);
    console.error("[proxy] Falling back to SSE with headers:", Object.fromEntries(Object.entries(headers || {})));
    const sseUrl = (() => {
      try {
        const u = new URL(remoteUrl);
        if (u.pathname.endsWith("/sse")) {
          // already a full SSE URL
        } else if (u.pathname.endsWith("/mcp")) {
          u.pathname = `${u.pathname}/sse`;
        } else if (u.pathname.endsWith("/mcp/")) {
          u.pathname = `${u.pathname}sse`;
        } else {
          u.pathname = `${u.pathname.replace(/\/$/, "")}/mcp/sse`;
        }
        return u;
      } catch (e) {
        console.error("[proxy] Failed to derive SSE URL from", remoteUrl, e);
        return remoteUrl;
      }
    })();
    const sse = new SSEAuthClientTransport(sseUrl, { headers });
    await client.connect(sse);
    console.error(`[proxy] Connected to ${sseUrl} via SSE`);
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
