## Setup

- Copy env: `cp .env.example .env`, then set:
  - `ADMIN_TOKEN`: static admin header for generated API admin routes
  - `MCP_TOKEN`: Bearer token for `/mcp` endpoints
  - `CLAUDE_CLI_PATH`: path to local `claude` binary (defaults to `claude`)
  - `CLOUDFLARE_TUNNEL_TOKEN`: token from Cloudflare Tunnel (see below)

## Make Targets

- `build`: builds images and starts containers in background
- `up`: starts containers in background
- `down`: stops and removes containers, networks, images, volumes
- `logs`: tails all compose service logs

Examples:
- `make build`
- `make logs`
- `make down && make build` (restart with fresh config)

## Services (internal)

- Control Plane MCP: `:8000`
- Claude Code Service: `:8300`
- Generated API (+ MCP): `:9000`

These ports are internal to the compose network; publish via Cloudflare Tunnel.

## Cloudflare Tunnel (Token Mode)

1) Add domain to Cloudflare and wait until DNS status is Active.
2) Zero Trust → Networks → Tunnels → Create → “Cloudflared”. Choose Docker, copy the token shown (`TUNNEL_TOKEN=...`).
3) Put the token into `.env` as `CLOUDFLARE_TUNNEL_TOKEN=...`.
4) Start: `make build`.
5) In the tunnel → Public hostnames, add these mappings:
   - `hr-resumes-api.<your-domain>` → `http://hr-resumes-mcp:9000`   (generated API)
   - `hr-resumes-mcp.<your-domain>` → `http://hr-resumes-mcp:8000`   (control-plane MCP)
   - `hr-resumes-cli.<your-domain>` → `http://hr-resumes-claude:8300` (Claude CLI service)

Cloudflare will auto-create proxied DNS CNAMEs for each hostname.

## Test

- External (via Cloudflare): `curl -I https://hr-resumes-api.<your-domain>/health`
- Internal (from inside the network): `curl -fsS http://hr-resumes-mcp:8000/health`

Auth headers when required:
- Admin: `X-Admin-Token: $ADMIN_TOKEN`
- MCP: `Authorization: Bearer $MCP_TOKEN`

## Troubleshooting

- Existing DNS record: If adding a Public hostname fails with “An A, AAAA, or CNAME record with that host already exists”, delete or rename the conflicting DNS record in Cloudflare → DNS → Records, or remove the hostname from any other tunnel that owns it.
- 502/522: Ensure the tunnel is Healthy and containers are running; try `make down && make build`.

## Optional: Config File Mode (manage hostnames in-repo)

If you prefer code-managed routes instead of dashboard-managed hostnames:

1) Download tunnel credentials JSON for your tunnel and place it at `cloudflared/<TUNNEL_ID>.json`.
2) Edit `cloudflared/config.yml` and set:
   - `tunnel: <TUNNEL_ID>`
   - `credentials-file: /etc/cloudflared/<TUNNEL_ID>.json`
   - Ingress rules already map:
     - `hr-resumes-api.<your-domain>` → `http://hr-resumes-mcp:9000`
     - `hr-resumes-mcp.<your-domain>` → `http://hr-resumes-mcp:8000`
     - `hr-resumes-cli.<your-domain>` → `http://hr-resumes-mcp:8300`
3) Update `docker-compose.yml` for config mode:
   - Comment out the `TUNNEL_TOKEN` environment.
   - Mount the config: `volumes: - ./cloudflared:/etc/cloudflared`.
   - Keep `command: tunnel run` (cloudflared auto-loads `/etc/cloudflared/config.yml`).
4) `make down && make build`.

Note: In config mode, ensure DNS CNAMEs exist for your hostnames pointing to the tunnel; the dashboard can create them automatically when the tunnel runs.

## Claude Desktop (legacy stdio support)

If your Claude Desktop build does not support HTTP/SSE MCP configs (shows error about `command: Required`), use the included stdio proxy:

1) Ensure Node.js 18+ is installed on your desktop.
2) Use this Claude Desktop config (Windows example) to launch the proxy as a `command` (the proxy will prefer `/mcp` Streamable HTTP and fall back to SSE automatically):

```
{
  "mcpServers": {
    "hr-resumes-proxy": {
      "command": "node",
      "args": ["C:\\path\\to\\repo\\hr-resumes\\mcp_proxy\\proxy.mjs"],
      "env": {
        "MCP_REMOTE_URL": "https://hr-resumes-mcp.<your-domain>/mcp",
        "MCP_REMOTE_BEARER": "<your-mcp-token>"
      }
    }
  }
}
```

3) Restart Claude Desktop. The proxy bridges all tools from the remote HTTP MCP to the local stdio transport.

Notes:
- The proxy only needs outbound HTTPS to your tunnel URL.
- Update the path and domain/token to match your setup.
