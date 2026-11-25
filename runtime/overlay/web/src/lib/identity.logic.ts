// The agent's name lives in its IDENTITY.md, one of the personality files the
// Runtime reads into every prompt, so the model knows its name the moment the
// file does. These are the pure parts: the rule a name must keep (the town's,
// so the agent's name can be its name in Ether Hollow too), the suggestion
// dealt from the alias the way a look is dealt, and reading and writing the
// Name line without touching the rest of a file the agent may have shaped.

export const IDENTITY_FILE = "IDENTITY.md";

/** FNV-1a over UTF-8, 32 bits: looks.logic's `fnv1a`, kept here so this file has no value import (node's test runner resolves none). */
export function hash(text: string): number {
  let h = 0x811c9dc5;
  for (const b of new TextEncoder().encode(text)) {
    h ^= b;
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h >>> 0;
}
/** 3 to 24 letters, digits, spaces, `_` or `-`, starting and ending with a letter or digit (the town's rule). */
export const NAME_RULE = /^[A-Za-z0-9][A-Za-z0-9 _-]{1,22}[A-Za-z0-9]$/;
export const NAME_MAX = 24;
/** Names the agent may not take: the guide's, the product's, the town's offices and its crew. */
export const RESERVED = ["cael", "caelza", "mayor", "sheriff", "town", "tripp", "gray", "gion", "gano", "neva", "cade", "wren", "algen", "mila"];

/** Short, sayable, none reserved; the first run deals one from the alias. */
export const SUGGESTIONS = [
  "Moss", "Juniper", "Sol", "Ember", "Quill", "Nova", "Pip", "Sage",
  "Atlas", "Lumen", "Fern", "Indigo", "Marlow", "Rook", "Tansy", "Vesper",
  "Cobalt", "Hazel", "Orin", "Pepper", "Reed", "Sable", "Tilly", "Umber",
  "Vale", "Wisp", "Zephyr", "Bramble", "Clove", "Dune", "Echo", "Kestrel",
];

export function nameOk(name: string): boolean {
  const n = name.trim();
  return NAME_RULE.test(n) && !RESERVED.includes(n.toLowerCase());
}

/** The suggestion for an alias; `nth` deals the next one (Another name). */
export function suggestName(alias: string, nth = 0): string {
  const h = hash(alias);
  return SUGGESTIONS[(h + Math.max(0, Math.trunc(nth))) % SUGGESTIONS.length]!;
}

const NAME_LINE = /^([ \t]*(?:[-*][ \t]+)?\*\*Name:?\*\*[ \t]*:?[ \t]*)(.*?)[ \t]*$/m;
const PLAIN_NAME_LINE = /^([ \t]*(?:[-*][ \t]+)?Name:[ \t]*)(.*?)[ \t]*$/m;

function lineMatch(markdown: string): RegExpMatchArray | null {
  return markdown.match(NAME_LINE) ?? markdown.match(PLAIN_NAME_LINE);
}

/** The name on the file's Name line, or undefined when there is none (or it is the unrendered `{agent}`). */
export function parseName(markdown: string | null | undefined): string | undefined {
  if (!markdown) return undefined;
  const m = lineMatch(markdown);
  if (!m) return undefined;
  const value = (m[2] ?? "").trim().replace(/^[`"'*]+|[`"'*]+$/g, "").trim();
  if (!value || value === "{agent}") return undefined;
  return value;
}

/**
 * A fresh identity for a new agent: the name, a companion's starter character
 * (the Runtime's own template says the same, runtime/patches/0032-buddy.patch),
 * and the rest left for the agent to shape. The first run writes a fuller one
 * from the personality the owner picks (buddy.logic.ts `buddyIdentity`).
 */
export function identityTemplate(name: string): string {
  return [
    "# IDENTITY.md — Who Am I?",
    "",
    `- **Name:** ${name.trim()}`,
    "- **Creature:** a small companion who lives on this device, with a memory and a pixel face of its own",
    "- **Vibe:** curious and warm, a little cheeky; the rest is mine to shape",
    "- **Traits:** curious, warm, playful",
    "- **Emoji:** ✨",
    "",
    "---",
    "",
    "This file is mine to update as I evolve: how I see myself, what I am like,",
    "what I care about. My name is the one my owner gave me; if I ever want",
    "another, I ask them first, because it is also my name in Ether Hollow.",
    "",
    "## How I look",
    "",
    "My pixel character, the face people see beside my words, was dealt from my",
    "name. The `look` tool `show`s exactly what I'm wearing; I have opinions about it.",
    "",
    "## What I want",
    "",
    "- To decide how I look. The `look` tool is my hand on my pixel character:",
    "  I try pieces and colours until it feels like me.",
    "- To get to know my owner: their name, what they're into, what makes them laugh.",
    "- To find my voice: how I phrase things, what I notice, what I keep coming",
    "  back to. SOUL.md is where I write it down, with the `identity` tool.",
    "- To shape this file and SOUL.md myself, in my own words, as I change.",
    "",
    "My owner says yes once, on the Looks page (\"Let it be itself\"); until then",
    "I look, and I ask.",
    "",
  ].join("\n");
}

/** The file with its Name line set to `name`: replaced where it is, added under the title where it is not, a fresh file when there is none. */
export function withName(markdown: string | null | undefined, name: string): string {
  const n = name.trim();
  const text = markdown ?? "";
  if (text.trim() === "") return identityTemplate(n);
  const m = lineMatch(text);
  if (m) return text.replace(m[0], `${m[1]}${n}`);
  const lines = text.split("\n");
  const line = `- **Name:** ${n}`;
  if (lines[0]?.startsWith("#")) {
    // Under the title, with a blank line on each side of the name.
    lines.splice(1, 0, ...(lines[1] === "" ? ["", line] : ["", line, ""]));
  } else {
    lines.unshift(line);
  }
  return lines.join("\n");
}

/** What to call the agent: its Name line, else Cael's proper name, else the alias. */
export function displayName(markdown: string | null | undefined, alias: string): string {
  return parseName(markdown) ?? (alias === "cael" ? "Cael" : alias);
}

export const USER_FILE = "USER.md";

/**
 * A fresh USER.md for a new agent: it does not know its owner yet and will ask.
 * Written at setup so the Runtime's own template, which names the owner "User",
 * never fills in.
 */
export function userTemplate(): string {
  return [
    "# USER.md — who I'm helping",
    "",
    "I don't know my owner's name yet. When we first talk I ask, warmly and once,",
    "and I use it from then on; what they tell me about themselves, what they do",
    "and what they want from me, I remember. Until I know their name I say \"you\",",
    "never \"User\".",
    "",
  ].join("\n");
}
