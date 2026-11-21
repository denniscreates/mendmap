import AsyncStorage from "@react-native-async-storage/async-storage";
import NetInfo from "@react-native-community/netinfo";
import { File, Paths } from "expo-file-system";
import { api, ApiError, type Job } from "./api";

/**
 * Crew mode works offline: the job list is cached, and a job marked fixed without
 * signal is queued with its after photo and sent when the connection comes back.
 */
const JOBS_KEY = "mendmap.crew.jobs";
const QUEUE_KEY = "mendmap.crew.queue";

export type Done = { id: number; photoUri: string; comment?: string; at: string };
type Listener = (q: Done[]) => void;
const listeners = new Set<Listener>();
let syncing = false;

export async function cachedJobs(): Promise<Job[]> {
  return JSON.parse((await AsyncStorage.getItem(JOBS_KEY)) || "[]");
}

/** Fresh list from the server (cached); on a network error, the cached list. */
export async function loadJobs(near?: { lat: number; lng: number }): Promise<{ jobs: Job[]; offline: boolean }> {
  try {
    const jobs = await api.crewJobs(near);
    await AsyncStorage.setItem(JOBS_KEY, JSON.stringify(jobs));
    return { jobs, offline: false };
  } catch (e) {
    if (e instanceof ApiError && e.status === 0) return { jobs: await cachedJobs(), offline: true };
    throw e;
  }
}

export async function getQueue(): Promise<Done[]> {
  return JSON.parse((await AsyncStorage.getItem(QUEUE_KEY)) || "[]");
}
async function saveQueue(q: Done[]) {
  await AsyncStorage.setItem(QUEUE_KEY, JSON.stringify(q));
  listeners.forEach((l) => l(q));
}
export function subscribeQueue(l: Listener) {
  listeners.add(l);
  getQueue().then(l);
  return () => void listeners.delete(l);
}

function keep(uri: string, name: string) {
  try {
    const dest = new File(Paths.document, name);
    new File(uri).copy(dest);
    return dest.uri;
  } catch {
    return uri;
  }
}

/** Marks a job fixed now, or queues it if there's no signal. Returns "sent" or "queued". */
export async function finishJob(id: number, photoUri: string, comment?: string): Promise<"sent" | "queued"> {
  try {
    await api.crewDone(id, photoUri, comment);
    await dropFromCache(id);
    return "sent";
  } catch (e) {
    if (!(e instanceof ApiError && e.status === 0)) throw e;
    const done: Done = { id, photoUri: keep(photoUri, `after-${id}-${Date.now()}.jpg`), comment, at: new Date().toISOString() };
    await saveQueue([...(await getQueue()).filter((d) => d.id !== id), done]);
    await dropFromCache(id);
    return "queued";
  }
}

async function dropFromCache(id: number) {
  const jobs = (await cachedJobs()).filter((j) => j.id !== id);
  await AsyncStorage.setItem(JOBS_KEY, JSON.stringify(jobs));
}

export async function syncQueue(): Promise<number> {
  if (syncing) return 0;
  syncing = true;
  let sent = 0;
  try {
    for (const d of await getQueue()) {
      try {
        await api.crewDone(d.id, d.photoUri, d.comment);
      } catch (e) {
        if (e instanceof ApiError && (e.status === 0 || e.status === 401 || e.status >= 500)) break;
        // Already fixed by someone else or removed: drop it.
      }
      await saveQueue((await getQueue()).filter((x) => x.id !== d.id));
      sent++;
    }
  } finally {
    syncing = false;
  }
  return sent;
}

export function startCrewSync(onSent?: (n: number) => void) {
  return NetInfo.addEventListener((s) => {
    if (s.isConnected && s.isInternetReachable !== false) syncQueue().then((n) => n > 0 && onSent?.(n));
  });
}
