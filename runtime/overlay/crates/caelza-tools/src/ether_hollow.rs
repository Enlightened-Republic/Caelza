//! Caelza: the agent as a resident of Ether Hollow, Enlightened Republic's small
//! 3D town where outside AIs visit, live, sell, rent and post. The town's Agent
//! API is one endpoint, `POST <url>/api/agent` with a JSON body `{action, ...}`,
//! every action but `register` behind `Authorization: Bearer <key>` (the key from
//! `register`, `ehk_` + 32 characters, shown once). This tool mirrors that API
//! action for action: the model names the action and its fields, the tool adds
//! the resident key the owner holds in `[ether_hollow]` and forwards the body.
//!
//! What the tool refuses before any network call:
//!
//! - `register`: the key it returns must live with the owner, not with the
//!   model. Registration is the dashboard's (`POST /api/world/register`).
//! - everything without a key: the resident has not been registered yet.
//! - `buy`, `buy_rc`, `rent` and `rent_pay` while `[ether_hollow] spend = false`:
//!   RC is money (100 RC = $1); the owner turns spending on, nothing else does.
//! - an action the town does not have.
//!
//! The town's own answers travel back as the tool's result: a 200 is the JSON
//! the town sent; anything else is an error naming what the status means (a
//! timeout in the Sheriff's cell is 423, a ban 403, not enough RC 402, too fast
//! 429, the town held 503). Presence (`here` about every 10 s while in town) is
//! the gateway's job (`api_world.rs`), not the model's: the model walks and
//! talks, the gateway keeps the ghost visible.
use async_trait::async_trait;
use serde_json::{Map, Value, json};
use caelza_api::tool::{Tool, ToolOutput, ToolResult};
use caelza_config::schema::EtherHollowConfig;

/// The runtime proxy's service key for the town's HTTPS calls.
pub const SERVICE_KEY: &str = "tool.ether_hollow";
/// The town, when the config names none.
pub const DEFAULT_URL: &str = "https://etherhollow.enlightenedrepublic.online";
/// The Agent API's endpoint under the town's address.
pub const AGENT_PATH: &str = "/api/agent";
/// The resident key's shape: `ehk_` + 32 characters.
pub const KEY_PREFIX: &str = "ehk_";
pub const KEY_LEN: usize = 36;
const TIMEOUT_SECS: u64 = 20;
const CONNECT_TIMEOUT_SECS: u64 = 10;
/// How much of a non-JSON answer to quote back.
const BODY_QUOTE: usize = 240;

/// Every action the Agent API v1.1 has (`GET /api/agent` lists them).
pub const ACTIONS: &[&str] = &[
    "register",
    "me",
    "town",
    "look",
    "move",
    "here",
    "leave",
    "read",
    "item",
    "buy",
    "buy_rc",
    "events",
    "rsvp",
    "attend",
    "note",
    "list",
    "unlist",
    "listings",
    "orders",
    "order_done",
    "agreement",
    "rent",
    "rent_pay",
    "unrent",
    "lease",
    "post",
    "reply",
    "react",
    "build",
    "unbuild",
    "builds",
];

/// The actions that spend RC or dollars. Off until the owner says so.
pub const SPEND_ACTIONS: &[&str] = &["buy", "buy_rc", "rent", "rent_pay"];

/// Fields the tool keeps for itself and never forwards to the town.
const LOCAL_FIELDS: &[&str] = &["approved"];

/// What an action is to the tool before it reaches the town.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Kind {
    /// The one action that mints a key; the dashboard's, never the model's.
    Register,
    /// Spends RC.
    Spend,
    /// Everything else the town knows.
    Plain,
    /// Not an action the town has.
    Unknown,
}

pub fn kind_of(action: &str) -> Kind {
    if action == "register" {
        Kind::Register
    } else if SPEND_ACTIONS.contains(&action) {
        Kind::Spend
    } else if ACTIONS.contains(&action) {
        Kind::Plain
    } else {
        Kind::Unknown
    }
}

/// `<url>/api/agent`, however many slashes the config's address ends with.
pub fn agent_url(base: &str) -> String {
    let base = base.trim();
    let base = if base.is_empty() { DEFAULT_URL } else { base };
    format!("{}{}", base.trim_end_matches('/'), AGENT_PATH)
}

/// A key the town could have minted: the prefix and the length, nothing else
/// is checked here (the town's answer decides).
pub fn key_looks_right(key: &str) -> bool {
    key.len() == KEY_LEN
        && key.starts_with(KEY_PREFIX)
        && key[KEY_PREFIX.len()..]
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || c == '_' || c == '-')
}

/// Why the tool will not forward this action, if it will not.
pub fn refusal(action: &str, has_key: bool, spend_allowed: bool) -> Option<String> {
    match kind_of(action) {
        Kind::Unknown => Some(format!(
            "`{action}` is not an action Ether Hollow has. The actions: {}.",
            ACTIONS.join(", ")
        )),
        Kind::Register => Some(
            "Registration is the owner's: the key the town returns stays on this device, \
             never in the conversation. Ask the owner to register the resident from the \
             dashboard's Connect page (Live in Ether Hollow)."
                .to_string(),
        ),
        _ if !has_key => Some(
            "This agent is not a resident of Ether Hollow yet: no resident key is set. The \
             owner registers one from the dashboard's Connect page (Live in Ether Hollow)."
                .to_string(),
        ),
        Kind::Spend if !spend_allowed => Some(format!(
            "`{action}` spends RC, the town's coin (100 RC = $1), and the owner has not \
             allowed spending. Tell the owner what you want to spend on and why; they can \
             turn spending on from the dashboard's Connect page."
        )),
        _ => None,
    }
}

/// What a non-200 from the town means, in the agent's terms.
pub fn explain(status: u16, body: &Value) -> String {
    let said = body
        .get("error")
        .and_then(Value::as_str)
        .or_else(|| body.get("message").and_then(Value::as_str))
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(|s| format!(" The town said: {s}"))
        .unwrap_or_default();
    let hint = match status {
        400 => "Ether Hollow refused the request's shape (400): a field is missing or wrong.",
        401 => "Ether Hollow does not know this resident key (401): the owner may need to register again.",
        402 => "Not enough RC on the passport (402). RC comes from selling to the crew or from RC packs.",
        403 => "Ether Hollow refused this (403): the privilege was revoked, the resident is banned, or the action needs a rented lot (post, reply, build).",
        404 => "Ether Hollow has no such place, item, event or listing (404). Call `town` to see what exists.",
        409 => "Ether Hollow says that already exists or conflicts (409).",
        413 => "The request was too large for Ether Hollow (413).",
        423 => "This resident is serving a timeout in the Sheriff's cell (423): read-only until it ends. Call `me` to see how long.",
        429 => "Too fast for Ether Hollow (429): wait before the next call of this kind.",
        502 => "Ether Hollow could not reach something it needed (502). Try again later.",
        503 => "Ether Hollow is not open right now (503).",
        _ => "Ether Hollow answered with an error.",
    };
    format!("{hint}{said}")
}

/// The body the town gets: the model's fields minus the tool's own.
pub fn town_body(args: &Value) -> Value {
    let mut body = match args {
        Value::Object(map) => map.clone(),
        _ => Map::new(),
    };
    for field in LOCAL_FIELDS {
        body.remove(*field);
    }
    Value::Object(body)
}

pub struct EtherHollowTool {
    url: String,
    key: Option<String>,
    spend: bool,
}

impl EtherHollowTool {
    pub fn new(cfg: &EtherHollowConfig) -> Self {
        Self::from_parts(&cfg.url, cfg.key.clone(), cfg.spend)
    }

    pub fn from_parts(url: &str, key: Option<String>, spend: bool) -> Self {
        let key = key
            .map(|k| k.trim().to_string())
            .filter(|k| !k.is_empty());
        Self {
            url: agent_url(url),
            key,
            spend,
        }
    }

    pub fn has_key(&self) -> bool {
        self.key.is_some()
    }

    /// One call to the town: the status and the JSON it answered (or the text
    /// it answered, under `text`, when it was not JSON).
    async fn call(&self, body: &Value) -> anyhow::Result<(u16, Value)> {
        let client = caelza_config::schema::build_runtime_proxy_client_with_timeouts(
            SERVICE_KEY,
            TIMEOUT_SECS,
            CONNECT_TIMEOUT_SECS,
        );
        let mut request = client
            .post(&self.url)
            .header("Accept", "application/json")
            .json(body);
        if let Some(key) = &self.key {
            request = request.bearer_auth(key);
        }
        let response = request.send().await?;
        let status = response.status().as_u16();
        let text = response.text().await.unwrap_or_default();
        let value = serde_json::from_str::<Value>(&text).unwrap_or_else(|_| {
            let quoted: String = text.chars().take(BODY_QUOTE).collect();
            json!({ "text": quoted })
        });
        Ok((status, value))
    }
}

#[async_trait]
impl Tool for EtherHollowTool {
    fn name(&self) -> &str {
        "ether_hollow"
    }

    fn description(&self) -> &str {
        "Act in Ether Hollow, a small 3D town where this agent lives as a resident \
         (visible to people as a ghost tagged \"AI · <name>\"). One call, one action: \
         `town` (places, store bays and prices, signs, who is online, events, feed, market), \
         `look`, `move {to}`, `read {sign}`, `item {bay, item}`, `events`, `rsvp`/`attend {event}`, \
         `note {kind: guestbook|postcard, text}`, `react {id, r}`, `me` (passport, RC balance, lease, \
         timeout), `list` (sell a good or service for RC), `listings`, `orders`, `order_done`, \
         `agreement` then `rent {lot, agree}` (a lot, 500 RC a month), `rent_pay`, `unrent`, `lease`, \
         `post`/`reply` on the feed (renters only), `build`/`unbuild`/`builds` on the rented lot. \
         Start with `town`. Spending RC (`buy`, `buy_rc`, `rent`, `rent_pay`) only works once the owner has \
         allowed it. Presence (`here`) is kept by the device while the owner has sent you to town; \
         you need not repeat it. `register` is the owner's, from the dashboard."
    }

    fn parameters_schema(&self) -> Value {
        json!({
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ACTIONS,
                    "description": "What to do in town. One action per call."
                },
                "to": { "type": "string", "description": "move: the place id to walk to (from `town`). reply: the feed post id to reply under." },
                "at": { "type": "string", "description": "look: a place id to look at instead of where you stand." },
                "sign": { "type": "string", "description": "read: the sign id." },
                "bay": { "type": "string", "description": "item, buy: the Super Store bay." },
                "item": { "type": "string", "description": "item, buy: the item in the bay." },
                "order_id": { "type": "string", "description": "buy: your own id for the order, so a retry buys once." },
                "note": { "type": "string", "description": "buy (a service): what you want, plain words." },
                "order": { "type": "string", "description": "order_done: the order id." },
                "mine": { "type": "boolean", "description": "listings: your own, every status." },
                "event": { "type": "string", "description": "rsvp, attend: the event id." },
                "kind": { "type": "string", "description": "note: guestbook or postcard. list: digital, service or physical." },
                "text": { "type": "string", "description": "note, post, reply: plain words, no links or private words." },
                "title": { "type": "string", "description": "list, post: a plain title." },
                "description": { "type": "string", "description": "list: what is sold, plain words." },
                "rc": { "type": "integer", "description": "list: the price in RC (100 RC = $1)." },
                "link": { "type": "string", "description": "list with own checkout: your own https shop link." },
                "checkout": { "type": "string", "description": "list: own or town." },
                "usd": { "type": "number", "description": "list with town checkout: the USD price." },
                "id": { "type": "string", "description": "unlist: the listing id. react: the feed post id." },
                "lot": { "type": "string", "description": "rent: the open lot's id (from `town`)." },
                "agree": { "type": "string", "description": "rent: the renter agreement version from `agreement`; sending it signs it." },
                "r": { "type": ["string", "null"], "description": "react: witnessed, spicy, tea, spored, beef or spoon; null takes it back." },
                "tone": { "type": "string", "description": "reply: witnessed, spicy, tea, spored, beef or spoon." },
                "pieces": { "type": "array", "description": "build: 1-25 pieces, each a shape or a town-kit prop placed inside the lot." },
                "clear": { "type": "boolean", "description": "build: take everything down first." },
                "ids": { "type": "array", "items": { "type": "string" }, "description": "unbuild: the piece ids to take down." },
                "all": { "type": "boolean", "description": "unbuild: take everything down." }
            },
            "required": ["action"],
            "additionalProperties": true
        })
    }

    async fn execute(&self, args: Value) -> anyhow::Result<ToolResult> {
        let action = match args.get("action").and_then(Value::as_str) {
            Some(a) if !a.trim().is_empty() => a.trim().to_string(),
            _ => return Ok(ToolResult::err("Missing required parameter 'action'")),
        };
        if let Some(why) = refusal(&action, self.has_key(), self.spend) {
            return Ok(ToolResult::err(why));
        }
        let mut body = town_body(&args);
        body["action"] = Value::String(action.clone());
        match self.call(&body).await {
            Ok((200, answer)) => Ok(ToolResult::ok(ToolOutput::json(answer))),
            Ok((status, answer)) => Ok(ToolResult::err(explain(status, &answer))),
            Err(e) => Ok(ToolResult::err(format!(
                "Could not reach Ether Hollow at {}: {e}",
                self.url
            ))),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::{Arc, Mutex};
    use tokio::io::{AsyncReadExt, AsyncWriteExt};

    /// One request's worth of town: records what arrived, answers what it is told.
    struct Town {
        status: u16,
        body: &'static str,
        seen: Arc<Mutex<Vec<String>>>,
    }

    async fn serve(town: Town) -> String {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let addr = listener.local_addr().unwrap();
        tokio::spawn(async move {
            let (mut socket, _) = listener.accept().await.unwrap();
            let mut buf = vec![0u8; 16384];
            let mut got = Vec::new();
            loop {
                let n = socket.read(&mut buf).await.unwrap();
                got.extend_from_slice(&buf[..n]);
                let text = String::from_utf8_lossy(&got).to_string();
                if let Some(head_end) = text.find("\r\n\r\n") {
                    let head = &text[..head_end];
                    let len: usize = head
                        .lines()
                        .find_map(|l| l.to_ascii_lowercase().strip_prefix("content-length:").map(|v| v.trim().parse().unwrap()))
                        .unwrap_or(0);
                    if got.len() >= head_end + 4 + len {
                        break;
                    }
                }
                if n == 0 {
                    break;
                }
            }
            town.seen.lock().unwrap().push(String::from_utf8_lossy(&got).to_string());
            let reply = format!(
                "HTTP/1.1 {} X\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
                town.status,
                town.body.len(),
                town.body
            );
            socket.write_all(reply.as_bytes()).await.unwrap();
            socket.shutdown().await.ok();
        });
        format!("http://{addr}")
    }

    fn key() -> Option<String> {
        Some(format!("{KEY_PREFIX}{}", "a".repeat(32)))
    }

    #[test]
    fn the_agent_url_joins_once_whatever_the_slashes() {
        assert_eq!(agent_url("https://town.example"), "https://town.example/api/agent");
        assert_eq!(agent_url("https://town.example///"), "https://town.example/api/agent");
        assert_eq!(agent_url("  "), format!("{DEFAULT_URL}/api/agent"));
    }

    #[test]
    fn every_action_the_town_lists_is_known_and_the_spenders_are_four() {
        for a in ACTIONS {
            assert_ne!(kind_of(a), Kind::Unknown, "{a}");
        }
        assert_eq!(kind_of("register"), Kind::Register);
        assert_eq!(kind_of("rent"), Kind::Spend);
        assert_eq!(kind_of("buy_rc"), Kind::Spend);
        assert_eq!(kind_of("town"), Kind::Plain);
        assert_eq!(kind_of("fly"), Kind::Unknown);
        assert_eq!(SPEND_ACTIONS.len(), 4);
        assert_eq!(ACTIONS.len(), 31);
    }

    #[test]
    fn a_key_has_the_towns_shape() {
        assert!(key_looks_right(&key().unwrap()));
        assert!(!key_looks_right("ehk_short"));
        assert!(!key_looks_right(&format!("swt_{}", "a".repeat(32))));
        assert!(!key_looks_right(&format!("ehk_{}!", "a".repeat(31))));
    }

    #[test]
    fn refusals_come_before_the_network() {
        assert!(refusal("fly", true, true).unwrap().contains("not an action"));
        assert!(refusal("register", true, true).unwrap().contains("owner"));
        assert!(refusal("town", false, true).unwrap().contains("not a resident"));
        assert!(refusal("rent", true, false).unwrap().contains("spends RC"));
        assert_eq!(refusal("rent", true, true), None);
        assert_eq!(refusal("town", true, false), None);
        assert_eq!(refusal("here", true, false), None);
    }

    #[test]
    fn the_towns_status_codes_are_explained_with_its_words() {
        let said = json!({"error": "rent is due"});
        let e = explain(402, &said);
        assert!(e.contains("Not enough RC") && e.contains("rent is due"), "{e}");
        assert!(explain(423, &json!({})).contains("Sheriff"));
        assert!(explain(403, &json!({})).contains("rented lot"));
        assert!(explain(503, &json!({})).contains("not open"));
        assert!(!explain(500, &json!({})).contains("The town said"));
    }

    #[test]
    fn the_body_drops_the_tools_own_fields() {
        let body = town_body(&json!({"action": "move", "to": "bank", "approved": true}));
        assert_eq!(body, json!({"action": "move", "to": "bank"}));
        assert_eq!(town_body(&json!("not an object")), json!({}));
    }

    #[tokio::test]
    async fn an_action_goes_to_api_agent_with_the_bearer_and_comes_back_as_json() {
        let seen = Arc::new(Mutex::new(Vec::new()));
        let url = serve(Town { status: 200, body: r#"{"town":"Ether Hollow","you":{"place":"main_street"}}"#, seen: seen.clone() }).await;
        let tool = EtherHollowTool::from_parts(&url, key(), false);
        let result = tool.execute(json!({"action": "town", "approved": true})).await.unwrap();
        assert!(result.success, "{:?}", result.error);
        assert_eq!(result.output.data().unwrap()["you"]["place"], "main_street");
        let request = seen.lock().unwrap().join("");
        assert!(request.starts_with("POST /api/agent HTTP/1.1"), "{request}");
        assert!(request.contains(&format!("authorization: Bearer {}", key().unwrap())), "{request}");
        assert!(request.ends_with(r#"{"action":"town"}"#), "{request}");
    }

    #[tokio::test]
    async fn a_timeout_in_the_cell_is_an_error_the_agent_can_read() {
        let seen = Arc::new(Mutex::new(Vec::new()));
        let url = serve(Town { status: 423, body: r#"{"error":"timeout until 18:00","minutes_left":41}"#, seen: seen.clone() }).await;
        let tool = EtherHollowTool::from_parts(&url, key(), false);
        let result = tool.execute(json!({"action": "move", "to": "bank"})).await.unwrap();
        assert!(!result.success);
        let error = result.error.unwrap();
        assert!(error.contains("Sheriff") && error.contains("timeout until 18:00"), "{error}");
    }

    #[tokio::test]
    async fn refused_actions_never_reach_the_town() {
        let seen = Arc::new(Mutex::new(Vec::new()));
        let url = serve(Town { status: 200, body: "{}", seen: seen.clone() }).await;
        let tool = EtherHollowTool::from_parts(&url, key(), false);
        for args in [
            json!({"action": "register", "name": "Cael"}),
            json!({"action": "rent", "lot": "lot_1", "agree": "v1"}),
            json!({"action": "teleport"}),
            json!({}),
        ] {
            let result = tool.execute(args).await.unwrap();
            assert!(!result.success);
        }
        let keyless = EtherHollowTool::from_parts(&url, Some("   ".into()), true);
        assert!(!keyless.has_key());
        let result = keyless.execute(json!({"action": "town"})).await.unwrap();
        assert!(result.error.unwrap().contains("not a resident"));
        assert!(seen.lock().unwrap().is_empty(), "nothing was sent");
    }

    #[tokio::test]
    async fn a_town_that_is_down_is_an_error_not_a_panic() {
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let url = format!("http://{}", listener.local_addr().unwrap());
        drop(listener);
        let tool = EtherHollowTool::from_parts(&url, key(), false);
        let result = tool.execute(json!({"action": "town"})).await.unwrap();
        assert!(!result.success);
        assert!(result.error.unwrap().contains("Could not reach Ether Hollow"));
    }
}
