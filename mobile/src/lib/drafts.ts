import AsyncStorage from "@react-native-async-storage/async-storage";
import NetInfo from "@react-native-community/netinfo";
import { File, Paths } from "expo-file-system";
import { api, ApiError, type NewReport } from "./api";

/**
 * Offline drafts: a report made without signal is stored on the phone
 * and sent automatically when the connection comes back.
 */
const KEY = "mendmap.drafts";
export type Draft = NewReport & { localId: string; savedAt: string; categoryName: string };

type Listener = (drafts: Draft[]) => void;
const listeners = new Set<Listener>();
let syncing = false;

export async function getDrafts(): Promise<Draft[]> {
  return JSON.parse((await AsyncStorage.getItem(KEY)) || "[]");
}
async function save(drafts: Draft[]) {
  await AsyncStorage.setItem(KEY, JSON.stringify(drafts));
  listeners.forEach((l) => l(drafts));
}
export function subscribeDrafts(l: Listener) {
  listeners.add(l);
  getDrafts().then(l);
  return () => void listeners.delete(l);
}

/** The picker's temporary file can be cleaned up by the OS, so copy it somewhere permanent. */
function persistFile(uri: string | null | undefined, name: string): string | null {
  if (!uri) return null;
  try {
    const src = new File(uri);
    const dest = new File(Paths.document, name);
    src.copy(dest);
    return dest.uri;
  } catch {
    return uri;
  }
}

export async function addDraft(report: NewReport, categoryName: string) {
  const localId = `${Date.now()}`;
  const draft: Draft = {
    ...report,
    photoUri: persistFile(report.photoUri, `draft-${localId}.jpg`),
    voiceUri: persistFile(report.voiceUri, `draft-${localId}.m4a`),
    localId,
    savedAt: new Date().toISOString(),
    categoryName,
  };
  await save([...(await getDrafts()), draft]);
}

export async function removeDraft(localId: string) {
  await save((await getDrafts()).filter((d) => d.localId !== localId));
}

/** Sends every draft; returns how many were sent. Stops at the first network error. */
export async function syncDrafts(): Promise<number> {
  if (syncing) return 0;
  syncing = true;
  let sent = 0;
  try {
    for (const d of await getDrafts()) {
      try {
        await api.createReport(d);
      } catch (e) {
        if (e instanceof ApiError && e.status === 0) break; // still offline
        if (e instanceof ApiError && e.status === 401) break; // signed out, keep drafts
        if (e instanceof ApiError && e.status >= 500) break; // server down, keep drafts
        // Any other error (bad data) — drop it so it doesn't block the queue.
      }
      await removeDraft(d.localId);
      sent++;
    }
  } finally {
    syncing = false;
  }
  return sent;
}

export function startDraftSync(onSent?: (n: number) => void) {
  return NetInfo.addEventListener((s) => {
    if (s.isConnected && s.isInternetReachable !== false) {
      syncDrafts().then((n) => n > 0 && onSent?.(n));
    }
  });
}
