from __future__ import annotations

PENDING_MEDIA: list[tuple[str, str]] = []


def emit_image(path: str, mime: str = "image/jpeg") -> None:
    PENDING_MEDIA.append((path, mime))


def drain() -> list[tuple[str, str]]:
    items = list(PENDING_MEDIA)
    PENDING_MEDIA.clear()
    return items
