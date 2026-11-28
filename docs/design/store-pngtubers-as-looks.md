# Our store's PNGtubers as Caelza looks: proposal

Status: **proposal, waiting on decisions** (2026-11-25). The mechanism ships in
patch 0031: Looks → Characters imports any PNGtuber zip as a look that any
agent can wear. What's open is whether, and how, Caelza offers our own
store's characters without the owner downloading them first.

## What we have

- **22 PNGtuber listings** in the store pipeline, $6.99 each, all 640 × 704
  with 12 frames (`01_closed`, `02_open`, `03_closed_blink`, `04_open_blink`,
  then 8 reactions):
  - **Live on Gumroad and Whop (16):** Cottagecore Frog, Fantasy
    Spellcaster, Forest Witch, Goth Horror Host, Mad Scientist, Neko Cafe,
    Pirate Radio DJ and Synthwave DJ, each as a Female and a Male version.
  - **Not listed anywhere yet (6):** Boo Crew, Cocoa Cabin and Punk Rock
    Skeleton, Female and Male.
- Each listing's `product.json` carries the slug, name, price, the
  Gumroad/Whop ids and the frame list. A frame is about 7 KB, so the three a
  look needs come to about 21 KB per character.
- **License on every listing:** "Use as your avatar on any platform,
  monetized streams included. No resale or redistribution."

## What works today (no decision needed)

1. A buyer downloads the zip from Gumroad or Whop.
2. They open Caelza → Looks → an agent → **Characters → Import a PNGtuber**
   and pick the zip.
3. The closed, talking and blink frames are found by name. The character is
   kept on their Runtime, wearable by any of their agents, and it talks in
   the chat.

This is "use as your avatar", so it fits the license as written. I checked
the reader against real store zips (Cottagecore Frog Female and Male, Algen
Character States): the right three frames come out, already under the size
cap.

## Options for offering the store's characters inside Caelza

| | What the owner sees | Hosting | Fits the license | Cost to us |
|---|---|---|---|---|
| **A. Store shelf (recommended first)** | The Shop lists our PNGtubers with a preview and a **Get it** link to the Gumroad/Whop page. After buying, they import the zip (above). | Nothing new: previews bundled with the release (`catalog.json` + a small PNG each); links to the existing listings | Yes: the buyer gets the file the normal way | Small: a `store` section in `catalog.json`, a Shop card |
| **B. Unlock code, frames bundled** | They buy, the receipt carries a Caelza code (the Arcade pack's Ed25519 scheme), and the character appears with no download | The three frames ship inside every release (~21 KB each, ~460 KB for 22) | We'd redistribute our own art inside Caelza. That's allowed for us, but anyone could pull the PNGs out of the release, so it's the same honesty level as the Arcade pack's codes | Medium: mint codes per sale (a Gumroad/Whop webhook or a manual batch), catalog entries |
| **C. Unlock code, frames fetched** | As B, but the frames download when the code is redeemed | A public or token-gated URL on an ER site serving the frames | As B | Higher: the dashboard's CSP is `connect-src 'self'`, so the gateway must fetch on the owner's behalf (a new outbound call from the Runtime) |
| **D. A free sampler** | One or two store characters free in the Shop, the rest via A | Bundled, as B | We'd give away a $6.99 listing | Lost sales on those characters; a marketing win |

**Recommendation:** start with **A** (no hosting, no license question), plus
**D** for one character if you want a free hook. Move to **B** once we can
mint codes on sale automatically. Skip C unless the bundle gets too big.

## Decisions needed (Hailey)

1. **Which characters:** all 16 live listings, or a starter set? Should the 6
   unlisted ones (Boo Crew, Cocoa Cabin, Punk Rock Skeleton) be listed first?
2. **Free or paid in Caelza:** keep them paid (A/B), or make one or two free
   samplers (D)? Which ones?
3. **Hosting / delivery:** the existing Gumroad/Whop pages (A), frames
   bundled in releases (B), or frames on an ER site (C)? If C, which site,
   and is a Runtime-side fetch OK?
4. **License wording:** add "as your AI agent's look in Caelza" to
   LICENSE.txt so it's explicit? "Use as your avatar on any platform" already
   reads as covering it.
5. **Codes on sale (B/C only):** a Gumroad/Whop webhook that mints a Caelza
   code per purchase, or a manual batch?

Nothing here has been published to any site or store.
