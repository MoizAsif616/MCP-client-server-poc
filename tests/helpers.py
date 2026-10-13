import base64
import hashlib
import re
import secrets
from urllib.parse import parse_qs, urlsplit

import httpx2


def hidden(html, name):
    match = re.search(r'name="' + re.escape(name) + r'" value="([^"]*)"', html)
    assert match, f"Missing hidden field {name}: {html[:300]}"
    from html import unescape
    return unescape(match[1])


async def signup(browser, origin, email, roles, password="demo-pass"):
    page = await browser.get(origin + "/signup")
    pairs = [("email", email), ("password", password), ("csrf", hidden(page.text, "csrf"))]
    pairs.extend(("roles", role) for role in roles)
    from urllib.parse import urlencode
    return await browser.post(origin + "/signup", content=urlencode(pairs),
                              headers={"Content-Type": "application/x-www-form-urlencoded"})


async def login(browser, origin, email, password="demo-pass"):
    page = await browser.get(origin + "/login")
    return await browser.post(origin + "/login", data={"email": email, "password": password,
                                                       "csrf": hidden(page.text, "csrf")})


def browser_login(email, password="demo-pass"):
    async def handler(url):
        origin = urlsplit(url)._replace(path="", query="", fragment="").geturl()
        async with httpx2.AsyncClient(follow_redirects=True) as browser:
            response = await browser.get(url)
            assert response.status_code == 200
            if 'action="/login?' in response.text:
                response = await browser.post(str(response.url), data={
                    "email": email, "password": password, "csrf": hidden(response.text, "csrf"),
                    "next": hidden(response.text, "next")})
            assert "Allow client access?" in response.text, response.text[:600]
            response = await browser.post(origin + "/consent", data={
                "csrf": hidden(response.text, "csrf"), "request": hidden(response.text, "request"),
                "decision": "allow"})
            assert response.status_code == 200, response.text
    return handler


async def register(http, origin, method="none", callback="http://127.0.0.1:9876/callback"):
    response = await http.post(origin + "/register", json={
        "client_name": "HTTP verification client", "redirect_uris": [callback],
        "token_endpoint_auth_method": method, "scope": "tools offline_access",
        "grant_types": ["authorization_code", "refresh_token"], "response_types": ["code"]})
    assert response.status_code == 201, response.text
    return response.json()


def auth_params(client, origin):
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    params = {"client_id": client["client_id"], "redirect_uri": client["redirect_uris"][0],
              "response_type": "code", "state": secrets.token_urlsafe(24), "resource": origin + "/mcp",
              "scope": "tools offline_access", "code_challenge": challenge, "code_challenge_method": "S256"}
    return params, verifier


async def get_code(browser, origin, params, decision="allow"):
    page = await browser.get(origin + "/authorize", params=params)
    assert page.status_code == 200, page.text
    response = await browser.post(origin + "/consent", data={
        "csrf": hidden(page.text, "csrf"), "request": hidden(page.text, "request"), "decision": decision})
    assert response.status_code == 303, response.text
    return parse_qs(urlsplit(response.headers["location"]).query)


async def grant(http, origin, client, params, verifier, code):
    data = {"grant_type": "authorization_code", "client_id": client["client_id"],
            "code": code, "redirect_uri": params["redirect_uri"], "code_verifier": verifier,
            "resource": params["resource"]}
    if client["token_endpoint_auth_method"] == "client_secret_post":
        data["client_secret"] = client["client_secret"]
    auth = httpx2.BasicAuth(client["client_id"], client["client_secret"]) if client["token_endpoint_auth_method"] == "client_secret_basic" else None
    return await http.post(origin + "/token", data=data, auth=auth)
