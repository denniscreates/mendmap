import type { BookingStatus } from "./api";
import type { Palette } from "./theme";

export function money(cents: number | null | undefined, currency = "eur", locale = "en"): string {
  const value = (cents ?? 0) / 100;
  try {
    return new Intl.NumberFormat(locale, { style: "currency", currency: currency.toUpperCase() }).format(value);
  } catch {
    return `€${value.toFixed(2)}`;
  }
}

/** Colour of a booking's status: amber waiting, orange "price came, pay now", blue paid, done in the fixed colour. */
export const statusTone = (c: Palette, s: BookingStatus) =>
  s === "requested" ? c.amber : s === "quoted" ? c.orange : s === "paid" ? c.blue : s === "done" ? c.fixed
    : s === "disputed" ? c.danger : c.muted;
