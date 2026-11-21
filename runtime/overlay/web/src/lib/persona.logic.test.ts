import assert from "node:assert/strict";
import test from "node:test";

import { PERSONA_TOOLS, freeOps } from "./persona.logic.ts";

test("freeOps: the switch alone, and the tools let through the agent's profile when it is known", () => {
  assert.deepEqual(freeOps(false), [{ op: "add", path: "/persona/free", value: false }]);
  assert.deepEqual(freeOps(true), [{ op: "add", path: "/persona/free", value: true }]);
  assert.deepEqual(freeOps(true, null, null), [{ op: "add", path: "/persona/free", value: true }]);
  assert.deepEqual(freeOps(true, "phone", ["weather"]), [
    { op: "add", path: "/persona/free", value: true },
    { op: "add", path: "/risk_profiles/phone/auto_approve", value: ["weather", "look", "identity"] },
  ]);
  // Already through: the list is left alone.
  assert.deepEqual(freeOps(true, "phone", ["look", "identity"]), [{ op: "add", path: "/persona/free", value: true }]);
  // One of the two missing: only it is added, the rest of the list kept in order.
  assert.deepEqual(freeOps(true, "desk", ["identity", "weather"])[1], {
    op: "add",
    path: "/risk_profiles/desk/auto_approve",
    value: ["identity", "weather", "look"],
  });
  // Off never touches the profile: the tools refuse on their own.
  assert.deepEqual(freeOps(false, "phone", []), [{ op: "add", path: "/persona/free", value: false }]);
  assert.deepEqual([...PERSONA_TOOLS], ["look", "identity"]);
});
