import base64
import hashlib
import json
import re
import secrets
import time
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from starlette.responses import JSONResponse, RedirectResponse
from starlette.routing import Route

from backend.authentication import browser_session, browser_user, check_csrf

SCOPES = {"tools", "offline_access"}


class OAuthError(Exception):
    def __init__(self, error, description, status=400):
        self.error, self.description, self.status = error, description, status


async def oauth_error(request, exc):
    return JSONResponse({"error": exc.error, "error_description": exc.description}, status_code=exc.status,
                        headers={"Cache-Control": "no-store"})


def require(condition, error, description):
    if not condition:
        raise OAuthError(error, description)


def scopes(value):
    require(isinstance(value, str), "invalid_scope", "Scope must be a space-separated string")
    selected = set(value.split())
    require(bool(selected) and selected <= SCOPES and "tools" in selected,
            "invalid_scope", "Allowed scopes: tools offline_access; tools is required")
    return " ".join(sorted(selected))


def valid_redirect(uri):
    parsed = urlsplit(uri)
    return (not parsed.fragment and not parsed.username and not parsed.password and bool(parsed.netloc)
            and (parsed.scheme == "https" or (parsed.scheme == "http"
                 and parsed.hostname in {"127.0.0.1", "localhost", "::1"})))


def callback_url(params, **values):
    parsed = urlsplit(params["redirect_uri"])
    query = parse_qs(parsed.query)
    query.update({k: [v] for k, v in values.items()})
    query["state"] = [params["state"]]
    return urlunsplit(parsed._replace(query=urlencode(query, doseq=True)))


async def resource_metadata(request):
    cfg = request.app.state.settings
    return JSONResponse({"resource": cfg.resource, "authorization_servers": [cfg.public_url],
                         "scopes_supported": ["tools"], "bearer_methods_supported": ["header"],
                         "resource_name": cfg.name})


async def authorization_metadata(request):
    cfg = request.app.state.settings
    return JSONResponse({"issuer": cfg.public_url, "authorization_endpoint": cfg.public_url + "/authorize",
                         "token_endpoint": cfg.public_url + "/token", "registration_endpoint": cfg.public_url + "/register",
                         "response_types_supported": ["code"],
                         "grant_types_supported": ["authorization_code", "refresh_token"],
                         "code_challenge_methods_supported": ["S256"],
                         "token_endpoint_auth_methods_supported": ["none", "client_secret_post", "client_secret_basic"],
                         "scopes_supported": sorted(SCOPES),
                         "authorization_response_iss_parameter_supported": True})


async def register(request):
    try:
        metadata = await request.json()
    except (ValueError, UnicodeDecodeError):
        raise OAuthError("invalid_client_metadata", "Expected a JSON object")
    require(isinstance(metadata, dict), "invalid_client_metadata", "Expected a JSON object")
    uris = metadata.get("redirect_uris", [])
    require(isinstance(uris, list) and uris and all(isinstance(uri, str) and valid_redirect(uri) for uri in uris),
            "invalid_redirect_uri", "Use exact HTTPS or loopback callback URLs without fragments")
    method = metadata.get("token_endpoint_auth_method", "none")
    require(method in {"none", "client_secret_basic", "client_secret_post"},
            "invalid_client_metadata", "Unsupported token endpoint authentication method")
    grants = metadata.get("grant_types", ["authorization_code", "refresh_token"])
    require(isinstance(grants, list) and all(isinstance(g, str) for g in grants) and "authorization_code" in grants
            and set(grants) <= {"authorization_code", "refresh_token"},
            "invalid_client_metadata", "Only authorization_code and refresh_token grants are supported")
    require(metadata.get("response_types", ["code"]) == ["code"], "invalid_client_metadata", "Only code is supported")
    result = {"client_id": secrets.token_urlsafe(24), "client_id_issued_at": int(time.time()),
              "client_name": str(metadata.get("client_name", "Registered client"))[:100],
              "redirect_uris": uris, "token_endpoint_auth_method": method,
              "grant_types": grants, "response_types": ["code"],
              "scope": scopes(metadata.get("scope", "tools offline_access"))}
    if method != "none":
        result.update(client_secret=secrets.token_urlsafe(32), client_secret_expires_at=0)
    with request.app.state.store.connect() as db:
        db.execute("INSERT INTO clients VALUES (?,?)", (result["client_id"], json.dumps(result)))
    return JSONResponse(result, status_code=201, headers={"Cache-Control": "no-store"})


def validate_authorization(request):
    query = request.query_params
    require(all(len(query.getlist(key)) == 1 for key in query), "invalid_request", "Duplicate parameters")
    params = dict(query)
    store, cfg = request.app.state.store, request.app.state.settings
    client = store.client(params.get("client_id", ""))
    require(client is not None, "invalid_client", "Register this client first")
    require(params.get("redirect_uri") in client["redirect_uris"], "invalid_request", "Unregistered callback")
    require(params.get("response_type") == "code", "unsupported_response_type", "Use response_type=code")
    require(params.get("resource") == cfg.resource, "invalid_target", "Resource must match this MCP URL")
    require(bool(params.get("state")), "invalid_request", "State is required")
    require(params.get("code_challenge_method") == "S256"
            and re.fullmatch(r"[A-Za-z0-9_-]{43}", params.get("code_challenge", "")),
            "invalid_request", "Use S256 PKCE with a valid challenge")
    params["scope"] = scopes(params.get("scope", "tools"))
    require(set(params["scope"].split()) <= set(client["scope"].split()), "invalid_scope", "Scope exceeds registration")
    return params


async def authorize(request):
    store = request.app.state.store
    ticket = request.query_params.get("request")
    if ticket:
        with store.connect() as db:
            row = db.execute("SELECT * FROM pending WHERE id=? AND expires>?", (ticket, time.time())).fetchone()
        require(row is not None, "invalid_request", "Authorization request expired; reconnect")
        params = json.loads(row["params"])
    else:
        params = validate_authorization(request)
        ticket = secrets.token_urlsafe(24)
        with store.connect() as db:
            db.execute("INSERT INTO pending VALUES (?,?,?)", (ticket, json.dumps(params), time.time() + 600))
    user = browser_user(request)
    if not user:
        return RedirectResponse("/login?" + urlencode({"next": "/authorize?request=" + ticket}), status_code=303)
    return request.app.state.templates.TemplateResponse(request, "consent.html", {
        "user": user, "client": store.client(params["client_id"]), "params": params,
        "callback_host": urlsplit(params["redirect_uri"]).netloc,
        "ticket": ticket, "csrf": browser_session(request)["csrf"],
    })


async def consent(request):
    form = await request.form()
    try:
        check_csrf(request, form)
    except PermissionError as exc:
        raise OAuthError("invalid_request", str(exc))
    user = browser_user(request)
    require(user is not None, "access_denied", "Log in first")
    cfg = request.app.state.settings
    with request.app.state.store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM pending WHERE id=? AND expires>?", (form.get("request"), time.time())).fetchone()
        require(row is not None, "invalid_request", "Authorization request expired or already used")
        params = json.loads(row["params"])
        db.execute("DELETE FROM pending WHERE id=?", (row["id"],))
        if form.get("decision") != "allow":
            return RedirectResponse(callback_url(params, error="access_denied", iss=cfg.public_url), status_code=303)
        code = secrets.token_urlsafe(32)
        db.execute("INSERT INTO codes VALUES (?,?,?,?)", (code, user["id"], row["params"], time.time() + cfg.code_seconds))
    return RedirectResponse(callback_url(params, code=code, iss=cfg.public_url), status_code=303,
                            headers={"Cache-Control": "no-store"})


def identify_client(request, form):
    client_id, secret = form.get("client_id"), form.get("client_secret")
    auth = request.headers.get("authorization", "")
    basic = auth.lower().startswith("basic ")
    if basic:
        from urllib.parse import unquote_plus
        try:
            identifier, secret = base64.b64decode(auth.split(" ", 1)[1], validate=True).decode().split(":", 1)
            client_id, secret = unquote_plus(identifier), unquote_plus(secret)
        except (ValueError, UnicodeError):
            raise OAuthError("invalid_client", "Invalid basic credentials", 401)
    client = request.app.state.store.client(client_id)
    if not client:
        raise OAuthError("invalid_client", "Unknown client", 401)
    method = client["token_endpoint_auth_method"]
    if method != "none":
        expected_basic = method == "client_secret_basic"
        if expected_basic != basic or not secrets.compare_digest(secret or "", client["client_secret"]):
            raise OAuthError("invalid_client", "Client authentication failed", 401)
    elif basic or secret:
        raise OAuthError("invalid_client", "Public clients do not send a secret", 401)
    return client


def issue(db, cfg, user_id, client_id, resource, scope):
    access = secrets.token_urlsafe(32)
    refresh = secrets.token_urlsafe(32) if "offline_access" in scope.split() else None
    now = time.time()
    db.execute("INSERT INTO tokens VALUES (?,?,?,?,?,?,?,?)", (
        access, refresh, user_id, client_id, resource, scope,
        now + cfg.access_seconds, now + cfg.refresh_seconds))
    response = {"access_token": access, "token_type": "Bearer", "expires_in": cfg.access_seconds, "scope": scope}
    if refresh:
        response["refresh_token"] = refresh
    return response


async def token(request):
    require(request.headers.get("content-type", "").split(";")[0] == "application/x-www-form-urlencoded",
            "invalid_request", "Use application/x-www-form-urlencoded")
    form = await request.form()
    require(all(len(form.getlist(key)) == 1 for key in form), "invalid_request", "Duplicate parameters")
    client = identify_client(request, form)
    cfg = request.app.state.settings
    require(form.get("resource") == cfg.resource, "invalid_target", "Resource must match this MCP URL")
    grant = form.get("grant_type")
    require(grant in client["grant_types"], "unauthorized_client", "This client is not registered for this grant")
    with request.app.state.store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        if grant == "authorization_code":
            code = db.execute("SELECT * FROM codes WHERE id=?", (form.get("code"),)).fetchone()
            require(code and code["expires"] > time.time(), "invalid_grant", "Code expired, unknown, or already used")
            params = json.loads(code["params"])
            require(params["client_id"] == client["client_id"] and params["redirect_uri"] == form.get("redirect_uri")
                    and params["resource"] == form["resource"], "invalid_grant", "Code binding mismatch")
            verifier = form.get("code_verifier", "")
            require(re.fullmatch(r"[A-Za-z0-9._~-]{43,128}", verifier), "invalid_grant", "Invalid PKCE verifier")
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
            require(secrets.compare_digest(challenge, params["code_challenge"]), "invalid_grant", "PKCE verification failed")
            db.execute("DELETE FROM codes WHERE id=?", (code["id"],))
            result = issue(db, cfg, code["user_id"], client["client_id"], params["resource"], params["scope"])
        elif grant == "refresh_token":
            old = db.execute("SELECT * FROM tokens WHERE refresh=?", (form.get("refresh_token"),)).fetchone()
            require(old and old["refresh_expires"] > time.time(), "invalid_grant", "Refresh token expired, unknown, or used")
            require(old["client_id"] == client["client_id"] and old["resource"] == form["resource"],
                    "invalid_grant", "Refresh binding mismatch")
            scope = scopes(form.get("scope", old["scope"]))
            require(set(scope.split()) <= set(old["scope"].split()), "invalid_scope", "Cannot expand a grant on refresh")
            db.execute("DELETE FROM tokens WHERE access=?", (old["access"],))
            result = issue(db, cfg, old["user_id"], client["client_id"], old["resource"], scope)
        else:
            raise OAuthError("unsupported_grant_type", "Use authorization_code or refresh_token")
    return JSONResponse(result, headers={"Cache-Control": "no-store", "Pragma": "no-cache"})


routes = [
    Route("/.well-known/oauth-protected-resource", resource_metadata),
    Route("/.well-known/oauth-protected-resource/mcp", resource_metadata),
    Route("/.well-known/oauth-authorization-server", authorization_metadata),
    Route("/register", register, methods=["POST"]),
    Route("/authorize", authorize),
    Route("/consent", consent, methods=["POST"]),
    Route("/token", token, methods=["POST"]),
]
