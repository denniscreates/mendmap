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
    morePhotos: report.morePhotos?.map((u, i) => persistFile(u, `draft-${localId}-${i + 2}.jpg`) ?? u),
    voiceUri: persistFile(report.voiceUri, `draft-${localId}.m4a`),
    localId,
    savedAt: new Date().toISOString(),
    categoryName,
  };
  await save([...(await getDrafts()), draft]);
}

export async function removeDraft(localId: string) {
  const all = await getDrafts();
  const gone = all.find((d) => d.localId === localId);
  await save(all.filter((d) => d.localId !== localId));
  // The copies made by persistFile: delete them, or every sent draft keeps its photos on the phone.
  for (const uri of gone ? [gone.photoUri, ...(gone.morePhotos ?? []), gone.voiceUri] : []) {
    if (!uri || !uri.includes("draft-")) continue;
    try {
      const f = new File(uri);
      if (f.exists) f.delete();
    } catch {
      // already gone
    }
  }
}

/** Sends every draft; returns how many were sent. Stops at the first network error. */
export async function syncDrafts(): Promise<number> {
  if (syncing) return 0;
  syncing = true;
  let sent = 0;
  try {
    for (const d of await getDrafts()) {
      let ok = true;
      try {
        await api.createReport(d);
      } catch (e) {
        if (!(e instanceof ApiError)) break; // unknown problem: keep the drafts and try again later
        // Still offline, signed out, too many requests, or the server is down: keep the drafts.
        if (e.status === 0 || e.status === 401 || e.status === 408 || e.status === 429 || e.status >= 500) break;
        ok = false; // the server refused this one (bad data): drop it so it doesn't block the queue
      }
      await removeDraft(d.localId);
      if (ok) sent++; // only count reports that really arrived
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
