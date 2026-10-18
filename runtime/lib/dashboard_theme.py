#!/usr/bin/env python3
"""Register `caelza-dark` / `caelza-light` in the dashboard theme registry and
make them the defaults.

    dashboard_theme.py <staged-runtime-tree> <brand/tokens.json>

The upstream dashboard picks its default palette from `web/src/contexts/themes.json`
(`DEFAULT_DARK_THEME` in `colorThemes.ts`), not from the `:root` fallbacks in
`index.css`, so a hex swap alone never changes what users see. This script
builds the two theme entries from brand/tokens.json, inserts them at the top of
the registry (idempotently), widens the `ColorThemeId` union, and points the
defaults at them. All other upstream themes stay selectable.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def _rgba(hex_: str, a: float) -> str:
    h = hex_.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{a:g})"


def _hexa(hex_: str, a: float) -> str:
    return f"{hex_}{int(round(a * 255)):02x}"


def theme_entries(tokens: dict) -> list[dict]:
    c = tokens["color"]
    light = c["light"]
    dark = {
        "id": "caelza-dark",
        "name": "Caelza Dark",
        "scheme": "dark",
        "preview": [c["void"], c["teal"], c["purple"], c["text_muted"], c["text"]],
        "vars": {
            "--pc-bg-base": c["void"],
            "--color-scheme": "dark",
            "--pc-bg-surface": c["bg2"],
            "--pc-bg-elevated": c["bg3"],
            "--pc-bg-input": c["void"],
            "--pc-bg-sidebar": _hexa(c["void"], 0.95),
            "--pc-bg-code": c["void"],
            "--pc-border": "rgba(255,255,255,0.08)",
            "--pc-border-strong": "rgba(255,255,255,0.15)",
            "--pc-text-primary": c["text"],
            "--pc-text-secondary": c["text_muted"],
            "--pc-text-muted": c["text_dim"],
            "--pc-text-faint": c["text_faint"],
            "--pc-scrollbar-thumb": c["bg4"],
            "--pc-scrollbar-track": c["bg2"],
            "--pc-scrollbar-thumb-hover": c["text_faint"],
            "--pc-hover": "rgba(255,255,255,0.05)",
            "--pc-hover-strong": "rgba(255,255,255,0.08)",
            "--pc-separator": "rgba(255,255,255,0.06)",
            "--pc-accent": c["teal"],
            "--pc-accent-light": c["teal_light"],
            "--pc-accent-dim": _rgba(c["teal"], 0.3),
            "--pc-accent-glow": _rgba(c["teal"], 0.1),
            "--pc-accent-rgb": c["teal_rgb"].replace(" ", ""),
        },
    }
    lt = {
        "id": "caelza-light",
        "name": "Caelza Light",
        "scheme": "light",
        "preview": [light["base"], light["teal"], c["purple"], light["text_muted"], light["text"]],
        "vars": {
            "--pc-bg-base": light["base"],
            "--color-scheme": "light",
            "--pc-bg-surface": light["surface"],
            "--pc-bg-elevated": light["elevated"],
            "--pc-bg-input": light["input"],
            "--pc-bg-sidebar": _hexa(light["base"], 0.95),
            "--pc-bg-code": light["elevated"],
            "--pc-border": "rgba(10,10,18,0.08)",
            "--pc-border-strong": "rgba(10,10,18,0.15)",
            "--pc-text-primary": light["text"],
            "--pc-text-secondary": light["text_muted"],
            "--pc-text-muted": light["text_dim"],
            "--pc-text-faint": light["text_faint"],
            "--pc-scrollbar-thumb": "#c9c9d8",
            "--pc-scrollbar-track": light["elevated"],
            "--pc-scrollbar-thumb-hover": light["text_faint"],
            "--pc-hover": "rgba(10,10,18,0.04)",
            "--pc-hover-strong": "rgba(10,10,18,0.07)",
            "--pc-separator": "rgba(10,10,18,0.06)",
            "--pc-accent": light["teal"],
            "--pc-accent-light": light["teal_light"],
            "--pc-accent-dim": _rgba(light["teal"], 0.3),
            "--pc-accent-glow": _rgba(light["teal"], 0.1),
            "--pc-accent-rgb": light["teal_rgb"].replace(" ", ""),
        },
    }
    return [dark, lt]


def patch_registry(themes_path: Path, entries: list[dict]) -> None:
    themes = json.loads(themes_path.read_text(encoding="utf-8"))
    ids = {e["id"] for e in entries}
    themes = entries + [t for t in themes if t.get("id") not in ids]
    body = ",\n".join(json.dumps(t, separators=(",", ":")) for t in themes)
    themes_path.write_text("[\n" + body + "\n]\n", encoding="utf-8")


def patch_color_themes(ts_path: Path, entries: list[dict]) -> None:
    src = ts_path.read_text(encoding="utf-8")
    union = " | ".join(f"'{e['id']}'" for e in entries)
    if "'caelza-dark'" not in src:
        src, n = re.subn(r"(export type ColorThemeId =\n)", rf"\1  | {union}\n", src, count=1)
        if n != 1:
            sys.exit("colorThemes.ts: ColorThemeId union not found; upstream layout changed")
    src, n1 = re.subn(r"export const DEFAULT_DARK_THEME: ColorThemeId = '[^']+';",
                      "export const DEFAULT_DARK_THEME: ColorThemeId = 'caelza-dark';", src)
    src, n2 = re.subn(r"export const DEFAULT_LIGHT_THEME: ColorThemeId = '[^']+';",
                      "export const DEFAULT_LIGHT_THEME: ColorThemeId = 'caelza-light';", src)
    if n1 != 1 or n2 != 1:
        sys.exit("colorThemes.ts: DEFAULT_*_THEME not found; upstream layout changed")
    ts_path.write_text(src, encoding="utf-8")


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    root, tokens_path = Path(sys.argv[1]), Path(sys.argv[2])
    tokens = json.loads(tokens_path.read_text(encoding="utf-8"))
    entries = theme_entries(tokens)
    themes_path = root / "web/src/contexts/themes.json"
    ts_path = root / "web/src/contexts/colorThemes.ts"
    if not themes_path.exists() or not ts_path.exists():
        sys.exit("dashboard theme files not found under the staged tree")
    patch_registry(themes_path, entries)
    patch_color_themes(ts_path, entries)
    print("dashboard: caelza-dark / caelza-light registered and set as defaults")


if __name__ == "__main__":
    main()
