"""The phone playbooks' deterministic half: what the SOPs lean on so the model
does not have to hold a package list in its head or eyeball `dumpsys`.

Pure functions only (no subprocesses, no adb): the curated debloat list and
its classifier, the parsers for `pm list packages`, `dumpsys package`,
`dumpsys window`, `appops get`, `dumpsys battery`, `df`, `/proc/meminfo` and
the rest of what `device_health` reads, the risk flags `device_suspects`
scores, and a reader for the SOP definitions in `body/sops/` (the same
`SOP.toml` + `SOP.md` grammar the Runtime loads). The tools in
`caelza_body/agent/tools/playbook.py` do the adb calls and feed this module;
`tests/test_playbook_evals.py` runs it over recorded phone output.
"""
from __future__ import annotations

import re
import shutil
import tomllib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# The debloat list
# ---------------------------------------------------------------------------
#
# Four classes, from least to most reversible:
#
#   remove    carrier app pushers, adware, preloaded games, partner stubs.
#             `pm uninstall --user 0`; `pm install-existing <pkg>` brings a
#             system one back, Play brings a third-party one back.
#   disable   carrier telemetry and device management. `pm disable-user`;
#             `pm enable` undoes it.
#   optional  heavy but useful first-party or carrier apps (YouTube, Chrome,
#             the Google app, visual voicemail). Listed with a reason and left
#             alone unless the owner names them at the checkpoint.
#   keep      the platform: AOSP, Play Services, radio and vendor packages,
#             Termux, Tailscale, overlays. Never offered.
#
# Anything else is `keep` when it is a system package and `review` when it is
# third-party: the owner's own apps are theirs to judge, and the plan only
# lists them. Exact names win over patterns; the first matching pattern wins.

REMOVE = {
    # carrier app pushers / adware
    "com.ironsrc.aura.tmo": "ironSource Aura: pushes carrier-sponsored apps and ads (140 MB live on the REVVL 7)",
    "com.tmobile.pr.adapt": "T-Mobile 'PR adapt': silent app installs on behalf of the carrier",
    "com.metro.minus1": "Metro '-1 screen' launcher feed (363 MB live)",
    "com.metropcs.metrozone": "MetroZone: carrier offers and app promotion (237 MB live)",
    "com.nuance.nmc.sihome.metropcs": "Nuance SiHome: carrier voice-assistant stub",
    "com.amazon.appmanager": "Amazon app manager: installs Amazon apps in the background",
    "com.amazon.storm.lightning.client.aosp": "Amazon Lightning: Fire TV remote stub, preloaded",
    "com.netflix.partner.activation": "Netflix partner activation stub (the Netflix app itself is optional)",
    "com.facebook.appmanager": "Facebook app manager: installs and updates Facebook apps silently",
    "com.facebook.services": "Facebook services stub: background install helper",
    "com.facebook.system": "Facebook system stub: background install helper",
}

DISABLE = {
    "com.tmobile.echolocate": "T-Mobile network telemetry (157 MB live)",
    "com.tmobile.echolocate.system": "T-Mobile network telemetry (76 MB live)",
    "com.tmobile.dm.cm": "T-Mobile device management client",
    "com.tmobile.dm.ms.services": "T-Mobile device management services",
    "com.verizon.mips.services": "Verizon interactive services: carrier telemetry",
    "com.att.iqi": "AT&T IQI: carrier telemetry",
    "com.sprint.ms.smf.services": "Sprint mobile services framework: carrier telemetry",
}

OPTIONAL = {
    "com.google.android.googlequicksearchbox": "the Google app, Discover feed and Assistant hotword (~400 MB live); disabling it also stops 'Hey Google'",
    "com.google.android.apps.googleassistant": "Google Assistant",
    "com.google.android.youtube": "YouTube (237 MB)",
    "com.google.android.apps.youtube.music": "YouTube Music (184 MB)",
    "com.google.android.apps.chromecast.app": "Google Home (165 MB)",
    "com.google.android.apps.messaging": "Google Messages; the default SMS app on many phones",
    "com.android.chrome": "Chrome (~750 MB with its sandboxes); Android System WebView is separate and stays",
    "com.google.android.safetycore": "Google on-device content scanning for Messages",
    "com.google.android.gm": "Gmail",
    "com.google.android.apps.docs": "Google Drive",
    "com.google.android.apps.photos": "Google Photos; often the default gallery",
    "com.google.android.apps.maps": "Google Maps",
    "com.google.android.apps.tachyon": "Google Meet (Duo)",
    "com.google.android.apps.bard": "Gemini",
    "com.google.android.videos": "Google TV / Play Movies",
    "com.google.android.apps.subscriptions.red": "Google One",
    "com.google.android.apps.wellbeing": "Digital Wellbeing",
    "com.google.android.apps.nbu.files": "Files by Google",
    "com.google.android.apps.walletnfcrel": "Google Wallet (tap to pay)",
    "com.google.android.projection.gearhead": "Android Auto",
    "com.google.ar.core": "Google Play Services for AR",
    "com.wingos.wingcamera": "the OEM camera app; the Body reaches the camera through camera2 without it",
    "com.tmobile.rsuapp": "T-Mobile remote SIM unlock; needed only to carrier-unlock the phone",
    "com.tmobile.rsusrv": "T-Mobile remote SIM unlock service; needed only to carrier-unlock the phone",
    "com.tmobile.rsuadapter.qualcomm": "T-Mobile remote SIM unlock adapter; needed only to carrier-unlock the phone",
    "com.google.android.apps.turbo": "Device Health Services (adaptive battery); keep unless you know why not",
}

#: (regex, class, why). Checked after the exact tables, first match wins.
PATTERNS: tuple[tuple[str, str, str], ...] = (
    # --- the platform: never offered
    (r"^android$", "keep", "the framework"),
    (r"^com\.android\.", "keep", "AOSP"),
    (r"^com\.google\.android\.(gms|gsf|vending|permissioncontroller|setupwizard|euicc|webview|packageinstaller|tts|as|ext|networkstack|modulemetadata|configupdater|captiveportallogin|cellbroadcast|providers|documentsui|contacts|deskclock|calculator|calendar|marvin|accessibility|overlay|safetycenter|odad|ondevicepersonalization|federatedcompute|rkpdapp|sdksandbox|adservices|appsearch|healthconnect|health|wifi|uwb|connectivity|hotspot2|partnersetup|onetimeinitializer|verifier|signature|photopicker|printservice|feedback|contactkeys|gmsintegration|inputmethod)(\.|$)", "keep", "Google platform component"),
    (r"^com\.google\.android\.apps\.(restore|safetyhub|customization|wallpaper|adm)(\.|$)", "keep", "Google platform component"),
    (r"^com\.google\.mainline\.", "keep", "Mainline module"),
    (r"^(com\.qti|com\.qualcomm|vendor\.|org\.codeaurora)", "keep", "radio / vendor component"),
    (r"^com\.termux(\.|$)", "keep", "Termux is the Body"),
    (r"^com\.tailscale\.ipn$", "keep", "Tailscale reaches the hub"),
    (r"(\.overlay|\.rro|_rro)(\.|$)", "keep", "resource overlay"),
    (r"^(com\.oem|com\.odm|com\.vendor|com\.wingtech|com\.smartsoft|com\.factory)\.", "keep", "OEM component"),
    # --- carrier app pushers / preloaded games / partner promos
    (r"^com\.aura\.oobe", "remove", "Aura out-of-box app pusher"),
    (r"^(com\.dti\.|com\.digitalturbine\.)", "remove", "Digital Turbine Ignite: carrier-sponsored app installer"),
    (r"^com\.ironsrc\.", "remove", "ironSource app pusher"),
    (r"^(com\.metro\.|com\.metropcs\.)", "remove", "Metro by T-Mobile promotion"),
    (r"^in\.playsimple\.", "remove", "preloaded game"),
    (r"^com\.vitastudio\.", "remove", "preloaded game"),
    (r"^com\.king\.candycrush", "remove", "preloaded game"),
    (r"^com\.gameloft\.", "remove", "preloaded game"),
    (r"^(com\.booking|com\.tripadvisor|flipboard\.boxer)", "remove", "partner promotion preload"),
    # --- useful carrier apps: the owner's call
    (r"^com\.tmobile\.", "optional", "T-Mobile app; keep it if you use it (voicemail, Scam Shield, the T-Life app)"),
    (r"^(com\.vzw\.|com\.verizon\.)", "optional", "Verizon app; keep it if you use it"),
    (r"^com\.att\.", "optional", "AT&T app; keep it if you use it"),
    (r"^(com\.amazon\.|com\.netflix\.|com\.microsoft\.|com\.linkedin\.|com\.spotify\.|com\.facebook\.)", "optional", "preloaded partner app; keep it if you use it"),
    (r"^com\.samsung\.android\.(bixby|app\.spage|game\.)", "optional", "Samsung extra; keep it if you use it"),
)

_COMPILED = tuple((re.compile(p), cls, why) for p, cls, why in PATTERNS)

#: Installers that count as a store. Anything else (the package installer, a
#: browser, `null` from adb or a preload) is sideloaded.
STORE_INSTALLERS = frozenset({
    "com.android.vending", "com.amazon.venezia", "com.sec.android.app.samsungapps",
    "org.fdroid.fdroid", "org.fdroid.basic", "com.aurora.store", "com.huawei.appmarket",
    "com.xiaomi.market", "com.oppo.market", "com.heytap.market",
})

#: Sideloaded on purpose on a Caelza phone; never a suspect.
TRUSTED_SIDELOADS = (re.compile(r"^com\.termux(\.|$)"), re.compile(r"^com\.tailscale\.ipn$"))


def classify(pkg: str) -> tuple[str, str]:
    """`(class, why)` for one package from the curated tables; `("", "")` when
    the lists say nothing about it."""
    for table, cls in ((REMOVE, "remove"), (DISABLE, "disable"), (OPTIONAL, "optional")):
        if pkg in table:
            return cls, table[pkg]
    for rx, cls, why in _COMPILED:
        if rx.search(pkg):
            return cls, why
    return "", ""


def debloat_plan(packages, third_party=(), disabled=(), keep=(), installers=None) -> dict:
    """Sort every installed package into remove / disable / optional / keep /
    review. `third_party` is `pm list packages -3`, `disabled` is `-d`
    (already-disabled packages are reported, not planned), `keep` is the
    owner's own never-touch list, `installers` is `{pkg: installer}` from
    `pm list packages -i`: a third-party package the owner installed from a
    store is theirs whatever the table says (the table knows Candy Crush as
    a carrier preload; `pm uninstall` would take the owner's game and its
    progress), so it goes to review, never to remove or disable."""
    third = set(third_party)
    off = set(disabled)
    installers = installers or {}
    pinned = {p.strip() for p in keep if p.strip()}
    out = {"remove": [], "disable": [], "optional": [], "review": []}
    kept = 0
    skipped = []
    for pkg in sorted(set(packages)):
        if pkg in pinned:
            kept += 1
            continue
        cls, why = classify(pkg)
        store = installers.get(pkg) if pkg in third else None
        if cls in ("remove", "disable") and store in STORE_INSTALLERS:
            out["review"].append({"pkg": pkg, "third_party": True, "installer": store,
                                  "why": f"the list calls it {why}, but it was installed from {store}, so it is the owner's own; yours to judge"})
            continue
        if cls in ("remove", "disable", "optional"):
            if pkg in off:
                skipped.append(pkg)
                continue
            item = {"pkg": pkg, "why": why, "third_party": pkg in third}
            if cls != "optional":
                item["reason"] = f"phone-debloat: {why}"
            out[cls].append(item)
        elif cls == "keep" or pkg not in third:
            kept += 1
        else:
            out["review"].append({"pkg": pkg, "why": "third-party app the list does not know; yours to judge"})
    return {
        "total": len(set(packages)),
        "third_party": len(third),
        "remove": out["remove"],
        "disable": out["disable"],
        "optional": out["optional"],
        "review": out["review"],
        "keep": kept,
        "already_disabled": skipped,
        "pinned": sorted(pinned),
    }


# ---------------------------------------------------------------------------
# Parsers for what adb returns
# ---------------------------------------------------------------------------

def strip_exit(out: str) -> tuple[int | None, str]:
    """`adb.run` prefixes its merged output with `exit N`; split that off."""
    first, _, rest = out.partition("\n")
    m = re.fullmatch(r"exit (-?\d+)", first.strip())
    if m:
        return int(m.group(1)), rest
    return None, out


def parse_packages(text: str) -> dict[str, dict]:
    """`pm list packages [-f] [-i]` → `{pkg: {"path": ..., "installer": ...}}`."""
    pkgs: dict[str, dict] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("package:"):
            continue
        body = line[len("package:"):]
        installer = None
        m = re.search(r"\s+installer=(\S+)", body)
        if m:
            installer = None if m.group(1) in ("null", "") else m.group(1)
            body = body[:m.start()]
        body = body.strip()
        path = None
        if "=" in body and body.startswith("/"):
            path, _, body = body.rpartition("=")
        if body:
            pkgs[body] = {"path": path, "installer": installer}
    return pkgs


_FOCUS = re.compile(r"\bu\d+\s+([A-Za-z][\w.]*)/([\w.$]+)")


def parse_foreground(text: str) -> dict:
    """The package and activity on screen, from `dumpsys window displays`
    (`mCurrentFocus`, `mFocusedApp`) or `dumpsys activity activities`
    (`topResumedActivity`, `ResumedActivity`)."""
    result = {"package": None, "activity": None, "note": None}
    for key in ("mCurrentFocus", "mFocusedApp", "topResumedActivity", "ResumedActivity", "mResumedActivity"):
        for line in text.splitlines():
            if key not in line:
                continue
            m = _FOCUS.search(line)
            if m:
                pkg, act = m.group(1), m.group(2)
                if act.startswith("."):
                    act = pkg + act
                result.update(package=pkg, activity=act)
                return result
            if result["note"] is not None:
                continue
            if "NotificationShade" in line or "StatusBar" in line:
                result["note"] = "the notification shade is open"
            elif "Keyguard" in line or "keyguard" in line:
                result["note"] = "the lock screen is showing"
            elif "=null" in line:
                result["note"] = "nothing has focus (screen off?)"
    return result


def parse_dumpsys_package(text: str) -> dict:
    """The few `dumpsys package <pkg>` fields the playbooks use."""
    info: dict = {"system": None, "first_install": None, "last_update": None,
                  "version": None, "installer": None, "permissions": []}
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith(("installerPackageName=", "installInitiatingPackageName=")):
            val = line.split("=", 1)[1].strip()
            if val and val != "null" and info["installer"] is None:
                info["installer"] = val
        elif line.startswith("firstInstallTime="):
            info["first_install"] = line.split("=", 1)[1].strip()
        elif line.startswith("lastUpdateTime="):
            info["last_update"] = line.split("=", 1)[1].strip()
        elif line.startswith("versionName="):
            info["version"] = line.split("=", 1)[1].strip()
        elif line.startswith(("pkgFlags=[", "flags=[")):
            info["system"] = re.search(r"\bSYSTEM\b", line.split("[", 1)[1]) is not None
        elif line.startswith("android.permission."):
            perm = line.split(":", 1)[0].split()[0]
            if perm not in info["permissions"]:
                info["permissions"].append(perm)
    return info


def parse_appops(text: str) -> dict[str, str]:
    """`appops get <pkg>` → `{OP: mode}` (`allow`, `ignore`, `deny`, `default`,
    `foreground`)."""
    ops: dict[str, str] = {}
    for raw in text.splitlines():
        m = re.match(r"\s*([A-Z_]+):\s*([a-z]+)", raw)
        if m:
            ops[m.group(1)] = m.group(2)
    return ops


def parse_component_list(text: str) -> set[str]:
    """`settings get secure enabled_accessibility_services` and friends:
    `pkg/Class:pkg2/Class2` → the set of packages."""
    text = text.strip()
    if not text or text == "null":
        return set()
    return {part.split("/", 1)[0] for part in text.split(":") if part.strip()}


_ADMIN_LINE = re.compile(r"^\s*([A-Za-z][\w.]*)/[\w.$]+:\s*$", re.M)


def parse_device_admins(text: str) -> set[str]:
    """Packages named as device admins in `dumpsys device_policy`. An
    enabled admin (the stalkerware trick) prints as `pkg/.Receiver:` under
    "Enabled Device Admins"; only a device or profile owner prints
    `admin=ComponentInfo{pkg/...}`. Both are read."""
    found = set(re.findall(r"ComponentInfo\{([\w.]+)/", text)) | set(re.findall(r"admin=([\w.]+)/", text))
    return found | set(_ADMIN_LINE.findall(text))


#: The shell-side `grep -E` that keeps the admin lines of `dumpsys device_policy`.
ADMIN_GREP = r"admin=|ComponentInfo|^ *[A-Za-z][A-Za-z0-9_.]*/[A-Za-z0-9_.$]*:$"


SENSITIVE_PERMISSIONS = {
    "android.permission.RECEIVE_SMS": "sms", "android.permission.READ_SMS": "sms",
    "android.permission.SEND_SMS": "sms", "android.permission.READ_CALL_LOG": "calls",
    "android.permission.CALL_PHONE": "calls", "android.permission.RECORD_AUDIO": "microphone",
    "android.permission.CAMERA": "camera", "android.permission.ACCESS_FINE_LOCATION": "location",
    "android.permission.READ_CONTACTS": "contacts", "android.permission.QUERY_ALL_PACKAGES": "app_list",
    "android.permission.PACKAGE_USAGE_STATS": "usage_stats",
    "android.permission.REQUEST_INSTALL_PACKAGES": "install_packages",
    "android.permission.SYSTEM_ALERT_WINDOW": "overlay",
    "android.permission.BIND_ACCESSIBILITY_SERVICE": "accessibility",
    "android.permission.BIND_DEVICE_ADMIN": "device_admin",
    "android.permission.BIND_NOTIFICATION_LISTENER_SERVICE": "notification_listener",
    "android.permission.WRITE_SETTINGS": "write_settings",
}

#: The shell-side `grep -E` that keeps the sensitive permissions of a
#: `dumpsys package` before the list is cut; an alphabetical `head` would
#: drop SEND_SMS and WRITE_SETTINGS on any app with many permissions.
SENSITIVE_PERMISSION_GREP = r"\.(" + "|".join(sorted(p.rsplit(".", 1)[1] for p in SENSITIVE_PERMISSIONS)) + ")$"

_FLAG_WEIGHT = {
    "sideloaded": 1, "recent": 1, "overlay": 2, "accessibility": 3, "device_admin": 3,
    "notification_listener": 1, "install_packages": 1, "sms": 2, "calls": 1,
    "usage_stats": 1, "microphone": 0, "camera": 0, "location": 0, "contacts": 0,
    "app_list": 0, "write_settings": 1,
}


def is_trusted_sideload(pkg: str) -> bool:
    return any(rx.search(pkg) for rx in TRUSTED_SIDELOADS)


def risk_flags(pkg: str, *, installer: str | None, info: dict, appops: dict[str, str],
               accessibility=(), admins=(), listeners=(), now: datetime | None = None,
               recent_days: int = 30) -> dict:
    """Score one third-party package. `flags` are the reasons, `risk` is
    low / medium / high. A sideloaded app with nothing else is low: the owner
    may well have put it there."""
    flags: list[str] = []
    if installer not in STORE_INSTALLERS and not is_trusted_sideload(pkg) and not info.get("system"):
        flags.append("sideloaded")  # a preload has no installer either, and is not a sideload
    if appops.get("SYSTEM_ALERT_WINDOW") == "allow":
        flags.append("overlay")
    if pkg in set(accessibility):
        flags.append("accessibility")
    if pkg in set(admins):
        flags.append("device_admin")
    if pkg in set(listeners):
        flags.append("notification_listener")
    if appops.get("REQUEST_INSTALL_PACKAGES") == "allow":
        flags.append("install_packages")
    for perm in info.get("permissions", ()):
        tag = SENSITIVE_PERMISSIONS.get(perm)
        if tag and tag not in flags and tag not in ("overlay", "accessibility", "device_admin",
                                                     "notification_listener", "install_packages"):
            flags.append(tag)
    first = info.get("first_install")
    if first and now is not None:
        try:
            when = datetime.strptime(first[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            if now - when <= timedelta(days=recent_days):
                flags.append("recent")
        except ValueError:
            pass
    score = sum(_FLAG_WEIGHT.get(f, 0) for f in flags)
    risk = "high" if score >= 5 else "medium" if score >= 2 else "low"
    return {"pkg": pkg, "installer": installer, "sideloaded": "sideloaded" in flags,
            "system": bool(info.get("system")), "first_install": first,
            "last_update": info.get("last_update"), "version": info.get("version"),
            "flags": flags, "score": score, "risk": risk}


# --- health -----------------------------------------------------------------

#: The shell the health tool runs on the phone, in one adb call. Each section is
#: fenced by a marker line so the output parses whatever a command printed.
HEALTH_MARK = "@@caelza:"

HEALTH_SCRIPT = (
    "echo '@@caelza:identity'; "
    "getprop ro.product.manufacturer; getprop ro.product.model; getprop ro.build.version.release; "
    "getprop ro.build.version.security_patch; getprop ro.build.version.sdk; "
    "echo '@@caelza:boot'; getprop ro.boot.verifiedbootstate; getprop ro.boot.flash.locked; getprop ro.debuggable; "
    "echo '@@caelza:battery'; dumpsys battery 2>/dev/null; "
    "echo '@@caelza:storage'; df -k /data 2>/dev/null; "
    "echo '@@caelza:memory'; head -5 /proc/meminfo; "
    "echo '@@caelza:uptime'; cat /proc/uptime; "
    "echo '@@caelza:thermal'; dumpsys thermalservice 2>/dev/null | grep -E 'Thermal Status|mStatus' | head -2; "
    "for z in /sys/class/thermal/thermal_zone*/temp; do cat $z 2>/dev/null; done | sort -n | tail -1; "
    "echo '@@caelza:top'; top -b -n 1 -m 6 2>/dev/null | tail -n 8; "
    "echo '@@caelza:crashes'; logcat -d -b crash -t 60 2>/dev/null | grep -E 'FATAL EXCEPTION|Process: ' | head -20; "
    "echo '@@caelza:settings'; "
    "for k in adb_wifi_enabled adb_enabled development_settings_enabled stay_on_while_plugged_in "
    "window_animation_scale transition_animation_scale animator_duration_scale package_verifier_user_consent; "
    "do echo \"$k=$(settings get global $k 2>/dev/null)\"; done; "
    "echo '@@caelza:whitelist'; dumpsys deviceidle whitelist 2>/dev/null | grep -E 'com\\.termux|com\\.tailscale'; "
    "echo '@@caelza:packages'; pm list packages 2>/dev/null | grep -E 'com\\.termux|com\\.tailscale\\.ipn'; "
    "echo '@@caelza:network'; ip -o -4 addr show 2>/dev/null | awk '{print $2, $4}'; "
    "echo '@@caelza:end'"
)

_BATTERY_STATUS = {1: "unknown", 2: "charging", 3: "discharging", 4: "not charging", 5: "full"}
_BATTERY_HEALTH = {1: "unknown", 2: "good", 3: "overheat", 4: "dead", 5: "over voltage",
                   6: "failure", 7: "cold"}


def split_sections(text: str, mark: str = HEALTH_MARK) -> dict[str, str]:
    sections: dict[str, str] = {}
    current = None
    for line in text.splitlines():
        if line.strip().startswith(mark):
            current = line.strip()[len(mark):]
            sections[current] = ""
        elif current is not None:
            sections[current] += line + "\n"
    return sections


def _kv_colon(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in text.splitlines():
        if ":" in raw:
            k, _, v = raw.strip().partition(":")
            out[k.strip()] = v.strip()
    return out


def _lines(text: str) -> list[str]:
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def _positional(text: str) -> list[str]:
    """One value per line with the positions kept: `getprop` prints an empty
    line for a property the build does not set, and a section read by
    position must not shift onto the next value."""
    lines = [ln.strip() for ln in text.splitlines()]
    while lines and not lines[-1]:
        lines.pop()
    return lines


def parse_battery(text: str) -> dict:
    kv = _kv_colon(text)
    out: dict = {}
    try:
        out["percent"] = int(kv.get("level", ""))
    except ValueError:
        out["percent"] = None
    try:
        out["status"] = _BATTERY_STATUS.get(int(kv.get("status", "")), "unknown")
    except ValueError:
        out["status"] = None
    try:
        out["health"] = _BATTERY_HEALTH.get(int(kv.get("health", "")), "unknown")
    except ValueError:
        out["health"] = None
    try:
        out["temperature_c"] = int(kv.get("temperature", "")) / 10
    except ValueError:
        out["temperature_c"] = None
    out["plugged"] = any(kv.get(k, "").lower() == "true" for k in ("AC powered", "USB powered", "Wireless powered"))
    return out


def parse_df(text: str) -> dict:
    for line in text.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 5:
            try:
                size, used, avail = (int(parts[1]), int(parts[2]), int(parts[3]))
            except ValueError:
                continue
            gb = 1024 * 1024
            return {"size_gb": round(size / gb, 1), "used_gb": round(used / gb, 1),
                    "free_gb": round(avail / gb, 1),
                    "used_percent": int(parts[4].rstrip("%")) if parts[4].rstrip("%").isdigit() else None}
    return {}


def parse_meminfo(text: str) -> dict:
    kv = {}
    for raw in text.splitlines():
        m = re.match(r"(\w+):\s+(\d+)\s*kB", raw.strip())
        if m:
            kv[m.group(1)] = int(m.group(2))
    if "MemTotal" not in kv:
        return {}
    mb = 1024
    out = {"total_mb": kv["MemTotal"] // mb}
    if "MemAvailable" in kv:
        out["available_mb"] = kv["MemAvailable"] // mb
        out["used_percent"] = round(100 * (1 - kv["MemAvailable"] / kv["MemTotal"]))
    return out


def parse_uptime(text: str) -> dict:
    try:
        secs = float(text.split()[0])
    except (IndexError, ValueError):
        return {}
    days, rem = divmod(int(secs), 86400)
    hours, rem = divmod(rem, 3600)
    return {"seconds": int(secs), "text": f"{days}d {hours}h {rem // 60}m"}


def parse_thermal(text: str) -> dict:
    out: dict = {}
    m = re.search(r"Thermal Status:\s*(\d+)|mStatus=(\d+)", text)
    if m:
        status = int(m.group(1) or m.group(2))
        out["status"] = status
        out["status_text"] = ["none", "light", "moderate", "severe", "critical", "emergency", "shutdown"][min(status, 6)]
    nums = [int(ln) for ln in _lines(text) if ln.isdigit()]
    if nums:
        hottest = max(nums)
        out["hottest_c"] = round(hottest / 1000, 1) if hottest > 1000 else hottest
    return out


def parse_top(text: str) -> list[dict]:
    rows: list[dict] = []
    header_seen = False
    cpu_idx = None
    for raw in text.splitlines():
        parts = raw.split()
        if not parts:
            continue
        if not header_seen:
            if "PID" in parts and any("CPU" in p for p in parts):
                header_seen = True
                i, token = next((i, p) for i, p in enumerate(parts) if "CPU" in p)
                # toybox prints the state and CPU columns under one header,
                # `S[%CPU]`; the rows keep them as two fields.
                cpu_idx = i + 1 if token.startswith("S") else i
            continue
        if cpu_idx is None or len(parts) <= cpu_idx:
            continue
        try:
            cpu = float(parts[cpu_idx].rstrip("%"))
        except ValueError:
            continue
        rows.append({"cpu": cpu, "name": parts[-1]})
    return rows


def parse_crashes(text: str) -> dict:
    fatal = sum(1 for ln in text.splitlines() if "FATAL EXCEPTION" in ln)
    procs = sorted({m.group(1) for m in re.finditer(r"Process:\s*([\w.:]+)", text)})
    return {"fatal_exceptions": fatal, "processes": procs}


def parse_settings_block(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in text.splitlines():
        if "=" in raw:
            k, _, v = raw.strip().partition("=")
            out[k] = v.strip()
    return out


def setup_checks(settings: dict[str, str], whitelist: str, packages: str, boot: str) -> dict:
    """The new-phone checklist as booleans the SOP can read off."""
    wl = whitelist
    pkgs = parse_packages(packages)
    boot_lines = _positional(boot)
    scales = [settings.get(k, "") for k in ("window_animation_scale", "transition_animation_scale", "animator_duration_scale")]
    return {
        "wireless_debugging": settings.get("adb_wifi_enabled") == "1",
        "adb_enabled": settings.get("adb_enabled") == "1",
        "developer_options": settings.get("development_settings_enabled") == "1",
        "stay_awake_plugged_in": settings.get("stay_on_while_plugged_in") not in ("", "0", "null"),
        "animations_off": all(s in ("0", "0.0") for s in scales) if any(scales) else False,
        "play_protect_consent": settings.get("package_verifier_user_consent") == "1",
        "termux_installed": "com.termux" in pkgs,
        "termux_api_installed": "com.termux.api" in pkgs,
        "termux_boot_installed": "com.termux.boot" in pkgs,
        "tailscale_installed": "com.tailscale.ipn" in pkgs,
        "termux_battery_unrestricted": ",com.termux," in wl or wl.rstrip().endswith(",com.termux"),
        "termux_api_battery_unrestricted": ",com.termux.api," in wl,
        "verified_boot": (boot_lines[0] or None) if boot_lines else None,
        "bootloader_locked": (boot_lines[1] == "1") if len(boot_lines) > 1 and boot_lines[1] in ("0", "1") else None,
    }


def parse_health(text: str) -> dict:
    """The whole `HEALTH_SCRIPT` output → one JSON-ready dict."""
    s = split_sections(text)
    if "end" not in s:
        return {"error": "health script did not finish", "sections": sorted(s)}
    ident = _positional(s.get("identity", ""))
    identity = {
        "manufacturer": (ident[0] or None) if len(ident) > 0 else None,
        "model": (ident[1] or None) if len(ident) > 1 else None,
        "android": (ident[2] or None) if len(ident) > 2 else None,
        "security_patch": (ident[3] or None) if len(ident) > 3 else None,
        "sdk": (ident[4] or None) if len(ident) > 4 else None,
    }
    settings = parse_settings_block(s.get("settings", ""))
    network = [ln for ln in _lines(s.get("network", "")) if not ln.startswith("lo ")]
    out = {
        "identity": identity,
        "battery": parse_battery(s.get("battery", "")),
        "storage": parse_df(s.get("storage", "")),
        "memory": parse_meminfo(s.get("memory", "")),
        "uptime": parse_uptime(s.get("uptime", "")),
        "thermal": parse_thermal(s.get("thermal", "")),
        "top": parse_top(s.get("top", "")),
        "crashes": parse_crashes(s.get("crashes", "")),
        "network": network,
        "setup": setup_checks(settings, s.get("whitelist", ""), s.get("packages", ""), s.get("boot", "")),
    }
    out["attention"] = health_attention(out)
    return out


def health_attention(h: dict) -> list[str]:
    """What a human should look at first, in plain words."""
    notes: list[str] = []
    b = h.get("battery", {})
    if b.get("percent") is not None and b["percent"] <= 15 and b.get("status") == "discharging":
        notes.append(f"battery at {b['percent']}% and discharging")
    if b.get("temperature_c") is not None and b["temperature_c"] >= 42:
        notes.append(f"battery hot: {b['temperature_c']} °C")
    if b.get("health") not in (None, "good", "unknown"):
        notes.append(f"battery health: {b['health']}")
    st = h.get("storage", {})
    if st.get("free_gb") is not None and st["free_gb"] < 2:
        notes.append(f"only {st['free_gb']} GB free")
    mem = h.get("memory", {})
    if mem.get("available_mb") is not None and mem["available_mb"] < 400:
        notes.append(f"memory tight: {mem['available_mb']} MB available")
    th = h.get("thermal", {})
    if th.get("status", 0) >= 3:
        notes.append(f"thermal status {th.get('status_text')}")
    cr = h.get("crashes", {})
    if cr.get("fatal_exceptions"):
        notes.append(f"{cr['fatal_exceptions']} crash(es) in the crash log: {', '.join(cr['processes'][:4])}")
    setup = h.get("setup", {})
    if setup.get("termux_installed") and not setup.get("termux_battery_unrestricted"):
        notes.append("Termux is not exempt from battery optimisation")
    if setup.get("verified_boot") not in (None, "", "green"):
        notes.append(f"verified boot state: {setup['verified_boot']}")
    return notes


# ---------------------------------------------------------------------------
# The SOP definitions
# ---------------------------------------------------------------------------

#: Step bullets the Runtime's parser recognises (`SopStepSyntaxKey`); anything
#: else under a step is prose appended to its body.
STEP_KEYS = (
    "tools", "allow-tools", "allow_tools", "deny-tools", "deny_tools", "requires_confirmation",
    "kind", "capability", "with", "input", "output", "when", "next", "terminal", "depends_on",
    "depends-on", "switch", "on_failure", "on-failure", "mode", "agent", "call", "prompt",
    "policy", "edit", "decide", "unless_decided",
)

_NUMBERED = re.compile(r"^(\d+)\.\s+(.*)$")
_BOLD = re.compile(r"^\*\*(.+?)\*\*\s*(?:[—–-]|:)?\s*(.*)$")


@dataclass
class Step:
    number: int
    title: str
    body: str = ""
    tools: list[str] = field(default_factory=list)
    allow_tools: list[str] = field(default_factory=list)
    requires_confirmation: bool = False
    kind: str = "execute"
    prompt: str | None = None
    extra: dict[str, str] = field(default_factory=dict)

    @property
    def gated(self) -> bool:
        return self.requires_confirmation or self.kind == "checkpoint"


def parse_sop_steps(md: str) -> list[Step]:
    """The `## Steps` section of a `SOP.md`, the way the Runtime reads it:
    numbered items in order, a bold title with the rest as body, known
    `- key: value` bullets as fields, everything else appended to the body."""
    steps: list[Step] = []
    in_steps = False
    cur: Step | None = None
    for raw in md.splitlines():
        line = raw.strip()
        if line.startswith("## "):
            if cur is not None:
                steps.append(cur)
                cur = None
            in_steps = line[3:].strip().lower() == "steps"
            continue
        if not in_steps:
            continue
        m = _NUMBERED.match(line)
        if m:
            if cur is not None:
                steps.append(cur)
            rest = m.group(2).strip()
            b = _BOLD.match(rest)
            cur = Step(number=len(steps) + 1, title=b.group(1).strip() if b else rest,
                       body=b.group(2).strip() if b else "")
            continue
        if cur is None or not line:
            continue
        if line.startswith("- "):
            bullet = line[2:].strip()
            key, sep, val = bullet.partition(":")
            key = key.strip().lower()
            if sep and key in STEP_KEYS:
                val = val.strip()
                if key == "tools":
                    cur.tools = [t.strip() for t in val.split(",") if t.strip()]
                elif key in ("allow-tools", "allow_tools"):
                    cur.allow_tools = [t.strip() for t in val.split(",") if t.strip()]
                elif key == "requires_confirmation":
                    cur.requires_confirmation = val.lower() == "true"
                elif key == "kind":
                    cur.kind = {"approval": "checkpoint"}.get(val.lower(), val.lower())
                elif key == "prompt":
                    cur.prompt = val
                else:
                    cur.extra[key] = val
                continue
        cur.body = (cur.body + "\n" + line).strip() if cur.body else line
    if cur is not None:
        steps.append(cur)
    return steps


@dataclass
class Playbook:
    name: str
    path: Path
    description: str
    version: str
    agent: str | None
    execution_mode: str | None
    triggers: list[dict]
    steps: list[Step]
    manifest: dict

    @property
    def gates(self) -> list[int]:
        return [s.number for s in self.steps if s.gated]

    @property
    def tools(self) -> set[str]:
        out: set[str] = set()
        for s in self.steps:
            out.update(s.tools)
            out.update(s.allow_tools)
        return out


def load_playbook(directory: Path) -> Playbook:
    directory = Path(directory)
    manifest = tomllib.loads((directory / "SOP.toml").read_text(encoding="utf-8"))
    meta = manifest.get("sop", {})
    md_path = directory / "SOP.md"
    steps = parse_sop_steps(md_path.read_text(encoding="utf-8")) if md_path.is_file() else []
    return Playbook(
        name=str(meta.get("name", directory.name)), path=directory,
        description=str(meta.get("description", "")), version=str(meta.get("version", "0.1.0")),
        agent=meta.get("agent"), execution_mode=meta.get("execution_mode"),
        triggers=list(manifest.get("triggers", [])), steps=steps, manifest=manifest,
    )


def shipped_root(repo_root: Path | str) -> Path:
    return Path(repo_root) / "body" / "sops"


def shipped_playbooks(repo_root: Path | str) -> list[Playbook]:
    root = shipped_root(repo_root)
    if not root.is_dir():
        return []
    return [load_playbook(d) for d in sorted(root.iterdir()) if (d / "SOP.toml").is_file()]


def install_playbooks(repo_root: Path | str, dest: Path | str, force: bool = False) -> list[tuple[str, str]]:
    """Copy the shipped SOP directories into `dest` (the Runtime's `sops_dir`,
    `~/.caelza/shared/sops` by default). Returns `(name, status)` per playbook:
    `installed`, `updated`, `unchanged`, or `kept` when the copy on disk differs
    from the shipped one and `force` is off (an owner's edits are theirs)."""
    dest = Path(dest).expanduser()
    results: list[tuple[str, str]] = []
    for pb in shipped_playbooks(repo_root):
        target = dest / pb.name
        src_files = {p.name: p.read_bytes() for p in pb.path.iterdir() if p.is_file()}
        if not target.exists():
            target.mkdir(parents=True)
            for name, data in src_files.items():
                (target / name).write_bytes(data)
            results.append((pb.name, "installed"))
            continue
        have = {p.name: p.read_bytes() for p in target.iterdir() if p.is_file()}
        if have == src_files:
            results.append((pb.name, "unchanged"))
            continue
        if not force:
            results.append((pb.name, "kept"))
            continue
        shutil.rmtree(target)
        target.mkdir(parents=True)
        for name, data in src_files.items():
            (target / name).write_bytes(data)
        results.append((pb.name, "updated"))
    return results
