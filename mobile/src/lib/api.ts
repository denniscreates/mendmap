import AsyncStorage from "@react-native-async-storage/async-storage";
import Constants from "expo-constants";
import type { Status } from "./theme";

/**
 * API base URL. Set EXPO_PUBLIC_API_URL (e.g. https://api.mendmap.app) for builds.
 * In development it goes through the Expo dev server's /api proxy (metro.config.js),
 * which forwards to FastAPI on port 8000. That works on the same Wi-Fi and through
 * `expo start --tunnel`, because the phone only has to reach the dev server.
 */
function resolveBaseUrl(): string {
  const fromEnv = process.env.EXPO_PUBLIC_API_URL;
  if (fromEnv) return fromEnv.replace(/\/$/, "");
  const devServer = Constants.expoConfig?.hostUri; // LAN "192.168.1.5:8081" or tunnel "abc.on.expo.app"
  if (!devServer) return "http://localhost:8000";
  const isTunnel = !/:\d+$/.test(devServer); // tunnel hosts have no port and use https
  return `${isTunnel ? "https" : "http"}://${devServer}/api`;
}
export const API_URL = resolveBaseUrl();
export const photoUrl = (path: string | null) => (path ? (path.startsWith("http") ? path : API_URL + path) : null);

const TOKEN_KEY = "mendmap.token";
let token: string | null = null;
let onUnauthorized: (() => void) | null = null;

export async function loadToken() {
  token = await AsyncStorage.getItem(TOKEN_KEY);
  return token;
}
export async function setToken(t: string | null) {
  token = t;
  if (t) await AsyncStorage.setItem(TOKEN_KEY, t);
  else await AsyncStorage.removeItem(TOKEN_KEY);
}
export const setUnauthorizedHandler = (fn: () => void) => (onUnauthorized = fn);

// ---------- types ----------
export type User = {
  id: number;
  name: string;
  email: string;
  role: "citizen" | "admin" | "crew";
  home_lat?: number | null;
  home_lng?: number | null;
  neighbourhood?: string | null;
};
export type Category = { id: number; name: string; icon: string };
export type StatusUpdate = { id: number; old_status: Status | null; new_status: Status; comment: string | null; created_at: string };
export type Report = {
  id: number;
  user_id: number;
  category: Category;
  description: string | null;
  photo_url: string | null;
  latitude: number;
  longitude: number;
  status: Status;
  confirmations: number;
  severity: number | null;
  after_photo_url: string | null;
  voice_url: string | null;
  voice_text?: string | null;
  created_at: string;
  updated_at: string;
  distance_m?: number | null;
  priority: number;
  priority_reasons: string[];
  neighbourhood: string | null;
  claimed_by: number | null;
  claimed_by_name: string | null;
  fix_status: "pending" | "verified" | null;
  neighbour_fixable: boolean;
  claim_deadline?: string | null;
  // The server's AI check of the photo (null until it has run).
  ai_is_problem?: boolean | null;
  ai_category?: string | null;
  ai_severity?: number | null;
  ai_reason?: string | null;
  ai_neighbour_safe?: boolean | null;
  ai_safety_reason?: string | null;
  ai_photo_kind?: string | null;
  ai_kind_reason?: string | null;
  // Fraud checks: e.g. ["fake_photo"], ["reused_photo"]. flagged = not cleared by an official.
  ai_flags?: string[];
  reused_from?: number | null;
  flagged?: boolean;
  fix_ai?: string | null; // auto_verified, looks_fixed, not_fixed, different_place, fake
  fix_ai_reason?: string | null;
};
export type Fixer = {
  neighbourhood: string | null;
  verified: number;
  pending: number;
  active: Report[];
  goal: number;
  reward_eur: number;
  rewards_earned: number;
  rewards_paid: number;
  level: string;
  next_level_at: number | null;
  claim_hours: number;
  max_active: number;
  available: Report[];
};
export type TopFixer = { name: string; neighbourhood: string | null; badges: number; level: string };
export type ReportDetail = Report & { updates: StatusUpdate[]; reporter_name: string | null };
export type Job = Report & { stop: number; leg_m: number | null };
export type PhotoCheck = {
  available: boolean;
  is_street_problem?: boolean;
  category?: string | null;
  severity?: number | null;
  reason?: string | null;
  neighbour_safe?: boolean | null;
  safety_reason?: string | null;
  photo_kind?: string | null;
  kind_reason?: string | null;
};
export type CrewStats = {
  open_jobs: number;
  fixed_today: number;
  fixed_week: number;
  fixed_total: number;
  avg_days_to_fix: number | null;
};
export type Badge = { key: string; earned: boolean; progress: number; goal: number };
export type PublicStats = {
  total: number;
  reported: number;
  in_progress: number;
  fixed: number;
  avg_days_to_fix: number | null;
  fix_rate: number;
  neighbourhoods: { name: string; total: number; fixed: number; open: number; fix_rate: number }[];
};

/** React Native's FormData takes { uri, name, type } objects as file parts. */
function filePart(uri: string, fallbackName: string, type: string) {
  const name = uri.split("/").pop() || fallbackName;
  return { uri, name, type } as unknown as Blob;
}
const imageType = (uri: string) => (/\.png$/i.test(uri) ? "image/png" : "image/jpeg");

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json", ...(init.headers as Record<string, string>) };
  if (token) headers.Authorization = `Bearer ${token}`;
  if (init.body && !(init.body instanceof FormData)) headers["Content-Type"] = "application/json";

  let res: { status: number; text: string };
  try {
    res = init.body instanceof FormData
      ? await xhrSend(API_URL + path, init.method ?? "POST", headers, init.body)
      : await fetch(API_URL + path, { ...init, headers }).then(async (r) => ({ status: r.status, text: await r.text() }));
  } catch (e) {
    console.warn(`MendMap: ${init.method ?? "GET"} ${path} failed:`, (e as Error)?.message ?? e);
    throw new ApiError(0, "Can't reach MendMap. Check your connection.");
  }
  if (res.status === 401 && token) onUnauthorized?.();
  const parse = () => {
    try {
      return res.text ? JSON.parse(res.text) : null;
    } catch {
      return null;
    }
  };
  if (res.status < 200 || res.status >= 300) {
    const body = parse() ?? {};
    const detail = typeof body.detail === "string" ? body.detail : Array.isArray(body.detail) ? body.detail[0]?.msg : null;
    throw new ApiError(res.status, detail ?? `Request failed (${res.status})`);
  }
  return (res.status === 204 ? null : parse()) as T;
}

/**
 * Uploads (photos, voice notes) go through React Native's XMLHttpRequest, which reads
 * `{ uri, name, type }` file parts from the phone's storage. Expo SDK 58 swaps the global
 * `fetch` for expo/fetch, which does not support those parts and fails before sending,
 * so every report with a photo looked "offline".
 */
function xhrSend(url: string, method: string, headers: Record<string, string>, body: FormData) {
  return new Promise<{ status: number; text: string }>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open(method, url);
    for (const [k, v] of Object.entries(headers)) xhr.setRequestHeader(k, v); // no Content-Type: XHR adds the boundary
    xhr.timeout = 120_000; // slow mobile uploads
    xhr.onload = () => resolve({ status: xhr.status, text: xhr.responseText ?? "" });
    xhr.onerror = () => reject(new Error("network error"));
    xhr.ontimeout = () => reject(new Error("upload timed out"));
    xhr.send(body);
  });
}

// ---------- endpoints ----------
type Auth = { token: string; user: User; is_new: boolean };
export type OtpSent = { sent: boolean; expires_in: number; resend_in: number; existing: boolean; demo_code: string | null };
export const api = {
  /** Emails a 6-digit code. In demo mode (no email service) the code comes back in `demo_code`. */
  sendOtp: (email: string, purpose: "register" | "social") =>
    request<OtpSent>("/auth/otp/send", { method: "POST", body: JSON.stringify({ email, purpose }) }),
  register: (name: string, email: string, password: string, neighbourhood: string | null, code: string) =>
    request<Auth>("/auth/register", { method: "POST", body: JSON.stringify({ name, email, password, neighbourhood, code }) }),
  /** Demo Google/Apple sign-in: the email is confirmed with the one-time code. */
  social: (provider: "google" | "apple", name: string, email: string, neighbourhood: string | null, code: string) =>
    request<Auth>("/auth/social", { method: "POST", body: JSON.stringify({ provider, name, email, neighbourhood, code }) }),
  neighbourhoods: () => request<string[]>("/neighbourhoods"),
  setNeighbourhood: (neighbourhood: string | null) =>
    request<User>("/me/neighbourhood", { method: "PUT", body: JSON.stringify({ neighbourhood }) }),
  // Neighbour fixes
  claim: (id: number) => request<ReportDetail>(`/reports/${id}/claim`, { method: "POST" }),
  unclaim: (id: number) => request<ReportDetail>(`/reports/${id}/unclaim`, { method: "POST" }),
  neighbourFixed: (id: number, afterPhotoUri: string, comment?: string) => {
    const form = new FormData();
    form.append("after_photo", filePart(afterPhotoUri, "after.jpg", imageType(afterPhotoUri)));
    if (comment) form.append("comment", comment);
    return request<ReportDetail>(`/reports/${id}/neighbour-fixed`, { method: "POST", body: form });
  },
  fixer: () => request<Fixer>("/me/fixer"),
  topFixers: () => request<TopFixer[]>("/public/fixers"),
  login: (email: string, password: string) =>
    request<Auth>("/auth/login", { method: "POST", body: JSON.stringify({ email, password }) }),
  me: () => request<User>("/me"),
  setPushToken: (push_token: string | null) =>
    request<null>("/me/push-token", { method: "PUT", body: JSON.stringify({ push_token }) }),
  categories: () => request<Category[]>("/categories"),
  reports: (q: { category?: number; status?: string; near?: { lat: number; lng: number }; radius?: number } = {}) => {
    const p = new URLSearchParams();
    if (q.category) p.set("category", String(q.category));
    if (q.status) p.set("status", q.status);
    if (q.near) p.set("near", `${q.near.lat},${q.near.lng}`);
    if (q.radius) p.set("radius", String(q.radius));
    return request<Report[]>(`/reports?${p}`);
  },
  report: (id: number) => request<ReportDetail>(`/reports/${id}`),
  confirm: (id: number) => request<Report>(`/reports/${id}/confirm`, { method: "POST" }),
  myReports: () => request<ReportDetail[]>("/me/reports"),
  createReport: (r: NewReport) => {
    const form = new FormData();
    form.append("category_id", String(r.categoryId));
    form.append("latitude", String(r.latitude));
    form.append("longitude", String(r.longitude));
    if (r.description) form.append("description", r.description);
    if (r.severity) form.append("severity", String(r.severity));
    if (r.photoUri) form.append("photo", filePart(r.photoUri, "photo.jpg", imageType(r.photoUri)));
    if (r.voiceUri) form.append("voice", filePart(r.voiceUri, "voice.m4a", "audio/m4a"));
    return request<Report>("/reports", { method: "POST", body: form });
  },
  /** AI photo check: suggested category and severity. { available: false } when the server has no AI key. */
  checkPhoto: (uri: string) => {
    const form = new FormData();
    form.append("photo", filePart(uri, "photo.jpg", imageType(uri)));
    return request<PhotoCheck>("/ai/check-photo", { method: "POST", body: form });
  },
  setHome: (coords: { latitude: number; longitude: number } | null) =>
    request<User>("/me/home", {
      method: "PUT",
      body: JSON.stringify(coords ?? { latitude: null, longitude: null }),
    }),
  nearby: () => request<Report[]>("/me/nearby"),
  badges: () => request<Badge[]>("/me/badges"),
  publicStats: () => request<PublicStats>("/public/stats"),
  crewStats: () => request<CrewStats>("/crew/stats"),
  crewJobs: (near?: { lat: number; lng: number }) =>
    request<Job[]>(`/crew/jobs${near ? `?near=${near.lat},${near.lng}` : ""}`),
  crewDone: (id: number, afterPhotoUri: string, comment?: string) => {
    const form = new FormData();
    form.append("after_photo", filePart(afterPhotoUri, "after.jpg", imageType(afterPhotoUri)));
    if (comment) form.append("comment", comment);
    return request<ReportDetail>(`/crew/jobs/${id}/done`, { method: "POST", body: form });
  },
};

export type NewReport = {
  categoryId: number;
  latitude: number;
  longitude: number;
  description?: string;
  photoUri?: string | null;
  voiceUri?: string | null;
  severity?: number | null;
};
