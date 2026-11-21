import assert from "node:assert/strict";
import test from "node:test";

import {
  ELEVEN_MODEL,
  MAX_OFFERED,
  MAX_SPEAK_CHARS,
  choiceFromPick,
  elevenOps,
  engineHere,
  keyOk,
  offerFromBrowser,
  pickBrowserVoice,
  pickValue,
  speakable,
  voiceLine,
} from "./voice.logic.ts";

const browser = [
  { name: "Samantha", lang: "en-US", voiceURI: "com.apple.voice.compact.en-US.Samantha", localService: true, default: true },
  { name: "Google UK English Female", lang: "en-GB", voiceURI: "Google UK English Female", localService: false },
  { name: "Daniel", lang: "en-GB", voiceURI: "com.apple.voice.compact.en-GB.Daniel", localService: true },
  { name: "Daniel", lang: "en-GB", voiceURI: "com.apple.voice.compact.en-GB.Daniel", localService: true },
];

test("offerFromBrowser: ids are the voiceURI, local voices first, the default ahead, no twins, capped", () => {
  const offer = offerFromBrowser(browser);
  assert.deepEqual(
    offer.map((v) => v.id),
    ["com.apple.voice.compact.en-US.Samantha", "com.apple.voice.compact.en-GB.Daniel", "Google UK English Female"],
  );
  assert.deepEqual(offer[0], { id: "com.apple.voice.compact.en-US.Samantha", name: "Samantha", lang: "en-US" });
  const many = Array.from({ length: MAX_OFFERED + 30 }, (_, i) => ({ name: `V${i}`, lang: "en", voiceURI: `uri:${i}` }));
  assert.equal(offerFromBrowser(many).length, MAX_OFFERED);
  assert.deepEqual(offerFromBrowser([]), []);
});

test("pickBrowserVoice: by voiceURI, then by name, only for a browser choice", () => {
  const byUri = pickBrowserVoice(browser, { version: 1, engine: "browser", voice: "com.apple.voice.compact.en-GB.Daniel" });
  assert.equal(byUri?.name, "Daniel");
  const byName = pickBrowserVoice(browser, { version: 1, engine: "browser", voice: "Samantha" });
  assert.equal(byName?.voiceURI, "com.apple.voice.compact.en-US.Samantha");
  const byStoredName = pickBrowserVoice(browser, { version: 1, engine: "browser", voice: "gone", name: "Daniel" });
  assert.equal(byStoredName?.name, "Daniel");
  assert.equal(pickBrowserVoice(browser, { version: 1, engine: "elevenlabs", voice: "Samantha" }), undefined);
  assert.equal(pickBrowserVoice(browser, null), undefined);
  assert.equal(pickBrowserVoice(browser, { version: 1, engine: "browser", voice: "nobody" }), undefined);
});

test("engineHere: the choice where it works, else the device's own, never ElevenLabs uninvited", () => {
  const pc = { browser: true, phone: false, elevenlabs: true };
  const app = { browser: false, phone: true, elevenlabs: true };
  const bare = { browser: false, phone: false, elevenlabs: true };
  const eleven = { version: 1 as const, engine: "elevenlabs" as const, voice: "21m00" };
  const phone = { version: 1 as const, engine: "phone" as const, voice: "en-us-x-iom-local" };
  assert.equal(engineHere(eleven, pc), "elevenlabs");
  assert.equal(engineHere(eleven, app), "elevenlabs");
  assert.equal(engineHere(phone, pc), "browser", "a phone voice on the PC: the browser's default");
  assert.equal(engineHere(phone, app), "phone");
  assert.equal(engineHere(null, pc), "browser");
  assert.equal(engineHere(null, app), "phone");
  assert.equal(engineHere(null, bare), null);
  assert.equal(engineHere(phone, bare), null);
});

test("speakable: words only, and a long reply ends on a sentence", () => {
  const md = [
    "# Plan",
    "",
    "Here is **what** I'd do, see [the docs](https://example.com/x) and `cargo test`:",
    "",
    "```rust",
    "fn main() {}",
    "```",
    "",
    "- first thing",
    "- second _thing_",
    "",
    "| a | b |",
    "|---|---|",
    "| 1 | 2 |",
    "",
    "> quoted",
    "![pic](x.png) and https://example.com/raw.",
  ].join("\n");
  const s = speakable(md);
  assert.ok(!s.includes("#") && !s.includes("**") && !s.includes("```") && !s.includes("|") && !s.includes("]("), s);
  assert.ok(s.startsWith("Plan\nHere is what I'd do, see the docs and cargo test:"), s);
  assert.ok(s.includes("(code)") && s.includes("first thing\nsecond thing"), s);
  assert.ok(s.includes("quoted") && s.includes("(link)") && !s.includes("x.png"), s);
  const long = `${"A sentence here. ".repeat(200)}tail without end`;
  const cut = speakable(long);
  assert.ok(cut.length <= MAX_SPEAK_CHARS && cut.endsWith("."), `${cut.length} ${cut.slice(-20)}`);
  assert.equal(speakable("   \n\n "), "");
});

test("keyOk and elevenOps: a key is one long token; the ops write it and the model into upstream's section", () => {
  assert.equal(keyOk("sk_0123456789abcdef0123"), true);
  assert.equal(keyOk("short"), false);
  assert.equal(keyOk("has space 0123456789abcdef"), false);
  assert.deepEqual(elevenOps("  sk_0123456789abcdef0123 "), [
    { op: "add", path: "/providers/tts/elevenlabs/default/api_key", value: "sk_0123456789abcdef0123" },
    { op: "add", path: "/providers/tts/elevenlabs/default/model", value: ELEVEN_MODEL },
  ]);
  assert.equal(ELEVEN_MODEL, "eleven_multilingual_v2");
});

test("pickValue and choiceFromPick: the select's value both ways, names filled from the offer", () => {
  const offered = [
    { engine: "browser" as const, voices: [{ id: "uri:1", name: "Samantha", lang: "en-US" }] },
    { engine: "elevenlabs" as const, voices: [{ id: "21m00", name: "Rachel" }] },
  ];
  assert.equal(pickValue(null), "");
  assert.equal(pickValue({ version: 1, engine: "elevenlabs", voice: "21m00" }), "elevenlabs:21m00");
  assert.deepEqual(choiceFromPick("elevenlabs:21m00", offered), { version: 1, engine: "elevenlabs", voice: "21m00", name: "Rachel" });
  assert.deepEqual(choiceFromPick("browser:uri:1", offered), { version: 1, engine: "browser", voice: "uri:1", name: "Samantha" });
  assert.deepEqual(choiceFromPick("phone:en-us-x-iom-local", offered), { version: 1, engine: "phone", voice: "en-us-x-iom-local" });
  assert.equal(choiceFromPick("", offered), null);
  assert.equal(choiceFromPick("radio:x", offered), null);
  assert.equal(choiceFromPick("browser:", offered), null);
});

test("voiceLine: the name and where it comes from", () => {
  const words = { none: "The device's own voice", browser: "this browser", phone: "this phone", elevenlabs: "ElevenLabs" };
  assert.equal(voiceLine(null, words), "The device's own voice");
  assert.equal(voiceLine({ version: 1, engine: "elevenlabs", voice: "21m00", name: "Rachel" }, words), "Rachel · ElevenLabs");
  assert.equal(voiceLine({ version: 1, engine: "phone", voice: "en-us-x-iom-local" }, words), "en-us-x-iom-local · this phone");
});
