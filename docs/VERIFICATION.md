# MCP POC verification

The local suite covers **23 real HTTP tests, one localhost.run regression, and three ngrok launcher checks** using Python 3.13.3 and official MCP SDK 2.3.0. The applications run as separate subprocesses and communicate over loopback HTTP. The suite also captures streamed SSE and HTTP 500 bodies. The current counts and pass status are in [the test summary](test-summary.json).

See [the machine-readable test report](test-results.xml), [test summary](test-summary.json), and [public HTTPS results](public-verification.json). The summary records the run time and exact verification directory; complete HTTP and tool logs remain there. Representative excerpts are linked in [the demonstration sequence](DEMO.md).

The ngrok integration has its own [setup and verification guide](NGROK.md), [HTTPS test summary](ngrok-test-summary.json), and [stop and restart results](ngrok-lifecycle.json). It uses the real ngrok HTTPS endpoint and a separate persistent synthetic database; the existing localhost.run report remains separate.

## Requirements and evidence

| Requirement | Current evidence |
| --- | --- |
| Independently runnable client and backend | Separate `python -m client` and `python -m backend` applications; client copied to a directory with no backend files, then successfully called a tool over HTTP |
| Official SDK Client and Streamable HTTP | `client/connection.py` uses `mcp.Client` and `streamable_http_client`; the tests exercise SDK 2.3.0 and its OAuth provider |
| Modular files and pinned dependencies | Backend and client have separate configuration, authentication, storage, logging, tools, permissions, routes, and entry points; complete versions in `requirements-lock.txt`; `pip check` passed |
| Real signup and selected credentials | New users sign up through HTTP forms; login succeeds with the chosen password and fails with a wrong password |
| Website and logout | HTTP tests check dashboard roles/tools/URL and logout; browser test exercised signup, login, dashboard, and Copy; [dashboard screenshot](dashboard.png) |
| Persistent SQLite data | A backend process tree is stopped, restarted against the same SQLite file, and the previously created account logs in successfully |
| Three roles and every combination | Seven nonempty role combinations tested against both dashboard and MCP tool discovery; five tools exercised |
| One mapping and shared endpoint | `backend/permissions.py` controls dashboard, list filtering, and call checks; users use the same `/mcp` URL |
| Hidden tools and user-data isolation | Manually supplied hidden names are denied; the second user's notes are empty; another user's ID is rejected for notes and profile |
| Our OAuth service and metadata | Real HTTP requests exercise resource metadata, authorization metadata, Dynamic Client Registration, browser login/consent, and form-encoded token exchange |
| Authentication challenge | Missing and invalid tokens produce 401 with the resource metadata pointer; a website cookie alone cannot authorize MCP |
| Authorization code with PKCE | Wrong verifier fails; valid S256 verifier succeeds; a code cannot be reused; redirect/client/resource mismatches fail |
| Callback and state validation | Real callback requests with wrong state/path fail; SDK issuer validation rejects missing or wrong issuer; the normal CLI/browser consent reached a successful callback |
| Expiry and refresh | Access token expires in real time; SDK client reloads its stored credentials and refreshes without opening a browser; public and confidential client refreshes rotate tokens and reject replay |
| Audience and scopes | Token for one live server URL is rejected by the other; wrong resource parameters, unsupported scopes, scope expansion, and wrong client bindings fail |
| Argument errors and unknown tools | Invalid number/string values, missing arguments, and empty notes fail; unknown tool name returns an error; standalone CLI displays readable errors and appropriate exit codes |
| Multiple MCP instances | Two live endpoints are discovered with prefixes; calls reach their respective servers; account persistence is checked after an actual server restart |
| Exact HTTP logs | Request bodies and query strings compared with client captures for JSON, forms, and Unicode text; application response status/body/headers compared; separate SSE and 500 captures verified |
| Authentication values and tool logs | Logs retain bearer headers, codes, verifiers, tokens, cookies, and form bodies; tool log fields checked against the six requested fields with success and denied/error outcomes |
| Free public HTTPS | Real localhost.run tunnel returned public metadata and 401 challenge; synthetic signup, OAuth consent, filtered discovery, a call returning 42, and hidden-tool denial passed over HTTPS |
| Free hostname changes | The provider rotated a hostname while SSH stayed connected; its actual output is saved in `observed-tunnel-rotation.log`; regression checks select the latest URL; launcher updates backend metadata, host allowlist, and client configuration on a change |
| Claude.ai preparation | Exact hosted callback accepted by registration; documented 2025-03-26, 2025-06-18, and 2025-11-25 MCP initialization, notification, tool discovery, and tool call flows passed over HTTP |
| Delivery | Working source, frontend, configurations, dependency pins, README, demonstration sequence, test reports, screenshot, and actual log excerpts are included |

## Verification boundaries

The actual Claude.ai web sign-in and integration test is reserved for the user and has not been performed. Choose Register automatically in its OAuth client settings. Support for Claude's published client identity is not advertised. Claude compatibility is prepared and locally checked against its documented protocol and OAuth behavior; a successful live Claude connection is not claimed.

The free tunnel uses a fresh isolated demo database. Public HTTPS verification contains only synthetic data. A free hostname can change or expire, so the URL in the report is evidence of the tested run; run `scripts/tunnel.py` for a current connector URL. While connected, the launcher detects provider hostname changes and updates its backend and client configuration. Claude.ai must be pointed at the newly printed URL and reconnected.

Logs capture exact application traffic rather than encrypted packets. ASGI exposes lowercase incoming header names; the client retains the headers exposed by its HTTP transport. Reverse proxies may add their own headers. The server cannot access Claude.ai's internal client-side logs.

This POC intentionally stores passwords without hashing and retains authentication values in local logs, as requested. Use demo credentials. There is no external identity provider, email verification, password reset, role editing after signup, or tool-list-change notification feature.

## Reproduce

```powershell
cd D:\MCP-client-server-POC
.\.venv\Scripts\python.exe -m pytest -q --junitxml=runtime/test-results.xml
.\.venv\Scripts\python.exe -m scripts.export_evidence
```

To reproduce HTTPS checks, keep `scripts/tunnel.py` running in another terminal, then run:

```powershell
.\.venv\Scripts\python.exe -m scripts.verify_public
.\.venv\Scripts\python.exe -m scripts.export_evidence
```

The HTTPS verification creates a synthetic user and authorizes the custom SDK client over the public endpoint. It does not sign in to Claude.ai.
