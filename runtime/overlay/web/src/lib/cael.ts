// Cael, the guide, made by the dashboard's Setup on a PC (the app makes him on
// a phone, scripts/model-setup.sh on a hub): the agent, his profile with the one
// tool, and his files through the personality API. His soul is
// guide/cael.system.md, copied beside the guide by runtime/build.sh and read
// here as text.
import caelSoul from "@/guide/cael.system.md?raw";

import { createMapKey, patchConfig, putProp } from "./api";
import { CAEL_AGENTS, CAEL_IDENTITY, CAEL_USER, GUIDE, GUIDE_PROFILE, guideProfileOps } from "./cael.logic";
import { putPersonality } from "./identity";

/**
 * Make Cael on the same model as the owner's agent. The profile first, so the
 * agent's reference to it is never dangling; the files last, over the
 * templates the Runtime seeds when an agent is created.
 */
export async function createCael(provider: string): Promise<void> {
  await createMapKey("risk_profiles", GUIDE_PROFILE).catch(() => undefined);
  await patchConfig(guideProfileOps());
  await createMapKey("agents", GUIDE).catch(() => undefined);
  await putProp(`agents.${GUIDE}.model_provider`, provider);
  await putProp(`agents.${GUIDE}.risk_profile`, GUIDE_PROFILE);
  await putPersonality(GUIDE, "SOUL.md", caelSoul);
  await putPersonality(GUIDE, "IDENTITY.md", CAEL_IDENTITY);
  await putPersonality(GUIDE, "USER.md", CAEL_USER);
  await putPersonality(GUIDE, "AGENTS.md", CAEL_AGENTS);
}
