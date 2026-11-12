//! Caelza: the Mind turned on from the Memory page (one tap, no Node to
//! install, no shell).
//!
//! What `mind/windows-install.ps1` and `mind/install.sh` do, done by the
//! gateway as a background job the page watches: the Mind's tarball for this
//! Caelza version from the release (its `.sha256` checked), a portable Node
//! from nodejs.org when none new enough is on PATH (the version pinned in
//! `bundle/manifest.toml`, the archive checked against `SHASUMS256.txt`),
//! `npm install --omit=dev` under the Mind's directory, the `caelza-mind`
//! launcher beside `caelza.exe` (or in `~/.local/bin`), one token per agent
//! minted into `~/.xanima/tokens`, the service started and waited for on
//! `/health`, and on Windows a Startup-folder shortcut. The page then sets
//! `memory.backend = "xanima"` through the config API and asks for the one
//! reload. The scripts stay for hubs and for anyone who prefers them; the
//! directories are the same, so either can follow the other.
//!
//! Routes (behind the dashboard's pairing auth):
//! - `GET  /api/mind/install`  whether this device can install, where things
//!   would go, what is there already, and the running job's stage, progress,
//!   log tail and error
//! - `POST /api/mind/install`  start the job (one at a time)
//!
//! Archives are unpacked with the system `tar` (Windows 10 and later ship
//! `tar.exe`, which reads zips too), so nothing new is linked in.

use super::AppState;
use super::api::require_auth;
use axum::{
    extract::State,
    http::{HeaderMap, StatusCode},
    response::{IntoResponse, Json, Response},
};
use serde::Serialize;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::{Mutex, OnceLock};
use std::time::Duration;

/// The portable Node the job fetches when none new enough is on PATH; the
/// same number is pinned in `bundle/manifest.toml` (`node_version`).
pub const NODE_VERSION: &str = "22.23.5";
/// The Mind needs Node 22 or newer.
pub const NODE_MAJOR_MIN: u64 = 22;
pub const NODE_DIST: &str = "https://nodejs.org/dist";
pub const REPO: &str = "Enlightened-Republic/Caelza";
/// The service's own port.
pub const MIND_PORT: u16 = 18790;
const LOG_KEEP: usize = 80;
const DOWNLOAD_TIMEOUT: Duration = Duration::from_secs(20 * 60);
const HEALTH_WAIT: Duration = Duration::from_secs(45);

fn error_response(status: StatusCode, message: impl Into<String>) -> Response {
    (status, Json(json!({"error": message.into()}))).into_response()
}

// --- the job's state -------------------------------------------------------------

#[derive(Debug, Clone, Serialize, Default)]
pub struct Install {
    pub running: bool,
    pub finished: bool,
    pub ok: bool,
    /// `release`, `node`, `install`, `launcher`, `tokens`, `start`, `startup`, `done`.
    pub stage: String,
    pub detail: String,
    pub done: u64,
    pub total: u64,
    pub log: Vec<String>,
    pub error: Option<String>,
    pub started_at: Option<String>,
    pub finished_at: Option<String>,
}

static JOB: OnceLock<Mutex<Install>> = OnceLock::new();

fn job() -> &'static Mutex<Install> {
    JOB.get_or_init(|| Mutex::new(Install::default()))
}

fn snapshot() -> Install {
    job().lock().map(|j| j.clone()).unwrap_or_default()
}

fn stage(stage: &str, detail: impl Into<String>) {
    let detail = detail.into();
    if let Ok(mut j) = job().lock() {
        j.stage = stage.to_string();
        j.detail = detail.clone();
        j.done = 0;
        j.total = 0;
        push_log(&mut j, &format!("[{stage}] {detail}"));
    }
}

fn log(line: impl Into<String>) {
    if let Ok(mut j) = job().lock() {
        push_log(&mut j, &line.into());
    }
}

fn push_log(j: &mut Install, line: &str) {
    for l in line.lines() {
        let l = l.trim_end();
        if l.is_empty() {
            continue;
        }
        j.log.push(l.to_string());
    }
    if j.log.len() > LOG_KEEP {
        let drop = j.log.len() - LOG_KEEP;
        j.log.drain(..drop);
    }
}

fn progress(done: u64, total: u64) {
    if let Ok(mut j) = job().lock() {
        j.done = done;
        j.total = total;
    }
}

fn now() -> String {
    chrono::Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Secs, true)
}

// --- where things go ----------------------------------------------------------------

/// The directories, the same ones the scripts use.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Layout {
    /// `%LOCALAPPDATA%\Caelza` on Windows, `$XDG_DATA_HOME/caelza` or `~/.local/share/caelza` elsewhere.
    pub base: PathBuf,
    /// `<base>/mind` (`CAELZA_MIND_DIR`): package.json, the tarball, node_modules, logs.
    pub mind_dir: PathBuf,
    /// `<base>/node`: the portable Node, one directory per version.
    pub node_dir: PathBuf,
    /// Where the launcher goes (`CAELZA_BIN_DIR`): beside `caelza.exe` on Windows, `~/.local/bin` elsewhere.
    pub bin_dir: PathBuf,
    /// `~/.xanima/tokens` (`XANIMA_HOME_OVERRIDE` honoured, as the service does).
    pub tokens_dir: PathBuf,
}

/// The layout from the given environment: testable without touching this process's.
pub fn layout_for(
    env: &dyn Fn(&str) -> Option<String>,
    home: Option<&Path>,
    exe_dir: Option<&Path>,
    windows: bool,
) -> Layout {
    let home = home.map(Path::to_path_buf).unwrap_or_else(|| PathBuf::from("."));
    let base = if windows {
        env("LOCALAPPDATA")
            .filter(|s| !s.is_empty())
            .map(|s| PathBuf::from(s).join("Caelza"))
            .unwrap_or_else(|| home.join(".local").join("share").join("caelza"))
    } else {
        env("XDG_DATA_HOME")
            .filter(|s| !s.is_empty())
            .map(|s| PathBuf::from(s).join("caelza"))
            .unwrap_or_else(|| home.join(".local").join("share").join("caelza"))
    };
    let mind_dir = env("CAELZA_MIND_DIR")
        .filter(|s| !s.is_empty())
        .map(PathBuf::from)
        .unwrap_or_else(|| base.join("mind"));
    let bin_dir = env("CAELZA_BIN_DIR")
        .filter(|s| !s.is_empty())
        .map(PathBuf::from)
        .unwrap_or_else(|| {
            if windows {
                exe_dir.map(Path::to_path_buf).unwrap_or_else(|| base.clone())
            } else {
                home.join(".local").join("bin")
            }
        });
    let xanima_home = env("XANIMA_HOME_OVERRIDE")
        .filter(|s| !s.is_empty())
        .map(PathBuf::from)
        .unwrap_or_else(|| home.clone());
    Layout {
        node_dir: base.join("node"),
        base,
        mind_dir,
        bin_dir,
        tokens_dir: xanima_home.join(".xanima").join("tokens"),
    }
}

fn home_dir() -> Option<PathBuf> {
    let order: [&str; 2] = if cfg!(windows) {
        ["USERPROFILE", "HOME"]
    } else {
        ["HOME", "USERPROFILE"]
    };
    order
        .iter()
        .find_map(|key| std::env::var_os(key).filter(|h| !h.is_empty()))
        .map(PathBuf::from)
}

/// This process's layout.
pub fn layout() -> Layout {
    let exe_dir = std::env::current_exe()
        .ok()
        .and_then(|p| p.parent().map(Path::to_path_buf));
    let home = home_dir();
    layout_for(
        &|k| std::env::var(k).ok(),
        home.as_deref(),
        exe_dir.as_deref(),
        cfg!(windows),
    )
}

// --- the archives ---------------------------------------------------------------------

/// A portable Node archive for one platform.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NodeAsset {
    /// `node-v22.23.5-linux-x64.tar.gz`, `node-v22.23.5-win-x64.zip`, …
    pub name: String,
    /// The directory the archive unpacks to.
    pub root: String,
    pub zip: bool,
}

/// The Node archive for `os`/`arch` (`std::env::consts` names), none where
/// nodejs.org has no build (Android: Termux's own `pkg install nodejs`).
pub fn node_asset(version: &str, os: &str, arch: &str) -> Option<NodeAsset> {
    let (plat, zip) = match (os, arch) {
        ("windows", "x86_64") => ("win-x64", true),
        ("windows", "aarch64") => ("win-arm64", true),
        ("linux", "x86_64") => ("linux-x64", false),
        ("linux", "aarch64") => ("linux-arm64", false),
        ("macos", "x86_64") => ("darwin-x64", false),
        ("macos", "aarch64") => ("darwin-arm64", false),
        _ => return None,
    };
    let root = format!("node-v{version}-{plat}");
    Some(NodeAsset {
        name: format!("{root}.{}", if zip { "zip" } else { "tar.gz" }),
        root,
        zip,
    })
}

/// Where `node` lives inside an unpacked archive.
pub fn node_exe(root: &Path, windows: bool) -> PathBuf {
    if windows {
        root.join("node.exe")
    } else {
        root.join("bin").join("node")
    }
}

/// Where npm's entry point lives inside an unpacked archive.
pub fn npm_cli(root: &Path, windows: bool) -> PathBuf {
    if windows {
        root.join("node_modules").join("npm").join("bin").join("npm-cli.js")
    } else {
        root.join("lib")
            .join("node_modules")
            .join("npm")
            .join("bin")
            .join("npm-cli.js")
    }
}

/// The sum for `name` out of a `SHASUMS256.txt` (`<hex>  <name>` lines).
pub fn parse_shasums(text: &str, name: &str) -> Option<String> {
    text.lines().find_map(|line| {
        let mut parts = line.split_whitespace();
        let sum = parts.next()?;
        let file = parts.next()?;
        (file == name && sum.len() == 64).then(|| sum.to_ascii_lowercase())
    })
}

/// The first field of a `.sha256` file (`<hex>  <name>`), as the release writes it.
pub fn parse_sha256_file(text: &str) -> Option<String> {
    let sum = text.split_whitespace().next()?;
    (sum.len() == 64 && sum.chars().all(|c| c.is_ascii_hexdigit())).then(|| sum.to_ascii_lowercase())
}

/// The release asset and its sum for a Caelza version.
pub fn mind_urls(version: &str) -> (String, String) {
    let v = version.trim().trim_start_matches('v');
    let base = format!("https://github.com/{REPO}/releases/download/v{v}/caelza-mind-{v}.tgz");
    (base.clone(), format!("{base}.sha256"))
}

/// The launcher. When the install used the `node` on PATH, the launcher
/// does too (a version manager moves it, as the scripts allow). When the
/// install fetched a portable Node because PATH had none new enough, the
/// launcher runs that one and nothing else: preferring PATH would hand the
/// service back to the Node the install rejected on its next start.
pub fn launcher_text(windows: bool, cli: &Path, node: &Path, prefer_path: bool) -> String {
    if windows {
        let mut lines = vec![
            "@echo off".to_string(),
            "rem Caelza Mind: xanima-server, installed from the Memory page".to_string(),
            format!("set \"NODE={}\"", node.display()),
        ];
        if prefer_path {
            lines.push("where node >nul 2>&1 && set \"NODE=node\"".to_string());
        }
        lines.push(format!("\"%NODE%\" \"{}\" %*", cli.display()));
        lines.join("\r\n") + "\r\n"
    } else if prefer_path {
        format!(
            "#!/bin/sh\n# Caelza Mind: xanima-server, installed from the Memory page\nnode=$(command -v node 2>/dev/null || printf '%s' \"{}\")\nexec \"$node\" \"{}\" \"$@\"\n",
            node.display(),
            cli.display()
        )
    } else {
        format!(
            "#!/bin/sh\n# Caelza Mind: xanima-server, installed from the Memory page (its own Node: PATH had none new enough)\nexec \"{}\" \"{}\" \"$@\"\n",
            node.display(),
            cli.display()
        )
    }
}

/// The systemd user unit install.sh writes on a Linux hub.
pub fn systemd_unit(launcher: &Path) -> String {
    format!(
        "[Unit]\nDescription=Caelza Mind (xanima-server, the brain service on 127.0.0.1:18790)\nAfter=network.target\n[Service]\nExecStart=\"{}\" serve\nRestart=on-failure\nRestartSec=5\n[Install]\nWantedBy=default.target\n",
        launcher.display()
    )
}

/// A path inside a single-quoted PowerShell literal: the quote doubled.
pub fn ps_quote(text: &str) -> String {
    text.replace('\'', "''")
}

/// The Caelza version this build answers to (the tag's, stamped at release).
pub fn caelza_version() -> &'static str {
    env!("CARGO_PKG_VERSION")
}

/// Whether this device can install the Mind, and why not.
pub fn can_install() -> (bool, String) {
    if cfg!(target_os = "android") {
        return (false, "The phone app joins a Mind instead of running one: share it from the device that runs it.".to_string());
    }
    match node_asset(NODE_VERSION, std::env::consts::OS, std::env::consts::ARCH) {
        Some(_) => (true, String::new()),
        None => (
            false,
            format!(
                "No portable Node build for {}/{}; install Node 22 and run mind/install.sh.",
                std::env::consts::OS,
                std::env::consts::ARCH
            ),
        ),
    }
}

// --- helpers ----------------------------------------------------------------------------

/// Download `url` to `dest`, reporting progress; the file's sha256.
async fn download(url: &str, dest: &Path, label: &str) -> Result<String, String> {
    let client = caelza_config::schema::build_runtime_proxy_client("mind.install");
    let response = client
        .get(url)
        .header("user-agent", "caelza-mind-installer")
        .header("accept", "application/octet-stream")
        .timeout(DOWNLOAD_TIMEOUT)
        .send()
        .await
        .map_err(|e| format!("{label}: GET {url} failed: {e}"))?;
    let status = response.status();
    if !status.is_success() {
        return Err(format!("{label}: GET {url} answered {status}"));
    }
    let total = response.content_length().unwrap_or(0);
    if let Some(parent) = dest.parent() {
        std::fs::create_dir_all(parent).map_err(|e| format!("creating {}: {e}", parent.display()))?;
    }
    let mut file = std::fs::File::create(dest).map_err(|e| format!("creating {}: {e}", dest.display()))?;
    let mut hasher = Sha256::new();
    let mut done = 0u64;
    let mut response = response;
    loop {
        let chunk = response
            .chunk()
            .await
            .map_err(|e| format!("{label}: reading {url}: {e}"))?;
        let Some(bytes) = chunk else { break };
        file.write_all(&bytes).map_err(|e| format!("writing {}: {e}", dest.display()))?;
        hasher.update(&bytes);
        done += bytes.len() as u64;
        progress(done, total.max(done));
    }
    file.flush().map_err(|e| e.to_string())?;
    Ok(hex::encode(hasher.finalize()))
}

async fn fetch_text(url: &str, label: &str) -> Result<String, String> {
    let client = caelza_config::schema::build_runtime_proxy_client("mind.install");
    let response = client
        .get(url)
        .header("user-agent", "caelza-mind-installer")
        .header("accept", "application/vnd.github+json, text/plain, */*")
        .timeout(Duration::from_secs(60))
        .send()
        .await
        .map_err(|e| format!("{label}: GET {url} failed: {e}"))?;
    let status = response.status();
    if !status.is_success() {
        return Err(format!("{label}: GET {url} answered {status}"));
    }
    response
        .text()
        .await
        .map_err(|e| format!("{label}: reading {url}: {e}"))
}

/// Run a command, log its output (unless `quiet`: the token mint's output
/// is a secret), fail on a non-zero exit.
async fn run(program: &Path, args: &[&str], cwd: Option<&Path>, path_prefix: Option<&Path>, label: &str, quiet: bool) -> Result<String, String> {
    let mut cmd = tokio::process::Command::new(program);
    cmd.args(args).stdin(std::process::Stdio::null());
    if let Some(cwd) = cwd {
        cmd.current_dir(cwd);
    }
    if let Some(prefix) = path_prefix {
        let sep = if cfg!(windows) { ";" } else { ":" };
        let old = std::env::var("PATH").unwrap_or_default();
        cmd.env("PATH", format!("{}{sep}{old}", prefix.display()));
    }
    #[cfg(windows)]
    cmd.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
    let out = cmd
        .output()
        .await
        .map_err(|e| format!("{label}: could not run {}: {e}", program.display()))?;
    let text = format!("{}{}", String::from_utf8_lossy(&out.stdout), String::from_utf8_lossy(&out.stderr));
    if !quiet {
        for line in text.lines().rev().take(12).collect::<Vec<_>>().into_iter().rev() {
            log(format!("  {line}"));
        }
    }
    if !out.status.success() {
        return Err(format!("{label}: {} exited {}", program.display(), out.status));
    }
    Ok(text)
}

/// Unpack with the system tar (a zip too, on Windows' bsdtar).
async fn extract(archive: &Path, into: &Path, zip: bool) -> Result<(), String> {
    std::fs::create_dir_all(into).map_err(|e| format!("creating {}: {e}", into.display()))?;
    let flag = if zip { "-xf" } else { "-xzf" };
    let tar = PathBuf::from(if cfg!(windows) { "tar.exe" } else { "tar" });
    run(
        &tar,
        &[flag, &archive.display().to_string(), "-C", &into.display().to_string()],
        None,
        None,
        "unpack",
        false,
    )
    .await
    .map(|_| ())
}

/// `node` on PATH when it is new enough and its `npm` is beside it; else
/// the portable one is fetched.
async fn node_on_path() -> Option<PathBuf> {
    let program = PathBuf::from("node");
    let out = tokio::process::Command::new(&program)
        .args(["-p", "process.versions.node"])
        .stdin(std::process::Stdio::null())
        .output()
        .await
        .ok()?;
    if !out.status.success() {
        return None;
    }
    let version = String::from_utf8_lossy(&out.stdout).trim().to_string();
    let major: u64 = version.split('.').next()?.parse().ok()?;
    if major < NODE_MAJOR_MIN {
        return None;
    }
    let npm = if cfg!(windows) { "npm.cmd" } else { "npm" };
    let npm_ok = tokio::process::Command::new(npm)
        .arg("--version")
        .stdin(std::process::Stdio::null())
        .output()
        .await
        .map(|o| o.status.success())
        .unwrap_or(false);
    npm_ok.then_some(program)
}

/// `GET /health` on loopback over a plain socket: the Runtime's proxied
/// client could send 127.0.0.1 through a configured proxy.
async fn health(port: u16) -> bool {
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    let probe = async {
        let mut stream = tokio::net::TcpStream::connect(("127.0.0.1", port)).await.ok()?;
        stream
            .write_all(format!("GET /health HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n").as_bytes())
            .await
            .ok()?;
        let mut head = [0u8; 64];
        let n = stream.read(&mut head).await.ok()?;
        let line = String::from_utf8_lossy(&head[..n]);
        Some(line.starts_with("HTTP/1.1 200") || line.starts_with("HTTP/1.0 200"))
    };
    matches!(tokio::time::timeout(Duration::from_secs(3), probe).await, Ok(Some(true)))
}

fn write_owner_only(path: &Path, text: &str) -> Result<(), String> {
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|e| format!("creating {}: {e}", parent.display()))?;
    }
    std::fs::write(path, text).map_err(|e| format!("writing {}: {e}", path.display()))?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600))
            .map_err(|e| format!("chmod {}: {e}", path.display()))?;
    }
    Ok(())
}

/// The installed service's entry point, when the install is there.
pub fn installed_cli(lay: &Layout) -> Option<PathBuf> {
    let cli = lay
        .mind_dir
        .join("node_modules")
        .join("xanima-server")
        .join("dist")
        .join("cli.js");
    cli.is_file().then_some(cli)
}

/// The scopes each agent's token carries: Cael reads, the others read and write.
pub fn scopes_for(agent: &str) -> &'static str {
    if agent == "cael" { "read" } else { "read,write" }
}

// --- the job ----------------------------------------------------------------------------

async fn run_install(agents: Vec<String>) -> Result<(), String> {
    let lay = layout();
    let windows = cfg!(windows);
    std::fs::create_dir_all(&lay.mind_dir).map_err(|e| format!("creating {}: {e}", lay.mind_dir.display()))?;
    // A crashed job's leftovers (another pid's work dir, a part-written archive) go first.
    let _ = std::fs::remove_dir_all(lay.base.join("tmp"));
    let work = lay.base.join("tmp").join(format!("mind-install-{}", std::process::id()));
    std::fs::create_dir_all(&work).map_err(|e| format!("creating {}: {e}", work.display()))?;

    // 1. The Mind's tarball: an archive given for the tests, else this version's release, else the latest.
    stage("release", "finding the Mind's package");
    let tgz = lay.mind_dir.join("caelza-mind.tgz");
    if let Some(given) = std::env::var_os("CAELZA_MIND_ARCHIVE").filter(|s| !s.is_empty()) {
        let given = PathBuf::from(given);
        if !given.is_file() {
            return Err(format!("CAELZA_MIND_ARCHIVE names no file: {}", given.display()));
        }
        std::fs::copy(&given, &tgz).map_err(|e| format!("copying {}: {e}", given.display()))?;
        log(format!("using {}", given.display()));
    } else {
        let (url, sha_url) = mind_urls(caelza_version());
        let (url, sha_url) = match fetch_text(&sha_url, "release").await {
            Ok(text) => (url, text),
            Err(e) => {
                log(format!("{e}; looking up the latest release"));
                let api = format!("https://api.github.com/repos/{REPO}/releases/latest");
                let rel: Value = serde_json::from_str(&fetch_text(&api, "release").await?)
                    .map_err(|e| format!("release: {api}: {e}"))?;
                let assets = rel.get("assets").and_then(Value::as_array).cloned().unwrap_or_default();
                let find = |pred: &dyn Fn(&str) -> bool| -> Option<String> {
                    assets.iter().find_map(|a| {
                        let name = a.get("name")?.as_str()?;
                        if !pred(name) {
                            return None;
                        }
                        a.get("browser_download_url")?.as_str().map(str::to_string)
                    })
                };
                let tgz_url = find(&|n| n.starts_with("caelza-mind-") && n.ends_with(".tgz"))
                    .ok_or_else(|| format!("the latest release ({}) has no caelza-mind-<version>.tgz", rel.get("tag_name").and_then(Value::as_str).unwrap_or("?")))?;
                let tgz_name = tgz_url.rsplit('/').next().unwrap_or_default().to_string();
                let sum_name = format!("{tgz_name}.sha256");
                let sum_url = find(&|n| n == sum_name)
                    .ok_or_else(|| format!("the latest release has no {sum_name} beside the Mind's package; refusing to install it unverified"))?;
                (tgz_url, fetch_text(&sum_url, "release").await?)
            }
        };
        let want = parse_sha256_file(&sha_url).ok_or_else(|| "the release's .sha256 is not a sum".to_string())?;
        stage("release", format!("downloading {}", url.rsplit('/').next().unwrap_or("the Mind")));
        let got = download(&url, &tgz, "release").await?;
        if got != want {
            let _ = std::fs::remove_file(&tgz);
            return Err(format!("checksum mismatch for the Mind's package: expected {want}, got {got}; not installing"));
        }
        log("checksum ok");
    }
    let listing = run(&PathBuf::from(if windows { "tar.exe" } else { "tar" }), &["-tzf", &tgz.display().to_string()], None, None, "release", true).await?;
    if !listing.lines().any(|l| l.trim() == "package/dist/cli.js") {
        return Err("that is not a caelza-mind package (no package/dist/cli.js inside)".to_string());
    }

    // 2. Node: PATH when new enough, else a portable one (an archive given for the tests, else nodejs.org).
    stage("node", "looking for Node 22");
    let node: PathBuf = if let Some(found) = node_on_path().await {
        log("node 22+ is on PATH; using it");
        found
    } else {
        let asset = node_asset(NODE_VERSION, std::env::consts::OS, std::env::consts::ARCH)
            .ok_or_else(|| format!("no portable Node for {}/{}", std::env::consts::OS, std::env::consts::ARCH))?;
        let root = lay.node_dir.join(&asset.root);
        let exe = node_exe(&root, windows);
        let whole = exe.is_file() && npm_cli(&root, windows).is_file();
        if whole {
            log(format!("portable Node already at {}", root.display()));
        } else {
            if root.exists() {
                log("a half-unpacked Node from before goes first");
                std::fs::remove_dir_all(&root).map_err(|e| format!("removing {}: {e}", root.display()))?;
            }
            let archive = work.join(&asset.name);
            if let Some(given) = std::env::var_os("CAELZA_NODE_ARCHIVE").filter(|s| !s.is_empty()) {
                let given = PathBuf::from(given);
                if !given.is_file() {
                    return Err(format!("CAELZA_NODE_ARCHIVE names no file: {}", given.display()));
                }
                std::fs::copy(&given, &archive).map_err(|e| format!("copying {}: {e}", given.display()))?;
                log(format!("using {}", given.display()));
            } else {
                let sums = fetch_text(&format!("{NODE_DIST}/v{NODE_VERSION}/SHASUMS256.txt"), "node").await?;
                let want = parse_shasums(&sums, &asset.name)
                    .ok_or_else(|| format!("nodejs.org lists no sum for {}", asset.name))?;
                stage("node", format!("downloading Node {NODE_VERSION} ({})", asset.name));
                let got = download(&format!("{NODE_DIST}/v{NODE_VERSION}/{}", asset.name), &archive, "node").await?;
                if got != want {
                    return Err(format!("checksum mismatch for {}: expected {want}, got {got}; not installing", asset.name));
                }
                log("checksum ok");
            }
            stage("node", "unpacking Node");
            let unpack = work.join("node");
            extract(&archive, &unpack, asset.zip).await?;
            let unpacked = unpack.join(&asset.root);
            if !node_exe(&unpacked, windows).is_file() || !npm_cli(&unpacked, windows).is_file() {
                return Err(format!("the Node archive left no node or npm under {}", unpacked.display()));
            }
            std::fs::create_dir_all(&lay.node_dir).map_err(|e| format!("creating {}: {e}", lay.node_dir.display()))?;
            // Whole or not at all: it moves in only once both are there.
            std::fs::rename(&unpacked, &root).map_err(|e| format!("moving Node into {}: {e}", root.display()))?;
        }
        exe
    };
    let node_from_path = node.as_os_str() == "node";
    let node_bin_dir = node.parent().map(Path::to_path_buf);

    // 3. npm install: a minimal project around the tarball, the way the scripts make it.
    stage("install", "installing the Mind (npm install --omit=dev; the native sqlite modules are prebuilt)");
    let pkg = lay.mind_dir.join("package.json");
    if !pkg.is_file() {
        std::fs::write(
            &pkg,
            "{\n  \"name\": \"caelza-mind\",\n  \"private\": true,\n  \"description\": \"the Caelza Mind: xanima-server, installed from the Memory page\"\n}\n",
        )
        .map_err(|e| format!("writing {}: {e}", pkg.display()))?;
    }
    let npm = if node.as_os_str() == "node" {
        PathBuf::from("npm")
    } else {
        let root = if windows { node.parent() } else { node.parent().and_then(Path::parent) }
            .map(Path::to_path_buf)
            .unwrap_or_default();
        npm_cli(&root, windows)
    };
    let mut args: Vec<String> = Vec::new();
    let program = if npm.as_os_str() == "npm" {
        PathBuf::from(if windows { "npm.cmd" } else { "npm" })
    } else {
        args.push(npm.display().to_string());
        node.clone()
    };
    for a in ["install", "--omit=dev", "--no-save", "--no-audit", "--no-fund", "--loglevel=error", "./caelza-mind.tgz"] {
        args.push(a.to_string());
    }
    let arg_refs: Vec<&str> = args.iter().map(String::as_str).collect();
    run(&program, &arg_refs, Some(&lay.mind_dir), node_bin_dir.as_deref().filter(|_| node.as_os_str() != "node"), "install", false)
        .await
        .map_err(|e| format!("{e}. The Mind needs a network path to registry.npmjs.org."))?;
    let cli = installed_cli(&lay).ok_or_else(|| "the install left no node_modules/xanima-server/dist/cli.js".to_string())?;

    // 4. The launcher beside caelza.exe (or in ~/.local/bin).
    stage("launcher", "writing the caelza-mind launcher");
    let launcher = lay.bin_dir.join(if windows { "caelza-mind.cmd" } else { "caelza-mind" });
    std::fs::create_dir_all(&lay.bin_dir).map_err(|e| format!("creating {}: {e}", lay.bin_dir.display()))?;
    std::fs::write(&launcher, launcher_text(windows, &cli, &node, node_from_path)).map_err(|e| format!("writing {}: {e}", launcher.display()))?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let _ = std::fs::set_permissions(&launcher, std::fs::Permissions::from_mode(0o755));
    }
    log(format!("launcher -> {}", launcher.display()));

    // 5. The Runtime's tokens: one per agent, minted once (files found are kept).
    stage("tokens", "minting the Runtime's tokens");
    let mut wanted: Vec<(String, String, String)> = agents
        .iter()
        .map(|a| (a.clone(), a.clone(), scopes_for(a).to_string()))
        .collect();
    if !agents.iter().any(|a| a == "main") {
        wanted.push(("main".into(), "main".into(), "read,write".into()));
    }
    wanted.push(("provision".into(), "provisioner".into(), "provision".into()));
    let mut minted = Vec::new();
    for (file, agent, scopes) in wanted {
        let path = lay.tokens_dir.join(format!("{file}.token"));
        // A file with a token in it is kept; an empty one (a write that died) is minted again.
        if std::fs::read_to_string(&path).map(|t| !t.trim().is_empty()).unwrap_or(false) {
            continue;
        }
        // Quiet: the reply is the token itself, which never goes into the log the page shows.
        let out = run(&node, &[&cli.display().to_string(), "token", "mint", "--agent", &agent, "--scopes", &scopes, "--json"], Some(&lay.mind_dir), None, "tokens", true).await?;
        let json_start = out.find('{').ok_or_else(|| format!("token mint for {agent} answered no JSON"))?;
        let parsed: Value = serde_json::from_str(out[json_start..].trim())
            .map_err(|e| format!("token mint for {agent}: {e}"))?;
        let token = parsed
            .get("token")
            .and_then(Value::as_str)
            .filter(|t| !t.is_empty())
            .ok_or_else(|| format!("token mint for {agent} answered no token"))?;
        write_owner_only(&path, &format!("{token}\n"))?;
        minted.push(file);
    }
    log(if minted.is_empty() {
        format!("tokens already in {}", lay.tokens_dir.display())
    } else {
        format!("tokens -> {} ({})", lay.tokens_dir.display(), minted.join(", "))
    });

    // 6. Start the service, unless one already answers.
    stage("start", "starting the Mind");
    if health(MIND_PORT).await {
        log(format!("a Mind already answers on 127.0.0.1:{MIND_PORT}; not starting another"));
    } else {
        let logs = lay.mind_dir.join("logs");
        std::fs::create_dir_all(&logs).map_err(|e| format!("creating {}: {e}", logs.display()))?;
        let log_file = std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(logs.join("service.log"))
            .map_err(|e| format!("opening the service log: {e}"))?;
        let err_file = log_file.try_clone().map_err(|e| e.to_string())?;
        let mut cmd = std::process::Command::new(&node);
        cmd.arg(&cli)
            .arg("serve")
            .current_dir(&lay.mind_dir)
            .stdin(std::process::Stdio::null())
            .stdout(log_file)
            .stderr(err_file);
        #[cfg(unix)]
        {
            use std::os::unix::process::CommandExt;
            cmd.process_group(0);
        }
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            cmd.creation_flags(0x0000_0008 | 0x0000_0200 | 0x0800_0000); // DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
        }
        let child = cmd.spawn().map_err(|e| format!("starting the Mind: {e}"))?;
        log(format!("started (pid {}); waiting for it to answer", child.id()));
        drop(child);
        let deadline = std::time::Instant::now() + HEALTH_WAIT;
        let mut up = false;
        while std::time::Instant::now() < deadline {
            if health(MIND_PORT).await {
                up = true;
                break;
            }
            tokio::time::sleep(Duration::from_millis(700)).await;
        }
        if !up {
            return Err(format!("the Mind did not answer on 127.0.0.1:{MIND_PORT} within {} s; see {}", HEALTH_WAIT.as_secs(), logs.join("service.log").display()));
        }
        log("the Mind answers on /health");
    }

    // 7. Start at logon: the Startup shortcut on Windows, the systemd user unit on a
    //    Linux hub (what install.sh writes with CAELZA_SERVICE=1); best effort both.
    if windows {
        stage("startup", "adding the Startup shortcut");
        let script = format!(
            "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([IO.Path]::Combine([Environment]::GetFolderPath('Startup'),'Caelza Mind.lnk')); $s.TargetPath=$env:ComSpec; $s.Arguments='/c start \"Caelza Mind\" /min \"{}\" serve'; $s.WorkingDirectory='{}'; $s.WindowStyle=7; $s.Description='Start the Caelza Mind at logon'; $s.Save()",
            ps_quote(&launcher.display().to_string()),
            ps_quote(&lay.bin_dir.display().to_string())
        );
        match run(&PathBuf::from("powershell.exe"), &["-NoProfile", "-NonInteractive", "-Command", &script], None, None, "startup", false).await {
            Ok(_) => log("Startup shortcut written (the Mind starts minimised when you log on)"),
            Err(e) => log(format!("no Startup shortcut ({e}); the Start menu's Caelza starts the Mind anyway")),
        }
    } else if cfg!(target_os = "linux") {
        stage("startup", "setting the Mind to start when you log in");
        let unit_dir = std::env::var_os("XDG_CONFIG_HOME")
            .filter(|s| !s.is_empty())
            .map(PathBuf::from)
            .or_else(|| home_dir().map(|h| h.join(".config")))
            .map(|c| c.join("systemd").join("user"));
        match unit_dir {
            Some(dir) => {
                let unit = dir.join("caelza-mind.service");
                let written = std::fs::create_dir_all(&dir)
                    .and_then(|()| std::fs::write(&unit, systemd_unit(&launcher)))
                    .map_err(|e| format!("writing {}: {e}", unit.display()));
                match written {
                    Ok(()) => {
                        log(format!("systemd user unit -> {}", unit.display()));
                        let systemctl = PathBuf::from("systemctl");
                        let enabled = run(&systemctl, &["--user", "daemon-reload"], None, None, "startup", true).await.is_ok()
                            && run(&systemctl, &["--user", "enable", "caelza-mind.service"], None, None, "startup", true).await.is_ok();
                        log(if enabled {
                            "enabled: the Mind starts with your next login (loginctl enable-linger keeps it up after you log out)".to_string()
                        } else {
                            "no user systemd here; the launcher starts it: caelza-mind serve".to_string()
                        });
                    }
                    Err(e) => log(format!("no autostart ({e}); the launcher starts it: caelza-mind serve")),
                }
            }
            None => log("no home for a systemd user unit; the launcher starts it: caelza-mind serve"),
        }
    }

    let _ = std::fs::remove_dir_all(&work);
    let _ = std::fs::remove_dir(lay.base.join("tmp"));
    stage("done", "the Mind is installed and running");
    Ok(())
}

// --- the routes -----------------------------------------------------------------------

fn report() -> Value {
    let lay = layout();
    let (can, reason) = can_install();
    let cli = installed_cli(&lay);
    let launcher = lay.bin_dir.join(if cfg!(windows) { "caelza-mind.cmd" } else { "caelza-mind" });
    let mut v = serde_json::to_value(snapshot()).unwrap_or_else(|_| json!({}));
    if let Some(obj) = v.as_object_mut() {
        obj.insert("can_install".into(), json!(can));
        obj.insert("reason".into(), json!(reason));
        obj.insert("installed".into(), json!(cli.is_some()));
        obj.insert("mind_dir".into(), json!(lay.mind_dir.display().to_string()));
        obj.insert("launcher".into(), json!(launcher.display().to_string()));
        obj.insert("launcher_present".into(), json!(launcher.is_file()));
        obj.insert("tokens_dir".into(), json!(lay.tokens_dir.display().to_string()));
        obj.insert("node_version".into(), json!(NODE_VERSION));
        obj.insert("caelza_version".into(), json!(caelza_version()));
        obj.insert("port".into(), json!(MIND_PORT));
    }
    v
}

/// GET /api/mind/install
pub async fn handle_install_get(State(state): State<AppState>, headers: HeaderMap) -> Response {
    if let Err(e) = require_auth(&state, &headers) {
        return e.into_response();
    }
    let mut v = report();
    if let Some(obj) = v.as_object_mut() {
        obj.insert("healthy".into(), json!(health(MIND_PORT).await));
    }
    Json(v).into_response()
}

/// POST /api/mind/install
pub async fn handle_install_post(State(state): State<AppState>, headers: HeaderMap) -> Response {
    if let Err(e) = require_auth(&state, &headers) {
        return e.into_response();
    }
    let (can, reason) = can_install();
    if !can {
        return error_response(StatusCode::CONFLICT, reason);
    }
    {
        let Ok(mut j) = job().lock() else {
            return error_response(StatusCode::INTERNAL_SERVER_ERROR, "the install state is poisoned; restart Caelza");
        };
        if j.running {
            return error_response(StatusCode::CONFLICT, "an install is already running");
        }
        *j = Install {
            running: true,
            stage: "release".into(),
            detail: "starting".into(),
            started_at: Some(now()),
            ..Install::default()
        };
    }
    let mut agents: Vec<String> = state.config.read().agents.keys().cloned().collect();
    agents.sort();
    tokio::spawn(async move {
        let result = run_install(agents).await;
        if let Ok(mut j) = job().lock() {
            j.running = false;
            j.finished = true;
            j.finished_at = Some(now());
            match result {
                Ok(()) => j.ok = true,
                Err(e) => {
                    push_log(&mut j, &format!("error: {e}"));
                    j.error = Some(e);
                }
            }
        }
    });
    Json(report()).into_response()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn env_of<'a>(pairs: &'a [(&'a str, &'a str)]) -> impl Fn(&str) -> Option<String> + 'a {
        move |k| pairs.iter().find(|(n, _)| *n == k).map(|(_, v)| v.to_string())
    }

    #[test]
    fn the_layout_is_the_scripts_layout() {
        let home = Path::new("/home/u");
        let lin = layout_for(&env_of(&[]), Some(home), Some(Path::new("/opt/caelza")), false);
        assert_eq!(lin.base, PathBuf::from("/home/u/.local/share/caelza"));
        assert_eq!(lin.mind_dir, PathBuf::from("/home/u/.local/share/caelza/mind"));
        assert_eq!(lin.node_dir, PathBuf::from("/home/u/.local/share/caelza/node"));
        assert_eq!(lin.bin_dir, PathBuf::from("/home/u/.local/bin"));
        assert_eq!(lin.tokens_dir, PathBuf::from("/home/u/.xanima/tokens"));
        let xdg = layout_for(&env_of(&[("XDG_DATA_HOME", "/data"), ("XANIMA_HOME_OVERRIDE", "/xh")]), Some(home), None, false);
        assert_eq!(xdg.base, PathBuf::from("/data/caelza"));
        assert_eq!(xdg.tokens_dir, PathBuf::from("/xh/.xanima/tokens"));
        let over = layout_for(&env_of(&[("CAELZA_MIND_DIR", "/m"), ("CAELZA_BIN_DIR", "/b")]), Some(home), None, false);
        assert_eq!(over.mind_dir, PathBuf::from("/m"));
        assert_eq!(over.bin_dir, PathBuf::from("/b"));
        let win = layout_for(&env_of(&[("LOCALAPPDATA", "C:\\Users\\u\\AppData\\Local")]), Some(Path::new("C:\\Users\\u")), Some(Path::new("C:\\Users\\u\\AppData\\Local\\Caelza")), true);
        assert_eq!(win.base, PathBuf::from("C:\\Users\\u\\AppData\\Local").join("Caelza"));
        assert_eq!(win.mind_dir, win.base.join("mind"));
        assert_eq!(win.bin_dir, PathBuf::from("C:\\Users\\u\\AppData\\Local\\Caelza"), "beside caelza.exe, where caelza-launch.cmd looks");
        assert_eq!(win.tokens_dir, PathBuf::from("C:\\Users\\u").join(".xanima").join("tokens"));
    }

    #[test]
    fn node_archives_are_named_the_way_nodejs_org_names_them() {
        let lin = node_asset("22.23.5", "linux", "x86_64").unwrap();
        assert_eq!(lin.name, "node-v22.23.5-linux-x64.tar.gz");
        assert_eq!(lin.root, "node-v22.23.5-linux-x64");
        assert!(!lin.zip);
        let win = node_asset("22.23.5", "windows", "x86_64").unwrap();
        assert_eq!(win.name, "node-v22.23.5-win-x64.zip");
        assert!(win.zip);
        assert_eq!(node_asset("22.23.5", "linux", "aarch64").unwrap().name, "node-v22.23.5-linux-arm64.tar.gz");
        assert_eq!(node_asset("22.23.5", "macos", "aarch64").unwrap().name, "node-v22.23.5-darwin-arm64.tar.gz");
        assert!(node_asset("22.23.5", "android", "aarch64").is_none());
        assert_eq!(node_exe(Path::new("/n"), false), PathBuf::from("/n/bin/node"));
        assert_eq!(node_exe(Path::new("C:\\n"), true), PathBuf::from("C:\\n").join("node.exe"));
        assert_eq!(npm_cli(Path::new("/n"), false), PathBuf::from("/n/lib/node_modules/npm/bin/npm-cli.js"));
        assert_eq!(npm_cli(Path::new("C:\\n"), true), PathBuf::from("C:\\n").join("node_modules").join("npm").join("bin").join("npm-cli.js"));
    }

    #[test]
    fn sums_are_read_the_way_the_files_are_written() {
        let sums = "8bd3dc69eee8f3f226315a80d7d1d4faccf217a4c8fae500168ac2e38f3bdba3  node-v22.23.5-linux-arm64.tar.gz\nC54118104ACC524633B5ABE106BBF44A53126EC8B4E5FA105CB92B5D7DE8A1A1  node-v22.23.5-linux-x64.tar.gz\n";
        assert_eq!(parse_shasums(sums, "node-v22.23.5-linux-x64.tar.gz").as_deref(), Some("c54118104acc524633b5abe106bbf44a53126ec8b4e5fa105cb92b5d7de8a1a1"));
        assert_eq!(parse_shasums(sums, "node-v22.23.5-win-x64.zip"), None);
        assert_eq!(parse_sha256_file("ABCDEF0123456789abcdef0123456789abcdef0123456789abcdef0123456789  caelza-mind-0.3.0.tgz\n").as_deref(), Some("abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789"));
        assert_eq!(parse_sha256_file("not a sum"), None);
        assert_eq!(parse_sha256_file(""), None);
    }

    #[test]
    fn the_release_urls_follow_the_tag() {
        let (tgz, sum) = mind_urls("0.3.0");
        assert_eq!(tgz, "https://github.com/Enlightened-Republic/Caelza/releases/download/v0.3.0/caelza-mind-0.3.0.tgz");
        assert_eq!(sum, format!("{tgz}.sha256"));
        assert_eq!(mind_urls("v0.3.0").0, tgz);
    }

    #[test]
    fn the_launcher_prefers_path_only_when_the_install_used_path() {
        let cli_w = Path::new("C:\\m\\node_modules\\xanima-server\\dist\\cli.js");
        let cmd = launcher_text(true, cli_w, Path::new("node"), true);
        assert!(cmd.starts_with("@echo off\r\n"));
        assert!(cmd.contains("set \"NODE=node\"\r\nwhere node >nul 2>&1 && set \"NODE=node\"\r\n"));
        assert!(cmd.ends_with("\"%NODE%\" \"C:\\m\\node_modules\\xanima-server\\dist\\cli.js\" %*\r\n"));
        // A portable Node, fetched because PATH had none new enough: PATH is never consulted again.
        let fixed = launcher_text(true, cli_w, Path::new("C:\\n\\node.exe"), false);
        assert!(fixed.contains("set \"NODE=C:\\n\\node.exe\"\r\n\"%NODE%\""));
        assert!(!fixed.contains("where node"));
        let sh = launcher_text(false, Path::new("/m/node_modules/xanima-server/dist/cli.js"), Path::new("node"), true);
        assert!(sh.starts_with("#!/bin/sh\n"));
        assert!(sh.contains("node=$(command -v node 2>/dev/null || printf '%s' \"node\")\n"));
        let sh_fixed = launcher_text(false, Path::new("/m/node_modules/xanima-server/dist/cli.js"), Path::new("/n/bin/node"), false);
        assert!(sh_fixed.ends_with("exec \"/n/bin/node\" \"/m/node_modules/xanima-server/dist/cli.js\" \"$@\"\n"));
        assert!(!sh_fixed.contains("command -v node"));
        // The unit install.sh writes, and PowerShell's quote doubled.
        let unit = systemd_unit(Path::new("/home/u/.local/bin/caelza-mind"));
        assert!(unit.contains("ExecStart=\"/home/u/.local/bin/caelza-mind\" serve\n") && unit.contains("WantedBy=default.target"));
        assert_eq!(ps_quote("C:\\Users\\O'Brien\\x"), "C:\\Users\\O''Brien\\x");
    }

    #[test]
    fn scopes_and_the_node_pin() {
        assert_eq!(scopes_for("main"), "read,write");
        assert_eq!(scopes_for("cael"), "read");
        assert_eq!(scopes_for("other"), "read,write");
        // bundle/manifest.toml pins the same number; tests/test_mind_install.py holds the two together.
        assert!(NODE_VERSION.starts_with("22."), "the Mind needs Node 22");
    }

    #[test]
    fn the_log_keeps_its_tail() {
        let mut j = Install::default();
        for i in 0..(LOG_KEEP + 10) {
            push_log(&mut j, &format!("line {i}\n\n"));
        }
        assert_eq!(j.log.len(), LOG_KEEP);
        assert_eq!(j.log[0], "line 10");
        assert_eq!(j.log.last().map(String::as_str), Some(&*format!("line {}", LOG_KEEP + 9)));
    }
}
