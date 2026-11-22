import type { TKey } from "./i18n";

/** Server times are UTC without a "Z". */
export const parseUtc = (iso: string) => new Date(iso.endsWith("Z") ? iso : iso + "Z");

const sameDay = (a: Date, b: Date) => a.toDateString() === b.toDateString();

/** "Today 10:00", "Tomorrow 09:00" or "Sat 30 Nov, 10:00" in the user's language. */
export function fmtWhen(iso: string, locale: string, t: (k: TKey) => string): string {
  const d = parseUtc(iso);
  const today = new Date();
  const tomorrow = new Date(today.getTime() + 86_400_000);
  let time: string, day: string;
  try {
    time = d.toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit" });
    day = d.toLocaleDateString(locale, { weekday: "short", day: "numeric", month: "short" });
  } catch {
    time = d.toLocaleTimeString();
    day = d.toLocaleDateString();
  }
  if (sameDay(d, today)) return `${t("cuToday")} ${time}`;
  if (sameDay(d, tomorrow)) return `${t("cuTomorrow")} ${time}`;
  return `${day}, ${time}`;
}

/** Calendar-style day box: "SAT" / "30". */
export function dayBox(iso: string, locale: string): { wd: string; day: string } {
  const d = parseUtc(iso);
  try {
    return { wd: d.toLocaleDateString(locale, { weekday: "short" }).toUpperCase(), day: String(d.getDate()) };
  } catch {
    return { wd: "", day: String(d.getDate()) };
  }
}
