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
    # A call naming a joined Body (a phone running its own Body over HTTP)
    # runs there, as a call on that phone's `self`; everything else is local.
    from caelza_body import fleet  # local import: fleet reaches back into the tools
    forwarded = fleet.forward(name, dict(arguments))
    if forwarded is not None:
        return forwarded
    try:
        result = fn(**arguments)
    except Exception as e:  # noqa: BLE001 - surfaced to the model as text
        return f"error: {type(e).__name__}: {e}"
    return result if isinstance(result, str) else json.dumps(result)


def accept_device(prefix: str, what: str) -> None:
    """Give every registered tool named `prefix*` a `device` argument so a
    joined Body can be addressed (`dispatch` forwards those calls). Locally
    the tools stay what they are: this phone's own, so any other device name
    that reaches the local function is refused with a plain explanation."""
    for name, fn in list(REGISTRY.items()):
        if not name.startswith(prefix):
            continue
        props = _SCHEMAS[name]["function"]["parameters"].setdefault("properties", {})
        if "device" in props:
            continue
        props["device"] = {
            "type": "string", "default": "self",
            "description": "`self` (this phone) or the name of a joined Body; an ADB-paired phone cannot answer this",
        }

        def wrap(fn=fn, name=name):
            def inner(*args, device="self", **kwargs):
                if device != "self":
                    return (f"error: {name} is {what} of this phone; {device!r} answers only as a joined Body "
                            f"(device_join), not as an ADB-paired phone")
                return fn(*args, **kwargs)
            inner.__name__ = fn.__name__
            return inner

        REGISTRY[name] = wrap()


def reset():
    REGISTRY.clear()
    _SCHEMAS.clear()
    from caelza_body.agent.tools import media  # local import: avoids a circular import at load
    media.PENDING_MEDIA.clear()


from caelza_body.agent.tools.media import PENDING_MEDIA, drain, emit_image  # noqa: E402,F401
