import re
import sqlite3
from urllib.parse import urlencode

from starlette.responses import JSONResponse, RedirectResponse
from starlette.routing import Route

from backend.authentication import browser_session, browser_user, check_csrf
from backend.permissions import ROLE_LABELS, ROLE_TOOLS, permitted_tools


def next_path(value):
    return value if value.startswith("/") and not value.startswith("//") and "\\" not in value else "/"


def set_session(response, session, settings):
    response.set_cookie("session", session["id"], httponly=True, secure=settings.secure_cookies,
                        samesite="lax", max_age=settings.session_seconds)
    return response


async def account_page(request, mode, error="", status=200):
    session = browser_session(request) or request.app.state.store.new_session()
    response = request.app.state.templates.TemplateResponse(request, "account.html", {
        "mode": mode, "error": error, "roles": ROLE_LABELS, "csrf": session["csrf"],
        "next": next_path(request.query_params.get("next", "/")),
    }, status_code=status)
    return set_session(response, session, request.app.state.settings)


async def signup(request):
    if request.method == "GET":
        return await account_page(request, "signup")
    form = await request.form()
    try:
        check_csrf(request, form)
    except PermissionError as exc:
        return await account_page(request, "signup", str(exc), 403)
    email = str(form.get("email", "")).strip().lower()
    password = str(form.get("password", ""))
    roles = sorted(set(form.getlist("roles")))
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email) or not password or len(password) > 200:
        return await account_page(request, "signup", "Enter an email and a password of 1–200 characters.", 400)
    if not roles or not set(roles) <= ROLE_TOOLS.keys():
        return await account_page(request, "signup", "Select at least one valid role.", 400)
    try:
        request.app.state.store.signup(email, password, roles)
    except sqlite3.IntegrityError:
        return await account_page(request, "signup", "This email already has an account.", 409)
    target = next_path(str(form.get("next", "/")))
    return RedirectResponse("/login?" + urlencode({"next": target}), status_code=303)


async def login(request):
    if request.method == "GET":
        return await account_page(request, "login")
    form = await request.form()
    try:
        check_csrf(request, form)
    except PermissionError as exc:
        return await account_page(request, "login", str(exc), 403)
    user_id = request.app.state.store.login(str(form.get("email", "")).strip().lower(), str(form.get("password", "")))
    if not user_id:
        return await account_page(request, "login", "Email or password is incorrect.", 401)
    old = browser_session(request)
    request.app.state.store.delete_session(old["id"])
    session = request.app.state.store.new_session(user_id)
    response = RedirectResponse(next_path(str(form.get("next", "/"))), status_code=303)
    return set_session(response, session, request.app.state.settings)


async def dashboard(request):
    user = browser_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    tools = await request.app.state.mcp.list_tools()
    allowed = permitted_tools(user)
    return request.app.state.templates.TemplateResponse(request, "dashboard.html", {
        "user": user, "role_labels": ROLE_LABELS, "resource": request.app.state.settings.resource,
        "tools": [tool for tool in tools if tool.name in allowed], "csrf": browser_session(request)["csrf"],
    })


async def logout(request):
    form = await request.form()
    try:
        check_csrf(request, form)
    except PermissionError as exc:
        return JSONResponse({"error": str(exc)}, status_code=403)
    request.app.state.store.delete_session(request.cookies.get("session", ""))
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie("session")
    return response


async def health(request):
    return JSONResponse({"status": "ok", "server": request.app.state.settings.name})


routes = [Route("/", dashboard), Route("/signup", signup, methods=["GET", "POST"]),
          Route("/login", login, methods=["GET", "POST"]), Route("/logout", logout, methods=["POST"]),
          Route("/health", health)]
