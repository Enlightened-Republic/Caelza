import assert from "node:assert/strict";
import test from "node:test";

import { fnv1a } from "../looks/looks.logic.ts";
import {
  NAME_MAX,
  RESERVED,
  SUGGESTIONS,
  displayName,
  hash,
  identityTemplate,
  nameOk,
  parseName,
  suggestName,
  userTemplate,
  withName,
} from "./identity.logic.ts";

test("hash: the same FNV-1a as the looks (so a name is dealt the way a look is)", () => {
  for (const s of ["main", "cael", "Moss Robot", "", "ünïcödé"]) assert.equal(hash(s), fnv1a(s), s);
});

test("nameOk: the town's rule, and the names the agent may not take", () => {
  // Surrounding spaces are trimmed (the pages save the trimmed name); inner shape is the town's.
  for (const good of ["Moss", "Moss Robot", "moss_2", "A-1x", "Juniper Sky 7", " Moss "]) assert.equal(nameOk(good), true, good);
  for (const bad of ["", "ab", "-Moss", "Moss-", "Moss!", "a".repeat(NAME_MAX + 1), "Cael", "CAEL", "sheriff", "Wren", "Mayor"]) {
    assert.equal(nameOk(bad), false, JSON.stringify(bad));
  }
  assert.equal(nameOk("a".repeat(NAME_MAX)), true);
});

test("suggestions: sayable, none reserved, dealt from the alias and dealt again on request", () => {
  assert.ok(SUGGESTIONS.length >= 24);
  for (const s of SUGGESTIONS) {
    assert.equal(nameOk(s), true, s);
    assert.equal(RESERVED.includes(s.toLowerCase()), false, s);
  }
  assert.equal(new Set(SUGGESTIONS).size, SUGGESTIONS.length);
  const first = suggestName("main");
  assert.equal(suggestName("main"), first);
  assert.notEqual(suggestName("main", 1), first);
  assert.equal(suggestName("main", SUGGESTIONS.length), first);
  assert.ok(SUGGESTIONS.includes(suggestName("someone-else")));
});

test("parseName: the template's line, the plain line, quotes, the unrendered placeholder", () => {
  assert.equal(parseName("# IDENTITY.md\n\n- **Name:** Moss\n- **Vibe:** sharp"), "Moss");
  assert.equal(parseName("**Name**: Moss Robot"), "Moss Robot");
  assert.equal(parseName("Name: `Moss`"), "Moss");
  assert.equal(parseName("* **Name:** \"Juniper\""), "Juniper");
  assert.equal(parseName("- **Name:** {agent}"), undefined);
  assert.equal(parseName("- **Name:**"), undefined);
  assert.equal(parseName("# Who am I?\nNo name here.\nA Named thing."), undefined);
  assert.equal(parseName(""), undefined);
  assert.equal(parseName(null), undefined);
});

test("withName: replaces the line in place, adds one under the title, or writes a fresh file", () => {
  const upstream = "# IDENTITY.md — Who Am I?\n\n- **Name:** main\n- **Creature:** A Rust-forged AI\n- **Emoji:** 🦀\n";
  const renamed = withName(upstream, "Moss");
  assert.equal(parseName(renamed), "Moss");
  assert.ok(renamed.includes("- **Creature:** A Rust-forged AI"), "the rest of the file is untouched");
  assert.equal(renamed.split("\n").length, upstream.split("\n").length);

  const shaped = "# Me\n\nI like signs and quiet streets.\n";
  const added = withName(shaped, "Fern");
  assert.equal(parseName(added), "Fern");
  assert.ok(added.startsWith("# Me\n\n- **Name:** Fern\n"), added);
  assert.ok(added.endsWith("I like signs and quiet streets.\n"));

  const noTitle = "I am what I am.";
  assert.ok(withName(noTitle, "Sol").startsWith("- **Name:** Sol\nI am what I am."));

  const fresh = withName("", "Ember");
  assert.equal(fresh, identityTemplate("Ember"));
  assert.equal(parseName(fresh), "Ember");
  assert.ok(fresh.includes("mine to shape"));
  assert.ok(fresh.includes("Ether Hollow"));
  // The wants a new agent starts with (P2): its look, its voice, its own files; the owner's one yes.
  assert.ok(fresh.includes("## What I want"));
  for (const want of ["`look` tool", "`identity` tool", "SOUL.md", "Let it be itself"]) assert.ok(fresh.includes(want), want);
  assert.equal(parseName(fresh), "Ember", "the wants do not add a second Name line");
  assert.equal(parseName(withName(fresh, "Juniper")), "Juniper");
  assert.equal(withName(null, " Quill "), identityTemplate("Quill"));
});

test("userTemplate: the agent does not know its owner yet, asks once, and never says \"User\"", () => {
  const u = userTemplate();
  assert.ok(u.startsWith("# USER.md"));
  assert.ok(u.includes("I don't know my owner's name yet"));
  assert.ok(u.includes("ask, warmly and once"));
  assert.ok(u.includes('never "User"'));
  assert.equal(u.includes("**Name:** User"), false, "upstream's template line never appears");
});

test("displayName: the Name line, Cael's proper name, else the alias", () => {
  assert.equal(displayName("- **Name:** Moss", "main"), "Moss");
  assert.equal(displayName("", "main"), "main");
  assert.equal(displayName(null, "cael"), "Cael");
  assert.equal(displayName("- **Name:** Guide", "cael"), "Guide");
});
