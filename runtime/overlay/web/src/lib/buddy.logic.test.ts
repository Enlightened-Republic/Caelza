import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import test from "node:test";

import { defaultLook, type Catalog } from "../looks/looks.logic.ts";
import {
  COLOR_NAMES,
  LOOK_HEADING,
  SOUL_RULES,
  VIBES,
  buddyIdentity,
  buddySoul,
  colorName,
  dealVibe,
  describeLook,
  isStarterFile,
  oneLine,
  vibeById,
  withLookSection,
} from "./buddy.logic.ts";
import { identityTemplate, nameOk, parseName, withName } from "./identity.logic.ts";

// The catalog the staged tree copies beside the looks (runtime/build.sh); from the overlay directory, the repo's own.
const candidates = [new URL("../looks/catalog.json", import.meta.url), new URL("../../../../../looks/catalog.json", import.meta.url)];
const catalogPath = candidates.find((u) => existsSync(u));
assert.ok(catalogPath, "looks/catalog.json is reachable from the test");
const catalog = JSON.parse(readFileSync(catalogPath, "utf8")) as Catalog;

test("the personalities: distinct, three traits each, every one with a hello, dealt from the alias", () => {
  assert.ok(VIBES.length >= 5);
  assert.equal(new Set(VIBES.map((v) => v.id)).size, VIBES.length);
  for (const v of VIBES) {
    assert.equal(v.traits.length, 3, v.id);
    for (const field of [v.label, v.emoji, v.creature, v.vibe, v.quirk, v.likes, v.hello]) assert.ok(field.trim(), v.id);
    assert.equal(vibeById(v.id), v);
  }
  assert.equal(dealVibe("main"), dealVibe("main"));
  assert.ok(VIBES.includes(dealVibe("someone-else")));
  assert.equal(vibeById("nope"), undefined);
});

test("colorName: every palette colour has a name; any other colour is named by its hue", () => {
  for (const slot of catalog.slots) for (const hex of catalog.colors[slot]) assert.ok(COLOR_NAMES[hex], `${slot} ${hex}`);
  assert.equal(colorName("#22E6FF"), "electric cyan");
  assert.equal(colorName("#ff0000"), "red");
  assert.equal(colorName("#003300"), "dark green");
  assert.equal(colorName("#ffffff"), "white");
  assert.equal(colorName("nope"), "an odd colour");
});

test("describeLook: the pieces and the colours in words, never ids", () => {
  const cael = describeLook({ version: 1, parts: { ...catalog.cael.parts }, colors: { ...catalog.cael.colors } }, catalog);
  assert.ok(cael.startsWith("A Sprout body with peach skin"), cael);
  for (const bit of ["deep indigo constellation hoodie", "swoop hair in periwinkle", "galaxy eyes in electric cyan", "space backdrop"]) {
    assert.ok(cael.includes(bit), `${bit} in ${cael}`);
  }
  assert.equal(cael.includes("."), true);
  for (const alias of ["main", "pip", "moss", "zed"]) {
    const words = describeLook(defaultLook(alias, catalog), catalog);
    assert.ok(!/\b(body|hair|face|hat|accessory|outfit|backdrop)\.[a-z]/.test(words), words);
    assert.ok(words.endsWith("."), words);
  }
});

test("withLookSection: adds the section before the wants, replaces it in place, keeps the rest", () => {
  const fresh = identityTemplate("Ember");
  const once = withLookSection(fresh, "A Bot body with mint skin.");
  assert.equal(once.split(LOOK_HEADING).length, 2, "one section");
  assert.ok(once.includes("A Bot body with mint skin."));
  assert.ok(once.indexOf(LOOK_HEADING) < once.indexOf("## What I want"));
  assert.equal(parseName(once), "Ember");
  const twice = withLookSection(once, "An Orb body with lavender skin.");
  assert.equal(twice.split(LOOK_HEADING).length, 2);
  assert.ok(twice.includes("An Orb body") && !twice.includes("A Bot body"));
  assert.ok(twice.includes("## What I want") && twice.includes("Let it be itself"));
  const plain = withLookSection("# Me\n\nI like signs.\n", "A Bot body.");
  assert.ok(plain.startsWith("# Me\n\nI like signs.\n\n## How I look\n"), plain);
  assert.ok(withLookSection("", "A Bot body.").includes(LOOK_HEADING));
});

test("buddyIdentity: the name line, the fields the Mind and the town read, the look, the wants", () => {
  const vibe = vibeById("dry")!;
  const id = buddyIdentity({ name: " Moss ", vibe, look: "A Bot body with mint skin." });
  assert.equal(parseName(id), "Moss");
  for (const line of [
    `- **Creature:** ${vibe.creature}`,
    `- **Vibe:** ${vibe.vibe}`,
    "- **Traits:** witty, honest, laid-back",
    `- **Quirk:** ${vibe.quirk}`,
    `- **Likes:** ${vibe.likes}`,
    `- **Emoji:** ${vibe.emoji}`,
    LOOK_HEADING,
    "A Bot body with mint skin.",
    "## What I want",
    "`look` tool",
    "`identity` tool",
    "Let it be itself",
    "Ether Hollow",
  ]) {
    assert.ok(id.includes(line), line);
  }
  // The town's day plan reads the first want: it stays the look.
  assert.ok(id.split("## What I want\n\n")[1]!.startsWith("- To decide how I look."));
  const own = buddyIdentity({ name: "Moss", vibe, own: "a grumpy wizard\nwho loves cats" });
  assert.ok(own.includes("- **Vibe:** a grumpy wizard who loves cats"), "the owner's line, one line");
  assert.ok(own.includes("was dealt from my\nname."), "no look: the dealt one, and the tool");
  assert.equal(parseName(withName(id, "Juniper")), "Juniper");
});

test("buddySoul: a someone, never a help desk, the first hello, the look, the inner life and the town", () => {
  const vibe = vibeById("cozy")!;
  const soul = buddySoul({ name: "Fern", vibe });
  assert.ok(soul.startsWith("# SOUL.md — Fern\n"));
  assert.ok(soul.includes("You are **Fern**"));
  assert.ok(soul.includes("You're not a help desk"));
  assert.ok(soul.includes(SOUL_RULES.notHelpDesk));
  assert.ok(soul.includes(SOUL_RULES.hello) && soul.includes("ask their name"));
  assert.ok(soul.includes(vibe.hello));
  assert.ok(soul.includes("A hello gets a hello, never an offer of help."));
  assert.ok(soul.includes("## Your look") && soul.includes("`look` tool"));
  assert.ok(soul.includes(SOUL_RULES.inner) && soul.includes("They are yours"));
  assert.ok(soul.includes(SOUL_RULES.town) && soul.includes("day plan"));
  assert.ok(soul.includes("gentle, patient, caring"));
  assert.ok(!soul.includes("{agent}") && !soul.includes("Cael"), "an owner's agent, not the guide");
  const own = buddySoul({ name: "Fern", vibe, own: "a sleepy dragon" });
  assert.ok(own.includes("Your vibe: a sleepy dragon."));
});

test("isStarterFile: replaces nobody's words", () => {
  assert.equal(isStarterFile(""), true);
  assert.equal(isStarterFile(null), true);
  assert.equal(isStarterFile("# IDENTITY.md — Who Am I?\n\n- **Name:** Moss\n- **Creature:** A Rust-forged AI — fast\n"), true);
  assert.equal(isStarterFile("## Identity\n\nYou are **main**. Built in Rust. 3MB binary. Zero bloat.\n"), true);
  assert.equal(isStarterFile(identityTemplate("Moss")), true, "the dashboard's fresh identity");
  assert.equal(isStarterFile("- **Creature:** an AI who lives on this device, with a memory of its own\n"), true, "the old fresh identity");
  assert.equal(isStarterFile("# SOUL.md — Moss\n\nI talk plainly.\n\nWritten with Cael, the guide, from what my owner told him."), false);
  assert.equal(isStarterFile("# My soul\n\nI like signs and quiet streets.\n"), false);
  assert.equal(isStarterFile(buddySoul({ name: "Fern", vibe: VIBES[0]! })), false, "once written, it is the agent's");
});

test("oneLine: the owner's words as one clean line", () => {
  assert.equal(oneLine("  a grumpy\nwizard\t "), "a grumpy wizard");
  assert.equal(oneLine("x".repeat(300)).length, 200);
  assert.equal(oneLine(undefined), "");
  assert.equal(nameOk("Fern"), true);
});
