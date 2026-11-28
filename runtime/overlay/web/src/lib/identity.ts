// The agent's identity file through the gateway's personality API
// (`GET/PUT /api/personality/IDENTITY.md?agent=<alias>`, upstream's; the
// Runtime reads the same file into every prompt). The name is one line of it.
import { apiFetch } from "./api";
import { IDENTITY_FILE, USER_FILE, displayName, withName } from "./identity.logic";

export interface PersonalityFile {
  filename: string;
  content: string | null;
  exists: boolean;
}

function path(alias: string): string {
  return `/api/personality/${IDENTITY_FILE}?agent=${encodeURIComponent(alias)}`;
}

function filePath(alias: string, file: string): string {
  return `/api/personality/${encodeURIComponent(file)}?agent=${encodeURIComponent(alias)}`;
}

export function getIdentity(alias: string): Promise<PersonalityFile> {
  return apiFetch<PersonalityFile>(path(alias));
}

/** One of the agent's personality files (IDENTITY.md, SOUL.md, USER.md...). */
export function getPersonality(alias: string, file: string): Promise<PersonalityFile> {
  return apiFetch<PersonalityFile>(filePath(alias, file));
}

/** Replace one of the agent's personality files whole (the Runtime reads them into every prompt). */
export function putPersonality(alias: string, file: string, content: string): Promise<unknown> {
  return apiFetch(filePath(alias, file), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
  });
}

export function putIdentity(alias: string, content: string): Promise<unknown> {
  return putPersonality(alias, IDENTITY_FILE, content);
}

/** The agent's USER.md: who it is helping (a fresh one says it does not know yet and will ask). */
export function setUserFile(alias: string, content: string): Promise<unknown> {
  return putPersonality(alias, USER_FILE, content);
}

/** The agent's name from its identity file; the alias when the file cannot be read. */
export async function fetchAgentName(alias: string): Promise<string> {
  try {
    const f = await getIdentity(alias);
    return displayName(f.content, alias);
  } catch {
    return displayName(null, alias);
  }
}

/** Set the Name line (the rest of the file, the agent's own words, stays). */
export async function setAgentName(alias: string, name: string): Promise<void> {
  const current = await getIdentity(alias).catch(() => null);
  await putIdentity(alias, withName(current?.content, name));
}
