"""The agent's voice (vision M10 §10, slice P2b).

A `voice` tool beside `look` and `identity`, the gateway's `/api/voice` (the
choice, the devices' offers, the owner's ElevenLabs voices, speech as MP3
through upstream's provider), the dashboard reading replies aloud behind a
speaker button, the phone's bridge to its text-to-speech engine, the Voice
card on the Looks page and the ElevenLabs card on the Connect page. These
tests keep the overlay, the patch, the app, the manifest, the FAQ, the README,
the design note and Cael's corpus saying the same thing; the tools' and the
routes' own behaviour is under `cargo test` (caelza-tools voice::, caelza-gateway
api_voice::), the pure web part under `voice.logic.test.ts`, the phone's
catalog under the app's unit tests.
"""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OVERLAY = REPO_ROOT / "runtime" / "overlay"
TOOL = (OVERLAY / "crates" / "caelza-tools" / "src" / "voice.rs").read_text()
API = (OVERLAY / "crates" / "caelza-gateway" / "src" / "api_voice.rs").read_text()
WEB = OVERLAY / "web" / "src"
LOGIC = (WEB / "lib" / "voice.logic.ts").read_text()
LOGIC_TEST = (WEB / "lib" / "voice.logic.test.ts").read_text()
CLIENT = (WEB / "lib" / "voice.ts").read_text()
SPEECH = (WEB / "lib" / "speech.tsx").read_text()
LOOKS = (WEB / "pages" / "Looks.tsx").read_text()
VOICE_CARD = (WEB / "pages" / "VoiceCard.tsx").read_text()
CONNECT = (WEB / "pages" / "connect" / "Connect.tsx").read_text()
ELEVEN_CARD = (WEB / "pages" / "connect" / "Voice.tsx").read_text()
PATCH = (REPO_ROOT / "runtime" / "patches" / "0024-voice.patch").read_text()
ANDROID = REPO_ROOT / "android" / "app" / "src" / "main" / "java" / "tech" / "enlightenedrepublic" / "caelza"
BRIDGE = (ANDROID / "voice" / "VoiceBridge.kt").read_text()
CATALOG = (ANDROID / "voice" / "VoiceCatalog.kt").read_text()
MAIN = (ANDROID / "MainActivity.kt").read_text()
CATALOG_TEST = (REPO_ROOT / "android" / "app" / "src" / "test" / "java" / "tech" / "enlightenedrepublic" / "caelza" / "voice" / "VoiceCatalogTest.kt").read_text()
FAQ = (REPO_ROOT / "guide" / "FAQ.md").read_text()
README = (REPO_ROOT / "README.md").read_text()
MANIFEST = tomllib.loads((REPO_ROOT / "bundle" / "manifest.toml").read_text())
NOTE = (REPO_ROOT / "docs" / "design" / "ether-hollow-open-world.md").read_text()

FAQ_TITLE = "## Can my agent talk, and pick its own voice?"


def test_the_tool_and_the_gateway_share_one_idea_of_a_voice():
    assert 'pub const ENGINES: [&str; 3] = ["browser", "phone", "elevenlabs"];' in TOOL
    assert 'pub const VOICE_FILE: &str = "voice.json";' in TOOL and 'pub const OFFERED_FILE: &str = "voices.json";' in TOOL
    assert "pub use crate::look::{Gate, NOT_FREE};" in TOOL, "the same yes as look and identity"
    for guarded in ('"set" => {\n                if !free {', '"reset" => {\n                if !free {'):
        assert guarded in TOOL, guarded
    assert "use caelza_tools::voice::{ENGINES, offered_path, tidy_offer, validate_voice, voice_path};" in API
    assert "use caelza_channels::tts::{ElevenLabsTtsProvider, TtsProvider};" in API, "upstream's provider, not a second one"
    assert 'pub const ELEVENLABS_DEFAULT_MODEL: &str = "eleven_multilingual_v2";' in API
    assert 'export const ELEVEN_MODEL = "eleven_multilingual_v2";' in LOGIC
    assert 'export const ELEVEN_PATH = "/providers/tts/elevenlabs/default";' in LOGIC
    # The same cap on both ends, and ElevenLabs is never a fallback the device picks on its own.
    assert "pub const MAX_SPEAK_CHARS: usize = 2000;" in API and "export const MAX_SPEAK_CHARS = 2000;" in LOGIC
    assert 'if (here.browser) return "browser";\n  if (here.phone) return "phone";\n  return null;' in LOGIC
    assert 'ENGINES = ["browser", "phone", "elevenlabs"] as const' in LOGIC
    for route in ("`GET    /api/voice/offer`", "`POST   /api/voice/offer`", "`GET    /api/voice/elevenlabs`", "`GET    /api/voice/{alias}`", "`PUT    /api/voice/{alias}`", "`DELETE /api/voice/{alias}`", "`POST   /api/voice/{alias}/speak`"):
        assert route in API, route
    assert '[(header::CONTENT_TYPE, "audio/mpeg"), (header::CACHE_CONTROL, "no-store")]' in API


def test_the_patch_registers_the_tool_the_routes_and_the_chats_speaker():
    files = re.findall(r"^\+\+\+ b/(.+)$", PATCH, flags=re.M)
    assert files == [
        "crates/caelza-gateway/src/lib.rs",
        "crates/caelza-runtime/src/agent/loop_.rs",
        "crates/caelza-runtime/src/tools/mod.rs",
        "crates/caelza-tools/src/attribution.rs",
        "crates/caelza-tools/src/inventory.rs",
        "crates/caelza-tools/src/lib.rs",
        "docs/book/src/developing/tool-inventory.md",
        "web/package.json",
        "web/src/contexts/AgentContext.tsx",
        "web/src/lib/i18n.ts",
        "web/src/pages/AgentChat.tsx",
    ], files
    assert "+pub mod api_voice;" in PATCH and "+pub mod voice;" in PATCH
    assert '+        .route("/api/voice/elevenlabs", get(api_voice::handle_elevenlabs_get))' in PATCH
    assert '+        .route("/api/voice/{alias}/speak", post(api_voice::handle_speak))' in PATCH
    assert '+        register_tool!("voice", Arc::new(VoiceTool::new(&root_config, agent_alias)));' in PATCH
    assert "+tool_attribution!(VoiceTool, ToolKind::Plugin);" in PATCH and '+        name: "voice",' in PATCH
    assert '+            "voice",' in PATCH, "the prompt's tool line"
    assert "+| Caelza | `look`, `identity`, `voice` |" in PATCH
    # The chat: the reply event the speaker listens for, the toggle, the mouth.
    assert "+          window.dispatchEvent(new CustomEvent('caelza-agent-reply', { detail: { alias: agentAlias, content: outcome.content } }));" in PATCH
    assert "+import { SpeakToggle, useSpeech } from '@/lib/speech';" in PATCH
    assert "+          <SpeakToggle alias={agentAlias} />" in PATCH
    assert "+          <AgentLook alias={agentAlias} size={28} talking={typing || speech.speaking} />" in PATCH
    assert "src/lib/voice.logic.test.ts" in PATCH
    # Every voice.* string the pages use is added by this patch.
    used = set(re.findall(r'"(voice\.[a-z_]+)"', SPEECH + VOICE_CARD + ELEVEN_CARD))
    added = set(re.findall(r"^\+    '(voice\.[a-z_]+)': ", PATCH, re.M))
    assert used and used <= added, sorted(used - added)


def test_the_dashboard_speaks_three_ways_and_the_cards_are_in_place():
    assert 'window.addEventListener("caelza-agent-reply"' in SPEECH
    assert "speechSynthesis.speak(utterance)" in SPEECH and "new SpeechSynthesisUtterance(clean)" in SPEECH
    assert "window.caelzaVoice" in SPEECH and 'window.addEventListener("caelza-voice", onEvent)' in SPEECH
    assert "await speakAudio(alias, clean" in SPEECH and "new Audio(url)" in SPEECH
    assert "export function SpeakToggle(" in SPEECH and "export function useSpeech(" in SPEECH
    assert "/api/voice/${encodeURIComponent(alias)}/speak" in CLIENT and "return response.blob();" in CLIENT
    assert 'import VoiceCard from "@/pages/VoiceCard";' in LOOKS
    assert '{alias !== "cael" ? <VoiceCard alias={alias} onNote={setNote} /> : null}' in LOOKS
    for marker in ("data-voice-card", "data-voice-select", "data-voice-hear", "data-voice-save", "data-voice-why"):
        assert marker in VOICE_CARD, marker
    assert 'import VoiceCard from "./Voice";' in CONNECT and "<VoiceCard disabled={!ready} />" in CONNECT
    assert 'data-connect="voice"' in ELEVEN_CARD and "await createMapKey(ELEVEN_SECTION, \"default\")" in ELEVEN_CARD
    assert "await patchConfig(elevenOps(k));" in ELEVEN_CARD
    assert 'type={shown ? "text" : "password"}' in ELEVEN_CARD, "the key is typed like a password"
    for fn in ("offerFromBrowser", "pickBrowserVoice", "engineHere", "speakable", "elevenOps", "choiceFromPick", "voiceLine"):
        assert f"export function {fn}" in LOGIC and fn in LOGIC_TEST, fn


def test_the_phone_offers_its_voices_through_a_bridge_the_webview_can_reach():
    assert BRIDGE.count("@JavascriptInterface") == 3
    assert 'const val JS_NAME = "caelzaVoice"' in BRIDGE
    assert "fun voices(): String = VoiceCatalog.json(phoneVoices())" in BRIDGE
    assert "fun speak(text: String, voice: String, rate: Float, pitch: Float): Boolean" in BRIDGE
    assert "new CustomEvent('caelza-voice'" in BRIDGE
    assert "addJavascriptInterface(it, VoiceBridge.JS_NAME)" in MAIN and "voiceBridge?.shutdown()" in MAIN
    assert "const val MAX = 200" in CATALOG and "export const MAX_OFFERED = 200;" in LOGIC and "pub const MAX_OFFERED: usize = 200;" in TOOL
    assert "class VoiceCatalogTest" in CATALOG_TEST


def test_the_body_speaks_in_the_chosen_voice():
    """P2c: both Bodies read the agent's voice.json and speak in it; the app fetches an ElevenLabs voice from the gateway."""
    body = ANDROID / "body"
    choice = (ANDROID / "voice" / "VoiceChoice.kt").read_text()
    body_voice = (body / "BodyVoice.kt").read_text()
    sensors = (body / "Sensors.kt").read_text()
    android_sensors = (body / "AndroidSensors.kt").read_text()
    body_tools = (body / "BodyTools.kt").read_text()
    service = (ANDROID / "RuntimeService.kt").read_text()
    python = (REPO_ROOT / "caelza_body" / "agent" / "tools" / "sensors.py").read_text()
    # One file, one shape, both Bodies.
    assert 'const val FILE = "voice.json"' in choice and 'VOICE_FILE = "voice.json"' in python
    assert 'val ENGINES = setOf("browser", "phone", "elevenlabs")' in choice and 'VOICE_ENGINES = ("browser", "phone", "elevenlabs")' in python
    assert "fun bodyAgent(configToml: String): String" in choice and "def body_agent(config_text: str) -> str:" in python
    assert "const val MIN = 0.5f" in choice and "const val MAX = 2f" in choice and "VOICE_RANGE = (0.5, 2.0)" in python
    # The app: the engine takes the voice; ElevenLabs comes from the gateway with the app's own token, never logged.
    assert "fun ttsSpeak(text: String, voice: VoiceChoice? = null)" in sensors and "fun play(audio: File)" in sensors
    assert "private fun applyVoice(engine: TextToSpeech, voice: VoiceChoice?)" in android_sensors
    assert "engine.setSpeechRate(voice?.rate ?: 1f)" in android_sensors and "engine.setPitch(voice?.pitch ?: 1f)" in android_sensors
    assert "override fun play(audio: File)" in android_sensors and "MediaPlayer()" in android_sensors
    assert '"http://127.0.0.1:${port()}/api/voice/$alias/speak"' in body_voice
    assert "const val MAX_SPEAK_CHARS = 2000" in body_voice, "the gateway's cap, so the phone speaks longer texts"
    assert 'conn.setRequestProperty("Authorization", "Bearer $token")' in body_voice and "Log." not in body_voice
    assert 'if (choice?.engine != "elevenlabs") {' in body_tools and "sensors.play(file)" in body_tools
    assert "the ElevenLabs voice did not come:" in body_tools
    assert "BodyVoice(store.configDir, port = { Gateway.port(store.configDir) }, token = ::gatewayToken)" in service
    # Termux: the locale, speed and pitch go to termux-tts-speak; ElevenLabs is spoken by the phone and the answer says so.
    assert 'RUNTIME_DIR_ENV = "CAELZA_CONFIG_DIR"' in python and "def tts_argv(text: str, choice: dict | None) -> list[str]:" in python
    assert 'argv += ["-l", language]' in python and 'argv += ["-n", region]' in python and 'argv += ["-r", rate]' in python and 'argv += ["-p", pitch]' in python
    assert "return ELEVENLABS_ELSEWHERE" in python
    # The same words in the app's tests and the docs.
    tests = REPO_ROOT / "android" / "app" / "src" / "test" / "java" / "tech" / "enlightenedrepublic" / "caelza"
    assert "class VoiceChoiceTest" in (tests / "voice" / "VoiceChoiceTest.kt").read_text()
    assert "class BodyVoiceTest" in (tests / "body" / "BodyVoiceTest.kt").read_text()
    assert "fun an_elevenlabs_voice_is_fetched_from_the_gateway_and_played_or_the_phone_speaks_and_says_why" in (tests / "body" / "SensorToolsTest.kt").read_text()
    assert "in the agent's chosen voice (`agents/<alias>/voice.json`" in (REPO_ROOT / "docs" / "design" / "android-app.md").read_text()
    assert "**In the agent's own voice.**" in (REPO_ROOT / "body" / "README.md").read_text()
    assert "When the agent speaks through its\nBody on the phone" in FAQ
    p2 = NOTE.split("**P2 · Wants, a look and a voice")[1].split("**P3 ·")[0]
    assert "Shipped 2026-11-23 (the Body, P2c)" in " ".join(p2.split())


def test_the_manifest_the_faq_the_readme_the_note_and_the_corpus_agree():
    patch = MANIFEST["components"]["runtime"]["voice_patch"]
    assert (REPO_ROOT / patch).is_file() and patch.endswith("0024-voice.patch")
    assert FAQ_TITLE in FAQ
    entry = " ".join(FAQ.split(FAQ_TITLE)[1].split("\n## ")[0].split())
    for phrase in ("speaker button", "ElevenLabs", "Connect page", "`voice`", "Let it be itself", "Voice card", "Cael"):
        assert phrase in entry, phrase
    assert "reads its replies aloud" in README
    p2 = NOTE.split("**P2 · Wants, a look and a voice")[1].split("**P3 ·")[0]
    assert "Shipped 2026-11-21 (the\nvoice, P2b)" in p2 or "Shipped 2026-11-21 (the voice, P2b)" in " ".join(p2.split())
    corpus = (REPO_ROOT / "guide" / "corpus.jsonl").read_text()
    assert FAQ_TITLE.lstrip("# ") in corpus
    assert corpus == (REPO_ROOT / "android" / "app" / "src" / "main" / "assets" / "cael-corpus.jsonl").read_text()
