from __future__ import annotations

import json

REGISTRY: dict = {}
_SCHEMAS: dict = {}


def tool(name, description, parameters):
    def deco(fn):
        REGISTRY[name] = fn
        _SCHEMAS[name] = {
            "type": "function",
            "function": {"name": name, "description": description, "parameters": parameters},
        }
        return fn
    return deco


def schemas():
    return list(_SCHEMAS.values())


def dispatch(name, arguments):
    fn = REGISTRY.get(name)
    if fn is None:
        return f"error: unknown tool {name}"
    try:
        result = fn(**arguments)
    except Exception as e:  # noqa: BLE001 - surfaced to the model as text
        return f"error: {type(e).__name__}: {e}"
    return result if isinstance(result, str) else json.dumps(result)


def reset():
    REGISTRY.clear()
    _SCHEMAS.clear()
    from niba.agent.tools import media  # local import: avoids a circular import at load
    media.PENDING_MEDIA.clear()


from niba.agent.tools.media import PENDING_MEDIA, drain, emit_image  # noqa: E402,F401
