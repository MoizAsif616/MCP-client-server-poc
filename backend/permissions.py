ROLE_TOOLS = {
    "calculator": {"add", "multiply"},
    "notes": {"save_note", "list_notes"},
    "profile": {"get_profile"},
}

ROLE_LABELS = {"calculator": "Calculator", "notes": "Notes", "profile": "Profile"}


def permitted_tools(user):
    return set().union(*(ROLE_TOOLS[role] for role in user["roles"]))


def authorize(user, tool_name):
    if tool_name not in set().union(*ROLE_TOOLS.values()):
        raise PermissionError("Unknown tool: " + str(tool_name))
    if tool_name not in permitted_tools(user):
        raise PermissionError("This role does not permit that tool")


def own_user(user, requested_id):
    if requested_id is not None and requested_id != user["id"]:
        raise PermissionError("You may only access your own data")
    return user["id"]
