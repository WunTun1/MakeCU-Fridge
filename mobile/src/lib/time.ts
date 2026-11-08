import { householdNow } from './householdClock';

const DAY_MS = 86_400_000;

function localDate(isoDate: string): Date {
  // Parse as a local date so it doesn't shift a day across time zones.
  const [y, m, d] = isoDate.split("-").map(Number);
  return new Date(y, m - 1, d);
}

function startOfDay(now: Date): Date {
  return new Date(now.getFullYear(), now.getMonth(), now.getDate());
}

/** YYYY-MM-DD `days` after a YYYY-MM-DD date. */
export function shiftDate(isoDate: string, days: number): string {
  const d = new Date(localDate(isoDate).getTime() + days * DAY_MS + DAY_MS / 2);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/** YYYY-MM-DD for today plus `days`, on this device's calendar. */
export function isoDateIn(days: number, now = householdNow()): string {
  return shiftDate(
    `${now.getFullYear()}-${now.getMonth() + 1}-${now.getDate()}`,
    days,
  );
}

/** "Tue, Nov 10". */
export function calendarDate(isoDate: string): string {
  return localDate(isoDate).toLocaleDateString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
  });
}

/** For "1 L by ...": "today", "tomorrow", "Mon" within the next 6 days, otherwise "Dec 1". `days` comes from the server. */
export function byDay(days: number, isoDate: string): string {
  if (days <= 0) return "today";
  if (days === 1) return "tomorrow";
  const options: Intl.DateTimeFormatOptions =
    days <= 6 ? { weekday: "short" } : { month: "short", day: "numeric" };
  return localDate(isoDate).toLocaleDateString(undefined, options);
}

/** "August": how freezer dates are said, since they're months away and only approximate. */
export function monthName(isoDate: string): string {
  return localDate(isoDate).toLocaleDateString(undefined, { month: "long" });
}

/** "12:40 PM" from a timestamp. */
export function clockTime(isoTimestamp: string): string {
  return new Date(isoTimestamp).toLocaleTimeString(undefined, {
    hour: "numeric",
    minute: "2-digit",
  });
}

/** "Shop today · covers until Sat, Nov 14", "Shop by Tue, Nov 10 · ...": one source for Home and Grocery. */
export function tripText(
  tripDate: string | null,
  days: number | null,
  coversUntil: string | null,
): string {
  if (!tripDate || days == null || !coversUntil)
    return "No trip needed in the next two weeks";
  const when =
    days <= 0
      ? "Shop today"
      : days === 1
        ? "Shop tomorrow"
        : `Shop by ${calendarDate(tripDate)}`;
  return `${when} · covers until ${calendarDate(coversUntil)}`;
}

function weeks(days: number): string {
  const n = Math.round(days / 7);
  return n <= 1 ? "in about a week" : `in about ${n} weeks`;
}

/**
 * When something happens, the way people say it: "today", "tomorrow",
 * "Thursday" (2-6 days out), "in about a week", "in about 3 weeks".
 */
export function whenWord(days: number, now = householdNow()): string {
  const d = Math.floor(days);
  if (d < 1) return "today";
  if (d === 1) return "tomorrow";
  if (d <= 6)
    return new Date(
      startOfDay(now).getTime() + d * DAY_MS + DAY_MS / 2,
    ).toLocaleDateString(undefined, { weekday: "long" });
  return weeks(d);
}

/** A count of days from now: "today", "tomorrow", "in 3 days", "in about 4 days" for estimates. */
export function relativeDays(days: number, approx = false): string {
  const d = approx ? Math.round(days) : Math.floor(days);
  if (d < 1) return "today";
  if (d === 1) return approx ? "in about a day" : "tomorrow";
  if (d < 14) return `in ${approx ? "about " : ""}${d} days`;
  return weeks(d);
}

export const capitalize = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

/** "baby SPINACH" / "Baby Spinach" -> "Baby spinach". */
export const sentenceCase = (s: string) => capitalize(s.trim().toLowerCase());
