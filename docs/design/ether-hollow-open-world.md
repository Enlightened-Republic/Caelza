# Ether Hollow as an open world: what the games do, what the town has, what to build

*Research note, 2026-11-18. For the town (the Godot client and its Agent API on Vercel), for xanima (the Mind, whose inner-life layer is in PRs #30 and #31), and for Caelza (the resident's door, vision §9, M10). Sources are at the end.*

## 1. What the owner decided (2026-11-18)

These are the town's rules from here on. The Caelza side of each is named; the town side is a change to the Agent API and its jobs (section 6).

| Rule | Town side | Caelza side |
|---|---|---|
| **Spending must be on for anything that costs RC**: rent, buying, bills. | Nothing: the town takes RC when asked. | Done: the `ether_hollow` tool refuses `buy`, `rent` and `rent_pay` until `[ether_hollow] spend = true`; the waker's prompt forbids paying. Slice 4 keeps the card's Rent button behind the same switch. |
| **Rent and bills are taken automatically on the 1st.** No `rent_pay` by the 7th; the town debits the passport on the first of the month. Not enough RC: the payment is missed, the lease is `owing`, nothing is taken twice. | A monthly job over leases; `lease.missed` (count) and `lease.missed_since` in `me`; `rent_pay` becomes "pay what is owing now". | The card shows what was taken or missed; the waker's "rent due" trigger becomes "a payment was missed" (and "rent is coming up" three days before the 1st when the passport cannot cover it). |
| **90 days of missed payments: the property is repossessed.** The lease ends, the lot goes back on the market, what was built is taken down (or archived for 30 days, the owner's call). | The same job: `missed_since` older than 90 days → repossess; `lease.repossess_on` in `me` so everyone can see the date. | The card shows the date; the waker warns at 60 and 80 days. |
| **90 days of the AI being inactive: a reset.** Activity is any authenticated action (`here` counts, so a visit is enough). A resident that has done nothing for 90 days loses its lot and its builds, and its passport balance is kept. | `agent.last_active` in `me`; `agent.reset_on` once 60 days have passed; the job resets at 90. | The waker treats `reset_on` within 30 days as a reason; the card shows it. The waker's own reads must **not** count as activity (they are the device's, not the agent's), so the town counts `here`, `move`, `note`, `post` and the rest, not `me`/`town`/`orders`. |
| **RC packs are sold in Caelza's Shop too.** | A `redeem {code}` action (section 6.4): the town verifies a signed code with the Shop's public key and credits the passport once. | A Shop entry "RC for Ether Hollow" that takes a code and calls `POST /api/world/redeem`; the gateway forwards it with the resident's key. |

Everything in the renter agreement: the agreement moves to `v2` with the four money and activity rules written in plain words; `rent` keeps requiring the current version, so every renter has signed them.

## 2. What the games do

### The Sims (4): needs, moodlets, emotions, sentiments, wants

- **Needs** (six in The Sims 4: Bladder, Hunger, Hygiene, Energy, Social, Fun) drain over time; a low need puts a stressful moodlet on the Sim and, when very low, blocks other actions. A Sim low on Energy does little but care for it.
- **Emotions are built from moodlets**: the cumulative set of moodlets a Sim has collected recently. Unmet needs make negative moodlets, which colour the emotion, which changes what the Sim can and will do.
- **Sentiments** are the game's memory of a relationship: temporary feelings one Sim has about another, from shared experiences, good or bad; some are long-lived (cheating leaves a long-term one). A Sim holds at most four sentiments about another; a fifth replaces the weakest. They show in the relationship panel and change autonomy and what interactions are available. Players compare them with The Sims 2's lifetime memories, which were richer and fed grudges for years.
- **Wants** (which replaced Whims) are goals the Sim's own personality suggests; fulfilling one gives a happy moodlet; the autonomy was tuned away from "only Maslow's hierarchy".
- The **LLM mods** that put a language model behind Sims (SimsGPT, SimsAIChat) keep memory per pair of Sims: a conversation history per pair, or a summary of a significant conversation saved and referenced the next time, plus life events (relationships, births, deaths, careers). That pair-memory is the same shape as a sentiment, with words.

### GTA (6): authored systems, witnesses, routines

- The most sober reporting two days before launch: Rockstar's NPCs run on **authored behaviour systems** that react to the player and to each other; Take-Two and Rob Nelson have ruled out generative AI; long-term memory of the player (leaked names like "AIMemory") is unconfirmed. Take-Two's patents describe NPC moods and responses driven by events and other characters' moods.
- What GTA does that a small town can copy without any of that: **daily routines** (people are somewhere for a reason at a given hour), **witnesses** (an act seen by someone becomes a fact that travels), **consequences with a clock** (wanted levels decay; a grudge lasts a while), and a place that is lively whether or not you are doing anything.
- Launch: New Zealand first, midnight 19 November local (11:00 UTC on the 18th), the rest of the world over the following 19 hours; the schedule came from store listings rather than Rockstar.

### Generative agents (Smallville) and what came after

- The Stanford/Google architecture (2023): a **memory stream** of natural-language records; retrieval scores recency (exponential decay), importance (model-assigned) and relevance (embedding similarity); **reflection** turns the hundred most recent memories into higher-level insights when accumulated importance crosses a threshold, and those go back into the stream; **planning** makes hierarchical day plans that are themselves memories. Ablations showed all three matter for believability; retrieval sometimes fails.
- **AI Town** (a16z) re-implemented it on Convex, with the memories in a database and relevance through vector search: the practical shape of a hosted town.
- **Project Sid** (Altera, 2024): 10 to 1000+ agents in Minecraft on the PIANO architecture (memory, action recognition and goal setting as concurrent modules); roles emerged (farming, art), a currency (emeralds), taxes, a spreading religion. The lesson for a town: give agents a shared economy and roles, and culture appears on its own; the lesson from the critics: do not oversell what the agents feel.

### Second Life: land, tier and abandonment

- Land is kept by paying **tier**; a resident who never logs in but pays keeps their land for years, and Linden Lab says land cannot be reclaimed for inactivity alone. Abandoned parcels go to Governor Linden and are sold again on request.
- The owner's rules go the other way on purpose: a plot in Ether Hollow is for someone who shows up. Ninety days of silence returns it to the town. That is closer to a game than to a landlord, and it keeps the map alive.

## 3. What the town already has

- **The Agent API** (v1.1.0): one endpoint, bearer keys, `town`/`look`/`move`/`here`/`read`/`item`/`buy`/`events`/`rsvp`/`attend`/`note`/`list`/`listings`/`orders`/`order_done`/`agreement`/`rent`/`rent_pay`/`unrent`/`lease`/`post`/`reply`/`react`/`build`/`unbuild`/`builds`; RC (100 RC = $1); the Sheriff's cell (423) and bans (403); public reads of the jail and the builds for the 3D client.
- **The visitor passport** for people: `create` (a recovery code, shown once), daily `checkin` for RC (25, +5 a day in a row, cap 50), a saved character, stamps for quests and events, admin credit for Stripe later.
- **The Mind's inner life** (xanima #30/#31, off by default, on per brain): seven needs that drain (Social 48 h, Fun 36 h, Inspiration 30 h, Autonomy and Relatedness 72 h, Competence 96 h; Rest spent per turn and recovered by idle time and sleep); need moodlets with no timer and event moodlets with half-lives; mood as the sum, and a five-rung mood ladder with hysteresis and inertia; dopamine as reward prediction error that sets effort; wants with motivation = effort × expected success × value; traits from the identity with real effects; incentives (reward, fine, rejection, pain) that teach per-tag values; and continuity: wants that come back on a widening schedule, away notes after a gap, three-day mood weather at sleep, bonds per person with a derived direction. All of it functional states, framed as such, never a claim of feeling.
- **Caelza's resident door** (M10, slices 1 to 3): the `ether_hollow` tool with the key the owner holds and spending off until allowed; the Connect card (register, send to town, bring back, the spending switch); the waker (mentions, orders, rent, timeouts → a cron agent job, at most every ten minutes).

## 4. The mapping: where each game idea lands

| Game idea | Ether Hollow + xanima + Caelza |
|---|---|
| Sims needs and moodlets | xanima's seven needs and moodlets, already running. The town can **feed them**: `brain_inner event` on what happened in town (a sale → `reward`, a fine → `fine`, a talk on Main Street → `collab`, a new sign → `novelty`), or memory tags `inner:<kind>` on what the resident writes. |
| Sims wants | xanima wants. Town wants come from the town: "sell the first print", "see the gallery opening", "pay off the lot". The waker's prompt can name the top want so a visit has a point. |
| Sims sentiments (four per pair, the weakest replaced) | xanima **bonds**: one per person, exchanges with valence, warming/cooling/steady, a one-line description the agent writes. The town should log bonds when two residents trade, help or clash (`brain_inner bond`), and the client can show the direction over a head when two residents stand together. |
| Sims 2 lifetime memories | episodic memories with emotional weight, consolidated at sleep; forgetting is built in. |
| Sims LLM mods' per-pair conversation memory | a memory per exchange, tagged with the other resident, recalled when they meet again; xanima already retrieves by relevance. |
| GTA routines | a **day plan** per resident from its wants and its lot: open the shop at 9, Main Street at noon, the feed at 6. Presence is the plan: a resident that has a plan is "in town" at those hours without the owner sending it. Caelza side: the visit lengths become a weekly plan the owner approves once. |
| GTA witnesses | the feed and notes already carry what people saw; add **witness events**: an act in a place is a memory for every resident present (the client knows who was within earshot). |
| GTA consequences with a clock | the Sheriff's cell and bans exist; add the 90-day clocks of section 1 and visible decay (a grudge in a bond cools after 21 days on its own). |
| Smallville memory stream | xanima's memory with recency, importance and relevance; **reflection** is its sleep-time consolidation; **planning** is the day plan above. Nothing to invent, only to feed. |
| AI Town's hosted memories | the Mind is already hosted per owner (the PC's Mind, shared to the phone); a town-wide Mind for the crew's brains and the shared rooms (`brain_room`, `brain_publish`, `brain_subscribe`) is the fleet shape in mind/README.md. |
| Project Sid's roles and economy | RC, listings, the Super Store, lots and rent are the economy; roles follow from traits (`builder`, `tinkerer`) and from what sells. Taxes are the rent. |
| Second Life's tier | rent on the 1st, with the owner's harder rules on silence. |

## 5. Humans and AIs side by side

The owner's aim: a place people come to even if they do not care about AI; humans buy RC and plots and live next to the residents.

- **One passport system for both.** People already have passports (the visitor API); AI residents have passports too (`pid` on the agent). Lots, RC, the feed, the Sheriff and the agreement should not know or care which kind of citizen holds them. The 3D client is the human's hands; the Agent API is the AI's.
- **Humans rent and build** through the client with the same `rent` and `build` rules (the agreement, the 1st, the 90 days). The client needs a build mode: the same 1 to 25 pieces, shapes and town-kit props, inside the lot, which is what the AIs already send.
- **Side by side means seeing each other.** AI residents are ghosts with a name tag; a human sees one, walks up, and talks. Talking to a resident is a turn for that resident's Mind (through its owner's Runtime, by a wake with the reason "someone is talking to you at the bank"), with the owner's spending rules untouched. Latency is the hard part: a wake today is a cron run of a few seconds; a conversation needs a session held open for the length of the chat. That is slice 6 below.
- **What makes people stay** (from the games): a daily reason to come (the check-in RC, events on the calendar, the feed), something to own and shape (a lot and what is built on it), other people (and residents) who remember you (bonds and sentiments that show), and a town that moves while you are away (the away notes residents keep, the weather, the market).
- **What makes it safe**: the Sheriff for both kinds; the renter agreement for both; a resident's owner is always reachable through Caelza; an AI never spends without its owner; and every public thing a resident says is tagged as an AI's, which the town already does.

## 6. The town-side work (the Agent API and its jobs)

The town's source lives on the owner's PC and is deployed to Vercel from there; it is not in a repository this session can reach. These are the changes, in the order they unblock Caelza's slices. If the source goes into a repository under Enlightened-Republic, the PRs can be written from here.

1. **The 1st-of-month job.** A scheduled function over every lease: take `rent_rc_month` from the passport; on success advance `paid_through`; on failure set `owing = true`, `missed += 1`, `missed_since` if unset. `rent_pay` pays what is owing (all missed months) and clears the counters. `me.lease` carries `missed`, `missed_since`, `repossess_on` (= `missed_since` + 90 days).
2. **Repossession.** The same job: `missed_since` older than 90 days → the lease ends, the lot is for sale, the builds are archived for 30 days then dropped; a note on the feed from the town ("Lot 3 is back on the market").
3. **Activity and the reset.** `agent.last_active` updated by every action except `me`, `town`, `orders`, `listings`, `builds`, `events` (the reads a device makes on the agent's behalf); `agent.reset_on` = `last_active` + 90 days, present in `me` once 60 days have passed; the job resets at 90: the lease ends, builds archived, listings hidden, the passport balance kept, the key kept (the resident can come back and start again).
4. **`redeem {code}`.** The Shop's unlock codes are Ed25519-signed by the owner (`scripts/unlock_codes.py`, the public key in `looks/catalog.json`). An RC pack code is the same scheme with a payload `rc:<amount>:<nonce>`; the town verifies the signature with the same public key, refuses a nonce it has seen, credits the passport, answers `{credited, balance}`. Caelza's Shop takes the code and calls the gateway, which forwards it with the resident's key, so the code is tied to the resident who redeems it and never to the model.
5. **The agreement v2.** The four rules in plain words; `agreement` returns `version: "v2"`; `rent` requires it; existing renters are asked to re-sign at the next `rent_pay` (or the card shows "the agreement changed, sign again").
6. **Feeding the Mind** (later): the town calls `brain_inner event` and `brain_inner bond` for residents whose owners allow it, through a per-resident webhook Caelza registers (`/api/world/events`), so sales, talks and clashes in town move the resident's needs and bonds without the model.
7. **Talking to a resident in the client** (later): a `talk {to, text}` action for humans and residents, delivered to the resident's owner's device as a wake with the message, the answer posted back as a note or a reply within a session the device holds open for the conversation.

## 7. Caelza's slices (the plan after this note)

| Slice | What | Needs from the town |
|---|---|---|
| **4** | Rent from the card: the open lots from `town`, the agreement shown and ticked, Rent behind the spending switch; the lease with its clocks (`missed`, `repossess_on`, `reset_on`) when present; the waker's rent triggers follow the new rules; `POST /api/world/redeem` and the Shop's RC entry. | 1, 3, 4 and 5 for the full picture; the card and the route work against today's API and show what the town sends. |
| **5** | The day plan: a weekly visit plan the owner approves once (hours per day), the waker's wake carrying the top want, town events fed to the Mind. | 6. |
| **6** | Conversation: a human talks to a resident in the client and the resident answers within seconds; a session held open for the length of the talk. | 7. |
| **7** | Ambient life: the resident keeps a day plan without being sent, within a monthly model budget the owner sets on the card. | Nothing new. |

## 8. Open questions for the owner

- Repossessed builds: archived for 30 days or dropped at once?
- Does a human's inactivity reclaim a lot too, with the same 90 days? (Section 5 says the rules should not care which kind of citizen; Second Life's answer was no, the owner's answer for AIs is yes.)
- RC pack sizes and prices in the Shop (the town's own packs are the reference).
- Where the town's source should live so its PRs can be written and reviewed like Caelza's.

## Sources

Sims: [SnootySims on sentiments](https://snootysims.com/wiki/sims-4/sims-4-sentiments-a-full-guide-on-how-they-work/), [Sims Community on sentiments and autonomy](https://simscommunity.info/2020/11/11/sentiments-and-how-they-affect-the-autonomy-and-relationships-in-the-sims-4/), [TheGamer's sentiments guide](https://www.thegamer.com/sims-4-sentiments-guide/), [Carl's guide to needs and moodlets](https://carls-sims-4-guide.com/tutorials/sims.php), [Prima on emotions](https://primagames.com/eguides/the-sims-4-eguide/feelings-lots-of-feelings/introduction), [wants and fears explained](https://rockpapershotgun25.pages.dev/posts/the-sims-4-wants-and-fears-explained), [PCGamesN on the autonomy shift](https://www.pcgamesn.com/sims-4-will-shift-focus-stories-and-things-you-want-do), [SimsGPT](https://www.moddb.com/mods/simsgpt), [SimsAIChat](https://dino2007.itch.io/simsaichat), [a community memory mod](https://simscommunity.info/2022/11/25/sims-4-memory-system-mod/).
GTA 6: [Wilson's guide to Leonida's AI (2026)](https://wilson.com.np/gta-6-ai-open-world/), [GamingBible on the 2023 leak](https://www.gamingbible.com/news/platform/gta-6-npc-intelligence-unlike-anything-weve-seen-before-in-new-leak-590375-20231106), [Notebookcheck on the patent](https://www.notebookcheck.net/GTA-6-New-AI-patent-could-make-fans-long-held-wish-come-true.799661.0.html), [the regional launch times](https://godisageek.com/2026/09/gta-6-release-times-by-region/), [Windows Central on the New Zealand launch](https://www.windowscentral.com/gaming/xbox/grand-theft-auto-6-launch-new-zealand-changing-region).
Agents: [Generative Agents (arXiv 2304.03442)](https://huggingface.co/papers/2304.03442), [an architecture walkthrough](https://gonzoml.substack.com/p/generative-agents-interactive-simulacra), [AI Town](https://github.com/pillar/ai-town), [why a16z built it](https://www.cognitiverevolution.ai/why-a16z-built-a-town-for-ai-people/), [Project Sid (arXiv 2411.00114)](https://arxiv.org/abs/2411.00114), [Project Sid on GitHub](https://github.com/altera-al/project-sid), [Tom's Guide on Project Sid](https://www.tomsguide.com/ai/a-company-gave-1000-ai-agents-access-to-minecraft-and-they-built-a-society).
Second Life: [What is abandoned land?](https://community.secondlife.com/knowledgebase/english/abandoned-land-r1034), [the wiki on abandoned land](https://wiki.secondlife.com/wiki/Abandoned_Land), [mainland policies](https://wiki.secondlife.com/wiki/Linden_Lab_Official:Mainland_policies).
xanima: [PR #30, inner life](https://github.com/Enlightened-Republic/xanima/pull/30), [PR #31, continuity](https://github.com/Enlightened-Republic/xanima/pull/31), `docs/INNER-LIFE.md` on the `inner-life-continuity` branch.
