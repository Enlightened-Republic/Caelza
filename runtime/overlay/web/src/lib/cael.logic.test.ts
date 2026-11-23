import assert from "node:assert/strict";
import test from "node:test";

import { CAEL_AGENTS, CAEL_IDENTITY, CAEL_USER, GUIDE, GUIDE_PROFILE, SHAPE_TOOL, guideProfileOps } from "./cael.logic.ts";
import { parseName } from "./identity.logic.ts";

test("Cael's files: his card names him, his USER.md never says User, his AGENTS.md names his one tool", () => {
  assert.equal(GUIDE, "cael");
  assert.equal(parseName(CAEL_IDENTITY), "Cael");
  assert.ok(CAEL_IDENTITY.includes("he/him") && CAEL_IDENTITY.includes("gives the owner's agent who it is"));
  assert.ok(CAEL_USER.includes("I don't know my owner's name yet") && CAEL_USER.includes('never "User"'));
  assert.equal(CAEL_USER.includes("**Name:** User"), false);
  assert.ok(CAEL_AGENTS.includes(`I run one tool, \`${SHAPE_TOOL}\``));
});

test("guideProfileOps: supervised, the one tool allowed and auto-approved, deny_all_tools off", () => {
  assert.deepEqual(guideProfileOps(), [
    { op: "add", path: `/risk_profiles/${GUIDE_PROFILE}/level`, value: "supervised" },
    { op: "add", path: `/risk_profiles/${GUIDE_PROFILE}/deny_all_tools`, value: false },
    { op: "add", path: `/risk_profiles/${GUIDE_PROFILE}/allowed_tools`, value: ["shape_agent"] },
    { op: "add", path: `/risk_profiles/${GUIDE_PROFILE}/auto_approve`, value: ["shape_agent"] },
  ]);
  assert.equal(GUIDE_PROFILE, "guide");
});
