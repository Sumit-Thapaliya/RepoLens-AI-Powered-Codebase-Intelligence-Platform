/**
 * Per-tab convenience state. sessionStorage gives each tab its own id and remembered analysis list.
 * These client-side ids are not credentials: the server-issued HttpOnly session cookie and the
 * server-held tab lease authorize every analysis request. Nothing here survives closing the tab.
 */

const WINDOW_ID_KEY = "repolens.windowId";
const RUN_IDS_KEY = "repolens.windowRuns";
const CURRENT_KEY = "repolens.windowCurrent";

function storage(): Storage | null {
  if (typeof window === "undefined") return null;
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

function randomId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") return crypto.randomUUID();
  return `w-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}

/** This window's id. Created once per window and reused after reloads. */
export function getWindowId(): string {
  const store = storage();
  if (!store) return "server";
  let id = store.getItem(WINDOW_ID_KEY);
  if (!id) {
    id = randomId();
    store.setItem(WINDOW_ID_KEY, id);
  }
  return id;
}

/** Locally remembered run ids; the API rechecks each id against the authenticated tab lease. */
export function readWindowRuns(): string[] {
  const store = storage();
  if (!store) return [];
  try {
    const parsed = JSON.parse(store.getItem(RUN_IDS_KEY) ?? "[]");
    return Array.isArray(parsed) ? parsed.filter((item): item is string => typeof item === "string") : [];
  } catch {
    return [];
  }
}

export function writeWindowRuns(ids: string[]): void {
  storage()?.setItem(RUN_IDS_KEY, JSON.stringify(Array.from(new Set(ids))));
}

/** The analysis this window is currently showing. */
export function readCurrentRun(): string | null {
  return storage()?.getItem(CURRENT_KEY) ?? null;
}

export function writeCurrentRun(id: string | null): void {
  const store = storage();
  if (!store) return;
  if (id) store.setItem(CURRENT_KEY, id);
  else store.removeItem(CURRENT_KEY);
}
