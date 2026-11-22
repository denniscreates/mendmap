import AsyncStorage from "@react-native-async-storage/async-storage";
import Constants from "expo-constants";
import { Platform } from "react-native";
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
  // In a browser (localhost:8081/login), the page's own dev server forwards /api to FastAPI.
  if (Platform.OS === "web" && typeof window !== "undefined") return `${window.location.origin}/api`;
  const devServer = Constants.expoConfig?.hostUri; // LAN "192.168.1.5:8081" or tunnel "abc.on.expo.app"
  if (!devServer) return "http://localhost:8000";
  const isTunnel = !/:\d+$/.test(devServer); // tunnel hosts have no port and use https
  return `${isTunnel ? "https" : "http"}://${devServer}/api`;
}
export type DemoAccount = { role: "admin" | "crew" | "citizen" | "mjeshter"; about: string; name: string; email: string; password: string };

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
/** For images the server only shows to signed-in people (booking photos). */
export const authHeaders = (): Record<string, string> => (token ? { Authorization: `Bearer ${token}` } : {});

// ---------- types ----------
export type User = {
  id: number;
  name: string;
  email: string;
  role: "citizen" | "admin" | "crew";
  home_lat?: number | null;
  home_lng?: number | null;
  neighbourhood?: string | null;
  language?: string | null; // main language, e.g. "sq"
  mjeshter_status?: "pending" | "approved" | "rejected" | null;
  mjeshter_skills?: string[]; // verified skills (only when approved)
};
export type Category = { id: number; name: string; icon: string };
export type StatusUpdate = { id: number; old_status: Status | null; new_status: Status; comment: string | null; created_at: string };
export type Report = {
  id: number;
  user_id: number;
  category: Category;
  description: string | null;
  address?: string | null;
  repeat_of?: number | null;
  photo_url: string | null;
  photos: string[]; // every photo, the cover first
  edited_at: string | null;
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
  ai_description?: string | null;
  blurred?: number | null; // faces and number plates blurred for privacy
  rating?: number | null; // 1 = I confirmed the fix
  reopened?: number;
  skill_needed?: string | null; // a job for a mjeshtër: plumbing, painting... or "any"
};
export type MjeshterMe = {
  status: "pending" | "approved" | "rejected";
  skills: string[];
  verified_skills: string[];
  days: string[];
  neighbourhood: string | null;
  bio: string | null;
  verified_by: "ai" | "admin" | null;
  ai_verdict: string | null;
  ai_reason_user: string | null;
  admin_note: string | null;
  created_at: string;
};
export type MjeshterPublic = {
  id: number;
  name: string;
  skills: string[];
  days: string[];
  neighbourhood: string | null;
  bio: string | null;
  verified_by: "ai" | "admin" | null;
  jobs_done: number;
  level: string;
};
export type Fixer = {
  neighbourhood: string | null;
  verified: number;
  pending: number;
  active: Report[];
  balance: number; // badges not spent yet
  spent: number;
  next_reward: PartnerReward | null;
  level: string;
  next_level_at: number | null;
  claim_hours: number;
  max_active: number;
  available: Report[];
};
export type PartnerReward = {
  id: number;
  partner: string;
  title: string;
  details: string | null;
  emoji: string;
  cost: number; // badges
  stock: number | null; // vouchers left, null = no limit
  active: boolean;
  claimed: number;
};
export type RewardClaim = {
  id: number;
  code: string;
  reward_id: number;
  partner: string;
  title: string;
  emoji: string;
  cost: number;
  used: boolean;
  created_at: string;
  used_at: string | null;
};
export type Rewards = { badges: number; spent: number; balance: number; rewards: PartnerReward[]; claims: RewardClaim[] };
export type TopFixer = { name: string; neighbourhood: string | null; badges: number; level: string };
export type ReportDetail = Report & { updates: StatusUpdate[]; reporter_name: string | null; adopted_by?: string[] };
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
  description?: string | null; // the AI's description of the photo, in the app's language
  blur_boxes?: { kind: "face" | "plate"; box: number[] }[];
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
  neighbourhoods: {
    name: string; total: number; fixed: number; open: number; fix_rate: number;
    avg_fix_days?: number | null; fixed_in_week?: number | null; came_back?: number;
  }[];
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

export type CleanupEvent = {
  id: number;
  room: string;
  title: string;
  details: string | null;
  starts_at: string;
  place: string;
  latitude: number | null;
  longitude: number | null;
  organiser_id: number;
  organiser_name: string;
  going: number;
  me_going: boolean;
  mine: boolean;
  cancelled: boolean;
  done: boolean;
  past: boolean;
  people: { user_id: number; name: string; attended: boolean }[];
};
export type NewEvent = { room: string; title: string; details?: string; starts_at: string; place: string; latitude?: number; longitude?: number };
export type Adoption = { id: number; street: string; sponsor: string | null; open: number; created_at: string };
export type TopReport = {
  id: number; title: string; address: string | null; neighbourhood: string | null; status: Status;
  confirmations: number; photo_url: string | null; created_at: string;
};

/** A street or place suggestion for the report location. */
export type Place = { name: string; detail: string | null; kind: "street" | "place"; latitude: number; longitude: number };

// ---------- paid bookings ----------
export type BookingStatus = "requested" | "quoted" | "declined" | "cancelled" | "paid" | "disputed" | "done" | "refunded";
export type Booking = {
  id: number;
  status: BookingStatus;
  description: string;
  address: string | null;
  report_id: number | null;
  has_photo: boolean;
  fee_cents: number | null;
  commission_cents: number | null;
  worker_gets_cents: number | null;
  commission_rate: number;
  currency: string;
  quote_note: string | null;
  decline_note: string | null;
  customer_name: string;
  worker_name: string;
  mjeshter_id: number;
  skill: string | null;
  as_role: "customer" | "worker";
  created_at: string;
  quoted_at: string | null;
  paid_at: string | null;
  done_at: string | null;
  worker_done_at: string | null; // the mjeshtër said "I finished the job"
  auto_release_at: string | null; // the money is sent then if nobody reports a problem
  problem_note: string | null;
  admin_note: string | null;
  released_at: string | null;
  refunded_at: string | null;
};
export type NewBooking = { mjeshterId: number; description: string; photoUri: string; address?: string; reportId?: number; skill?: string };
export type PayInfo = {
  mode: "stripe" | "demo";
  client_secret: string | null;
  publishable_key: string | null;
  amount_cents: number;
  commission_cents: number;
  currency: string;
  merchant_country: string;
};
export type Payouts = { configured: boolean; demo: boolean; started: boolean; ready: boolean; commission_rate: number };
export const bookingPhotoUrl = (id: number) => `${API_URL}/bookings/${id}/photo`;

// ---------- community chat ----------
export type ChatEvent = { id: number; title: string; starts_at: string; place: string; going: number; me_going: boolean; cancelled: boolean };
export type ChatMessage = {
  id: number;
  room: string;
  kind: "message" | "announcement" | "event";
  event: ChatEvent | null;
  text: string;
  user_id: number;
  user_name: string;
  badge: "city" | "mjeshter" | null;
  report: { id: number; title: string; status: Status; photo_url: string | null } | null;
  created_at: string;
  mine: boolean;
};
export type ChatRoom = {
  id: string;
  name: string;
  mine: boolean;
  last_id: number | null;
  last_text: string | null;
  last_name: string | null;
  last_at: string | null;
  today: number;
};
const room = (r: string) => `/chat/rooms/${encodeURIComponent(r)}`;

// ---------- endpoints ----------
type Auth = { token: string; user: User; is_new: boolean };
export type OtpSent = { sent: boolean; expires_in: number; resend_in: number; existing: boolean; demo_code: string | null };
export const api = {
  /** Emails a 6-digit code. In demo mode (no email service) the code comes back in `demo_code`. */
  sendOtp: (email: string, purpose: "register" | "social") =>
    request<OtpSent>("/auth/otp/send", { method: "POST", body: JSON.stringify({ email, purpose }) }),
  register: (name: string, email: string, password: string, neighbourhood: string | null, code: string, language: string | null) =>
    request<Auth>("/auth/register", { method: "POST", body: JSON.stringify({ name, email, password, neighbourhood, code, language }) }),
  /** Demo Google/Apple sign-in: the email is confirmed with the one-time code. */
  social: (provider: "google" | "apple", name: string, email: string, neighbourhood: string | null, code: string, language: string | null) =>
    request<Auth>("/auth/social", { method: "POST", body: JSON.stringify({ provider, name, email, neighbourhood, code, language }) }),
  /** The main language, offered everywhere next to English and the local language. */
  setLanguage: (language: string) => request<User>("/me/language", { method: "PUT", body: JSON.stringify({ language }) }),
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
  // Mjeshtrit: skilled volunteers
  mjeshtrit: (skill?: string | null, day?: string | null) => {
    const p = new URLSearchParams();
    if (skill) p.set("skill", skill);
    if (day) p.set("day", day);
    return request<MjeshterPublic[]>(`/mjeshtrit?${p}`);
  },
  mjeshterMe: () => request<MjeshterMe | null>("/mjeshtrit/me"),
  /** Sign up with proof of the skill; the AI checks the document before this returns. */
  mjeshterApply: (a: {
    skills: string[]; days: string[]; neighbourhood: string | null; bio: string;
    proof: { uri: string; name: string; mime: string }; lang: string;
  }) => {
    const form = new FormData();
    form.append("skills", a.skills.join(","));
    form.append("days", a.days.join(","));
    if (a.neighbourhood) form.append("neighbourhood", a.neighbourhood);
    if (a.bio) form.append("bio", a.bio);
    form.append("lang", a.lang);
    form.append("proof", { uri: a.proof.uri, name: a.proof.name, type: a.proof.mime } as unknown as Blob);
    return request<MjeshterMe>("/mjeshtrit/apply", { method: "POST", body: form });
  },
  askMjeshter: (id: number) => request<{ notified: number }>(`/reports/${id}/ask-mjeshter`, { method: "POST" }),
  // Partner rewards, paid for with fixer badges
  searchStreets: (q: string) => request<Place[]>(`/geo/search?q=${encodeURIComponent(q)}`),
  chatTranslate: (id: number, lang: string) =>
    request<{ text: string }>(`/chat/messages/${id}/translate`, { method: "POST", body: JSON.stringify({ lang }) }),
  events: (room?: string | null, past = false) => {
    const p = new URLSearchParams();
    if (room) p.set("room", room);
    if (past) p.set("past", "true");
    return request<CleanupEvent[]>(`/events${p.size ? `?${p}` : ""}`);
  },
  event: (id: number) => request<CleanupEvent>(`/events/${id}`),
  createEvent: (e: NewEvent) => request<CleanupEvent>("/events", { method: "POST", body: JSON.stringify(e) }),
  rsvp: (id: number, going: boolean) => request<CleanupEvent>(`/events/${id}/rsvp`, { method: going ? "POST" : "DELETE" }),
  attendance: (id: number, userIds: number[]) =>
    request<CleanupEvent>(`/events/${id}/attendance`, { method: "POST", body: JSON.stringify({ user_ids: userIds }) }),
  cancelEvent: (id: number) => request<CleanupEvent>(`/events/${id}`, { method: "DELETE" }),
  myStreets: () => request<Adoption[]>("/adoptions/me"),
  adopt: (street: string, sponsor?: string | null) =>
    request<Adoption>("/adoptions", { method: "POST", body: JSON.stringify({ street, sponsor: sponsor || null }) }),
  unadopt: (id: number) => request<null>(`/adoptions/${id}`, { method: "DELETE" }),
  top10: () => request<TopReport[]>("/public/top?days=30"),
  bookings: (as?: "customer" | "worker") => request<Booking[]>(`/bookings${as ? `?as=${as}` : ""}`),
  booking: (id: number) => request<Booking>(`/bookings/${id}`),
  createBooking: (b: NewBooking) => {
    const form = new FormData();
    form.append("mjeshter_id", String(b.mjeshterId));
    form.append("description", b.description);
    form.append("photo", filePart(b.photoUri, "photo.jpg", imageType(b.photoUri)));
    if (b.address) form.append("address", b.address);
    if (b.reportId) form.append("report_id", String(b.reportId));
    if (b.skill) form.append("skill", b.skill);
    return request<Booking>("/bookings", { method: "POST", body: form });
  },
  quoteBooking: (id: number, fee: number, note?: string) =>
    request<Booking>(`/bookings/${id}/quote`, { method: "POST", body: JSON.stringify({ fee, note: note || null }) }),
  declineBooking: (id: number) => request<Booking>(`/bookings/${id}/decline`, { method: "POST", body: JSON.stringify({}) }),
  cancelBooking: (id: number) => request<Booking>(`/bookings/${id}/cancel`, { method: "POST" }),
  payBooking: (id: number) => request<PayInfo>(`/bookings/${id}/pay`, { method: "POST" }),
  confirmBookingPayment: (id: number) => request<Booking>(`/bookings/${id}/confirm-payment`, { method: "POST" }),
  bookingDone: (id: number) => request<Booking>(`/bookings/${id}/done`, { method: "POST" }),
  bookingFinished: (id: number) => request<Booking>(`/bookings/${id}/finished`, { method: "POST" }),
  bookingProblem: (id: number, note: string) =>
    request<Booking>(`/bookings/${id}/problem`, { method: "POST", body: JSON.stringify({ note }) }),
  payouts: () => request<Payouts>("/payouts/me"),
  payoutsOnboard: () => request<{ url: string }>("/payouts/onboard", { method: "POST" }),
  chatRooms: () => request<ChatRoom[]>("/chat/rooms"),
  chatMessages: (r: string, q: { after?: number; before?: number } = {}) => {
    const p = new URLSearchParams();
    if (q.after != null) p.set("after", String(q.after));
    if (q.before != null) p.set("before", String(q.before));
    return request<ChatMessage[]>(`${room(r)}/messages${p.size ? `?${p}` : ""}`);
  },
  chatHidden: (r: string, after: number) => request<number[]>(`${room(r)}/hidden?after=${after}`),
  chatSend: (r: string, text: string, lang: string, reportId?: number | null) =>
    request<ChatMessage>(`${room(r)}/messages`, { method: "POST", body: JSON.stringify({ text, lang, report_id: reportId ?? null }) }),
  chatFlag: (id: number) => request<{ flags: number; hidden: boolean }>(`/chat/messages/${id}/flag`, { method: "POST" }),
  chatDelete: (id: number) => request<null>(`/chat/messages/${id}`, { method: "DELETE" }),
  rewards: () => request<Rewards>("/rewards"),
  claimReward: (id: number) => request<RewardClaim>(`/rewards/${id}/claim`, { method: "POST" }),
  /** Demo accounts for judges and testers; empty unless the server runs with SEED_DEMO=1. */
  demoAccounts: () => request<DemoAccount[]>("/auth/demo-accounts"),
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
  /** The reporter says whether it's really fixed; "not fixed" reopens it. */
  rateFix: (id: number, ok: boolean, comment?: string) =>
    request<ReportDetail>(`/reports/${id}/rate`, { method: "POST", body: JSON.stringify({ ok, comment }) }),
  myReports: () => request<ReportDetail[]>("/me/reports"),
  createReport: (r: NewReport) => {
    const form = new FormData();
    form.append("category_id", String(r.categoryId));
    form.append("latitude", String(r.latitude));
    form.append("longitude", String(r.longitude));
    if (r.description) form.append("description", r.description);
    if (r.address) form.append("address", r.address);
    if (r.severity) form.append("severity", String(r.severity));
    if (r.photoUri) form.append("photo", filePart(r.photoUri, "photo.jpg", imageType(r.photoUri)));
    (r.morePhotos ?? []).forEach((u, i) => form.append("photos", filePart(u, `photo-${i + 2}.jpg`, imageType(u))));
    if (r.voiceUri) form.append("voice", filePart(r.voiceUri, "voice.m4a", "audio/m4a"));
    return request<Report>("/reports", { method: "POST", body: form });
  },
  /** AI photo check: suggested category and severity. { available: false } when the server has no AI key. */
  checkPhoto: (uris: string | string[], lang = "en") => {
    const form = new FormData();
    (Array.isArray(uris) ? uris : [uris]).forEach((u, i) => form.append("photo", filePart(u, `photo-${i + 1}.jpg`, imageType(u))));
    form.append("lang", lang);
    return request<PhotoCheck>("/ai/check-photo", { method: "POST", body: form });
  },
  /** The reporter changes their post (only while nobody is working on it). */
  editReport: (id: number, e: ReportEdit) => {
    const form = new FormData();
    if (e.categoryId != null) form.append("category_id", String(e.categoryId));
    if (e.description != null) form.append("description", e.description);
    if (e.address != null) form.append("address", e.address);
    if (e.severity !== undefined) form.append("severity", String(e.severity ?? 0));
    form.append("keep", e.keep.join(","));
    e.add.forEach((u, i) => form.append("photos", filePart(u, `photo-${i + 1}.jpg`, imageType(u))));
    return request<ReportDetail>(`/reports/${id}`, { method: "PUT", body: form });
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
  address?: string;
  photoUri?: string | null;
  morePhotos?: string[]; // up to 4 more photos of the same problem
  voiceUri?: string | null;
  severity?: number | null;
};
export const MAX_PHOTOS = 5;
export type ReportEdit = {
  categoryId?: number;
  description?: string;
  address?: string;
  severity?: number | null; // null: let the AI decide
  keep: string[]; // photo urls to keep, in order
  add: string[]; // new local photos
};
