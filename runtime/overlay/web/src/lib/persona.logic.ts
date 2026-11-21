// The owner's one yes (vision M10 §10, slice P2): `[persona] free` lets the
// agent use its `look` and `identity` tools without asking, so it dresses
// itself and shapes its own IDENTITY.md and SOUL.md. The Runtime's tools read
// the switch from the config file at each call; the dashboard writes it here.
// Pure, so the test runner can import it without React or the API client.
import type { PatchOp } from "@/lib/api";

/** The tools the yes lets through: they refuse on their own while the switch is off. */
export const PERSONA_TOOLS = ["look", "identity"] as const;

/**
 * The config patch for the switch. A tool call runs with no one to answer a
 * prompt when the agent acts on its own, so turning it on also lets the two
 * tools through the agent's risk profile when the profile and its list are
 * known (the same shape as the town's wake). Off never touches the profile:
 * the tools refuse by themselves.
 */
export function freeOps(on: boolean, profile?: string | null, autoApprove?: readonly string[] | null): PatchOp[] {
  const ops: PatchOp[] = [{ op: "add", path: "/persona/free", value: on }];
  if (on && profile) {
    const current = autoApprove ?? [];
    const missing = PERSONA_TOOLS.filter((t) => !current.includes(t));
    if (missing.length) ops.push({ op: "add", path: `/risk_profiles/${profile}/auto_approve`, value: [...current, ...missing] });
  }
  return ops;
}
