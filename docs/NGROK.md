# Ngrok setup and demonstration

The existing MCP POC is available through an authenticated ngrok HTTPS tunnel. The launcher runs a separate backend on loopback port **8004**, uses a persistent database containing synthetic demo data, and configures its public URLs from the agent's actual HTTPS origin. Local and localhost.run configurations remain available.

## Public URLs

- Website: https://portless-unelderly-nigel.ngrok-free.dev
- MCP and Claude connector URL: https://portless-unelderly-nigel.ngrok-free.dev/mcp
- Protected resource metadata: https://portless-unelderly-nigel.ngrok-free.dev/.well-known/oauth-protected-resource/mcp
- Authorization metadata: https://portless-unelderly-nigel.ngrok-free.dev/.well-known/oauth-authorization-server

These URLs work while the demo controller, backend, ngrok agent, and this PC's internet connection remain running. Check `runtime/ngrok/state.json` for the current URL after starting again.

## Start and stop

Run from PowerShell:

```powershell
cd D:\MCP-client-server-POC
.\.venv\Scripts\python.exe -m scripts.ngrok --background
```

The command returns only after both local backend health and public HTTPS health checks pass. No further token entry is required. For foreground operation, omit `--background`; Ctrl+C stops the owned backend and agent. Background mode runs without a visible terminal window and continues after the starting terminal closes. It does not install a Windows service or start automatically after reboot.

```powershell
.\.venv\Scripts\python.exe -m scripts.ngrok --status
.\.venv\Scripts\python.exe -m scripts.ngrok --stop
```

Stop signals this controller through a unique request file. The controller stops only the process trees it started and acknowledges completion. It does not kill arbitrary stored PIDs or unrelated servers. The OS releases the controller lock after a crash. Startup refuses occupied ports and duplicate controllers. If a controller crashed and left its children running, startup reports occupied ports; inspect their ownership before stopping them.

To choose different loopback ports:

```powershell
.\.venv\Scripts\python.exe -m scripts.ngrok --background --port 8005 --api-port 4042
```

The ngrok agent API is bound only to loopback, by default `127.0.0.1:4041`. Only backend port 8004 is forwarded publicly. The launcher reports safe `ERR_NGROK_*` identifiers for agent failures and suppresses raw agent diagnostics.

## Installation and private credentials

The official Store agent was installed with `winget install ngrok -s msstore`. Its verified version at installation was **3.39.9-msix-stable**. This is a supported [official Windows installation method](https://ngrok.com/download/windows).

The launcher uses the existing authorized credential configuration at:

```text
C:\Users\Moiz\AppData\Local\ngrok\ngrok-poc.yml
```

The agent consumes that file directly. The launcher does not read or copy its token, pass it on the command line, or write it into application logs. A separate nonsecret runtime configuration sets the loopback agent API address. Unrelated ngrok settings and the normal `ngrok.yml` are preserved. Agent traffic inspection is disabled for this instance.

## Backend and client configuration

The launcher starts the existing `python -m backend` with:

| Setting | Value |
| --- | --- |
| `PORT` | `8004` by default |
| `PUBLIC_URL` | Actual agent HTTPS origin |
| `DATABASE` | `data/ngrok-demo.sqlite3` |
| `LOG_DIR` | `logs/ngrok-backend` |
| `SERVER_NAME` | `Ngrok demo MCP` |
| `ACCESS_TOKEN_SECONDS` | `3600` in normal operation |

Website links, `/mcp`, resource identifiers, issuer, `/authorize`, `/register`, `/token`, metadata, secure cookies, and SDK host/origin allowlists all derive from `PUBLIC_URL`. The database is retained across restarts. Use invented credentials; the learning POC keeps its existing simplified password storage and detailed OAuth logs.

`client/servers-ngrok.json` is generated after health checks. Its separate token and log directories are `client/tokens/ngrok` and `logs/ngrok-client`.

```powershell
.\.venv\Scripts\python.exe -m client --config client/servers-ngrok.json list
.\.venv\Scripts\python.exe -m client --config client/servers-ngrok.json call ngrok:add --args '{"a":20,"b":22}'
```

The first client connection opens a browser for POC login and consent. This uses the existing official SDK `Client`, not the ngrok account credential. Sign in with a synthetic POC account having the Calculator role. Remove only this client's saved token JSON when demonstrating consent as a different user.

## Verified behavior and evidence

On 13 October 2026, **27 local checks and 22 real ngrok HTTPS checks passed**, with zero failures. Nine additional lifecycle checks passed, and the demo was left running with normal one-hour access tokens. The installed dependencies also passed `pip check`.

The local suite and separate opt-in HTTPS suite use real backend processes and generated accounts. HTTPS verification covers all seven nonempty role combinations, website signup/login/logout, metadata and 401 challenges, dynamic registration, login/consent, S256 PKCE, state and issuer validation, token exchange and replay, resource/client/redirect/scope bindings, expiration and refresh, permitted calls, hidden-tool denial, private user data, invalid arguments/tokens, protocol versions, standalone client execution, public origin validation, and rejection of a token issued for a different server audience.

Callback rejection requests go to the client's real loopback callback listener. Metadata, authorization, token exchange, and MCP calls go through ngrok HTTPS. The browser flow is exercised using HTTP requests to the actual login and consent forms.

Results and actual log excerpts:

- [HTTPS test summary](ngrok-test-summary.json) and [JUnit report](ngrok-test-results.xml).
- [Stop and restart results](ngrok-lifecycle.json), including the synthetic stakeholder account.
- [Client HTTP](ngrok-representative-client-http.jsonl), [backend HTTP](ngrok-representative-backend-http.jsonl), [callback HTTP](ngrok-representative-callback-http.jsonl), [tool calls](ngrok-representative-tools.jsonl), and [body and query audit](ngrok-audit-client.jsonl).
- [Local regression summary](test-summary.json) and [local JUnit report](test-results.xml).

The logs are actual application exchanges. JSON, form, text, query, status, and content type are checked against client/backend captures. ngrok adds proxy and response headers, so application and client header sets need not be identical. The ngrok account authtoken is separate from all POC HTTP traffic and evidence. POC passwords, cookies, authorization codes, and access/refresh tokens remain in these learning logs as previously requested.

## Reproduce the checks

Start the demo with a short access lifetime for the expiration test:

```powershell
.\.venv\Scripts\python.exe -m scripts.ngrok --stop
.\.venv\Scripts\python.exe -m scripts.ngrok --background --access-token-seconds 30
$env:NGROK_VERIFY = '1'
.\.venv\Scripts\python.exe -m pytest tests/test_ngrok_public.py -q --junitxml=runtime/ngrok-test-results.xml
Remove-Item Env:NGROK_VERIFY
.\.venv\Scripts\python.exe -m pytest tests/test_http.py tests/test_tunnel.py tests/test_ngrok_launcher.py -q --junitxml=runtime/test-results.xml
.\.venv\Scripts\python.exe -m scripts.verify_ngrok_lifecycle
.\.venv\Scripts\python.exe -m scripts.export_evidence
.\.venv\Scripts\python.exe -m scripts.export_ngrok_evidence
```

The lifecycle check creates an account and note, rejects a duplicate start, stops owned processes, checks that their ports close and other local backends remain available, verifies rejection of an occupied backend port, and restarts against the same database without token entry. It confirms the saved account/note and an HTTPS SDK call, and leaves the demo running with the normal 3600-second access lifetime. Without `NGROK_VERIFY=1`, the internet tests are skipped.

## Stakeholder demonstration

1. Open the public website. On ngrok's browser warning, select **Visit Site** once.
2. Sign up with an invented email/password and select Calculator and Profile. The dashboard shows only Add, Multiply, and Get Profile with the common `/mcp` URL.
3. Run the client `list` command, log in, and allow consent. Run Add with 20 and 22 to see 42.
4. Attempt `ngrok:save_note` with `--args '{"text":"hidden tool attempt"}'`. The server denies the hidden tool.
5. Create two Notes accounts. Save a note as one user, consent as the other, and show that the second user's list is empty. Use separate client token files when switching users.
6. Show an actual successful and denied tool row from `logs/ngrok-backend/tools.jsonl` and the matching HTTP exchanges.

The saved synthetic account in `ngrok-lifecycle.json` has all three roles and a persisted demonstration note, for a quick second demonstration.

## Claude web connector

You perform the actual Claude.ai sign-in and integration test. The ngrok/custom-client flow is verified; live Claude.ai integration is prepared and remains unverified.

1. Sign up on the public POC website with the roles you want.
2. In Claude.ai, open Customize → Connectors → Add custom connector.
3. Enter the current HTTPS URL **including `/mcp`**.
4. Choose OAuth and **Register automatically** where OAuth client settings are offered. This POC exposes `/register` for Dynamic Client Registration and does not advertise published client identity support.
5. Log in to the POC and approve consent. If ngrok displays its browser warning, continue to the site.
6. Enable the connector in a conversation and request a permitted tool.

The hosted callback `https://claude.ai/api/mcp/auth_callback` is accepted and tested through registration. See [Claude's authentication requirements](https://claude.com/docs/connectors/building/authentication) for DCR, 401 discovery, PKCE, and refresh behavior. Inspect `logs/ngrok-backend/http.jsonl` for requests Claude actually sends during your test.

## Free plan limits

As checked on 13 October 2026, the free plan includes one assigned development domain, up to three online endpoints and three concurrent agents, 1 GB outgoing transfer and 20,000 HTTP requests per month. HTTPS endpoints have no session timeout. HTML browser visits show ngrok's warning; continuing suppresses it for that domain for seven days. Programmatic API requests are unaffected. Usage limits and PC sleep, shutdown, or lost connectivity can interrupt access. No paid resources were created. [Official free plan limits](https://ngrok.com/docs/pricing-limits/free-plan-limits).
