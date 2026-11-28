import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import test from "node:test";

import {
  AVATAR_SIZE,
  FRAMES,
  KEYS,
  LAYERS,
  OUTLINE,
  SLOTS,
  STARTER,
  avatarGeometry,
  avatarLook,
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
  sampleAvatar,
  sheetUrl,
  slotsInUse,
  unlocked,
  validateLook,
  addedPacks,
  packLayers,
  wearPack,
  wearCharacter,
  CHARACTER_ID,
  type Catalog,
} from "./looks.logic.ts";
import {
  CHARACTER_ID as CHARACTER_ID_FILES,
  MAX_FRAME_BYTES,
  characterId,
  characterName,
  fitSizes,
  frameToDraw,
  frameUrl,
  pickFrames,
  pngsInZip,
} from "./characters.logic.ts";

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

test("the avatar: the frame at the largest whole scale that fits, centred, the edges continued (parts.py agrees)", () => {
  assert.deepEqual(avatarGeometry(AVATAR_SIZE), { size: 512, scale: 11, ox: 36, oy: 14 });
  assert.deepEqual(avatarGeometry(100, 2, 3), { size: 100, scale: 33, ox: 17, oy: 0 });
  assert.deepEqual(avatarGeometry(1, 40, 44), { size: 1, scale: 1, ox: -20, oy: -22 }, "a square smaller than the frame still samples its middle (floored, as Python's //)");
  // A 2 x 3 frame of distinct colours on a 10 x 10 square: scale 3, margins 2 (x) and 0 (y) + 1 row below.
  const frame = new Uint8ClampedArray(2 * 3 * 4);
  const colours = [
    [1, 0, 0, 255],
    [0, 1, 0, 255],
    [0, 0, 1, 255],
    [9, 9, 0, 255],
    [9, 0, 9, 255],
    [0, 9, 9, 255],
  ];
  colours.forEach((c, i) => frame.set(c, i * 4));
  const g = avatarGeometry(10, 2, 3);
  assert.deepEqual(g, { size: 10, scale: 3, ox: 2, oy: 0 });
  const out = sampleAvatar(frame, 2, 3, g);
  const px = (X: number, Y: number) => Array.from(out.slice((Y * 10 + X) * 4, (Y * 10 + X) * 4 + 4));
  assert.deepEqual(px(0, 0), colours[0], "the left margin continues the frame's left column");
  assert.deepEqual(px(2, 0), colours[0]);
  assert.deepEqual(px(4, 0), colours[0], "scale 3: columns 2..4 are the frame's first column");
  assert.deepEqual(px(5, 0), colours[1]);
  assert.deepEqual(px(9, 0), colours[1], "the right margin continues the right column");
  assert.deepEqual(px(3, 3), colours[2], "row 2 of the frame at rows 3..5");
  assert.deepEqual(px(6, 8), colours[5]);
  assert.deepEqual(px(6, 9), colours[5], "the row below the frame continues its last row");
  assert.equal(out.length, 10 * 10 * 4);
  const bare = defaultLook("main", catalog);
  bare.parts.backdrop = "backdrop.none";
  assert.equal(avatarLook(bare).parts.backdrop, "backdrop.space", "no backdrop: Space behind the avatar");
  assert.equal(avatarLook(defaultLook("cael", catalog)).parts.backdrop, "backdrop.space");
  const grid = { ...bare, parts: { ...bare.parts, backdrop: "backdrop.grid" } };
  assert.equal(avatarLook(grid).parts.backdrop, "backdrop.grid", "a backdrop stays");
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

// ---- the packs the owner added, worn in one tap -----------------------------------

test("the packs the owner added are the wardrobe's, not the starter, in catalog order", () => {
  const owned = ownedPacks(catalog, { version: 1, packs: ["cosmic"] });
  assert.deepEqual(addedPacks(catalog, owned).map((p) => p.id), ["cosmic"]);
  assert.deepEqual(addedPacks(catalog, ownedPacks(catalog, null)), [], "only the starter: nothing added");
});

test("wearing a pack puts its first piece on every layer it covers and takes a character off", () => {
  const base = { ...defaultLook("main", catalog), character: "pirate" };
  const worn = wearPack(base, catalog, "cosmic");
  const layers = packLayers(catalog, "cosmic");
  assert.ok(layers.length > 0);
  for (const layer of LAYERS) {
    const part = catalog.parts.find((p) => p.id === worn.parts[layer])!;
    if (layers.includes(layer)) assert.equal(part.pack, "cosmic", layer);
    else assert.equal(worn.parts[layer], base.parts[layer], `${layer} stays`);
  }
  assert.equal(worn.character, undefined, "the pieces show, not a character");
  assert.deepEqual(worn.colors, base.colors);
  assert.deepEqual(lockedParts(worn, catalog, ownedPacks(catalog, { version: 1, packs: ["cosmic"] })), []);
});

// ---- characters: a downloaded PNGtuber as a look -----------------------------------

test("a look may wear a character; it survives normalizing and counts as a change", () => {
  const look = defaultLook("main", catalog);
  const dressed = wearCharacter(look, "pirate-radio-dj-female");
  assert.equal(normalizeLook(dressed, "main", catalog).character, "pirate-radio-dj-female");
  assert.ok(!lookEquals(look, dressed), "putting a character on is a change to save");
  assert.ok(lookEquals(wearCharacter(dressed, null), look), "taking it off is the parts again");
  assert.equal(normalizeLook({ ...look, character: "../etc" }, "main", catalog).character, undefined);
  assert.equal(normalizeLook({ ...look, character: 7 }, "main", catalog).character, undefined);
  assert.deepEqual(Object.keys(normalizeLook(look, "main", catalog)), ["version", "parts", "colors"], "no character: no key");
});

test("the dashboard and the Runtime agree on what a character id is", () => {
  assert.equal(String(CHARACTER_ID), String(CHARACTER_ID_FILES));
  const here = new URL(".", import.meta.url);
  const rs = [
    new URL("../../../crates/caelza-gateway/src/api_looks.rs", here),
    new URL("../../../../../runtime/overlay/crates/caelza-gateway/src/api_looks.rs", here),
  ].find((u) => existsSync(u));
  if (!rs) return; // the staged web tree alone: the repo's test_looks.py checks the Rust side
  const src = readFileSync(rs, "utf8");
  assert.match(src, /id\.len\(\) <= 48/);
  assert.match(src, /pub const MAX_FRAME_BYTES: usize = 60 \* 1024;/);
  assert.equal(MAX_FRAME_BYTES, 60 * 1024);
});

test("a PNGtuber's frames are found by name: our store's, and the usual idle/talking/blink", () => {
  const ours = ["01_closed.png", "02_open.png", "03_closed_blink.png", "04_open_blink.png", "05_smile.png", "coverphoto.png"];
  assert.deepEqual(pickFrames(ours), { closed: "01_closed.png", open: "02_open.png", blink: "03_closed_blink.png" });
  assert.deepEqual(
    pickFrames(["Pack/idle.png", "Pack/talking.png", "Pack/blink.png", "Pack/angry.png"]),
    { closed: "Pack/idle.png", open: "Pack/talking.png", blink: "Pack/blink.png" },
  );
  assert.deepEqual(pickFrames(["Mouth Closed.png", "Mouth Open.png"]), { closed: "Mouth Closed.png", open: "Mouth Open.png" });
  assert.deepEqual(pickFrames(["b.png", "a.png"]), { closed: "a.png" }, "no names to go by: the first file is the face");
  assert.deepEqual(pickFrames([]), {});
});

test("a character is named from its file, without the word PNGTuber", () => {
  assert.equal(characterName("Pirate Radio DJ Female - PNGTuber.zip"), "Pirate Radio DJ Female");
  assert.equal(characterName("C:\\Users\\h\\Downloads\\neko_cafe_pngtuber_male.zip"), "neko cafe male");
  assert.equal(characterName("01_closed.png"), "01 closed");
  assert.equal(characterName(".zip"), "Character");
});

test("a character's id is its name in lowercase words, made unique", () => {
  assert.equal(characterId("Pirate Radio DJ Female", []), "pirate-radio-dj-female");
  assert.equal(characterId("Pirate Radio DJ Female", ["pirate-radio-dj-female"]), "pirate-radio-dj-female-2");
  assert.equal(characterId("Café ✨", []), "cafe");
  assert.equal(characterId("!!!", []), "character");
  assert.match(characterId("x".repeat(80), []), CHARACTER_ID);
});

test("a frame is fitted under the body limit by whole steps, starting no taller than 704", () => {
  const ours = fitSizes(640, 704);
  assert.deepEqual(ours[0], { width: 640, height: 704 });
  assert.deepEqual(ours[1], { width: 320, height: 352 });
  assert.ok(ours.every((s) => Math.abs(s.width / s.height - 640 / 704) < 0.02), "the ratio holds");
  assert.deepEqual(fitSizes(2000, 2200)[0], { width: 640, height: 704 });
  const smallest = fitSizes(2000, 2200);
  assert.ok(smallest[smallest.length - 1]!.height >= 88);
  assert.deepEqual(fitSizes(40, 44), [{ width: 40, height: 44 }], "a small frame is sent as it is");
});

test("the frame drawn falls back to the closed one; the URL is the Runtime's", () => {
  assert.equal(frameToDraw({ frames: ["closed"] }, "open"), "closed");
  assert.equal(frameToDraw({ frames: ["closed", "open", "blink"] }, "blink"), "blink");
  assert.equal(frameToDraw(null, "open"), "closed");
  assert.equal(frameUrl("pirate-dj", "open"), "/api/looks/characters/pirate-dj/open");
});

// A zip as a store's would be: one stored PNG, one deflated, a folder, macOS shadows.
async function zipOf(entries: Array<{ name: string; data: Uint8Array; deflate?: boolean }>): Promise<Uint8Array> {
  const enc = new TextEncoder();
  const locals: Uint8Array[] = [];
  const centrals: Uint8Array[] = [];
  let offset = 0;
  for (const e of entries) {
    const name = enc.encode(e.name);
    const body = e.deflate
      ? new Uint8Array(await new Response(new Blob([e.data]).stream().pipeThrough(new CompressionStream("deflate-raw"))).arrayBuffer())
      : e.data;
    const local = new Uint8Array(30 + name.length + body.length);
    const lv = new DataView(local.buffer);
    lv.setUint32(0, 0x04034b50, true);
    lv.setUint16(8, e.deflate ? 8 : 0, true);
    lv.setUint32(18, body.length, true);
    lv.setUint32(22, e.data.length, true);
    lv.setUint16(26, name.length, true);
    local.set(name, 30);
    local.set(body, 30 + name.length);
    const central = new Uint8Array(46 + name.length);
    const cv = new DataView(central.buffer);
    cv.setUint32(0, 0x02014b50, true);
    cv.setUint16(10, e.deflate ? 8 : 0, true);
    cv.setUint32(20, body.length, true);
    cv.setUint32(24, e.data.length, true);
    cv.setUint16(28, name.length, true);
    cv.setUint32(42, offset, true);
    central.set(name, 46);
    locals.push(local);
    centrals.push(central);
    offset += local.length;
  }
  const cdSize = centrals.reduce((n, c) => n + c.length, 0);
  const end = new Uint8Array(22);
  const ev = new DataView(end.buffer);
  ev.setUint32(0, 0x06054b50, true);
  ev.setUint16(8, entries.length, true);
  ev.setUint16(10, entries.length, true);
  ev.setUint32(12, cdSize, true);
  ev.setUint32(16, offset, true);
  const all = [...locals, ...centrals, end];
  const out = new Uint8Array(all.reduce((n, a) => n + a.length, 0));
  let at = 0;
  for (const a of all) {
    out.set(a, at);
    at += a.length;
  }
  return out;
}

test("the PNGs come out of a zip, stored or deflated, folders and macOS shadows left out", async () => {
  const closed = new Uint8Array(500).map((_, i) => i % 7);
  const open = new Uint8Array([137, 80, 78, 71, 1, 2, 3]);
  const zip = await zipOf([
    { name: "Pirate DJ/", data: new Uint8Array() },
    { name: "Pirate DJ/01_closed.png", data: closed, deflate: true },
    { name: "Pirate DJ/02_open.png", data: open },
    { name: "Pirate DJ/listing.txt", data: new TextEncoder().encode("hi") },
    { name: "__MACOSX/Pirate DJ/._01_closed.png", data: open },
    { name: "Pirate DJ/.hidden.png", data: open },
  ]);
  const files = await pngsInZip(zip);
  assert.deepEqual(files.map((f) => f.name), ["Pirate DJ/01_closed.png", "Pirate DJ/02_open.png"]);
  assert.deepEqual([...files[0]!.data], [...closed], "deflate inflates back");
  assert.deepEqual([...files[1]!.data], [...open]);
  await assert.rejects(pngsInZip(new Uint8Array([1, 2, 3])), /not a zip/);
});
