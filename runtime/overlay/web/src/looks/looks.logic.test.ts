import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import test from "node:test";

import {
  FRAMES,
  KEYS,
  LAYERS,
  OUTLINE,
  SLOTS,
  STARTER,
  defaultLook,
  finishPixels,
  fnv1a,
  isPriced,
  lockedParts,
  lookEquals,
  normalizeLook,
  ownedPacks,
  packRgb,
  parseUnlockCode,
  partUrl,
  priceLabel,
  ramp,
  recolorTable,
  sheetUrl,
  slotsInUse,
  unlocked,
  validateLook,
  type Catalog,
} from "./looks.logic.ts";

// The catalog beside this file in the staged tree (runtime/build.sh copies
// looks/catalog.json here); from the overlay directory, the repo's own.
const here = new URL(".", import.meta.url);
const candidates = [new URL("./catalog.json", here), new URL("../../../../../looks/catalog.json", here)];
const catalogPath = candidates.find((u) => existsSync(u));
assert.ok(catalogPath, "looks/catalog.json is reachable from the test");
const catalog = JSON.parse(readFileSync(catalogPath, "utf8")) as Catalog;

test("the catalog's shape is the renderer's", () => {
  assert.deepEqual(catalog.layers, LAYERS);
  assert.deepEqual(catalog.frames, FRAMES);
  assert.deepEqual(catalog.slots, SLOTS);
  for (const layer of LAYERS) {
    assert.ok(catalog.parts.some((p) => p.layer === layer && p.pack === STARTER), `a starter ${layer}`);
  }
  for (const pid of Object.values(catalog.cael.parts)) assert.ok(catalog.parts.some((p) => p.id === pid), pid);
  assert.ok(catalog.packs.some((p) => p.id === STARTER && p.status === "available"));
});

test("the hash and the deal agree with looks/parts.py", () => {
  // FNV-1a 32-bit test vectors.
  assert.equal(fnv1a(""), 0x811c9dc5);
  assert.equal(fnv1a("a"), 0xe40c292c);
  assert.equal(fnv1a("foobar"), 0xbf9cf968);
  // Cael is fixed; everyone else is dealt from the starter pack and the palettes.
  const cael = defaultLook("cael", catalog);
  assert.deepEqual(cael.parts, catalog.cael.parts);
  assert.deepEqual(cael.colors, catalog.cael.colors);
  const main = defaultLook("main", catalog);
  assert.equal(validateLook(main, catalog).length, 0);
  for (const id of Object.values(main.parts)) assert.equal(catalog.parts.find((p) => p.id === id)?.pack, STARTER);
  for (const slot of SLOTS) assert.ok(catalog.colors[slot].includes(main.colors[slot]));
  // Pinned so the Python side's render of "main" is the dashboard's (tests/test_looks.py renders the same deal).
  const h = fnv1a("main");
  const starterBody = catalog.parts.filter((p) => p.layer === "body" && p.pack === STARTER);
  assert.equal(main.parts.body, starterBody[(h >>> 4) % starterBody.length]!.id);
  assert.notDeepEqual(defaultLook("niba", catalog), main);
});

test("the ramps and the key table are parts.py's maths", () => {
  assert.deepEqual(ramp("#22e6ff"), { m: [34, 230, 255], d: [26, 141, 166], l: [118, 240, 255] });
  assert.deepEqual(ramp("#000000").d, [5, 3, 13]);
  const table = recolorTable({ skin: "#e0a98a", eyes: "#22e6ff" });
  assert.deepEqual(table.get(packRgb(250, 1, 1)), [224, 169, 138]);
  assert.deepEqual(table.get(packRgb(1, 250, 250)), [34, 230, 255]);
  assert.equal(table.get(packRgb(1, 250, 1)), undefined, "hair was not chosen, so its key stays");
  assert.equal(table.size, 4);
  for (const slot of SLOTS) for (const key of Object.values(KEYS[slot])) assert.ok(key.every((v) => v === 1 || v === 120 || v >= 200), slot);
});

test("the pixel pass outlines the silhouette and swaps the keys", () => {
  // A 3 x 3 image: one silhouette pixel in the middle in the skin key, one detail pixel at a corner.
  const w = 3;
  const data = new Uint8ClampedArray(w * w * 4);
  const sil = new Uint8Array(w * w);
  const set = (i: number, rgb: number[]) => {
    data.set([...rgb, 255], i * 4);
  };
  set(4, [250, 1, 1]);
  sil[4] = 1;
  set(0, [1, 250, 250]);
  finishPixels(data, sil, w, w, recolorTable({ skin: "#e0a98a", eyes: "#22e6ff" }));
  // The four neighbours of the middle took the outline; the corners (not neighbours) did not, the detail corner kept its colour (swapped).
  for (const i of [1, 3, 5, 7]) assert.deepEqual([...data.slice(i * 4, i * 4 + 4)], [...OUTLINE, 255], `pixel ${i}`);
  assert.deepEqual([...data.slice(16, 20)], [224, 169, 138, 255]);
  assert.deepEqual([...data.slice(0, 4)], [34, 230, 255, 255]);
  assert.equal(data[2 * 4 + 3], 0);
});

test("part and sheet URLs live under the dashboard's static prefix", () => {
  assert.equal(partUrl("", "hair.swoop"), "/_app/looks/parts/hair/swoop.png");
  assert.equal(partUrl("/x", "face.round", "blink"), "/x/_app/looks/parts/face/round.blink.png");
  assert.equal(partUrl("", "face.round"), "/_app/looks/parts/face/round.closed.png");
  assert.equal(sheetUrl("", "cosmic"), "/_app/looks/sheets/cosmic.png");
});

test("the outline goes over an opaque backdrop and under the detail layers, as in parts.py", () => {
  // 3 x 3, every pixel an opaque backdrop, the silhouette in the middle, a detail pixel to its right.
  const width = 3;
  const height = 3;
  const data = new Uint8ClampedArray(width * height * 4);
  for (let i = 0; i < width * height; i++) data.set([5, 3, 16, 255], i * 4);
  data.set([250, 1, 1, 255], 4 * 4); // the silhouette pixel, in the skin key
  data.set([1, 250, 250, 255], 5 * 4); // a detail pixel (eyes key), right of it
  const sil = new Uint8Array([0, 0, 0, 0, 1, 0, 0, 0, 0]);
  const det = new Uint8Array([0, 0, 0, 0, 0, 1, 0, 0, 0]);
  finishPixels(data, sil, width, height, recolorTable({ skin: "#e0a98a", eyes: "#22e6ff" }), det);
  const px = (i: number) => [data[i * 4], data[i * 4 + 1], data[i * 4 + 2]];
  assert.deepEqual(px(1), OUTLINE, "above the silhouette: outline over the backdrop");
  assert.deepEqual(px(3), OUTLINE, "left");
  assert.deepEqual(px(7), OUTLINE, "below");
  assert.deepEqual(px(5), ramp("#22e6ff").m, "the detail pixel keeps its colour: the outline is under it");
  assert.deepEqual(px(0), [5, 3, 16], "a corner is not a 4-neighbour");
  assert.deepEqual(px(4), ramp("#e0a98a").m, "the silhouette is recoloured, not outlined");
  // Without `det`, an opaque non-silhouette pixel counts as detail: right for a look with no backdrop.
  const bare = new Uint8ClampedArray(width * height * 4);
  bare.set([250, 1, 1, 255], 4 * 4);
  finishPixels(bare, sil, width, height, recolorTable({ skin: "#e0a98a" }));
  assert.deepEqual([bare[1 * 4], bare[1 * 4 + 1], bare[1 * 4 + 2], bare[1 * 4 + 3]], [...OUTLINE, 255]);
});

test("the wardrobe: the starter always, available packs when added, a priced pack once a code opened it", () => {
  assert.deepEqual([...ownedPacks(catalog, null)], [STARTER]);
  assert.deepEqual([...ownedPacks(catalog, { version: 1, packs: ["cosmic", "arcade", "nope"] })], [STARTER, "cosmic"], "arcade is priced: in the wardrobe but not opened");
  assert.deepEqual([...ownedPacks(catalog, { version: 1, packs: ["cosmic", "arcade"], unlocks: { arcade: "TEST2345" } })], [STARTER, "cosmic", "arcade"]);
  assert.ok(unlocked("arcade", { version: 1, packs: [], unlocks: { arcade: "TEST2345" } }), "opened before: back in without a code");
  assert.ok(!unlocked("arcade", { version: 1, packs: ["arcade"] }));
  const arcade = catalog.packs.find((p) => p.id === "arcade");
  assert.ok(arcade && isPriced(arcade) && arcade.unlock === "code" && arcade.status === "available", "the Arcade pack is for sale");
  assert.ok(catalog.parts.filter((p) => p.pack === "arcade").length >= 7);
  assert.equal(catalog.unlock?.scheme, "ed25519-v1");
  assert.match(catalog.unlock?.public_key ?? "", /^[0-9a-f]{64}$/);
  const cael = defaultLook("cael", catalog);
  assert.ok(lockedParts(cael, catalog, ownedPacks(catalog, null)).length > 0, "Cael's hoodie is cosmic");
  assert.deepEqual(lockedParts(cael, catalog, ownedPacks(catalog, { version: 1, packs: ["cosmic"] })), []);
  assert.equal(priceLabel({ id: "x", name: "x", blurb: "", price: "free", status: "available" }), "Free");
  assert.equal(priceLabel({ id: "x", name: "x", blurb: "", price: { usd: 2.5 }, status: "available" }), "$2.50");
});

test("an unlock code's shape: the pack, eight characters, the signature", () => {
  const code = "ARCADE-TEST2345-Pnj8FQev4WFjpZzV5W7lLxPCuAfWQVi5tqaTVoXR4xsirpwYtC907gtdHruBANsm2J_goTsOL6fOd2qclwMRBg";
  assert.deepEqual(parseUnlockCode(code), { pack: "arcade", id: "TEST2345" });
  assert.deepEqual(parseUnlockCode(` arcade-test2345-${code.slice(16)} `), { pack: "arcade", id: "TEST2345" }, "case and spaces do not matter");
  assert.deepEqual(parseUnlockCode(`ARCADE-TEST2345-${code.slice(16, 60)}\n${code.slice(60)}`), { pack: "arcade", id: "TEST2345" }, "a line break from a receipt is fine");
  for (const bad of ["", "ARCADE", "ARCADE-TEST2345", "ARCADE-TEST2345-short", `ARCADE-TEST0345-${code.slice(16)}`, `${code}x`, `ARC_ADE-TEST2345-${code.slice(16)}`.replace("_", "."), `COSMIC-TEST2345-${code.slice(16)}x`]) {
    assert.equal(parseUnlockCode(bad), null, bad);
  }
});

test("a saved look is validated, and a broken one made whole", () => {
  const good = defaultLook("main", catalog);
  assert.deepEqual(validateLook(good, catalog), []);
  assert.deepEqual(validateLook({ ...good, version: 2 }, catalog), ["version must be 1"]);
  const bad = { version: 1, parts: { ...good.parts, hat: "hair.swoop", face: "face.nope" }, colors: { ...good.colors, eyes: "blue" } };
  assert.deepEqual(validateLook(bad, catalog), ["hat: hair.swoop is a hair part", "face: face.nope is not in the catalog", "eyes: not a #rrggbb colour"]);
  assert.deepEqual(validateLook(null, catalog), ["a look is an object"]);
  const fixed = normalizeLook(bad, "main", catalog);
  assert.equal(fixed.parts.hat, good.parts.hat);
  assert.equal(fixed.parts.face, good.parts.face);
  assert.equal(fixed.colors.eyes, good.colors.eyes);
  assert.equal(normalizeLook({ version: 1, colors: { skin: "#ABCDEF" } }, "main", catalog).colors.skin, "#abcdef");
  assert.ok(lookEquals(normalizeLook(good, "main", catalog), good));
  assert.ok(!lookEquals(fixed, { ...good, colors: { ...good.colors, skin: "#000000" } }));
  assert.deepEqual(slotsInUse(defaultLook("cael", catalog), catalog), ["skin", "hair", "outfit", "accent", "eyes"]);
});
