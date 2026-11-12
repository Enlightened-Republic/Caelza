"""The Mind turned on from the Memory page: one tap, no Node to install, no shell.

The gateway's api_mind_install.rs does what mind/windows-install.ps1 and
mind/install.sh do, as a background job the page watches. These tests keep
the module, the patch, the page, the client, the scripts and the docs saying
the same thing; the module's own behaviour is under `cargo test -p
caelza-gateway api_mind_install`, the page's pure part under the web test list.
"""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OVERLAY = REPO_ROOT / "runtime" / "overlay"
GATEWAY = (OVERLAY / "crates" / "caelza-gateway" / "src" / "api_mind_install.rs").read_text()
PATCH = (REPO_ROOT / "runtime" / "patches" / "0017-mind-install.patch").read_text()
PAGE = (OVERLAY / "web" / "src" / "pages" / "Memory.tsx").read_text()
LOGIC = (OVERLAY / "web" / "src" / "pages" / "mind.install.logic.ts").read_text()
LOGIC_TEST = (OVERLAY / "web" / "src" / "pages" / "mind.install.logic.test.ts").read_text()
CLIENT = (OVERLAY / "web" / "src" / "lib" / "mind.ts").read_text()
MANIFEST = tomllib.loads((REPO_ROOT / "bundle" / "manifest.toml").read_text())
PS1 = (REPO_ROOT / "mind" / "windows-install.ps1").read_text()
SH = (REPO_ROOT / "mind" / "install.sh").read_text()
README = (REPO_ROOT / "README.md").read_text()
FAQ = (REPO_ROOT / "guide" / "FAQ.md").read_text()
MIND_README = (REPO_ROOT / "mind" / "README.md").read_text()
VISION = (REPO_ROOT / "docs" / "design" / "caelza-vision.md").read_text()
CORPUS = (REPO_ROOT / "guide" / "corpus.jsonl").read_text()


def squash(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def test_the_patch_registers_the_module_and_its_routes_only():
    files = re.findall(r"^\+\+\+ b/(.+)$", PATCH, flags=re.M)
    assert files == ["crates/caelza-gateway/src/lib.rs", "web/package.json"], files
    assert "src/pages/mind.share.logic.test.ts src/pages/mind.install.logic.test.ts " in PATCH
    assert "+pub mod api_mind_install;" in PATCH
    assert '+            "/api/mind/install",' in PATCH
    assert "+            get(api_mind_install::handle_install_get).post(api_mind_install::handle_install_post)," in PATCH


def test_the_node_pin_is_one_number_everywhere():
    pinned = MANIFEST["components"]["mind"]["node_version"]
    assert re.fullmatch(r"22\.\d+\.\d+", pinned), pinned
    assert f'pub const NODE_VERSION: &str = "{pinned}";' in GATEWAY
    assert "pub const NODE_MAJOR_MIN: u64 = 22;" in GATEWAY
    # The same floor the scripts enforce.
    assert "$major -lt 22" in PS1 and "node >= 22" in SH


def test_the_job_does_what_the_scripts_do_in_the_same_places():
    # Directories: the scripts' defaults.
    assert "Join-Path $env:LOCALAPPDATA 'Caelza'" in PS1
    assert '.map(|s| PathBuf::from(s).join("Caelza"))' in GATEWAY
    assert 'home.join(".local").join("share").join("caelza")' in GATEWAY
    assert 'env("CAELZA_MIND_DIR")' in GATEWAY and 'env("CAELZA_BIN_DIR")' in GATEWAY
    assert 'xanima_home.join(".xanima").join("tokens")' in GATEWAY
    # The launcher goes where caelza-launch.cmd looks: beside caelza.exe.
    assert "exe_dir.map(Path::to_path_buf).unwrap_or_else(|| base.clone())" in GATEWAY
    # The same npm line, the same project file, the same tarball check.
    assert '"install", "--omit=dev", "--no-save", "--no-audit", "--no-fund", "--loglevel=error", "./caelza-mind.tgz"' in GATEWAY
    assert "install --omit=dev --no-save --no-audit --no-fund --loglevel=error ./caelza-mind.tgz" in PS1
    assert 'l.trim() == "package/dist/cli.js"' in GATEWAY and "package/dist/cli.js" in SH
    # The same tokens: main read,write; cael read; a provision token minted as "provisioner".
    assert 'if agent == "cael" { "read" } else { "read,write" }' in GATEWAY
    assert 'wanted.push(("provision".into(), "provisioner".into(), "provision".into()));' in GATEWAY
    assert "if ($agent -eq 'provision') { $agent = 'provisioner' }" in PS1
    # Checksums: the release's .sha256, nodejs.org's SHASUMS256.txt; a mismatch installs nothing.
    assert "checksum mismatch for the Mind's package" in GATEWAY and "SHASUMS256.txt" in GATEWAY
    assert "refusing to install it unverified" in GATEWAY
    # The system tar unpacks (Windows' bsdtar reads zips), nothing new linked in.
    assert 'if cfg!(windows) { "tar.exe" } else { "tar" }' in GATEWAY
    # A Mind already answering is not started twice; the service is waited for.
    assert "not starting another" in GATEWAY and "the Mind answers on /health" in GATEWAY
    # Detached on both platforms, logging to the service log.
    assert "cmd.process_group(0);" in GATEWAY and "DETACHED_PROCESS" in GATEWAY
    assert 'logs.join("service.log")' in GATEWAY
    # The bug check's fixes: PATH is preferred by the launcher only when the install used PATH's node.
    assert "launcher_text(windows, &cli, &node, node_from_path)" in GATEWAY
    assert 'let node_from_path = node.as_os_str() == "node";' in GATEWAY
    # The Runtime reads the tokens where they are minted, on Windows too (USERPROFILE, XANIMA_HOME_OVERRIDE).
    xanima = (OVERLAY / "crates" / "caelza-memory" / "src" / "xanima.rs").read_text()
    assert 'std::env::var_os("XANIMA_HOME_OVERRIDE")' in xanima and '["USERPROFILE", "HOME"]' in xanima
    assert "fn expand_home_in(path: &str, home: Option<&Path>) -> PathBuf" in xanima
    # A half-unpacked Node is replaced; Node moves in whole; the unit on Linux; the quote in PowerShell.
    assert "let whole = exe.is_file() && npm_cli(&root, windows).is_file();" in GATEWAY
    assert "std::fs::rename(&unpacked, &root)" in GATEWAY
    assert "pub fn systemd_unit(launcher: &Path) -> String" in GATEWAY and '"enable", "caelza-mind.service"' in GATEWAY
    assert "ps_quote(&launcher.display().to_string())" in GATEWAY
    # The latest release's sum is the tarball's own; loopback health is a plain socket; an empty token file is minted again.
    assert 'let sum_name = format!("{tgz_name}.sha256");' in GATEWAY
    assert 'tokio::net::TcpStream::connect(("127.0.0.1", port))' in GATEWAY
    assert "std::fs::read_to_string(&path).map(|t| !t.trim().is_empty()).unwrap_or(false)" in GATEWAY
    assert 'let _ = std::fs::remove_dir_all(lay.base.join("tmp"));' in GATEWAY
    assert "npm_ok.then_some(program)" in GATEWAY
    assert "void load();\n    }\n  }, [load]);" in PAGE
    # The token mint's output is the token: it is never logged (the page shows the log).
    assert '"--scopes", &scopes, "--json"], Some(&lay.mind_dir), None, "tokens", true)' in GATEWAY
    assert "if !quiet {" in GATEWAY
    # One job at a time, behind the dashboard's auth, never on the phone.
    assert "an install is already running" in GATEWAY
    assert GATEWAY.count("require_auth(&state, &headers)") == 2
    assert 'if cfg!(target_os = "android")' in GATEWAY


def test_the_page_offers_the_tap_then_wires_the_backend():
    assert "<InstallCard onNote={setDevicesNote} onChanged={refresh} />" in PAGE
    assert 'data-mind-install="start"' in PAGE and 'data-mind-install="use"' in PAGE
    assert "setInfo(await startMindInstall());" in PAGE
    assert "await patchConfig(installBackendOps());" in PAGE
    assert "if (busy && info?.finished && info.ok && !wiring) void useIt();" in PAGE
    assert "window.setInterval(() => void load(), POLL_MS)" in PAGE
    assert "{info.log.slice(-8).join('\\n')}" in PAGE, "a failure shows the log's tail"
    assert "about 60 MB once" in PAGE and "nothing leaves this device" in PAGE
    assert "export function installBackendOps(): PatchOp[] {" in LOGIC
    assert "{ op: 'add', path: '/memory/backend', value: 'xanima' }" in LOGIC
    assert "apiFetch<MindInstall>('/api/mind/install', { method: 'POST' })" in CLIENT
    for name in ("stageLabel", "percent", "megabytes", "installBackendOps"):
        assert f"{name}(" in LOGIC_TEST, name


def test_the_docs_say_the_same():
    assert "## How do I turn on long-term memory on the PC?" in FAQ
    faq = squash(FAQ)
    assert "tap **Turn on memory**" in faq and "about 60 MB, once" in faq
    assert "nothing leaves the PC" in faq and "Reload daemon" in faq
    assert "On the dashboard's Memory page, tap **Turn on memory**" in README
    assert "The PowerShell line still works instead" in README
    assert "**Turned on from the Memory page: shipped.**" in MIND_README
    assert "**Shipped (turned on from the page):**" in VISION and "0017-mind-install.patch" in VISION
    assert "How do I turn on long-term memory on the PC?" in CORPUS
