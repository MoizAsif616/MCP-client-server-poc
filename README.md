# MCP learning POC

A local website, OAuth service, and MCP server, plus an independent Python client. Sign up with your own demo credentials, choose roles, and call permitted tools without an LLM or paid API.

## Start locally

Tested on Windows with Python 3.13.3. Open PowerShell in this project:

```powershell
cd D:\MCP-client-server-POC
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.\.venv\Scripts\python.exe -m backend
```

Open [the website](http://127.0.0.1:8000/signup), sign up, select at least one role, and log in. Keep the backend running.

In another PowerShell window:

```powershell
cd D:\MCP-client-server-POC
.\.venv\Scripts\python.exe -m client list
.\.venv\Scripts\python.exe -m client interactive
```

On first connection, the client opens a browser. Log in to the website and allow the client on the consent page. The callback listener returns you to the terminal. In interactive mode, select a displayed `server:tool` name and enter a JSON object, such as `{"a":2,"b":3}`.

For a direct call:

```powershell
.\.venv\Scripts\python.exe -m client call local:add --args '{"a":2,"b":3}'
```

`requirements.txt` pins runtime dependencies; `requirements-dev.txt` adds the tests; `requirements-lock.txt` pins the complete tested environment. `scripts/start-local.ps1` combines installation and startup.

## Roles and tools

| Role | Tools | What they do |
| --- | --- | --- |
| Calculator | `add`, `multiply` | Arithmetic with two numbers |
| Notes | `save_note`, `list_notes` | Save and list the signed-in user's private notes |
| Profile | `get_profile` | Read the signed-in user's email and selected roles |

Multiple roles combine permissions. `backend/permissions.py` supplies the one role mapping used by the dashboard, MCP tool discovery, and tool authorization. Private data tools reject another user's ID. Roles are fixed at signup for this POC.

## How the connection works

1. The client sends an MCP request to the configured `/mcp` URL.
2. Without a valid access token, the backend returns `401` with a protected-resource metadata URL.
3. The SDK reads resource and authorization metadata and registers this OAuth client.
4. The browser opens the authorization page. The user logs in and approves access for this client, callback host, resource, and scopes.
5. The backend issues a single-use authorization code. The client's callback listener checks `state`; the SDK checks the returned issuer.
6. The SDK exchanges the code and PKCE verifier for an access token and refresh token bound to the client, user, and MCP resource.
7. The SDK sends the bearer token with tool discovery and tool calls. The server validates it on each HTTP request and checks permission again on each tool call.
8. After expiry, the SDK refreshes the token. Refresh tokens rotate; the previous refresh token cannot be reused.

The website's cookie and the MCP client's tokens are separate. A website login alone cannot authorize an MCP request. Logging out closes the website session; previously consented client tokens remain usable until expiration or rotation.

The official SDK's `mcp.Client` handles MCP messages, discovery/initialization, transport, and sessions. Its `OAuthClientProvider` handles OAuth discovery, registration, PKCE, issuer validation, exchange, and refresh. A small subclass restores the expiry timer when loading saved tokens, which SDK 2.3.0 otherwise omits. A test restarts the client and confirms that the expired token refreshes without browser login.

## Connect multiple servers

Keep the first backend running, then start the second instance in another terminal:

```powershell
cd D:\MCP-client-server-POC
.\scripts\start-second.ps1
```

Run the client with both URLs:

```powershell
.\.venv\Scripts\python.exe -m client --config client/servers-multi.json list
.\.venv\Scripts\python.exe -m client --config client/servers-multi.json call first:add --args '{"a":2,"b":3}'
.\.venv\Scripts\python.exe -m client --config client/servers-multi.json call second:multiply --args '{"a":2,"b":3}'
```

The instances share the default SQLite account database, so the same account can log in to both. Each endpoint requires a separate resource-bound token. The client retains each tool's source URL and prefixes its name, such as `first:add` and `second:add`. A token issued for the first URL is rejected by the second.

## Free HTTPS and Claude.ai

Windows OpenSSH and localhost.run provide the free tunnel. No tunnel account or API key is required. Run:

```powershell
cd D:\MCP-client-server-POC
.\.venv\Scripts\python.exe scripts/tunnel.py
```

The command starts a tunnel and a backend on port 8002, prints the HTTPS website and MCP URLs, and writes `client/servers-public.json`. Keep it running. Ctrl+C stops its processes. Each tunnel launch uses a fresh isolated database under `runtime/public-demo`, so sign up on the public website using demo credentials. Existing local accounts and sessions are not exposed. The SQLite file remains on disk after stopping.

If port 8002 is occupied, use `scripts/tunnel.py --port 8003`. Free tunnel hostnames can change while SSH remains connected. The launcher detects the latest hostname, restarts its backend against the same demo database, and updates the SDK host allowlist, OAuth metadata, and client configuration together. Use the newly printed URL and reconnect Claude.ai after a change. If SSH ends, restart the command. See the provider's [free-tier limits](https://localhost.run/docs/forever-free/).

To connect **Claude.ai on the web**:

1. Sign up on the public HTTPS website and choose roles.
2. In Claude.ai, open Customize → Connectors → Add custom connector.
3. Enter the printed **HTTPS MCP URL including `/mcp`**.
4. Choose OAuth sign-in and **Register automatically** for the OAuth client. This POC supports Dynamic Client Registration; it does not advertise Claude's published-identity mechanism.
5. Connect, log in to this POC, and allow access on its consent page.
6. Enable the connector in a conversation and ask for one of your permitted tools.

The backend accepts the documented Claude.ai callback `https://claude.ai/api/mcp/auth_callback`. It supports S256 PKCE, form-encoded token exchange, rotating refresh tokens, resource metadata, and a `401` challenge. HTTP tests cover the documented MCP versions 2025-03-26, 2025-06-18, and 2025-11-25. The custom client also exercises SDK 2.3.0's newer protocol.

**Locally verified:** the full OAuth and tool flow, plus the same flow through a real public HTTPS tunnel with synthetic data. **Prepared for your test:** actual Claude.ai sign-in and connector integration. Those live Claude.ai actions have not been performed. The server logs all application requests it receives, including future Claude.ai requests; it cannot see Claude.ai's internal client logs.

Official references: [Python SDK Client](https://py.sdk.modelcontextprotocol.io/client/), [SDK OAuth provider](https://py.sdk.modelcontextprotocol.io/client/oauth-clients/), [MCP authorization](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization), [Claude connector authentication](https://claude.com/docs/connectors/building/authentication), and [localhost.run](https://localhost.run/docs/).

## Configuration

For the installed ngrok agent, public URLs, background startup/stop commands, HTTPS verification, and Claude.ai instructions, see [Ngrok setup and demonstration](docs/NGROK.md). Start with `.\.venv\Scripts\python.exe -m scripts.ngrok --background`; it uses a separate persistent synthetic demo database and generates `client/servers-ngrok.json`.

Backend environment variables:

| Variable | Default | Purpose |
| --- | --- | --- |
| `PORT` | `8000` | Local listening port |
| `PUBLIC_URL` | `http://127.0.0.1:8000` | Advertised origin for the website, MCP, OAuth, and metadata URLs |
| `SERVER_NAME` | `Learning MCP` | Server name in discovery |
| `DATABASE` | `data/app.sqlite3` | Persistent users, notes, sessions, clients, codes, and tokens |
| `LOG_DIR` | `logs/backend` | Backend HTTP and tool logs |
| `ACCESS_TOKEN_SECONDS` | `3600` | Access token lifetime |
| `REFRESH_TOKEN_SECONDS` | `604800` | Refresh token lifetime |

Set `PORT` and `PUBLIC_URL` together when changing ports. Public origins require HTTPS; HTTP is allowed on loopback. Server URLs derive from the configured origin: `/mcp`, `/authorize`, `/token`, `/register`, `/.well-known/oauth-authorization-server`, and `/.well-known/oauth-protected-resource/mcp`. The root protected-resource metadata path is also served.

`client/servers.json` contains one or more entries with `name` and `url`. Optional entry fields are `callback_url`, `callback_port`, `token_dir`, and `log_dir`. The default callback is `http://127.0.0.1:8765/callback`. A public HTTPS callback URL may point through a separate tunnel to that listener; its path must match the configured callback path. Parallel client processes need different callback ports and matching URLs. The listener binds only to loopback.

Client tokens are stored by server name and URL in `client/tokens`. To consent as a different user, remove that server's token JSON file and reconnect. Do not share this folder or authentication logs.

## Files and verification

| Location | Responsibility |
| --- | --- |
| `backend/app.py`, `backend/__main__.py` | Web/backend composition and startup |
| `backend/web.py`, `templates`, `static` | Website routes and frontend |
| `backend/oauth.py`, `authentication.py` | Our OAuth service, website sessions, and bearer validation |
| `backend/permissions.py` | Role and user-data authorization |
| `backend/storage.py` | SQLite persistence |
| `backend/mcp_server.py`, `tools.py` | SDK server, permission checks, and tool functions |
| `backend/logging.py` | Backend HTTP and tool logging |
| `client/connection.py`, `routing.py` | SDK Client connections and source-server routing |
| `client/authentication.py`, `storage.py` | Browser callback and saved OAuth credentials |
| `client/config.py`, `logging.py`, `errors.py`, `__main__.py` | Client configuration, traffic logs, readable errors, and CLI |
| `tests` | Real HTTP checks with isolated data and subprocess servers |

The client imports only its own modules and installed libraries. It can run from a separate directory containing only the `client` package; this is tested. The backend does not require the client package.

Run the tests:

```powershell
.\.venv\Scripts\python.exe -m pytest -q --junitxml=runtime/test-results.xml
```

The suite starts and stops its own backend processes on free loopback ports and stores each run under `runtime/verification`. On this managed Codex host, stopping Windows process trees requires sandbox approval; ordinary local PowerShell does not have that sandbox restriction.

See [verification results](docs/VERIFICATION.md), [the stakeholder demonstration](docs/DEMO.md), and [the dashboard preview](docs/dashboard.png).

## Read the traffic logs

`logs/backend/http.jsonl` records incoming requests and outgoing responses; `tools.jsonl` records tool names, client IDs, receiving URLs, authenticated users, and outcomes. The client writes outbound traffic to `logs/client/http.jsonl` and callback traffic to `callback-http.jsonl`.

Each HTTP record contains timestamp, direction, method, URL including its query, actual application headers, content type, original body, and response status where applicable. Bodies remain exact strings inside the JSONL envelope: JSON stays JSON text, forms stay form text, and text/SSE stays text. Binary bodies use base64. Parse a JSON body separately to inspect its original number, boolean, null, and array types.

Headers are preserved as exposed by each application's HTTP layer. ASGI lowercases incoming header names. Uvicorn's optional Date and Server headers are disabled so normal application response headers match the client capture. A tunnel or HTTP transport may add its own headers or transfer framing; these are application traffic logs, not packet captures. Streaming logs retain the chunks actually received/sent, including any consumed portion of a stream closed early.

For this requested learning POC, passwords are stored without hashing and logs retain passwords, cookies, authorization codes, PKCE verifiers, and access/refresh tokens. Use invented demo credentials. There is no email verification, password reset, external identity provider, role editor, or tool-list-change notification feature.
