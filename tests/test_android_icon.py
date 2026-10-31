"""The brand mark as the Android launcher icon (an M7 carry-over).

`brand/make_assets.py --android android/app` renders the adaptive icon from
brand/tokens.json: the mark alone on a transparent foreground layer, inside the
66 dp circle every launcher shape shows; the cosmic backdrop's nebula as the
background layer; both at the five densities; and the mark's silhouette as a
VectorDrawable for Android 13's themed icons and the Runtime notification's
status-bar icon. The files are committed; `--check` (the brand CI job) and the
Pillow-backed tests here keep them in step with the generator, and the rest
pins the wiring without Pillow.
"""
from __future__ import annotations

import math
import struct
import sys
import tomllib
import xml.dom.minidom
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
APP = REPO_ROOT / "android" / "app"
RES = APP / "src" / "main" / "res"
DENSITIES = {"mdpi": 108, "hdpi": 162, "xhdpi": 216, "xxhdpi": 324, "xxxhdpi": 432}   # 108 dp × the density scale


def png_size(path: Path) -> tuple[int, int]:
    head = path.read_bytes()[:24]
    assert head[:8] == b"\x89PNG\r\n\x1a\n" and head[12:16] == b"IHDR", path
    return struct.unpack(">II", head[16:24])


# --- the wiring (no Pillow needed) ----------------------------------------------

def test_the_adaptive_icon_has_both_layers_at_every_density_and_a_monochrome_vector():
    for dpi, px in DENSITIES.items():
        for layer in ("foreground", "background"):
            assert png_size(RES / f"mipmap-{dpi}" / f"ic_launcher_{layer}.png") == (px, px), (dpi, layer)
    xml = (RES / "mipmap-anydpi-v26" / "ic_launcher.xml").read_text()
    assert '<background android:drawable="@mipmap/ic_launcher_background" />' in xml
    assert '<foreground android:drawable="@mipmap/ic_launcher_foreground" />' in xml
    assert '<monochrome android:drawable="@drawable/ic_launcher_monochrome" />' in xml
    assert (APP / "src/main/AndroidManifest.xml").read_text().count('android:icon="@mipmap/ic_launcher"') == 1


def test_the_monochrome_vector_is_an_outlined_bolt_the_system_can_tint():
    mono = (RES / "drawable" / "ic_launcher_monochrome.xml").read_text()
    for name in ("drawable/ic_launcher_monochrome.xml", "mipmap-anydpi-v26/ic_launcher.xml"):
        xml.dom.minidom.parse(str(RES / name))   # aapt is strict: a "--" inside a comment fails the build
    assert "<vector" in mono and 'android:viewportWidth="108"' in mono and 'android:viewportHeight="108"' in mono
    assert 'android:strokeColor="#FFFFFFFF"' in mono and 'android:fillColor="#00000000"' in mono, \
        "the bolt is an outline, never filled (brand/BRAND.md)"
    assert mono.count('android:fillColor="#FFFFFFFF"') == 1, "the four stars, as one filled path"
    assert "gradient" not in mono and "aapt:attr" not in mono, "a single-colour alpha shape: the system tints it"
    assert not (RES / "drawable" / "ic_launcher_foreground.xml").exists(), "the placeholder ring is gone"
    service = (APP / "src/main/java/tech/enlightenedrepublic/caelza/RuntimeService.kt").read_text()
    assert ".setSmallIcon(R.drawable.ic_launcher_monochrome)" in service, "the status-bar icon is the silhouette"


def test_ci_and_the_manifest_point_at_the_generator():
    ci = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text()
    assert "python3 brand/make_assets.py --android android/app --check" in ci
    manifest = tomllib.loads((REPO_ROOT / "bundle" / "manifest.toml").read_text())
    assert manifest["android"]["launcher_icon"] == "brand/make_assets.py --android android/app"


# --- the pixels (Pillow) --------------------------------------------------------

@pytest.fixture(scope="module")
def make_assets():
    pytest.importorskip("PIL")
    sys.path.insert(0, str(REPO_ROOT / "brand"))
    import make_assets  # noqa: E402
    return make_assets


def test_the_committed_icon_is_what_the_generator_renders(make_assets):
    assert make_assets.check_android(APP) == []
    targets = make_assets.android_targets(APP)
    assert len(targets) == 2 * len(DENSITIES) + 1
    assert {p.name for p in targets} == {"ic_launcher_foreground.png", "ic_launcher_background.png", "ic_launcher_monochrome.xml"}


def test_the_check_notices_a_layer_that_drifted(make_assets, tmp_path):
    from PIL import Image
    app = tmp_path / "app"
    make_assets.render_android(app)
    assert make_assets.check_android(app) == []
    moved = app / "src/main/res/mipmap-mdpi/ic_launcher_foreground.png"
    with Image.open(moved) as im:
        shifted = im.convert("RGBA").transform(im.size, Image.AFFINE, (1, 0, 3, 0, 1, 0))
    shifted.save(moved)
    (app / "src/main/res/drawable/ic_launcher_monochrome.xml").write_text("<vector/>\n")
    (app / "src/main/res/mipmap-xxxhdpi/ic_launcher_background.png").unlink()
    drift = make_assets.check_android(app)
    assert [d.split(": ", 1)[1].split(" (")[0] for d in drift] == [
        "pixels differ", "missing", "the vector differs from the generator's"], drift


def test_the_mark_and_its_glow_stay_inside_the_safe_circle(make_assets):
    """Launchers show the centre 72 dp of the 108 dp layer and most shapes
    about 66 dp of it; nothing of the bolt may reach past that circle."""
    from PIL import Image
    for dpi, px in DENSITIES.items():
        with Image.open(RES / f"mipmap-{dpi}" / "ic_launcher_foreground.png") as im:
            alpha = im.convert("RGBA").getchannel("A").tobytes()   # one byte per pixel, row-major
        centre, radius = (px - 1) / 2, px * 33 / 108
        outside = [(i % px, i // px) for i, a in enumerate(alpha)
                   if a > 8 and math.hypot(i % px - centre, i // px - centre) > radius]
        assert not outside, f"{dpi}: {len(outside)} visible pixels outside the safe circle, e.g. {outside[:3]}"
        assert sum(1 for a in alpha if a > 128) > px * px * 0.03, f"{dpi}: the mark is there"


def test_the_background_is_the_opaque_nebula_and_the_vector_follows_the_tokens(make_assets):
    from PIL import Image
    with Image.open(RES / "mipmap-xxhdpi" / "ic_launcher_background.png") as im:
        bg = im.convert("RGBA")
    assert bg.getchannel("A").getextrema() == (255, 255), "opaque: the launcher's shape is filled"
    r, g, b, _ = bg.getpixel((162, 162))
    assert max(r, g, b) < 60 and b >= r, "space black with the violet cast, the mark's surface"
    vector = make_assets.launcher_monochrome_vector()
    side = 108 * make_assets.LAUNCHER_MARK
    off = (108 - side) / 2
    x0, y0 = make_assets.M["bolt"][0]
    assert f"M{off + x0 * side:.2f},{off + y0 * side:.2f} L" in vector, "the bolt's head where tokens.json puts it"
    assert f'android:strokeWidth="{make_assets.M["stroke"] * side * make_assets.MONO_STROKE:.2f}"' in vector
