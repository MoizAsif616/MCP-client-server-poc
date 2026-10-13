from typing import Annotated, Any

from mcp.server.mcpserver import Context
from pydantic import Field

from backend.authentication import principal
from backend.permissions import own_user


def add(a: float, b: float) -> float:
    """Add two numbers and return their sum."""
    return a + b


def multiply(a: float, b: float) -> float:
    """Multiply two numbers and return their product."""
    return a * b

def save_note(text: Annotated[str, Field(min_length=1, max_length=2000)], ctx: Context) -> dict[str, Any]:
    """Save a private note for the signed-in user."""
    request = ctx.request_context.request
    user = principal(request)["user"]
    with request.app.state.store.connect() as db:
        cursor = db.execute("INSERT INTO notes (user_id,text) VALUES (?,?)", (user["id"], text))
        return {"note_id": cursor.lastrowid, "text": text}


def list_notes(ctx: Context, user_id: str | None = None) -> dict[str, Any]:
    """List your private notes; another user's ID is rejected."""
    request = ctx.request_context.request
    user = principal(request)["user"]
    owner = own_user(user, user_id)
    with request.app.state.store.connect() as db:
        rows = db.execute("SELECT id,text FROM notes WHERE user_id=? ORDER BY id", (owner,)).fetchall()
    return {"user_id": owner, "notes": [dict(row) for row in rows]}


def get_profile(ctx: Context, user_id: str | None = None) -> dict[str, Any]:
    """Read your email and demo roles; another user's ID is rejected."""
    user = principal(ctx.request_context.request)["user"]
    own_user(user, user_id)
    return user


TOOLS = [add, multiply, save_note, list_notes, get_profile]

