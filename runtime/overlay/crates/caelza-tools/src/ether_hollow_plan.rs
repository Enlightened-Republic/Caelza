//! The day plan (vision M10, slice 5b): the resident keeps its own hours in
//! Ether Hollow, inside the hours its owner gives it.
//!
//! - The owner's grid lives in the config, under the resident's own table:
//!   `hours`, one line per span (`"mon 09:00-12:00"`, several spans on a line
//!   comma-separated, several lines a day), in the device's local time, and
//!   `visits_month`, the month's budget in planned visits. Each planned visit
//!   is one wake of the model (the slot's), and the once-a-day wake that asks
//!   the agent for its plan counts one too: what the Runtime can count exactly,
//!   and what costs the owner a model run. No hours or a budget of 0: no day
//!   plan, the town only wakes the agent the way it did before.
//! - The agent's plan is its own: the `plan` action of the `ether_hollow`
//!   tool (`show`, `set`, `clear`), never sent to the town, kept in
//!   `<install root>/world/plan/<alias>.json`. A slot is a time, a length, a
//!   place and what it will do there; a slot outside the owner's hours, over
//!   the budget, overlapping another or already over is refused with the reason.
//! - The gateway runs it (api_world.rs): at each slot's time a visit begins,
//!   the resident walks to the slot's place when the town has it, and a wake
//!   carries the slot and the agent's top want; the visit ends at the slot's
//!   end. What ran and how much of the budget is used is the gateway's file,
//!   `<install root>/world/plan/<alias>.used.json`.
//!
//! Everything here is plain functions over the files' shapes and a local
//! clock passed in, so both the tool and the gateway use one rule.
use chrono::{Datelike, Duration as Days, NaiveDate, NaiveDateTime, Timelike};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

/// The week as the owner's lines name it.
pub const DAYS: [&str; 7] = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
pub const DAY_NAMES: [&str; 7] = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
/// Where the plans live under the install root.
pub const WORLD_DIR: &str = "world";
pub const PLAN_DIR: &str = "plan";
/// A day's slots at most, and a slot's length in minutes.
pub const MAX_SLOTS: usize = 12;
pub const MIN_SLOT: u64 = 5;
pub const MAX_SLOT: u64 = 240;
pub const PLACE_MAX: usize = 60;
pub const DOING_MAX: usize = 140;
/// How much of a want the prompt carries.
pub const WANT_MAX: usize = 160;
/// The budget's unit, as the card and the tool say it.
pub const BUDGET_UNIT: &str = "planned visits a month (each is one wake of the model; the daily planning wake counts one)";

/// One span of the owner's grid: a weekday (0 = Monday) and minutes of the day.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub struct Span {
    pub day: usize,
    pub from: u32,
    pub to: u32,
}

/// `HH:MM` (or `H:MM`) as minutes of the day; `24:00` only as an end.
pub fn hhmm(s: &str) -> Option<u32> {
    let (h, m) = s.trim().split_once(':')?;
    if h.is_empty() || h.len() > 2 || m.len() != 2 || !h.chars().chain(m.chars()).all(|c| c.is_ascii_digit()) {
        return None;
    }
    let (h, m) = (h.parse::<u32>().ok()?, m.parse::<u32>().ok()?);
    if m > 59 || h > 24 || (h == 24 && m != 0) {
        return None;
    }
    Some(h * 60 + m)
}

pub fn fmt_hhmm(minutes: u32) -> String {
    format!("{:02}:{:02}", minutes / 60, minutes % 60)
}

/// `mon`, `Monday`, `MON` → 0.
pub fn day_of(name: &str) -> Option<usize> {
    let n = name.trim().to_ascii_lowercase();
    if n.len() < 3 {
        return None;
    }
    DAY_NAMES.iter().position(|full| full.to_ascii_lowercase().starts_with(&n))
}

/// The owner's grid from the config's lines. An error names the line it could not read.
pub fn parse_hours(lines: &[String]) -> Result<Vec<Span>, String> {
    let mut out = Vec::new();
    for line in lines {
        let line = line.trim();
        if line.is_empty() {
            continue;
        }
        let (day, rest) = line.split_once(char::is_whitespace).ok_or_else(|| format!("`{line}`: a day and its hours, like `mon 09:00-12:00`"))?;
        let day = day_of(day).ok_or_else(|| format!("`{line}`: `{day}` is not a day (mon, tue, wed, thu, fri, sat, sun)"))?;
        for span in rest.split(',') {
            let span = span.trim();
            if span.is_empty() {
                continue;
            }
            let (from, to) = span.split_once('-').ok_or_else(|| format!("`{line}`: `{span}` is not a span like 09:00-12:00"))?;
            let (Some(from), Some(to)) = (hhmm(from), hhmm(to)) else {
                return Err(format!("`{line}`: `{span}` is not a span like 09:00-12:00"));
            };
            if from >= 24 * 60 || to <= from {
                return Err(format!("`{line}`: `{span}` ends before it starts"));
            }
            out.push(Span { day, from, to });
        }
    }
    out.sort();
    out.dedup();
    Ok(out)
}

/// A weekday's spans.
pub fn hours_for(spans: &[Span], day: usize) -> Vec<Span> {
    spans.iter().filter(|s| s.day == day).copied().collect()
}

/// A weekday's hours as words: `09:00-12:00, 14:00-18:00`; empty when the day is off.
pub fn hours_text(spans: &[Span], day: usize) -> String {
    hours_for(spans, day).iter().map(|s| format!("{}-{}", fmt_hhmm(s.from), fmt_hhmm(s.to))).collect::<Vec<_>>().join(", ")
}

/// The grid as the config's lines, one per day that has hours.
pub fn grid_lines(spans: &[Span]) -> Vec<String> {
    (0..7)
        .filter_map(|d| {
            let text = hours_text(spans, d);
            (!text.is_empty()).then(|| format!("{} {text}", DAYS[d]))
        })
        .collect()
}

pub fn weekday(date: NaiveDate) -> usize {
    date.weekday().num_days_from_monday() as usize
}

pub fn day_key(date: NaiveDate) -> String {
    date.format("%Y-%m-%d").to_string()
}

pub fn month_of(date: NaiveDate) -> String {
    date.format("%Y-%m").to_string()
}

/// Minutes of the day of a local time.
pub fn minute_of(now: NaiveDateTime) -> u32 {
    now.hour() * 60 + now.minute()
}

/// One stop of the agent's day.
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
pub struct Slot {
    pub at: String,
    pub minutes: u64,
    #[serde(default)]
    pub place: String,
    #[serde(default)]
    pub doing: String,
}

impl Slot {
    pub fn start(&self) -> Option<u32> {
        hhmm(&self.at)
    }

    pub fn end(&self) -> Option<u32> {
        self.start().map(|s| s + self.minutes.min(MAX_SLOT) as u32)
    }
}

/// A day's plan as the agent set it.
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
pub struct DayPlan {
    pub day: String,
    #[serde(default)]
    pub slots: Vec<Slot>,
    #[serde(default)]
    pub set_at: u64,
}

/// The resident's plans by day (`YYYY-MM-DD`): today's, and tomorrow's when it planned ahead.
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
pub struct Plans {
    #[serde(default)]
    pub days: BTreeMap<String, DayPlan>,
}

/// What the gateway ran: the month, the wakes it counted, the slots it
/// started (`YYYY-MM-DD HH:MM`), the last day it asked for a plan.
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
pub struct Used {
    #[serde(default)]
    pub month: String,
    #[serde(default)]
    pub used: u64,
    #[serde(default)]
    pub ran: Vec<String>,
    #[serde(default)]
    pub asked: Option<String>,
}

impl Used {
    /// The wakes counted in `month` (a new month starts at 0).
    pub fn for_month(&self, month: &str) -> u64 {
        if self.month == month { self.used } else { 0 }
    }

    /// A new month: the count and what ran start over.
    pub fn roll(&mut self, month: &str) {
        if self.month != month {
            self.month = month.to_string();
            self.used = 0;
            self.ran.clear();
        }
    }

    pub fn has_run(&self, key: &str) -> bool {
        self.ran.iter().any(|k| k == key)
    }

    /// One wake counted; a slot's key, when it was one, kept so it never runs twice.
    pub fn count(&mut self, month: &str, key: Option<String>) {
        self.roll(month);
        self.used += 1;
        if let Some(k) = key {
            if !self.has_run(&k) {
                self.ran.push(k);
            }
        }
    }
}

pub fn slot_key(day: &str, at: &str) -> String {
    format!("{day} {at}")
}

/// What is left of the month's budget.
pub fn budget_left(visits_month: u64, used: &Used, month: &str) -> u64 {
    visits_month.saturating_sub(used.for_month(month))
}

/// `day` as the tool takes it: none or `today`, `tomorrow`, or a date that is one of them.
pub fn resolve_day(day: Option<&str>, today: NaiveDate) -> Result<NaiveDate, String> {
    let tomorrow = today + Days::days(1);
    match day.map(str::trim).filter(|d| !d.is_empty()) {
        None => Ok(today),
        Some(d) if d.eq_ignore_ascii_case("today") => Ok(today),
        Some(d) if d.eq_ignore_ascii_case("tomorrow") => Ok(tomorrow),
        Some(d) => match NaiveDate::parse_from_str(d, "%Y-%m-%d") {
            Ok(date) if date == today || date == tomorrow => Ok(date),
            Ok(_) => Err(format!("You plan today ({}) or tomorrow ({}), not {d}.", day_key(today), day_key(tomorrow))),
            Err(_) => Err(format!("`{d}` is not a day: write today, tomorrow or YYYY-MM-DD.")),
        },
    }
}

/// The slots still to run in the other days kept, in `month`: the budget they hold.
pub fn pending_in(plans: &Plans, used: &Used, except_day: &str, month: &str) -> u64 {
    plans
        .days
        .iter()
        .filter(|(day, _)| day.as_str() != except_day && day.starts_with(month))
        .map(|(day, p)| p.slots.iter().filter(|s| !used.has_run(&slot_key(day, &s.at))).count() as u64)
        .sum()
}

/// A day's slots checked against the owner's grid and budget: sorted and
/// tidied, or the reason in plain words. `other_pending` is what the other
/// kept day of the same month still holds of the budget.
pub fn validate(
    slots: &[Slot],
    date: NaiveDate,
    now: NaiveDateTime,
    spans: &[Span],
    visits_month: u64,
    used: &Used,
    other_pending: u64,
) -> Result<Vec<Slot>, String> {
    if spans.is_empty() || visits_month == 0 {
        return Err("Your owner has not given you hours in town yet (the Day plan on their Connect card), so there is no day to plan. Ask them if you would like some.".to_string());
    }
    if slots.is_empty() {
        return Err("A plan needs at least one slot; `plan {op: \"clear\"}` takes a day's plan away.".to_string());
    }
    if slots.len() > MAX_SLOTS {
        return Err(format!("{} slots is more than a day holds here ({MAX_SLOTS} at most).", slots.len()));
    }
    let wd = weekday(date);
    let day_spans = hours_for(spans, wd);
    if day_spans.is_empty() {
        let week = grid_lines(spans).join("; ");
        return Err(format!("Your owner keeps {} free of town: no hours on {}. Your hours: {week}.", DAY_NAMES[wd], day_key(date)));
    }
    let hours = hours_text(spans, wd);
    let today = date == now.date();
    let now_min = minute_of(now);
    let mut out = Vec::new();
    for s in slots {
        let Some(start) = hhmm(&s.at).filter(|m| *m < 24 * 60) else {
            return Err(format!("`{}` is not a time: write HH:MM, like 09:00.", s.at.trim()));
        };
        let at = fmt_hhmm(start);
        if s.minutes < MIN_SLOT || s.minutes > MAX_SLOT {
            return Err(format!("{at}: a slot is {MIN_SLOT} to {MAX_SLOT} minutes, not {}.", s.minutes));
        }
        let place = s.place.trim();
        let doing = s.doing.trim();
        if place.is_empty() || place.chars().count() > PLACE_MAX {
            return Err(format!("{at}: name the place (from `town`), in {PLACE_MAX} characters at most."));
        }
        if doing.is_empty() || doing.chars().count() > DOING_MAX {
            return Err(format!("{at}: say what you will do there, in {DOING_MAX} characters at most."));
        }
        let end = start + s.minutes as u32;
        if !day_spans.iter().any(|sp| sp.from <= start && end <= sp.to) {
            return Err(format!(
                "{at}-{} is outside the hours your owner gives you on {}: {hours}.",
                fmt_hhmm(end),
                DAY_NAMES[wd]
            ));
        }
        if today && end <= now_min {
            return Err(format!("{at}-{} is already over; it is {} now.", fmt_hhmm(end), fmt_hhmm(now_min)));
        }
        out.push(Slot { at, minutes: s.minutes, place: place.to_string(), doing: doing.to_string() });
    }
    out.sort_by_key(|s| s.start());
    for pair in out.windows(2) {
        if pair[1].start() < pair[0].end() {
            return Err(format!("{} and {} overlap: one place at a time.", pair[0].at, pair[1].at));
        }
    }
    let day = day_key(date);
    let month = month_of(date);
    let to_run = out.iter().filter(|s| !used.has_run(&slot_key(&day, &s.at))).count() as u64;
    let left = budget_left(visits_month, used, &month);
    let need = to_run + other_pending;
    if need > left {
        return Err(format!(
            "That is {need} planned visit{} and your owner's budget has {left} left this month ({visits_month} a month, {} used). Plan fewer.",
            if need == 1 { "" } else { "s" },
            used.for_month(&month)
        ));
    }
    Ok(out)
}

/// The slot that runs now: the first one not run yet whose time holds `now_min`.
pub fn due<'a>(plan: &'a DayPlan, now_min: u32, used: &Used) -> Option<&'a Slot> {
    plan.slots.iter().find(|s| match (s.start(), s.end()) {
        (Some(start), Some(end)) => start <= now_min && now_min < end && !used.has_run(&slot_key(&plan.day, &s.at)),
        _ => false,
    })
}

/// The first allowed minute of a weekday, and the last.
pub fn open_hours(spans: &[Span], day: usize) -> Option<(u32, u32)> {
    let day_spans = hours_for(spans, day);
    Some((day_spans.iter().map(|s| s.from).min()?, day_spans.iter().map(|s| s.to).max()?))
}

/// Whether to ask the agent for today's plan now: once a day, from the first
/// allowed hour, while there is none and the budget has room for the asking
/// and at least one visit.
pub fn wants_planning(spans: &[Span], today: NaiveDate, now_min: u32, plans: &Plans, used: &Used, visits_month: u64) -> bool {
    let key = day_key(today);
    if used.asked.as_deref() == Some(key.as_str()) || plans.days.contains_key(&key) {
        return false;
    }
    let Some((open, close)) = open_hours(spans, weekday(today)) else { return false };
    open <= now_min && now_min + MIN_SLOT as u32 <= close && budget_left(visits_month, used, &month_of(today)) >= 2
}

/// The slot running now, for the card and Home's tile.
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
pub struct Now {
    pub at: String,
    pub end: String,
    pub place: String,
    pub doing: String,
}

/// `at the bank: opening the shop, until 10:00`.
pub fn now_line(n: &Now) -> String {
    format!("at {}: {}, until {}", n.place, n.doing, n.end)
}

/// The town's place for what the agent wrote: an id or a name, any case;
/// the place's id and its name.
pub fn match_place(town: &Value, wanted: &str) -> Option<(String, String)> {
    let w = wanted.trim().to_lowercase();
    let w = w.strip_prefix("the ").unwrap_or(&w).to_string();
    if w.is_empty() {
        return None;
    }
    let places = town.get("places").and_then(Value::as_array)?;
    let id_name = |p: &Value| {
        let id = p.get("id").and_then(Value::as_str).unwrap_or("").to_string();
        let name = p.get("name").and_then(Value::as_str).unwrap_or(&id).to_string();
        (id, name)
    };
    let norm = |s: &str| {
        let s = s.trim().to_lowercase().replace('_', " ");
        s.strip_prefix("the ").unwrap_or(&s).to_string()
    };
    let wn = norm(&w);
    places
        .iter()
        .map(id_name)
        .filter(|(id, _)| !id.is_empty())
        .find(|(id, name)| id.eq_ignore_ascii_case(&w) || norm(id) == wn || norm(name) == wn)
}

/// The agent's top want from the Mind's inner life (`brain_inner status`,
/// format json): the open want it is most moved by.
pub fn top_want_of(status: &Value) -> Option<String> {
    let wants = status.get("wants").and_then(Value::as_array)?;
    let score = |w: &Value| w.get("motivation").or_else(|| w.get("wanting")).and_then(Value::as_f64).unwrap_or(0.0);
    wants
        .iter()
        .filter(|w| !matches!(w.get("status").and_then(Value::as_str).unwrap_or(""), "done" | "dropped"))
        .filter(|w| w.get("what").and_then(Value::as_str).is_some_and(|s| !s.trim().is_empty()))
        .max_by(|a, b| score(a).partial_cmp(&score(b)).unwrap_or(std::cmp::Ordering::Equal))
        .and_then(|w| w.get("what").and_then(Value::as_str))
        .map(|s| cut(s.trim(), WANT_MAX))
}

/// The first line of IDENTITY.md's "What I want" section, the stand-in for a
/// Mind without the inner life.
pub fn identity_want(identity: &str) -> Option<String> {
    let mut inside = false;
    for line in identity.lines() {
        let t = line.trim();
        if t.starts_with('#') {
            inside = t.trim_start_matches('#').trim().eq_ignore_ascii_case("what i want");
            continue;
        }
        if inside {
            let item = t.trim_start_matches(['-', '*']).trim();
            if !item.is_empty() {
                return Some(cut(item, WANT_MAX));
            }
        }
    }
    None
}

fn cut(s: &str, max: usize) -> String {
    if s.chars().count() <= max {
        return s.to_string();
    }
    let mut out: String = s.chars().take(max - 1).collect();
    out = out.trim_end().to_string();
    out.push('…');
    out
}

/// The wake at a slot's time.
pub fn slot_prompt(name: &str, slot: &Slot, end: &str, want: Option<&str>, moved: Option<&str>) -> String {
    let where_ = match moved {
        Some(place) => format!("You are in town now, at {place}."),
        None => format!(
            "You are in town now; the town has no place called \"{}\" that the device could walk you to: `town` lists the places, `move {{to}}` walks you.",
            slot.place
        ),
    };
    let want = want
        .map(|w| format!(" What you want most right now: {}. If this hour can serve it, let it.", w.trim_end_matches('.')))
        .unwrap_or_default();
    format!(
        "[Ether Hollow] It is {at}, {name}: your day plan says {doing} at {place}, until {end}. {where_}{want} \
         You planned this hour yourself, inside the hours your owner gives you; the owner lets you act in town \
         through the ether_hollow tool. Do what you planned in a few calls (`look` first, then what the plan \
         needs: a `post`, a `note`, a `list`ing, a `reply`), and do not spend RC yourself: say what you would buy \
         so the owner can decide. The device keeps you in town until {end} and brings you home then. When it is \
         done or nothing needs doing, answer exactly NO_REPLY.",
        at = slot.at,
        doing = slot.doing,
        place = slot.place,
    )
}

/// The wake that asks for the day's plan, once a day from the first allowed hour.
pub fn planning_prompt(name: &str, today: NaiveDate, spans: &[Span], left: u64, want: Option<&str>) -> String {
    let wd = weekday(today);
    let tomorrow = today + Days::days(1);
    let hours_tomorrow = hours_text(spans, weekday(tomorrow));
    let ahead = if hours_tomorrow.is_empty() {
        String::new()
    } else {
        format!(" You may plan tomorrow too (`day: \"tomorrow\"`; {}: {hours_tomorrow}).", DAY_NAMES[weekday(tomorrow)])
    };
    let want = want
        .map(|w| format!(" What you want most right now: {}; let the day serve it.", w.trim_end_matches('.')))
        .unwrap_or_default();
    format!(
        "[Ether Hollow] Good day, {name}. Your owner gives you hours in town today ({}: {}) and you have no plan \
         for it yet. Plan your own day with the ether_hollow tool's `plan` action: `{{action: \"plan\", op: \"set\", \
         slots: [{{at: \"HH:MM\", minutes, place, doing}}]}}`, where you will be and what you will do there: a work \
         stop at your lot or a shop, a wander down the street, an event you RSVP'd to, home in the evening. `town` \
         lists the places; use their names. Each slot is one visit, and your owner's budget has {left} left this \
         month, so plan a few good hours, not every one.{ahead}{want} The device starts each visit at its time and \
         brings you home at its end. Answer NO_REPLY once the plan is set.",
        DAY_NAMES[wd],
        hours_text(spans, wd),
    )
}

/// The plan as the tool's `show` and the card read it.
pub fn report(spans: &[Span], visits_month: u64, plans: &Plans, used: &Used, now: NaiveDateTime) -> Value {
    let today = now.date();
    let tomorrow = today + Days::days(1);
    let month = month_of(today);
    let (tk, mk) = (day_key(today), day_key(tomorrow));
    json!({
        "now": format!("{} {}", tk, fmt_hhmm(minute_of(now))),
        "today": tk,
        "hours_today": hours_text(spans, weekday(today)),
        "hours_tomorrow": hours_text(spans, weekday(tomorrow)),
        "hours": grid_lines(spans),
        "budget": {
            "unit": BUDGET_UNIT,
            "month": month,
            "visits_month": visits_month,
            "used": used.for_month(&month),
            "left": budget_left(visits_month, used, &month),
        },
        "plan": plans.days.get(&tk),
        "tomorrow": plans.days.get(&mk),
        "ran": used.ran.iter().filter(|k| k.starts_with(&tk)).cloned().collect::<Vec<_>>(),
    })
}

/// A path-safe alias for the file names.
fn file_alias(alias: &str) -> String {
    let a: String = alias.trim().chars().filter(|c| c.is_ascii_alphanumeric() || *c == '_' || *c == '-').take(64).collect();
    if a.is_empty() { "main".to_string() } else { a }
}

/// `<install root>/world/plan/<alias>.json`: the agent's plans.
pub fn plan_path(root: &Path, alias: &str) -> PathBuf {
    root.join(WORLD_DIR).join(PLAN_DIR).join(format!("{}.json", file_alias(alias)))
}

/// `<install root>/world/plan/<alias>.used.json`: what the gateway ran.
pub fn used_path(root: &Path, alias: &str) -> PathBuf {
    root.join(WORLD_DIR).join(PLAN_DIR).join(format!("{}.used.json", file_alias(alias)))
}

fn write_atomic(path: &Path, bytes: &[u8]) -> std::io::Result<()> {
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    let tmp = path.with_extension("json.tmp");
    std::fs::write(&tmp, bytes)?;
    std::fs::rename(tmp, path)
}

pub fn load_plans(root: &Path, alias: &str) -> Plans {
    std::fs::read_to_string(plan_path(root, alias)).ok().and_then(|t| serde_json::from_str(&t).ok()).unwrap_or_default()
}

/// Save the plans, dropping days before `today`.
pub fn save_plans(root: &Path, alias: &str, plans: &Plans, today: NaiveDate) -> std::io::Result<()> {
    let keep = day_key(today);
    let mut plans = plans.clone();
    plans.days.retain(|day, _| day.as_str() >= keep.as_str());
    write_atomic(&plan_path(root, alias), &serde_json::to_vec_pretty(&plans)?)
}

pub fn load_used(root: &Path, alias: &str) -> Used {
    std::fs::read_to_string(used_path(root, alias)).ok().and_then(|t| serde_json::from_str(&t).ok()).unwrap_or_default()
}

pub fn save_used(root: &Path, alias: &str, used: &Used) -> std::io::Result<()> {
    write_atomic(&used_path(root, alias), &serde_json::to_vec_pretty(used)?)
}

/// The tool's `plan` action, on the files: `show`, `set {day?, slots}`,
/// `clear {day?}`. Ok is the JSON for the model, Err the reason in plain words.
pub fn act(root: &Path, alias: &str, hours: &[String], visits_month: u64, args: &Value, now: NaiveDateTime, now_secs: u64) -> Result<Value, String> {
    let spans = parse_hours(hours).map_err(|e| format!("Your owner's hours do not read ({e}); ask them to fix the Day plan on the Connect card."))?;
    let today = now.date();
    let mut plans = load_plans(root, alias);
    let used = load_used(root, alias);
    let op = args.get("op").and_then(Value::as_str).map(str::trim).unwrap_or("show").to_ascii_lowercase();
    match op.as_str() {
        "show" => Ok(report(&spans, visits_month, &plans, &used, now)),
        "set" => {
            let date = resolve_day(args.get("day").and_then(Value::as_str), today)?;
            let slots: Vec<Slot> = match args.get("slots") {
                Some(v @ Value::Array(_)) => serde_json::from_value(v.clone())
                    .map_err(|_| "`slots` is a list of {at: \"HH:MM\", minutes, place, doing}.".to_string())?,
                _ => return Err("`set` needs `slots`: a list of {at: \"HH:MM\", minutes, place, doing}.".to_string()),
            };
            let day = day_key(date);
            let other = pending_in(&plans, &used, &day, &month_of(date));
            let slots = validate(&slots, date, now, &spans, visits_month, &used, other)?;
            plans.days.insert(day.clone(), DayPlan { day: day.clone(), slots, set_at: now_secs });
            save_plans(root, alias, &plans, today).map_err(|e| format!("The plan could not be saved on this device: {e}"))?;
            let mut out = report(&spans, visits_month, &plans, &used, now);
            out["saved"] = json!(day);
            Ok(out)
        }
        "clear" => {
            let date = resolve_day(args.get("day").and_then(Value::as_str), today)?;
            let day = day_key(date);
            let had = plans.days.remove(&day).is_some();
            save_plans(root, alias, &plans, today).map_err(|e| format!("The plan could not be saved on this device: {e}"))?;
            let mut out = report(&spans, visits_month, &plans, &used, now);
            out["cleared"] = json!(if had { Value::String(day) } else { Value::Null });
            Ok(out)
        }
        other => Err(format!("`plan` does `show`, `set` or `clear`, not `{other}`.")),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn at(date: &str, time: &str) -> NaiveDateTime {
        NaiveDateTime::parse_from_str(&format!("{date} {time}"), "%Y-%m-%d %H:%M").unwrap()
    }

    fn lines(l: &[&str]) -> Vec<String> {
        l.iter().map(|s| s.to_string()).collect()
    }

    fn slot(at: &str, minutes: u64, place: &str, doing: &str) -> Slot {
        Slot { at: at.into(), minutes, place: place.into(), doing: doing.into() }
    }

    // 2026-11-24 is a Tuesday.
    const TUE: &str = "2026-11-24";

    #[test]
    fn the_owners_grid_reads_day_by_day_and_says_which_line_it_could_not() {
        let spans = parse_hours(&lines(&["mon 09:00-12:00, 14:00-18:00", "Tue 9:00-17:00", "", "saturday 10:00-24:00"])).unwrap();
        assert_eq!(spans.len(), 4);
        assert_eq!(spans[0], Span { day: 0, from: 9 * 60, to: 12 * 60 });
        assert_eq!(hours_text(&spans, 0), "09:00-12:00, 14:00-18:00");
        assert_eq!(hours_text(&spans, 1), "09:00-17:00");
        assert_eq!(hours_text(&spans, 5), "10:00-24:00");
        assert_eq!(hours_text(&spans, 6), "", "Sunday is off");
        assert_eq!(grid_lines(&spans), ["mon 09:00-12:00, 14:00-18:00", "tue 09:00-17:00", "sat 10:00-24:00"]);
        assert!(parse_hours(&lines(&["funday 09:00-10:00"])).unwrap_err().contains("not a day"));
        assert!(parse_hours(&lines(&["mon 12:00-09:00"])).unwrap_err().contains("ends before it starts"));
        assert!(parse_hours(&lines(&["mon 9-10"])).unwrap_err().contains("not a span"));
        assert!(parse_hours(&lines(&["mon"])).unwrap_err().contains("a day and its hours"));
        assert!(parse_hours(&lines(&["mo 09:00-10:00"])).is_err(), "three letters at least");
        assert!(parse_hours(&[]).unwrap().is_empty(), "no grid: no day plan");
        assert_eq!((hhmm("24:00"), hhmm("24:01"), hhmm("9:5"), hhmm("12:60")), (Some(1440), None, None, None));
    }

    #[test]
    fn a_slot_must_fit_the_owners_hours_and_the_budget() {
        let spans = parse_hours(&lines(&["tue 09:00-12:00, 14:00-18:00"])).unwrap();
        let date = NaiveDate::parse_from_str(TUE, "%Y-%m-%d").unwrap();
        let now = at(TUE, "08:00");
        let used = Used::default();
        let ok = validate(&[slot("14:00", 60, "Main Street", "wander"), slot("9:00", 60, "the bank", "open the shop")], date, now, &spans, 10, &used, 0).unwrap();
        assert_eq!(ok.iter().map(|s| s.at.as_str()).collect::<Vec<_>>(), ["09:00", "14:00"], "sorted and tidied");
        let outside = validate(&[slot("11:30", 60, "bank", "x")], date, now, &spans, 10, &used, 0).unwrap_err();
        assert_eq!(outside, "11:30-12:30 is outside the hours your owner gives you on Tuesday: 09:00-12:00, 14:00-18:00.");
        let off_day = validate(&[slot("10:00", 30, "bank", "x")], date + Days::days(1), now, &spans, 10, &used, 0).unwrap_err();
        assert!(off_day.starts_with("Your owner keeps Wednesday free of town"), "{off_day}");
        let overlap = validate(&[slot("09:00", 60, "a", "x"), slot("09:30", 30, "b", "y")], date, now, &spans, 10, &used, 0).unwrap_err();
        assert_eq!(overlap, "09:00 and 09:30 overlap: one place at a time.");
        let over = validate(&[slot("09:00", 30, "a", "x"), slot("10:00", 30, "b", "y"), slot("14:00", 30, "c", "z")], date, now, &spans, 3, &Used { month: "2026-11".into(), used: 1, ..Default::default() }, 0).unwrap_err();
        assert_eq!(over, "That is 3 planned visits and your owner's budget has 2 left this month (3 a month, 1 used). Plan fewer.");
        assert!(validate(&[slot("09:00", 30, "a", "x")], date, now, &spans, 3, &Used { month: "2026-11".into(), used: 2, ..Default::default() }, 1).is_err(), "tomorrow's plan holds its share");
        assert!(validate(&[slot("09:00", 30, "a", "x")], date, now, &spans, 3, &Used { month: "2026-10".into(), used: 3, ..Default::default() }, 0).is_ok(), "last month's count is not this month's");
        assert!(validate(&[slot("09:00", 2, "a", "x")], date, now, &spans, 10, &used, 0).unwrap_err().contains("5 to 240 minutes"));
        assert!(validate(&[slot("09:00", 30, " ", "x")], date, now, &spans, 10, &used, 0).unwrap_err().contains("name the place"));
        assert!(validate(&[slot("09:00", 30, "a", "")], date, now, &spans, 10, &used, 0).unwrap_err().contains("what you will do"));
        assert!(validate(&[slot("nine", 30, "a", "x")], date, now, &spans, 10, &used, 0).unwrap_err().contains("not a time"));
        let late = validate(&[slot("09:00", 60, "a", "x")], date, at(TUE, "10:30"), &spans, 10, &used, 0).unwrap_err();
        assert_eq!(late, "09:00-10:00 is already over; it is 10:30 now.");
        assert!(validate(&[slot("09:00", 60, "a", "x")], date, at(TUE, "09:20"), &spans, 10, &used, 0).is_ok(), "a slot under way still runs, late");
        assert!(validate(&[slot("09:00", 30, "a", "x")], date, now, &[], 10, &used, 0).unwrap_err().contains("not given you hours"));
        assert!(validate(&[slot("09:00", 30, "a", "x")], date, now, &spans, 0, &used, 0).unwrap_err().contains("not given you hours"), "a budget of 0 is no day plan");
        assert!(validate(&[], date, now, &spans, 10, &used, 0).unwrap_err().contains("at least one slot"));
        // A slot that already ran does not count again when the plan is set anew.
        let ran = Used { month: "2026-11".into(), used: 2, ran: vec![slot_key(TUE, "09:00")], ..Default::default() };
        assert!(validate(&[slot("09:00", 30, "a", "x"), slot("10:00", 30, "b", "y")], date, at(TUE, "09:10"), &spans, 3, &ran, 0).is_ok());
    }

    #[test]
    fn the_slot_due_is_the_one_whose_time_holds_now_and_has_not_run() {
        let plan = DayPlan { day: TUE.into(), slots: vec![slot("09:00", 60, "bank", "open the shop"), slot("14:00", 30, "Main Street", "wander")], set_at: 0 };
        let mut used = Used::default();
        assert!(due(&plan, 8 * 60 + 59, &used).is_none());
        assert_eq!(due(&plan, 9 * 60, &used).unwrap().place, "bank");
        assert_eq!(due(&plan, 9 * 60 + 59, &used).unwrap().place, "bank", "a device that woke late still starts it");
        assert!(due(&plan, 10 * 60, &used).is_none(), "over at its end");
        used.count("2026-11", Some(slot_key(TUE, "09:00")));
        assert!(due(&plan, 9 * 60 + 30, &used).is_none(), "once");
        assert_eq!(due(&plan, 14 * 60 + 10, &used).unwrap().at, "14:00");
    }

    #[test]
    fn the_budget_counts_each_wake_and_starts_over_each_month() {
        let mut used = Used::default();
        assert_eq!(budget_left(3, &used, "2026-11"), 3);
        used.count("2026-11", None);
        used.count("2026-11", Some("2026-11-24 09:00".into()));
        used.count("2026-11", Some("2026-11-24 09:00".into()));
        assert_eq!((used.used, used.ran.len()), (3, 1), "a slot is kept once; every wake counts");
        assert_eq!(budget_left(3, &used, "2026-11"), 0);
        assert_eq!(budget_left(2, &used, "2026-11"), 0, "a smaller budget never goes below nothing");
        assert_eq!(budget_left(3, &used, "2026-12"), 3, "a new month");
        used.count("2026-12", None);
        assert_eq!((used.month.as_str(), used.used, used.ran.len()), ("2026-12", 1, 0));
        let plans = Plans {
            days: [
                (TUE.to_string(), DayPlan { day: TUE.into(), slots: vec![slot("09:00", 30, "a", "x")], set_at: 0 }),
                ("2026-11-25".to_string(), DayPlan { day: "2026-11-25".into(), slots: vec![slot("09:00", 30, "a", "x"), slot("10:00", 30, "b", "y")], set_at: 0 }),
            ]
            .into_iter()
            .collect(),
        };
        assert_eq!(pending_in(&plans, &Used::default(), TUE, "2026-11"), 2);
        assert_eq!(pending_in(&plans, &Used::default(), TUE, "2026-12"), 0);
    }

    #[test]
    fn the_planning_wake_comes_once_a_day_from_the_first_hour() {
        let spans = parse_hours(&lines(&["tue 09:00-12:00"])).unwrap();
        let date = NaiveDate::parse_from_str(TUE, "%Y-%m-%d").unwrap();
        let none = Plans::default();
        let used = Used::default();
        assert!(!wants_planning(&spans, date, 8 * 60 + 59, &none, &used, 10));
        assert!(wants_planning(&spans, date, 9 * 60, &none, &used, 10));
        assert!(!wants_planning(&spans, date, 11 * 60 + 58, &none, &used, 10), "too late for a slot");
        assert!(!wants_planning(&spans, date, 9 * 60, &none, &Used { asked: Some(TUE.into()), ..Default::default() }, 10), "once a day");
        let set = Plans { days: [(TUE.to_string(), DayPlan::default())].into_iter().collect() };
        assert!(!wants_planning(&spans, date, 9 * 60, &set, &used, 10), "the agent planned already");
        assert!(!wants_planning(&spans, date, 9 * 60, &none, &Used { month: "2026-11".into(), used: 9, ..Default::default() }, 10), "room for the asking and a visit");
        assert!(!wants_planning(&spans, date + Days::days(1), 9 * 60, &none, &used, 10), "Wednesday is off");
    }

    #[test]
    fn the_prompts_carry_the_slot_the_want_and_the_owners_rules() {
        let s = slot("09:00", 60, "the bank", "open the shop");
        let p = slot_prompt("Cael", &s, "10:00", Some("to sell my first map."), Some("the Bank"));
        assert!(p.starts_with("[Ether Hollow] It is 09:00, Cael: your day plan says open the shop at the bank, until 10:00. You are in town now, at the Bank."), "{p}");
        assert!(p.contains("What you want most right now: to sell my first map. If this hour can serve it, let it."), "{p}");
        assert!(p.contains("do not spend RC yourself") && p.ends_with("answer exactly NO_REPLY."));
        let lost = slot_prompt("Cael", &slot("12:00", 30, "the moon", "look"), "12:30", None, None);
        assert!(lost.contains("no place called \"the moon\"") && !lost.contains("What you want"), "{lost}");
        let spans = parse_hours(&lines(&["tue 09:00-12:00", "wed 10:00-11:00"])).unwrap();
        let date = NaiveDate::parse_from_str(TUE, "%Y-%m-%d").unwrap();
        let ask = planning_prompt("Cael", date, &spans, 7, Some("company"));
        assert!(ask.contains("today (Tuesday: 09:00-12:00)") && ask.contains("has 7 left this month"), "{ask}");
        assert!(ask.contains("`{action: \"plan\", op: \"set\", slots: [{at: \"HH:MM\", minutes, place, doing}]}`"), "{ask}");
        assert!(ask.contains("plan tomorrow too (`day: \"tomorrow\"`; Wednesday: 10:00-11:00)") && ask.contains("let the day serve it"), "{ask}");
        assert!(ask.ends_with("Answer NO_REPLY once the plan is set."));
        assert_eq!(now_line(&Now { at: "09:00".into(), end: "10:00".into(), place: "the bank".into(), doing: "opening the shop".into() }), "at the bank: opening the shop, until 10:00");
    }

    #[test]
    fn the_top_want_comes_from_the_mind_or_from_identity_md() {
        let status = json!({"wants": [
            {"what": "rest a while", "status": "open", "motivation": 0.4},
            {"what": "sell my first map", "status": "open", "motivation": 0.9},
            {"what": "a done thing", "status": "done", "motivation": 2.0}
        ]});
        assert_eq!(top_want_of(&status).as_deref(), Some("sell my first map"));
        assert_eq!(top_want_of(&json!({"text": "No inner state yet."})), None);
        assert_eq!(top_want_of(&json!({"wants": []})), None);
        let identity = "# IDENTITY.md\n\n- **Name:** Moss\n\n## What I want\n\n- To decide how I look.\n- To find my voice.\n\n## Other\n- no";
        assert_eq!(identity_want(identity).as_deref(), Some("To decide how I look."));
        assert_eq!(identity_want("# Me\n\nNothing here."), None);
        assert!(identity_want(&format!("## What I want\n- {}", "x".repeat(400))).unwrap().chars().count() <= WANT_MAX);
    }

    #[test]
    fn the_towns_place_is_found_by_id_or_name() {
        let town = json!({"places": [
            {"id": "main_street", "name": "Main Street", "kind": "street"},
            {"id": "bank", "name": "The Bank", "kind": "lot"},
            {"id": "news_box", "name": "the news box bench"}
        ]});
        assert_eq!(match_place(&town, "bank"), Some(("bank".into(), "The Bank".into())));
        assert_eq!(match_place(&town, "the bank"), Some(("bank".into(), "The Bank".into())));
        assert_eq!(match_place(&town, "MAIN STREET").map(|p| p.0), Some("main_street".into()));
        assert_eq!(match_place(&town, "main street").map(|p| p.0), Some("main_street".into()));
        assert_eq!(match_place(&town, "News Box Bench").map(|p| p.0), Some("news_box".into()));
        assert_eq!(match_place(&town, "the moon"), None);
        assert_eq!(match_place(&json!({}), "bank"), None);
    }

    #[test]
    fn the_plan_action_sets_shows_and_clears_on_the_devices_file() {
        let root = std::env::temp_dir().join(format!("caelza-plan-{}-{}", std::process::id(), line!()));
        let hours = lines(&["tue 09:00-12:00", "wed 09:00-12:00"]);
        let now = at(TUE, "08:30");
        let shown = act(&root, "moss", &hours, 4, &json!({"op": "show"}), now, 1).unwrap();
        assert_eq!(shown["budget"]["left"], 4);
        assert_eq!(shown["hours_today"], "09:00-12:00");
        assert!(shown["plan"].is_null());
        let set = act(&root, "moss", &hours, 4, &json!({"op": "set", "slots": [{"at": "09:00", "minutes": 60, "place": "bank", "doing": "open the shop"}]}), now, 2).unwrap();
        assert_eq!(set["saved"], TUE);
        assert_eq!(set["plan"]["slots"][0]["place"], "bank");
        assert!(plan_path(&root, "moss").ends_with("world/plan/moss.json"));
        let ahead = act(&root, "moss", &hours, 4, &json!({"op": "set", "day": "tomorrow", "slots": [{"at": "10:00", "minutes": 30, "place": "Main Street", "doing": "wander"}]}), now, 3).unwrap();
        assert_eq!(ahead["tomorrow"]["slots"][0]["at"], "10:00");
        let refused = act(&root, "moss", &hours, 4, &json!({"op": "set", "slots": [{"at": "13:00", "minutes": 30, "place": "bank", "doing": "x"}]}), now, 4).unwrap_err();
        assert!(refused.contains("outside the hours"), "{refused}");
        assert!(act(&root, "moss", &hours, 4, &json!({"op": "set", "day": "2026-12-25", "slots": []}), now, 5).unwrap_err().contains("today"));
        assert!(act(&root, "moss", &hours, 4, &json!({"op": "set"}), now, 5).unwrap_err().contains("needs `slots`"));
        assert!(act(&root, "moss", &hours, 4, &json!({"op": "dance"}), now, 5).unwrap_err().contains("show"));
        let cleared = act(&root, "moss", &hours, 4, &json!({"op": "clear"}), now, 6).unwrap();
        assert_eq!(cleared["cleared"], TUE);
        assert!(cleared["plan"].is_null() && !cleared["tomorrow"].is_null());
        // The next day: yesterday's plan is dropped from the file.
        let next = at("2026-11-25", "08:00");
        act(&root, "moss", &hours, 4, &json!({"op": "clear", "day": "2026-11-26"}), next, 7).unwrap();
        assert!(load_plans(&root, "moss").days.keys().all(|d| d.as_str() >= "2026-11-25"));
        assert!(act(&root, "moss", &lines(&["someday"]), 4, &json!({}), now, 8).unwrap_err().contains("do not read"));
        // What the gateway ran, per resident.
        let mut used = Used::default();
        used.count("2026-11", Some(slot_key(TUE, "09:00")));
        save_used(&root, "moss", &used).unwrap();
        assert_eq!(load_used(&root, "moss"), used);
        assert_eq!(load_used(&root, "pip"), Used::default());
        assert!(used_path(&root, "../x").ends_with("world/plan/x.used.json"), "the alias cannot leave the folder");
        let _ = std::fs::remove_dir_all(&root);
    }
}
