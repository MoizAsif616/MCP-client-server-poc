# MCP stakeholder demonstration

Demonstrate an account choosing permissions, an independent client obtaining consent, and a server enforcing access through actual HTTP. Keep the local backend running and open the project in two PowerShell windows.

## Demonstration sequence

| Step | Action | Expected result |
| --- | --- | --- |
| 1 | Sign up at `http://127.0.0.1:8000/signup` with invented credentials and select Calculator and Notes | The account and roles persist in SQLite |
| 2 | Log in with those credentials | Dashboard shows four tools, both roles, and the shared MCP URL |
| 3 | Click Copy | “URL copied” appears |
| 4 | Run `python -m client list` using the project virtual environment | Browser opens to log in and consent for this client |
| 5 | Review the client name, callback host, resource, and scopes; allow access | Callback succeeds; the terminal lists only Calculator and Notes tools |
| 6 | Run `python -m client interactive` | Select `local:add`, enter `{"a":19,"b":23}`, and obtain `42` |
| 7 | Call `local:save_note` with `{"text":"My private demo note"}`, then `local:list_notes` with `{}` | The note belongs to this user |
| 8 | Manually call `local:get_profile` despite its absence from the list | The server denies the hidden tool |
| 9 | Enter `{"a":"wrong","b":2}` for `local:add` | The client displays a validation error |
| 10 | Sign up as another Notes user and consent using a separate configured client name | That user's notes are empty; supplying the first user's ID is denied |
| 11 | Start `scripts/start-second.ps1`, then list using `client/servers-multi.json` | Duplicate names appear with `first:` and `second:` prefixes |
| 12 | Call `first:add` and `second:multiply` | Each call goes to the source server's URL; the two server logs show separate receiving endpoints |

Use `.\.venv\Scripts\python.exe` in place of `python` above. For step 8:

```powershell
.\.venv\Scripts\python.exe -m client call local:get_profile --args '{}'
```

An unauthorized tool returns a tool error and exit code 2. Connection/JSON/protocol errors return exit code 1. Successful direct calls return 0.

For step 10, add another server entry with a different name, such as `second_user`, but the same `http://127.0.0.1:8000/mcp` URL. Its token file is separate. Use a different browser session or log out of the website before granting consent to the other user.

## Show the OAuth traffic

Open the representative logs below. They are excerpts copied from actual verification traffic, with original field values and bodies preserved.

- [Client HTTP requests and responses](representative-client-http.jsonl): initial unauthenticated MCP request, `401`, metadata, registration, code exchange, authenticated discovery, and calls.
- [Backend HTTP requests and responses](representative-backend-http.jsonl): signup, login, consent, OAuth exchanges, and MCP traffic, including form bodies and cookies.
- [Client callback requests and responses](representative-callback-http.jsonl): actual callback URL with code, state, and issuer.
- [Tool outcomes](representative-tools.jsonl): permitted calls and rejected hidden tools with client ID, receiving URL, and authenticated user.

The authorization request's challenge is the SHA-256/base64url derivative of the token exchange's verifier. The callback returns the same `state` chosen by the client. The token exchange includes the MCP resource URL. The subsequent MCP request carries its access token in the Authorization header.

The complete logs for each test run are under the directory recorded in `runtime/latest-verification.json`. The JSONL outer envelope escapes body strings; decoding the envelope restores the original JSON, form, HTML, or text body.

## Demonstrate refresh quickly

Start a backend with a short access lifetime in its own terminal:

```powershell
$env:ACCESS_TOKEN_SECONDS = '10'
.\.venv\Scripts\python.exe -m backend
```

Authorize the client, call a tool, wait more than 10 seconds, and call again. The client refreshes without another browser login. Its log shows a form-encoded `grant_type=refresh_token` exchange, and the new refresh token replaces the old one. Tests also verify that replaying the old refresh token fails.

## Demonstrate the public boundary

Run `.\.venv\Scripts\python.exe scripts/tunnel.py`, sign up on its printed HTTPS website, and run the client with `client/servers-public.json`. The tunnel starts an isolated public demo database.

The actual Claude.ai connection is the user's remaining integration exercise: add the printed `/mcp` URL as a web custom connector, select OAuth sign-in and Register automatically, then log in and consent. Local and HTTPS tests cover the supported flow; they do not represent a live Claude.ai sign-in. Future Claude requests appear in the public backend log, while Claude.ai's internal client logs remain unavailable.
