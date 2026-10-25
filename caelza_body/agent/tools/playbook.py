"""Read-only device tools the phone playbooks (body/sops) lean on.

Four reads, all over the same adb the `device_*` tools use, all pure
inspection: nothing here changes the phone. They exist so the deterministic
part of each playbook is code, not a package list the model has to carry or a
`dumpsys` it has to eyeball:

- ``device_debloat_plan``  the curated debloat list applied to what is installed
- ``device_suspects``      sideloaded apps with the permissions malware wants
- ``device_foreground``    what is on screen right now and who installed it
- ``device_health``        identity, battery, storage, memory, uptime, heat,
                           crashes, and the new-phone checklist

The parsing lives in `caelza_body.agent.playbooks` (tested on recorded phone
output); this module only makes the adb calls. It registers into the `device`
group and needs `device.configure()` to have run.
"""
from __future__ import annotations

import shlex
from datetime import datetime, timezone

from caelza_body.agent import playbooks as pb
from caelza_body.agent import tools
from caelza_body.agent.tools import device

#: `device_suspects` inspects at most this many sideloaded packages per call.
MAX_SUSPECTS = 25


def _shell(dev: str, script: str, timeout: int = 60) -> tuple[str | None, str]:
    """Run one remote shell script uncapped; `(error, output)`. Every script
    ends in an `echo`, so a non-zero exit is adb's own (no device, offline,
    not installed, timed out), not a `grep` that found nothing."""
    out = device.adb.run_uncapped(dev, "shell", script, timeout=timeout)
    rc, body = pb.strip_exit(out)
    text = body.strip()
    if rc == -1 or (rc not in (0, None) and (not text or text.lower().startswith(("error", "adb")))):
        return f"error: adb on {dev!r}: {text[:200] or f'exit {rc}'}", ""
    return None, body


def _unknown(dev: str) -> str | None:
    return device._unknown(dev)


def _installers(dev: str, flags: str = "-3") -> tuple[str | None, dict[str, dict]]:
    err, out = _shell(dev, f"pm list packages -i {flags}; echo '@@caelza:end'")
    if err:
        return err, {}
    return None, pb.parse_packages(out)


def register() -> None:
    @tools.tool(
        "device_debloat_plan",
        "Plan a debloat: sort every installed package into remove (carrier app "
        "pushers, adware, preloaded games), disable (carrier telemetry and device "
        "management), optional (heavy first-party apps the owner may want), keep "
        "(the platform) and review (third-party apps the list does not know). "
        "Read-only; nothing is removed. `keep` is a comma-separated list of "
        "packages to leave alone whatever the list says.",
        {"type": "object",
         "properties": {"device": {"type": "string", "default": "self"},
                        "keep": {"type": "string", "default": ""}}},
    )
    def device_debloat_plan(device: str = "self", keep: str = ""):
        err = _unknown(device)
        if err:
            return err
        err, everything = _shell(device, "pm list packages; echo '@@caelza:end'")
        if err:
            return err
        all_pkgs = pb.parse_packages(everything)
        if not all_pkgs:
            return f"error: `pm list packages` returned no packages on {device!r}: {everything[:200]}"
        _, third = _shell(device, "pm list packages -3; echo '@@caelza:end'")
        _, disabled = _shell(device, "pm list packages -d; echo '@@caelza:end'")
        plan = pb.debloat_plan(all_pkgs, pb.parse_packages(third), pb.parse_packages(disabled),
                               keep.split(",") if keep else ())
        plan["device"] = device
        plan["how"] = ("remove: device_uninstall(pkg, reason) per package, which snapshots the package list first; "
                       "disable: device_disable(pkg, reason); optional: only what the owner names; "
                       "review: show the owner, touch nothing. Both reversible: `pm install-existing` / `pm enable`.")
        return plan

    @tools.tool(
        "device_suspects",
        "Malware triage, read-only: the third-party packages that did not come "
        "from an app store, each with who installed it, when, and the risk flags "
        "that matter (draws over other apps, accessibility service, device admin, "
        "notification listener, can install packages, SMS or call permissions, "
        "installed in the last `days`). Sorted highest risk first. Termux and "
        "Tailscale are known and skipped.",
        {"type": "object",
         "properties": {"device": {"type": "string", "default": "self"},
                        "days": {"type": "integer", "default": 30}}},
    )
    def device_suspects(device: str = "self", days: int = 30):
        err = _unknown(device)
        if err:
            return err
        err, third = _installers(device, "-3")
        if err:
            return err
        candidates = sorted(p for p, meta in third.items()
                            if meta.get("installer") not in pb.STORE_INSTALLERS and not pb.is_trusted_sideload(p))
        inspected = candidates[:MAX_SUSPECTS]
        script = _suspects_script(inspected)
        err, out = _shell(device, script, timeout=120)
        if err:
            return err
        sections = pb.split_sections(out, "@@caelza:")
        accessibility = pb.parse_component_list(sections.get("accessibility", ""))
        listeners = pb.parse_component_list(sections.get("listeners", ""))
        admins = pb.parse_device_admins(sections.get("admins", ""))
        now = datetime.now(timezone.utc)
        rows = []
        for pkg in inspected:
            info = pb.parse_dumpsys_package(sections.get(f"pkg {pkg}", ""))
            ops = pb.parse_appops(sections.get(f"ops {pkg}", ""))
            rows.append(pb.risk_flags(pkg, installer=third[pkg].get("installer"), info=info, appops=ops,
                                      accessibility=accessibility, admins=admins, listeners=listeners,
                                      now=now, recent_days=days))
        rows.sort(key=lambda r: (-r["score"], r["pkg"]))
        return {
            "device": device,
            "third_party": len(third),
            "sideloaded": len(candidates),
            "inspected": len(inspected),
            "truncated": len(candidates) > len(inspected),
            "suspects": rows,
            "accessibility_services": sorted(accessibility),
            "device_admins": sorted(admins),
            "notification_listeners": sorted(listeners),
            "how": ("a popup or ad you did not ask for usually comes from a `high` row: device_disable(pkg, reason) "
                    "stops it (reversible), device_appops(pkg, 'SYSTEM_ALERT_WINDOW', 'deny', reason) takes the "
                    "overlay away without removing the app. Show the owner the list before either."),
        }

    @tools.tool(
        "device_foreground",
        "What is on the screen right now: the foreground package and activity, "
        "who installed it, whether it is a system app or sideloaded, and its "
        "risk flags. Read-only. The first thing to call when the owner reports a "
        "popup they did not ask for.",
        {"type": "object",
         "properties": {"device": {"type": "string", "default": "self"}}},
    )
    def device_foreground(device: str = "self"):
        err = _unknown(device)
        if err:
            return err
        err, out = _shell(device, "dumpsys window displays 2>/dev/null | grep -E 'mCurrentFocus|mFocusedApp'; "
                                  "dumpsys activity activities 2>/dev/null | grep -E 'topResumedActivity|ResumedActivity' | head -3; "
                                  "echo '@@caelza:end'")
        if err:
            return err
        fg = pb.parse_foreground(out)
        fg["device"] = device
        pkg = fg.get("package")
        if not pkg:
            fg["note"] = fg.get("note") or "no foreground activity found"
            return fg
        q = shlex.quote(pkg)
        err, detail = _shell(device, f"pm list packages -i {q} 2>/dev/null; "
                                     f"echo '@@caelza:pkg'; dumpsys package {q} 2>/dev/null | "
                                     f"grep -E 'installerPackageName|installInitiatingPackageName|firstInstallTime|lastUpdateTime|versionName|pkgFlags=|^ *flags=|android\\.permission\\.' | head -60; "
                                     f"echo '@@caelza:ops'; appops get {q} 2>/dev/null; "
                                     f"echo '@@caelza:accessibility'; settings get secure enabled_accessibility_services; "
                                     f"echo '@@caelza:admins'; dumpsys device_policy 2>/dev/null | grep -E 'admin=|ComponentInfo' | head -10; "
                                     f"echo '@@caelza:end'")
        if err:
            fg["error"] = err
            return fg
        head, _, rest = detail.partition("@@caelza:pkg")
        installer = pb.parse_packages(head).get(pkg, {}).get("installer")
        sections = pb.split_sections("@@caelza:pkg" + rest, "@@caelza:")
        info = pb.parse_dumpsys_package(sections.get("pkg", ""))
        if installer is None:
            installer = info.get("installer")
        flags = pb.risk_flags(pkg, installer=installer, info=info, appops=pb.parse_appops(sections.get("ops", "")),
                              accessibility=pb.parse_component_list(sections.get("accessibility", "")),
                              admins=pb.parse_device_admins(sections.get("admins", "")),
                              now=datetime.now(timezone.utc))
        fg.update(flags)
        if flags["system"]:
            fg["note"] = "a system app; not a sideload"
        elif flags["sideloaded"]:
            fg["note"] = "sideloaded: not from an app store"
        return fg

    @tools.tool(
        "device_health",
        "One read of the phone's health: model and patch level, battery (level, "
        "charging, temperature, health), storage, memory, uptime, heat, the top "
        "CPU users, recent crashes, network addresses, and the new-phone setup "
        "checklist (wireless debugging, Termux and Termux:API installed and exempt "
        "from battery optimisation, Tailscale, developer options, animations). "
        "`attention` lists what to look at first. Read-only.",
        {"type": "object",
         "properties": {"device": {"type": "string", "default": "self"}}},
    )
    def device_health(device: str = "self"):
        err = _unknown(device)
        if err:
            return err
        err, out = _shell(device, pb.HEALTH_SCRIPT, timeout=90)
        if err:
            return err
        health = pb.parse_health(out)
        health["device"] = device
        if "error" in health:
            return f"error: {health['error']} on {device!r} (sections: {', '.join(health.get('sections', []))})"
        return health


def _suspects_script(pkgs: list[str]) -> str:
    parts = []
    for pkg in pkgs:
        q = shlex.quote(pkg)
        parts.append(
            f"echo '@@caelza:pkg {pkg}'; d=$(dumpsys package {q} 2>/dev/null); "
            f"echo \"$d\" | grep -E 'installerPackageName|installInitiatingPackageName|firstInstallTime|lastUpdateTime|versionName|pkgFlags=|^ *flags=' | head -8; "
            f"echo \"$d\" | grep -oE 'android\\.permission\\.[A-Z_]+' | sort -u | head -40; "
            f"echo '@@caelza:ops {pkg}'; appops get {q} 2>/dev/null"
        )
    parts.append("echo '@@caelza:accessibility'; settings get secure enabled_accessibility_services")
    parts.append("echo '@@caelza:listeners'; settings get secure enabled_notification_listeners")
    parts.append("echo '@@caelza:admins'; dumpsys device_policy 2>/dev/null | grep -E 'admin=|ComponentInfo' | head -10")
    parts.append("echo '@@caelza:end'")
    return "; ".join(parts)

