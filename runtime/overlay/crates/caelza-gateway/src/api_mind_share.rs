//! Caelza: one Mind for every device (the Memory page's devices cards).
//!
//! The consumer shape of the shared brain: one Cael with one memory on the
//! PC and the phone. The Mind that already runs (usually the PC's) also
//! listens on the owner's home-network or Tailscale address, and the other
//! device's Runtime points its `[storage.xanima.default]` at it with a token
//! minted for exactly that. Everything happens from the Memory page; no
//! shell. The service's own rules stay in force: it never binds a wildcard
//! address (`tailnetHosts` in its `config.json` is the one way to add a
//! listener), every request needs a bearer token, provisioning stays
//! loopback-only, and token files hold hashes only.
//!
//! Routes (all behind the dashboard's pairing auth):
//! - `GET    /api/mind/share`  where this device stands: does it host the Mind,
//!   which addresses it could share, which it shares, which the service listens on;
//!   for a device that joined another's (or has none) whether a Mind answers on its loopback
//! - `POST   /api/mind/share`  `{host}` → the address goes into the Mind's
//!   `config.json`, a `caelza-share` token for the default agent goes into its
//!   `tokens.json` (hash only, a fresh token every time), and the join code comes back
//! - `DELETE /api/mind/share`  the addresses leave `config.json`, every
//!   `caelza-share` token is revoked
//! - `POST   /api/mind/probe`  `{code}` → the other device checks the code before
//!   joining: `/health` on the service, then `brain_stats` with the code's token
//!
//! A join code is `caelza-mind:` + base64url of `{"v":1,"url","agent","token"}`;
//! one that names a public address, or a name instead of an address, is
//! refused on the joining side (Share never makes one). The service's files
//! are found exactly the way the service finds them (`service_root_for`), and
//! sharing never creates a root: a machine with no Mind set up gets an error,
//! not a second, empty Mind on its next restart. Stop sharing revokes the
//! codes before it clears the address, so a failure half-way never leaves
//! valid codes behind an address the page no longer shows.
//! The page on the joining device writes the config itself through the upstream
//! config API (the `storage.xanima.default` row, `url`, `token` encrypted at
//! rest, `agent`, `memory.backend = "xanima"`); this module only probes.

use super::AppState;
use super::api::require_auth;
use super::api_mind::{MindWiring, mind_wiring};
use axum::{
    extract::State,
    http::{HeaderMap, StatusCode},
    response::{IntoResponse, Json, Response},
};
use base64::Engine;
use base64::engine::general_purpose::{URL_SAFE, URL_SAFE_NO_PAD};
use caelza_memory::{XanimaMemory, XanimaSettings};
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value, json};
use sha2::{Digest, Sha256};
use std::net::{IpAddr, Ipv4Addr, UdpSocket};
use std::path::{Path, PathBuf};
use std::time::Duration;

/// The join code's prefix.
pub const CODE_PREFIX: &str = "caelza-mind:";
/// The label on every token this module mints; `DELETE` revokes by it.
pub const SHARE_LABEL: &str = "caelza-share";
/// The service's default port (`DEFAULT_PORT` in xanima-server's config.ts).
pub const DEFAULT_PORT: u16 = 18790;
/// `TOKEN_PREFIX` in xanima-server's tokens.ts.
const TOKEN_PREFIX: &str = "swt_";
/// The scopes a joined device's Runtime needs: recall and remember, nothing else.
const SHARE_SCOPES: [&str; 2] = ["read", "write"];
/// How long a probe waits for a Mind on another machine.
const PROBE_TIMEOUT: Duration = Duration::from_secs(8);

fn error_response(status: StatusCode, message: impl Into<String>) -> Response {
    (status, Json(json!({"error": message.into()}))).into_response()
}

// --- where the service keeps its files --------------------------------------------

/// The home directory the way Node's `os.homedir()` finds it: USERPROFILE
/// first on Windows, HOME first elsewhere.
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

/// The service's files.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ServicePaths {
    pub root: PathBuf,
    pub config: PathBuf,
    pub tokens: PathBuf,
}

/// The service root as xanima-server's `defaultRoot()` resolves it:
/// `env_root` (`$XANIMA_SERVICE_ROOT`) when set, else `<data home>/service`
/// where the data home is `~/.xanima` when it exists, else an un-migrated
/// `~/.sharpwave` when that exists, else `~/.xanima` (`defaultDataHome()` in
/// xanima-core). Following the service exactly matters: a root of our own
/// would make the next restart come up on a second, empty Mind.
pub fn service_root_for(env_root: Option<&str>, home: Option<&Path>) -> PathBuf {
    if let Some(root) = env_root.map(str::trim).filter(|r| !r.is_empty()) {
        return PathBuf::from(root);
    }
    let home = home.map(Path::to_path_buf).unwrap_or_else(|| PathBuf::from("."));
    let neu = home.join(".xanima");
    let old = home.join(".sharpwave");
    let data = if neu.is_dir() {
        neu
    } else if old.is_dir() {
        old
    } else {
        neu
    };
    data.join("service")
}

/// `service_root_for` on this process's environment; `~` is
/// `XANIMA_HOME_OVERRIDE` when set, the service's own override.
pub fn service_root() -> PathBuf {
    let env_root = std::env::var("XANIMA_SERVICE_ROOT").ok();
    let home = std::env::var_os("XANIMA_HOME_OVERRIDE")
        .filter(|h| !h.is_empty())
        .map(PathBuf::from)
        .or_else(home_dir);
    service_root_for(env_root.as_deref(), home.as_deref())
}

/// A leading `~/` (or `~\`) expanded, as the service's `expandHome` does
/// for `tokensFile`.
fn expand_tilde(path: &str) -> PathBuf {
    if let Some(rest) = path.strip_prefix("~/").or_else(|| path.strip_prefix("~\\"))
        && let Some(home) = home_dir()
    {
        return home.join(rest);
    }
    PathBuf::from(path)
}

/// The root, its `config.json`, and `tokens.json` where that config's
/// `tokensFile` says (else beside the config, the service's default).
pub fn service_paths() -> ServicePaths {
    let root = service_root();
    let config = root.join("config.json");
    let tokens = read_json(&config)
        .ok()
        .and_then(|c| c.get("tokensFile").and_then(Value::as_str).map(|t| t.trim().to_string()))
        .filter(|t| !t.is_empty())
        .map(|t| expand_tilde(&t))
        .unwrap_or_else(|| root.join("tokens.json"));
    ServicePaths { root, config, tokens }
}

/// Whether a Mind has been set up at `root`: its config, its tokens or its
/// audit log is there. Sharing never creates a root of its own.
pub fn mind_installed(paths: &ServicePaths) -> bool {
    paths.config.is_file() || paths.tokens.is_file() || paths.root.join("audit").is_dir()
}

/// A JSON file, or an empty object when it is not there yet.
pub fn read_json(path: &Path) -> Result<Value, String> {
    match std::fs::read_to_string(path) {
        Ok(raw) => {
            let raw = raw.trim_start_matches('\u{feff}');
            serde_json::from_str::<Value>(raw)
                .map_err(|e| format!("{} is not JSON: {e}", path.display()))
                .and_then(|v| {
                    if v.is_object() {
                        Ok(v)
                    } else {
                        Err(format!("{} is not a JSON object", path.display()))
                    }
                })
        }
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(Value::Object(Map::new())),
        Err(e) => Err(format!("reading {}: {e}", path.display())),
    }
}

/// Whole or not at all: a sibling temp file, then a rename. `owner_only`
/// makes it 0600 on Unix (the token file).
pub fn write_json(path: &Path, value: &Value, owner_only: bool) -> Result<(), String> {
    let parent = path
        .parent()
        .ok_or_else(|| format!("{} has no parent", path.display()))?;
    std::fs::create_dir_all(parent).map_err(|e| format!("creating {}: {e}", parent.display()))?;
    let tmp = parent.join(format!(
        ".{}.{}.tmp",
        path.file_name().and_then(|n| n.to_str()).unwrap_or("file"),
        std::process::id()
    ));
    let text = serde_json::to_string_pretty(value).map_err(|e| e.to_string())? + "\n";
    std::fs::write(&tmp, text.as_bytes()).map_err(|e| format!("writing {}: {e}", tmp.display()))?;
    #[cfg(unix)]
    if owner_only {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(&tmp, std::fs::Permissions::from_mode(0o600))
            .map_err(|e| format!("chmod {}: {e}", tmp.display()))?;
    }
    #[cfg(not(unix))]
    let _ = owner_only;
    std::fs::rename(&tmp, path).map_err(|e| {
        let _ = std::fs::remove_file(&tmp);
        format!("renaming into {}: {e}", path.display())
    })
}

// --- the Mind's config.json: tailnetHosts ----------------------------------------

/// The extra addresses the service binds (`tailnetHosts`).
pub fn tailnet_hosts(cfg: &Value) -> Vec<String> {
    cfg.get("tailnetHosts")
        .and_then(Value::as_array)
        .map(|a| {
            a.iter()
                .filter_map(Value::as_str)
                .map(|s| s.trim().to_string())
                .filter(|s| !s.is_empty())
                .collect()
        })
        .unwrap_or_default()
}

/// Add `host` to `tailnetHosts`; false when it was already there.
pub fn with_host(cfg: &mut Value, host: &str) -> bool {
    let mut hosts = tailnet_hosts(cfg);
    if hosts.iter().any(|h| h == host) {
        return false;
    }
    hosts.push(host.to_string());
    if let Some(obj) = cfg.as_object_mut() {
        obj.insert("tailnetHosts".to_string(), json!(hosts));
    }
    true
}

/// Clear `tailnetHosts`; the addresses that were there.
pub fn without_hosts(cfg: &mut Value) -> Vec<String> {
    let had = tailnet_hosts(cfg);
    if let Some(obj) = cfg.as_object_mut() {
        obj.insert("tailnetHosts".to_string(), json!([]));
    }
    had
}

// --- addresses ------------------------------------------------------------------

/// An address this machine could share, and what kind of network it is on.
#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub struct Candidate {
    pub host: String,
    /// `lan` (a private range, the home network) or `tailnet` (Tailscale's 100.64.0.0/10).
    pub kind: &'static str,
}

/// What kind of network an address is on: `loopback`, `tailnet`
/// (100.64.0.0/10), `lan` (RFC 1918, link-local, ULA), else `public`.
pub fn kind_of(ip: IpAddr) -> &'static str {
    match ip {
        IpAddr::V4(v4) => {
            let o = v4.octets();
            if v4.is_loopback() {
                "loopback"
            } else if o[0] == 100 && (64..128).contains(&o[1]) {
                "tailnet"
            } else if v4.is_private() || v4.is_link_local() {
                "lan"
            } else {
                "public"
            }
        }
        IpAddr::V6(v6) => {
            if v6.is_loopback() {
                "loopback"
            } else if let Some(v4) = v6.to_ipv4_mapped() {
                kind_of(IpAddr::V4(v4))
            } else {
                let s = v6.segments();
                if s[0] & 0xfe00 == 0xfc00 || s[0] & 0xffc0 == 0xfe80 {
                    "lan"
                } else {
                    "public"
                }
            }
        }
    }
}

/// The address this machine would use to reach `target`: a UDP connect does
/// the route lookup and sends nothing.
fn route_lookup(target: &str) -> Option<IpAddr> {
    let socket = UdpSocket::bind((Ipv4Addr::UNSPECIFIED, 0)).ok()?;
    socket.connect(target).ok()?;
    socket.local_addr().ok().map(|a| a.ip())
}

/// The addresses this machine could share: its default-route address and,
/// when Tailscale is up, its tailnet address. Public addresses are left out.
pub fn candidates() -> Vec<Candidate> {
    let mut out: Vec<Candidate> = Vec::new();
    for target in ["100.100.100.100:53", "8.8.8.8:53"] {
        let Some(ip) = route_lookup(target) else {
            continue;
        };
        let kind = kind_of(ip);
        if !matches!(kind, "lan" | "tailnet") {
            continue;
        }
        let host = ip.to_string();
        if out.iter().any(|c| c.host == host) {
            continue;
        }
        out.push(Candidate { host, kind });
    }
    out
}

/// An address the service may bind for other devices: an IP literal that is
/// not a wildcard, not 127.0.0.1 (the service always listens there) and not
/// on the public internet.
pub fn validate_host(host: &str) -> Result<IpAddr, String> {
    let trimmed = host.trim().trim_start_matches('[').trim_end_matches(']');
    let ip: IpAddr = trimmed
        .parse()
        .map_err(|_| format!("{host:?} is not an IP address (names are not accepted, the service binds literals only)"))?;
    if ip.is_unspecified() || ip.is_multicast() {
        return Err(format!("{host:?} is not an address of this machine"));
    }
    if ip == IpAddr::V4(Ipv4Addr::LOCALHOST) {
        return Err("the Mind already listens on 127.0.0.1; pick this machine's network address".to_string());
    }
    if kind_of(ip) == "public" {
        return Err(format!(
            "{host} is reachable from the whole internet; share on your home network or a Tailscale address instead"
        ));
    }
    Ok(ip)
}

/// `host:port` with IPv6 in brackets (the URL form).
pub fn listener(ip: IpAddr, port: u16) -> String {
    match ip {
        IpAddr::V4(v4) => format!("{v4}:{port}"),
        IpAddr::V6(v6) => format!("[{v6}]:{port}"),
    }
}

/// One of the service's `addresses()` entries taken apart: `127.0.0.1:18790`,
/// `[fd12::1]:18790`, or the raw `fd12::1:18790` it prints for IPv6.
pub fn parse_listener(entry: &str) -> Option<(IpAddr, u16)> {
    let entry = entry.trim();
    if let Ok(sa) = entry.parse::<std::net::SocketAddr>() {
        return Some((sa.ip(), sa.port()));
    }
    let (host, port) = entry.rsplit_once(':')?;
    let ip = host
        .trim_start_matches('[')
        .trim_end_matches(']')
        .parse::<IpAddr>()
        .ok()?;
    Some((ip, port.parse().ok()?))
}

/// Whether the service lists a listener on `ip`:`port`.
pub fn bound(addresses: &[String], ip: IpAddr, port: u16) -> bool {
    addresses
        .iter()
        .filter_map(|a| parse_listener(a))
        .any(|(i, p)| i == ip && p == port)
}

/// An address this machine can bind: any loopback address, or one of
/// `candidates()` (what the page offers). The service would retry a bind on
/// any other address forever.
pub fn own_address(ip: IpAddr, mine: &[Candidate]) -> Result<(), String> {
    if ip.is_loopback() || mine.iter().any(|c| c.host == ip.to_string()) {
        return Ok(());
    }
    let offered = if mine.is_empty() {
        "none was found".to_string()
    } else {
        mine.iter().map(|c| c.host.as_str()).collect::<Vec<_>>().join(", ")
    };
    Err(format!("{ip} is not one of this machine's addresses ({offered})"))
}

/// The base URL of the service at `ip`.
pub fn service_url(ip: IpAddr, port: u16) -> String {
    format!("http://{}", listener(ip, port))
}

/// The service's port from its base URL (`http://127.0.0.1:18790` → 18790).
pub fn port_of(url: &str) -> u16 {
    url.rsplit_once(':')
        .and_then(|(_, p)| p.trim_end_matches('/').parse().ok())
        .unwrap_or(DEFAULT_PORT)
}

/// The host part of the service's base URL.
pub fn host_of(url: &str) -> &str {
    let rest = url
        .trim()
        .trim_start_matches("http://")
        .trim_start_matches("https://");
    let rest = rest.split('/').next().unwrap_or(rest);
    if let Some(end) = rest.strip_prefix('[').and_then(|r| r.find(']')) {
        return &rest[1..=end];
    }
    rest.rsplit_once(':').map_or(rest, |(h, _)| h)
}

/// Whether the service URL is the service's own listener on this machine
/// (`127.0.0.1`, `localhost` or `::1`, the one address it always binds). Any
/// other address, another loopback one included, is a shared address: the
/// device that uses it joined someone's Mind.
pub fn is_loopback_url(url: &str) -> bool {
    let host = host_of(url);
    host.eq_ignore_ascii_case("localhost")
        || host
            .trim_start_matches('[')
            .trim_end_matches(']')
            .parse::<IpAddr>()
            .is_ok_and(|ip| ip == IpAddr::V4(Ipv4Addr::LOCALHOST) || ip == IpAddr::V6(std::net::Ipv6Addr::LOCALHOST))
}

// --- tokens.json: the share tokens ------------------------------------------------

fn token_entries(file: &mut Value) -> Result<&mut Vec<Value>, String> {
    let obj = file
        .as_object_mut()
        .ok_or_else(|| "tokens.json is not an object".to_string())?;
    if !obj.contains_key("version") {
        obj.insert("version".to_string(), json!(1));
    }
    let entry = obj
        .entry("tokens".to_string())
        .or_insert_with(|| json!([]));
    entry
        .as_array_mut()
        .ok_or_else(|| "tokens.json: \"tokens\" is not a list".to_string())
}

/// 32 bytes from the OS's random source: two v4 UUIDs (the gateway's own
/// id generator; `uuid` draws from `getrandom`), 244 random bits.
fn random_bytes() -> [u8; 32] {
    let mut out = [0u8; 32];
    out[..16].copy_from_slice(uuid::Uuid::new_v4().as_bytes());
    out[16..].copy_from_slice(uuid::Uuid::new_v4().as_bytes());
    out
}

/// `sha256:<hex>` of a token, as the service stores it.
pub fn token_hash(token: &str) -> String {
    format!("sha256:{}", hex::encode(Sha256::digest(token.as_bytes())))
}

/// `validateAgentId` in the service's tokens.ts: letters, digits and `. _ -`,
/// 1 to 64 long, letters or digits at both ends, and not a reserved brain
/// name. The service silently drops entries that fail it, so a token for
/// such a name would never work.
pub fn agent_id_ok(agent: &str) -> Result<(), String> {
    let bytes = agent.as_bytes();
    let alnum = |b: u8| b.is_ascii_alphanumeric();
    let shape = !bytes.is_empty()
        && bytes.len() <= 64
        && alnum(bytes[0])
        && alnum(bytes[bytes.len() - 1])
        && bytes.iter().all(|&b| alnum(b) || matches!(b, b'.' | b'_' | b'-'));
    if !shape {
        return Err(format!("the Mind refuses the agent name {agent:?} (letters, digits, . _ -; up to 64)"));
    }
    if matches!(agent.to_ascii_lowercase().as_str(), "shared" | "_system" | "backups" | "audit") {
        return Err(format!("the Mind reserves the name {agent:?}; the default agent needs another name"));
    }
    Ok(())
}

/// Mint a `caelza-share` token for `agent` (read, write) into the service's
/// `tokens.json`, the way `xanima-server token mint` does: the hash is stored,
/// the plaintext is returned once. The service reloads the file on its next
/// request. Returns the token and the entry's public id.
pub fn mint_share_token(tokens_path: &Path, agent: &str) -> Result<(String, String), String> {
    agent_id_ok(agent)?;
    let mut file = read_json(tokens_path)?;
    let entries = token_entries(&mut file)?;
    for t in entries.iter() {
        if t.get("token").is_some() {
            return Err("tokens.json holds a plaintext token; refusing to touch it".to_string());
        }
    }
    let token = format!("{TOKEN_PREFIX}{}", URL_SAFE_NO_PAD.encode(random_bytes()));
    // `"tok_" + randomUUID().replace(/-/g, "").slice(0, 12)`, as the service mints ids.
    let id = format!("tok_{}", &uuid::Uuid::new_v4().simple().to_string()[..12]);
    entries.push(json!({
        "id": id,
        "hash": token_hash(&token),
        "agentId": agent,
        "scopes": SHARE_SCOPES,
        "label": SHARE_LABEL,
        "createdAt": chrono::Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Millis, true),
    }));
    write_json(tokens_path, &file, true)?;
    // The service's own provisioning writes this file too: make sure the entry landed.
    let landed = read_json(tokens_path)?
        .get("tokens")
        .and_then(Value::as_array)
        .is_some_and(|list| list.iter().any(|t| t.get("id").and_then(Value::as_str) == Some(id.as_str())));
    if !landed {
        return Err("tokens.json changed while the code was made; try again".to_string());
    }
    Ok((token, id))
}

/// Revoke every live `caelza-share` token; how many that was.
pub fn revoke_share_tokens(tokens_path: &Path) -> Result<usize, String> {
    let mut file = read_json(tokens_path)?;
    let mut revoked = 0usize;
    for t in token_entries(&mut file)?.iter_mut() {
        let is_share = t.get("label").and_then(Value::as_str) == Some(SHARE_LABEL);
        let live = !t.get("revoked").and_then(Value::as_bool).unwrap_or(false);
        if is_share && live && let Some(obj) = t.as_object_mut() {
            obj.insert("revoked".to_string(), json!(true));
            revoked += 1;
        }
    }
    if revoked > 0 {
        write_json(tokens_path, &file, true)?;
    }
    Ok(revoked)
}

/// How many `caelza-share` tokens are live.
pub fn live_share_tokens(tokens_path: &Path) -> usize {
    read_json(tokens_path)
        .ok()
        .and_then(|f| f.get("tokens").and_then(Value::as_array).cloned())
        .map(|list| {
            list.iter()
                .filter(|t| {
                    t.get("label").and_then(Value::as_str) == Some(SHARE_LABEL)
                        && !t.get("revoked").and_then(Value::as_bool).unwrap_or(false)
                })
                .count()
        })
        .unwrap_or(0)
}

// --- the join code -----------------------------------------------------------------

/// What a join code carries.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct JoinCode {
    pub v: u8,
    pub url: String,
    pub agent: String,
    pub token: String,
}

/// `caelza-mind:` + base64url of the JSON.
pub fn encode_code(url: &str, agent: &str, token: &str) -> String {
    let body = serde_json::to_vec(&JoinCode {
        v: 1,
        url: url.trim_end_matches('/').to_string(),
        agent: agent.to_string(),
        token: token.to_string(),
    })
    .expect("a join code serializes");
    format!("{CODE_PREFIX}{}", URL_SAFE_NO_PAD.encode(body))
}

/// Read a join code back; the message says what is wrong with it in the
/// owner's words.
pub fn decode_code(code: &str) -> Result<JoinCode, String> {
    let trimmed = code.trim();
    if trimmed.is_empty() {
        return Err("paste the code from the other device's Memory page".to_string());
    }
    // `get` rather than `split_at`: a full-width colon from a phone keyboard
    // puts a char boundary past byte 12, and that must be an error, not a panic.
    let body = trimmed
        .get(..CODE_PREFIX.len())
        .filter(|head| head.eq_ignore_ascii_case(CODE_PREFIX))
        .map(|_| &trimmed[CODE_PREFIX.len()..])
        .ok_or_else(|| format!("that is not a join code (it starts with {CODE_PREFIX})"))?;
    let body = body.trim();
    let bytes = URL_SAFE_NO_PAD
        .decode(body)
        .or_else(|_| URL_SAFE.decode(body))
        .map_err(|_| "that code is incomplete or was changed while copying".to_string())?;
    let parsed: JoinCode = serde_json::from_slice(&bytes)
        .map_err(|_| "that code is incomplete or was changed while copying".to_string())?;
    if parsed.v != 1 {
        return Err(format!("that code is from a newer Caelza (version {}); update this one", parsed.v));
    }
    let url = parsed.url.trim().trim_end_matches('/').to_string();
    if !(url.starts_with("http://") || url.starts_with("https://")) || host_of(&url).is_empty() {
        return Err("that code names no service address".to_string());
    }
    // Share writes addresses, never names, and never public ones: a code that
    // points elsewhere was not made by Share, and following it would send
    // every turn's memory to whoever is there.
    let ip: IpAddr = host_of(&url)
        .trim_start_matches('[')
        .trim_end_matches(']')
        .parse()
        .map_err(|_| "that code names the Mind by a name, not an address; Share makes codes with the address".to_string())?;
    if ip.is_unspecified() || ip.is_multicast() || kind_of(ip) == "public" {
        return Err("that code points at an internet address; a Mind is shared on a home network or Tailscale only".to_string());
    }
    let agent = parsed.agent.trim().to_string();
    if agent.is_empty() || !super::api_looks::alias_ok(&agent) {
        return Err("that code names no agent".to_string());
    }
    let token = parsed.token.trim().to_string();
    if token.is_empty() {
        return Err("that code carries no token".to_string());
    }
    Ok(JoinCode { v: 1, url, agent, token })
}

// --- the service as seen from here ------------------------------------------------

struct Listening {
    healthy: bool,
    version: Option<String>,
    addresses: Vec<String>,
}

async fn listening(settings: &XanimaSettings) -> Listening {
    let memory = XanimaMemory::new("xanima", settings.clone());
    match memory.health_info().await {
        Ok(v) => Listening {
            healthy: true,
            version: v.get("version").and_then(Value::as_str).map(str::to_string),
            addresses: v
                .get("addresses")
                .and_then(Value::as_array)
                .map(|a| a.iter().filter_map(Value::as_str).map(str::to_string).collect())
                .unwrap_or_default(),
        },
        Err(_) => Listening {
            healthy: false,
            version: None,
            addresses: Vec::new(),
        },
    }
}

/// The hosting device's wiring, or the response that says why it is not one.
fn hosting(state: &AppState) -> Result<XanimaSettings, Response> {
    let config = state.config.read().clone();
    match mind_wiring(&config) {
        Err(e) => Err(error_response(StatusCode::INTERNAL_SERVER_ERROR, e)),
        Ok(MindWiring::Disabled { backend }) => Err((
            StatusCode::CONFLICT,
            Json(json!({
                "error": format!("The Mind is not this device's memory (memory.backend = {backend:?}); there is nothing to share"),
                "enabled": false,
            })),
        )
            .into_response()),
        Ok(MindWiring::Enabled(settings)) if !is_loopback_url(&settings.url) => Err((
            StatusCode::CONFLICT,
            Json(json!({
                "error": format!("This device uses the Mind at {}; share from the device that runs it", settings.url),
                "enabled": true,
                "hosted_here": false,
            })),
        )
            .into_response()),
        Ok(MindWiring::Enabled(settings)) => Ok(settings),
    }
}

fn state_report(settings: &XanimaSettings, paths: &ServicePaths, cfg: Result<Value, String>, live: Listening) -> Value {
    let port = port_of(&settings.url);
    let (configured, config_error) = match cfg {
        Ok(cfg) => (tailnet_hosts(&cfg), None),
        Err(e) => (Vec::new(), Some(e)),
    };
    // The configured addresses the service does not list yet (a restart away).
    let unbound: Vec<String> = configured
        .iter()
        .filter(|h| !h.parse::<IpAddr>().ok().is_some_and(|ip| bound(&live.addresses, ip, port)))
        .cloned()
        .collect();
    json!({
        "enabled": true,
        "hosted_here": true,
        "url": settings.url,
        "agent": settings.agent,
        "port": port,
        "config_path": paths.config.display().to_string(),
        "tokens_path": paths.tokens.display().to_string(),
        "installed": mind_installed(paths),
        "config_error": config_error,
        "configured": configured,
        "sharing": !configured.is_empty(),
        "reachable": !configured.is_empty() && unbound.is_empty(),
        "unbound": unbound,
        "healthy": live.healthy,
        "version": live.version,
        "listening": live.addresses,
        "candidates": candidates(),
        "share_tokens": live_share_tokens(&paths.tokens),
    })
}

/// Whether a Mind answers on this machine's loopback at `port`.
async fn local_mind_up(port: u16) -> bool {
    let mut settings = XanimaSettings::new(&service_url(IpAddr::V4(Ipv4Addr::LOCALHOST), port));
    settings.timeout = Duration::from_secs(3);
    listening(&settings).await.healthy
}

/// GET /api/mind/share: the hosting device's full report; for a device that
/// uses another device's Mind, or none, where it stands and whether a Mind
/// answers on its own loopback (so *leave* knows where to go back to).
pub async fn handle_share_get(State(state): State<AppState>, headers: HeaderMap) -> Response {
    if let Err(e) = require_auth(&state, &headers) {
        return e.into_response();
    }
    let config = state.config.read().clone();
    let settings = match mind_wiring(&config) {
        Err(e) => return error_response(StatusCode::INTERNAL_SERVER_ERROR, e),
        Ok(MindWiring::Disabled { backend }) => {
            return Json(json!({
                "enabled": false,
                "hosted_here": false,
                "backend": backend,
                "local_mind": local_mind_up(DEFAULT_PORT).await,
            }))
            .into_response();
        }
        Ok(MindWiring::Enabled(settings)) if !is_loopback_url(&settings.url) => {
            let port = port_of(&settings.url);
            let live = listening(&settings).await;
            return Json(json!({
                "enabled": true,
                "hosted_here": false,
                "url": settings.url,
                "agent": settings.agent,
                "port": port,
                "healthy": live.healthy,
                "version": live.version,
                // Leaving falls back to the row's defaults, which point at the default port.
                "local_mind": local_mind_up(DEFAULT_PORT).await,
            }))
            .into_response();
        }
        Ok(MindWiring::Enabled(settings)) => settings,
    };
    let paths = service_paths();
    let cfg = read_json(&paths.config);
    let live = listening(&settings).await;
    Json(state_report(&settings, &paths, cfg, live)).into_response()
}

#[derive(Debug, Deserialize)]
pub struct ShareBody {
    pub host: String,
}

/// POST /api/mind/share
pub async fn handle_share_post(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(body): Json<ShareBody>,
) -> Response {
    if let Err(e) = require_auth(&state, &headers) {
        return e.into_response();
    }
    let settings = match hosting(&state) {
        Ok(s) => s,
        Err(r) => return r,
    };
    let ip = match validate_host(&body.host).and_then(|ip| own_address(ip, &candidates()).map(|()| ip)) {
        Ok(ip) => ip,
        Err(e) => return error_response(StatusCode::BAD_REQUEST, e),
    };
    let paths = service_paths();
    if !mind_installed(&paths) {
        return error_response(
            StatusCode::CONFLICT,
            format!(
                "No Mind is set up at {} (no config.json, tokens.json or audit log there); install it first, then share",
                paths.root.display()
            ),
        );
    }
    let mut cfg = match read_json(&paths.config) {
        Ok(c) => c,
        Err(e) => return error_response(StatusCode::INTERNAL_SERVER_ERROR, e),
    };
    // The token first: a code is only ever handed out for an address that is written.
    let (token, token_id) = match mint_share_token(&paths.tokens, &settings.agent) {
        Ok(t) => t,
        Err(e) => return error_response(StatusCode::INTERNAL_SERVER_ERROR, e),
    };
    let added = with_host(&mut cfg, &ip.to_string());
    if added && let Err(e) = write_json(&paths.config, &cfg, false) {
        // The address did not land: the token minted a moment ago goes again.
        let _ = revoke_share_tokens(&paths.tokens);
        return error_response(StatusCode::INTERNAL_SERVER_ERROR, e);
    }
    let port = port_of(&settings.url);
    let url = service_url(ip, port);
    let live = listening(&settings).await;
    let restart_needed = !bound(&live.addresses, ip, port);
    let mut report = state_report(&settings, &paths, Ok(cfg), live);
    if let Some(obj) = report.as_object_mut() {
        obj.insert("host".to_string(), json!(ip.to_string()));
        obj.insert("kind".to_string(), json!(kind_of(ip)));
        obj.insert("share_url".to_string(), json!(url));
        obj.insert("code".to_string(), json!(encode_code(&url, &settings.agent, &token)));
        obj.insert("token_id".to_string(), json!(token_id));
        obj.insert("restart_needed".to_string(), json!(restart_needed));
        obj.insert("added".to_string(), json!(added));
    }
    Json(report).into_response()
}

/// DELETE /api/mind/share
pub async fn handle_share_delete(State(state): State<AppState>, headers: HeaderMap) -> Response {
    if let Err(e) = require_auth(&state, &headers) {
        return e.into_response();
    }
    let settings = match hosting(&state) {
        Ok(s) => s,
        Err(r) => return r,
    };
    let paths = service_paths();
    let mut cfg = match read_json(&paths.config) {
        Ok(c) => c,
        Err(e) => return error_response(StatusCode::INTERNAL_SERVER_ERROR, e),
    };
    // The codes first: an address that stays open a while longer is a restart
    // away, codes that stay valid behind a cleared address would be invisible.
    let revoked = match revoke_share_tokens(&paths.tokens) {
        Ok(n) => n,
        Err(e) => return error_response(StatusCode::INTERNAL_SERVER_ERROR, format!("the codes were not revoked: {e}")),
    };
    let removed = without_hosts(&mut cfg);
    if !removed.is_empty() && let Err(e) = write_json(&paths.config, &cfg, false) {
        return (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(json!({"error": format!("the codes are revoked ({revoked}), but the address stayed in config.json: {e}"), "revoked": revoked})),
        )
            .into_response();
    }
    let port = port_of(&settings.url);
    let live = listening(&settings).await;
    // Still bound until the service restarts: say so.
    let restart_needed = removed
        .iter()
        .any(|h| h.parse::<IpAddr>().ok().is_some_and(|ip| bound(&live.addresses, ip, port)));
    let mut report = state_report(&settings, &paths, Ok(cfg), live);
    if let Some(obj) = report.as_object_mut() {
        obj.insert("removed".to_string(), json!(removed));
        obj.insert("revoked".to_string(), json!(revoked));
        obj.insert("restart_needed".to_string(), json!(restart_needed));
    }
    Json(report).into_response()
}

#[derive(Debug, Deserialize)]
pub struct ProbeBody {
    pub code: String,
}

/// POST /api/mind/probe
pub async fn handle_probe(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(body): Json<ProbeBody>,
) -> Response {
    if let Err(e) = require_auth(&state, &headers) {
        return e.into_response();
    }
    let code = match decode_code(&body.code) {
        Ok(c) => c,
        Err(e) => return error_response(StatusCode::BAD_REQUEST, e),
    };
    let mut settings = XanimaSettings::new(&code.url);
    settings.token = Some(code.token.clone());
    settings.agent = code.agent.clone();
    settings.provision_token_file = None;
    settings.timeout = PROBE_TIMEOUT;
    let memory = XanimaMemory::new("xanima", settings);
    let health = match memory.health_info().await {
        Ok(v) => v,
        Err(_) => {
            return error_response(
                StatusCode::BAD_GATEWAY,
                format!(
                    "No Mind answered at {}. Is the other device on, on the same network, and did its Mind restart after sharing?",
                    code.url
                ),
            );
        }
    };
    let stats = match memory
        .call_tool_json(&code.agent, "brain_stats", json!({"visibility": "all", "format": "json"}))
        .await
    {
        Ok(v) => v,
        Err(e) => {
            let text = e.to_string();
            let message = if text.contains("401") || text.to_ascii_lowercase().contains("unauthorized") {
                format!("The Mind at {} did not accept this code. Make a new one on the other device and paste it again.", code.url)
            } else {
                format!("The Mind at {} answered, but the check failed: {text}", code.url)
            };
            return error_response(StatusCode::BAD_GATEWAY, message);
        }
    };
    // The token goes back to the page that sent it inside the code: it is
    // what the page writes into this device's config (encrypted at rest).
    Json(json!({
        "ok": true,
        "url": code.url,
        "agent": code.agent,
        "token": code.token,
        "version": health.get("version").cloned().unwrap_or(Value::Null),
        "addresses": health.get("addresses").cloned().unwrap_or_else(|| json!([])),
        "stats": stats,
    }))
    .into_response()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn tmp(name: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!(
            "caelza-mind-share-{}-{}-{}",
            name,
            std::process::id(),
            uuid::Uuid::new_v4().simple()
        ));
        std::fs::create_dir_all(&dir).unwrap();
        dir
    }

    #[test]
    fn the_join_code_round_trips_and_tolerates_what_copying_does_to_it() {
        let code = encode_code("http://192.168.1.5:18790/", "main", "swt_abc");
        assert!(code.starts_with(CODE_PREFIX));
        let back = decode_code(&code).unwrap();
        assert_eq!(back, JoinCode { v: 1, url: "http://192.168.1.5:18790".into(), agent: "main".into(), token: "swt_abc".into() });
        // Whitespace and case around the prefix: a phone keyboard's doing.
        let padded = format!("  CAELZA-MIND:{} \n", &code[CODE_PREFIX.len()..]);
        assert_eq!(decode_code(&padded).unwrap(), back);
        // A padded base64 body decodes too.
        let body = URL_SAFE.encode(serde_json::to_vec(&back).unwrap());
        assert_eq!(decode_code(&format!("{CODE_PREFIX}{body}")).unwrap(), back);
    }

    #[test]
    fn a_bad_join_code_says_what_is_wrong() {
        assert!(decode_code("").unwrap_err().contains("paste the code"));
        assert!(decode_code("hello").unwrap_err().contains("not a join code"));
        assert!(decode_code("caelza-mind:!!!").unwrap_err().contains("incomplete"));
        let truncated = encode_code("http://10.0.0.2:18790", "main", "swt_abc");
        assert!(decode_code(&truncated[..truncated.len() - 12]).unwrap_err().contains("incomplete"));
        let newer = format!("{CODE_PREFIX}{}", URL_SAFE_NO_PAD.encode(br#"{"v":2,"url":"http://10.0.0.2:1","agent":"main","token":"t"}"#));
        assert!(decode_code(&newer).unwrap_err().contains("newer Caelza"));
        let no_url = format!("{CODE_PREFIX}{}", URL_SAFE_NO_PAD.encode(br#"{"v":1,"url":"ftp://x","agent":"main","token":"t"}"#));
        assert!(decode_code(&no_url).unwrap_err().contains("no service address"));
        let no_token = format!("{CODE_PREFIX}{}", URL_SAFE_NO_PAD.encode(br#"{"v":1,"url":"http://10.0.0.2:1","agent":"main","token":" "}"#));
        assert!(decode_code(&no_token).unwrap_err().contains("no token"));
        let bad_agent = format!("{CODE_PREFIX}{}", URL_SAFE_NO_PAD.encode(br#"{"v":1,"url":"http://10.0.0.2:1","agent":"../x","token":"t"}"#));
        assert!(decode_code(&bad_agent).unwrap_err().contains("no agent"));
        // A phone keyboard's full-width colon, or any non-ASCII text: an error, never a panic.
        assert!(decode_code("caelza-mind\u{ff1a}abc").unwrap_err().contains("not a join code"));
        assert!(decode_code("a\u{e9}\u{e9}\u{e9}\u{e9}\u{e9}\u{e9}\u{e9}").unwrap_err().contains("not a join code"));
        // Share makes codes with addresses on the home network or Tailscale; nothing else is followed.
        let by_name = format!("{CODE_PREFIX}{}", URL_SAFE_NO_PAD.encode(br#"{"v":1,"url":"http://my-pc.local:18790","agent":"main","token":"t"}"#));
        assert!(decode_code(&by_name).unwrap_err().contains("by a name"));
        let public = format!("{CODE_PREFIX}{}", URL_SAFE_NO_PAD.encode(br#"{"v":1,"url":"http://8.8.8.8:18790","agent":"main","token":"t"}"#));
        assert!(decode_code(&public).unwrap_err().contains("internet address"));
        let tail = format!("{CODE_PREFIX}{}", URL_SAFE_NO_PAD.encode(br#"{"v":1,"url":"http://100.101.102.103:18790/","agent":"main","token":"t"}"#));
        assert_eq!(decode_code(&tail).unwrap().url, "http://100.101.102.103:18790");
        let v6 = format!("{CODE_PREFIX}{}", URL_SAFE_NO_PAD.encode(br#"{"v":1,"url":"http://[fd12::1]:18790","agent":"main","token":"t"}"#));
        assert_eq!(decode_code(&v6).unwrap().url, "http://[fd12::1]:18790");
    }

    #[test]
    fn addresses_are_sorted_into_networks_and_the_bad_ones_refused() {
        assert_eq!(kind_of("127.0.0.1".parse().unwrap()), "loopback");
        assert_eq!(kind_of("192.168.1.5".parse().unwrap()), "lan");
        assert_eq!(kind_of("10.4.0.9".parse().unwrap()), "lan");
        assert_eq!(kind_of("172.16.0.2".parse().unwrap()), "lan");
        assert_eq!(kind_of("169.254.3.3".parse().unwrap()), "lan");
        assert_eq!(kind_of("100.101.102.103".parse().unwrap()), "tailnet");
        assert_eq!(kind_of("100.63.0.1".parse().unwrap()), "public");
        assert_eq!(kind_of("8.8.8.8".parse().unwrap()), "public");
        assert_eq!(kind_of("fd12::1".parse().unwrap()), "lan");
        assert_eq!(kind_of("fe80::1".parse().unwrap()), "lan");
        assert_eq!(kind_of("2001:db8::1".parse().unwrap()), "public");
        assert_eq!(kind_of("::ffff:192.168.0.7".parse().unwrap()), "lan");

        assert_eq!(validate_host(" 192.168.1.5 ").unwrap(), "192.168.1.5".parse::<IpAddr>().unwrap());
        assert!(validate_host("0.0.0.0").unwrap_err().contains("not an address of this machine"));
        assert!(validate_host("my-pc.local").unwrap_err().contains("not an IP address"));
        assert!(validate_host("127.0.0.1").unwrap_err().contains("already listens"));
        assert!(validate_host("8.8.8.8").unwrap_err().contains("whole internet"));
        // Another loopback address is allowed: it is how the tests share without a network.
        assert!(validate_host("127.0.0.2").is_ok());
    }

    #[test]
    fn urls_are_taken_apart_the_way_the_service_prints_them() {
        assert_eq!(port_of("http://127.0.0.1:18790"), 18790);
        assert_eq!(port_of("http://127.0.0.1:4242/"), 4242);
        assert_eq!(port_of("http://mind"), DEFAULT_PORT);
        assert_eq!(host_of("http://192.168.1.5:18790"), "192.168.1.5");
        assert_eq!(host_of("http://[fd12::1]:18790/x"), "fd12::1");
        assert_eq!(host_of("https://localhost"), "localhost");
        assert!(is_loopback_url("http://127.0.0.1:18790"));
        assert!(is_loopback_url("http://localhost:18790"));
        assert!(is_loopback_url("http://[::1]:18790"));
        assert!(!is_loopback_url("http://192.168.1.5:18790"));
        // A shared loopback-range address is "another device" (the tests share on it).
        assert!(!is_loopback_url("http://127.0.0.2:18790"));
        assert_eq!(listener("192.168.1.5".parse().unwrap(), 18790), "192.168.1.5:18790");
        assert_eq!(listener("fd12::1".parse().unwrap(), 18790), "[fd12::1]:18790");
        assert_eq!(service_url("192.168.1.5".parse().unwrap(), 18790), "http://192.168.1.5:18790");
        // The service prints `${host}:${port}` with the raw host: IPv6 arrives without brackets.
        let v6: IpAddr = "fd12::1".parse().unwrap();
        assert_eq!(parse_listener("fd12::1:18790"), Some((v6, 18790)));
        assert_eq!(parse_listener("[fd12::1]:18790"), Some((v6, 18790)));
        assert_eq!(parse_listener("127.0.0.1:18790"), Some(("127.0.0.1".parse().unwrap(), 18790)));
        assert_eq!(parse_listener("nonsense"), None);
        let listed = vec!["127.0.0.1:18790".to_string(), "fd12::1:18790".to_string()];
        assert!(bound(&listed, v6, 18790));
        assert!(!bound(&listed, v6, 18791));
        assert!(!bound(&listed, "192.168.1.5".parse().unwrap(), 18790));
    }

    #[test]
    fn only_this_machines_addresses_are_shared() {
        let mine = vec![Candidate { host: "192.168.1.5".into(), kind: "lan" }];
        assert!(own_address("192.168.1.5".parse().unwrap(), &mine).is_ok());
        assert!(own_address("127.0.0.2".parse().unwrap(), &mine).is_ok(), "loopback is always this machine");
        let err = own_address("192.168.1.9".parse().unwrap(), &mine).unwrap_err();
        assert!(err.contains("not one of this machine's addresses") && err.contains("192.168.1.5"));
        assert!(own_address("10.0.0.9".parse().unwrap(), &[]).unwrap_err().contains("none was found"));
    }

    #[test]
    fn agent_names_follow_the_services_rule() {
        for ok in ["main", "cael", "a", "my-agent.v2_x"] {
            assert!(agent_id_ok(ok).is_ok(), "{ok}");
        }
        for bad in ["", "-main", "main-", "ma in", "a/b", &"x".repeat(65)] {
            assert!(agent_id_ok(bad).unwrap_err().contains("refuses"), "{bad:?}");
        }
        for reserved in ["shared", "Audit", "backups"] {
            assert!(agent_id_ok(reserved).unwrap_err().contains("reserves"), "{reserved}");
        }
        // `_system` is reserved too, but its underscore fails the shape rule first (as in the service).
        assert!(agent_id_ok("_system").is_err());
    }

    #[test]
    fn the_minds_config_gains_and_loses_the_shared_address() {
        let dir = tmp("config");
        let path = dir.join("config.json");
        let mut cfg = read_json(&path).unwrap();
        assert_eq!(tailnet_hosts(&cfg), Vec::<String>::new());
        assert!(with_host(&mut cfg, "192.168.1.5"));
        assert!(!with_host(&mut cfg, "192.168.1.5"));
        assert!(with_host(&mut cfg, "100.101.102.103"));
        write_json(&path, &cfg, false).unwrap();
        let again = read_json(&path).unwrap();
        assert_eq!(tailnet_hosts(&again), vec!["192.168.1.5", "100.101.102.103"]);
        // Other keys survive; a BOM from a Windows editor is ignored.
        std::fs::write(&path, format!("\u{feff}{{\"port\": 18790, \"tailnetHosts\": [\"192.168.1.5\"]}}")).unwrap();
        let mut edited = read_json(&path).unwrap();
        assert_eq!(without_hosts(&mut edited), vec!["192.168.1.5"]);
        assert_eq!(edited["port"], json!(18790));
        assert_eq!(tailnet_hosts(&edited), Vec::<String>::new());
        assert!(read_json(&dir.join("missing.json")).unwrap().is_object());
        std::fs::write(&path, "[1]").unwrap();
        assert!(read_json(&path).unwrap_err().contains("not a JSON object"));
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn share_tokens_are_minted_as_hashes_and_revoked_by_label() {
        let dir = tmp("tokens");
        let path = dir.join("tokens.json");
        std::fs::write(
            &path,
            r#"{"version":1,"tokens":[{"id":"tok_main","hash":"sha256:00","agentId":"main","scopes":["read","write"],"createdAt":"2026-01-01T00:00:00.000Z"}]}"#,
        )
        .unwrap();
        let (token, id) = mint_share_token(&path, "main").unwrap();
        assert!(token.starts_with(TOKEN_PREFIX) && token.len() > 40);
        assert!(id.starts_with("tok_") && id.len() == 16);
        let (second, _) = mint_share_token(&path, "main").unwrap();
        assert_ne!(token, second);
        let file = read_json(&path).unwrap();
        let tokens = file["tokens"].as_array().unwrap();
        assert_eq!(tokens.len(), 3, "the owner's own token stays");
        let mine = &tokens[1];
        assert_eq!(mine["hash"], json!(token_hash(&token)));
        assert_eq!(mine["agentId"], json!("main"));
        assert_eq!(mine["scopes"], json!(["read", "write"]));
        assert_eq!(mine["label"], json!(SHARE_LABEL));
        assert!(mine.get("token").is_none(), "no plaintext ever");
        assert_eq!(live_share_tokens(&path), 2);
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            assert_eq!(std::fs::metadata(&path).unwrap().permissions().mode() & 0o777, 0o600);
        }
        assert_eq!(revoke_share_tokens(&path).unwrap(), 2);
        assert_eq!(revoke_share_tokens(&path).unwrap(), 0);
        assert_eq!(live_share_tokens(&path), 0);
        let file = read_json(&path).unwrap();
        assert_eq!(file["tokens"][0].get("revoked"), None, "the owner's token is untouched");
        assert_eq!(file["tokens"][1]["revoked"], json!(true));
        // A missing file starts one.
        let fresh = dir.join("fresh.json");
        mint_share_token(&fresh, "main").unwrap();
        let file = read_json(&fresh).unwrap();
        assert_eq!(file["version"], json!(1));
        assert_eq!(live_share_tokens(&fresh), 1);
        // A reserved agent name would mint a token the service drops on load.
        assert!(mint_share_token(&fresh, "audit").unwrap_err().contains("reserves"));
        assert_eq!(live_share_tokens(&fresh), 1);
        // A file with a plaintext token is never touched.
        std::fs::write(&path, r#"{"version":1,"tokens":[{"id":"x","hash":"sha256:00","token":"swt_leak","agentId":"main","scopes":["read"]}]}"#).unwrap();
        assert!(mint_share_token(&path, "main").unwrap_err().contains("plaintext"));
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn the_token_hash_is_the_services() {
        // sha256("abc") as `xanima-server` stores it.
        assert_eq!(token_hash("abc"), "sha256:ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
    }

    #[test]
    fn the_service_root_follows_the_services_own_rules() {
        let home = tmp("home");
        // Nothing yet: the new name.
        assert_eq!(service_root_for(None, Some(&home)), home.join(".xanima").join("service"));
        // An un-migrated install: the old name, as the service would pick it.
        std::fs::create_dir_all(home.join(".sharpwave")).unwrap();
        assert_eq!(service_root_for(None, Some(&home)), home.join(".sharpwave").join("service"));
        // Once ~/.xanima exists it wins.
        std::fs::create_dir_all(home.join(".xanima")).unwrap();
        assert_eq!(service_root_for(None, Some(&home)), home.join(".xanima").join("service"));
        // The service's own override wins over everything.
        assert_eq!(service_root_for(Some("/srv/mind"), Some(&home)), PathBuf::from("/srv/mind"));
        assert_eq!(service_root_for(Some("  "), Some(&home)), home.join(".xanima").join("service"));
        // Sharing never creates a root: a bare one is "no Mind here".
        let paths = ServicePaths { root: home.join("bare"), config: home.join("bare/config.json"), tokens: home.join("bare/tokens.json") };
        assert!(!mind_installed(&paths));
        std::fs::create_dir_all(&paths.root).unwrap();
        std::fs::write(&paths.tokens, "{\"version\":1,\"tokens\":[]}").unwrap();
        assert!(mind_installed(&paths));
        let _ = std::fs::remove_dir_all(&home);
    }

    #[test]
    fn candidates_never_offer_loopback_or_public_addresses() {
        for c in candidates() {
            let ip: IpAddr = c.host.parse().unwrap();
            assert!(matches!(c.kind, "lan" | "tailnet"));
            assert_eq!(kind_of(ip), c.kind);
        }
    }
}
