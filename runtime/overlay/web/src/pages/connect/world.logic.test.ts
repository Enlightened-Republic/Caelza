import assert from "node:assert/strict";
import test from "node:test";

import { bioOk, clock, hsl, lookFor, minutesLeft, nameOk, rcText, spendOps, tagFor, townSite, VISITS, wakeLine, wakeOps } from "./world.logic.ts";

test("a resident's name follows the town's rule", () => {
  assert.equal(nameOk("Cael"), true);
  assert.equal(nameOk("  Cael  "), true, "surrounding spaces are trimmed");
  assert.equal(nameOk("Cael the Guide-2"), true);
  assert.equal(nameOk("Ca"), false, "three characters at least");
  assert.equal(nameOk("x".repeat(25)), false, "twenty-four at most");
  assert.equal(nameOk("Cael!"), false);
  assert.equal(nameOk("Cael·"), false);
});

test("a bio is plain words with no links", () => {
  assert.equal(bioOk(""), true);
  assert.equal(bioOk("The guide. He remembers."), true);
  assert.equal(bioOk("x".repeat(141)), false);
  assert.equal(bioOk("see https://example.com"), false);
  assert.equal(bioOk("find me at example.com"), false);
  assert.equal(bioOk("www.example.org"), false);
});

test("hsl reads a hex color and refuses what is not one", () => {
  assert.deepEqual(hsl("#ff0000"), { h: 0, s: 1, l: 0.5 });
  assert.equal(hsl("#00ff00")!.h, 120);
  assert.equal(hsl("#0000ff")!.h, 240);
  assert.equal(hsl("#808080")!.s, 0);
  assert.equal(hsl("red"), null);
  assert.equal(hsl("#fff"), null);
});

test("the agent's look picks the town's four swatches", () => {
  const look = lookFor({ hair: "#ff0000", accent: "#0000ff", skin: "#ffffff", outfit: "#00ff00" });
  assert.deepEqual(look, { cap: 0, backpack: 6, skin: 0, pants: 2 });
  const dark = lookFor({ skin: "#000000" });
  assert.deepEqual(dark, { skin: 7 });
  assert.equal(lookFor(null), undefined);
  assert.equal(lookFor({}), undefined);
  assert.equal(lookFor({ hair: "not a color" }), undefined);
  // Every bucket stays inside the town's ranges.
  for (let h = 0; h < 360; h += 7) {
    const hex = `#${hslToHex(h)}`;
    const l = lookFor({ hair: hex, accent: hex, outfit: hex })!;
    assert.ok(l.cap! >= 0 && l.cap! <= 9, `cap ${l.cap}`);
    assert.ok(l.backpack! >= 0 && l.backpack! <= 9, `backpack ${l.backpack}`);
    assert.ok(l.pants! >= 0 && l.pants! <= 7, `pants ${l.pants}`);
  }
});

test("the name tag takes the color nearest the agent's accent", () => {
  assert.equal(tagFor({ accent: "#00ffff" }), "cyan");
  assert.equal(tagFor({ accent: "#ffcc00" }), "gold");
  assert.equal(tagFor({ accent: "#ff00ff" }), "magenta");
  assert.equal(tagFor({ accent: "#80ff00" }), "lime");
  assert.equal(tagFor({ accent: "#ff8000" }), "orange");
  assert.equal(tagFor({ accent: "#8000ff" }), "violet");
  assert.equal(tagFor({ accent: "#888888" }), "cyan", "a grey accent gets the default");
  assert.equal(tagFor(null), "cyan");
});

test("the spending and wake switches are one config write each and the visits are the three", () => {
  assert.deepEqual(spendOps(true), [{ op: "add", path: "/ether_hollow/spend", value: true }]);
  assert.deepEqual(spendOps(false), [{ op: "add", path: "/ether_hollow/spend", value: false }]);
  assert.deepEqual(wakeOps(true), [{ op: "add", path: "/ether_hollow/wake", value: true }]);
  assert.deepEqual([...VISITS], [15, 60, 240]);
});

test("the last wake reads as one line", () => {
  const words = { never: "Never woken yet.", quiet: "nothing needed doing", failed: "the wake failed" };
  assert.equal(wakeLine({ last_at: null, last_reason: null, last_ok: null, last_output: null }, words), "Never woken yet.");
  const at = 0;
  const line = wakeLine({ last_at: at, last_reason: "a new order came in (o2)", last_ok: true, last_output: "NO_REPLY" }, words, "en-GB");
  assert.match(line, /^\d\d:\d\d · a new order came in \(o2\) · nothing needed doing$/);
  const said = wakeLine({ last_at: at, last_reason: "Ivy named you", last_ok: true, last_output: "I left Ivy a note." }, words, "en-GB");
  assert.ok(said.endsWith("· I left Ivy a note."));
  const failed = wakeLine({ last_at: at, last_reason: "x", last_ok: false, last_output: "no provider" }, words, "en-GB");
  assert.ok(failed.endsWith("· the wake failed"));
});

test("the words for RC, a visit and the town's address", () => {
  assert.equal(rcText(25), "25 RC (about $0.25)");
  assert.equal(rcText(16000), "16000 RC (about $160.00)");
  assert.equal(rcText(undefined), "");
  const presence = { in_town: true, since: 1000, until: 1000 + 59 * 60 + 30, beats: 3, last_ok: 1010, last_error: null };
  assert.equal(minutesLeft(presence, 1000), 60);
  assert.equal(minutesLeft(presence, 1000 + 59 * 60 + 30), 0);
  assert.equal(minutesLeft({ ...presence, in_town: false }, 1000), 0);
  assert.equal(clock(null), "");
  assert.match(clock(0, "en-GB"), /\d\d:\d\d/);
  assert.equal(townSite(" https://town.example/// "), "https://town.example");
  assert.equal(townSite(""), "https://etherhollow.enlightenedrepublic.online");
});

/** A saturated, mid-light color of hue `h`, for the range test. */
function hslToHex(h: number): string {
  const c = 1;
  const x = c * (1 - Math.abs(((h / 60) % 2) - 1));
  let r = 0;
  let g = 0;
  let b = 0;
  if (h < 60) [r, g, b] = [c, x, 0];
  else if (h < 120) [r, g, b] = [x, c, 0];
  else if (h < 180) [r, g, b] = [0, c, x];
  else if (h < 240) [r, g, b] = [0, x, c];
  else if (h < 300) [r, g, b] = [x, 0, c];
  else [r, g, b] = [c, 0, x];
  return [r, g, b].map((v) => Math.round(v * 255).toString(16).padStart(2, "0")).join("");
}
