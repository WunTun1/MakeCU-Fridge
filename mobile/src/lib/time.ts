const DAY_MS = 86_400_000;

function localDate(isoDate: string): Date {
  // Parse as a local date so it doesn't shift a day across time zones.
  const [y, m, d] = isoDate.split('-').map(Number);
  return new Date(y, m - 1, d);
}

function startOfDay(now: Date): Date {
  return new Date(now.getFullYear(), now.getMonth(), now.getDate());
}

/** Whole days from today until a YYYY-MM-DD date (negative when it's past). */
export function daysUntil(isoDate: string, now = new Date()): number {
  return Math.round((localDate(isoDate).getTime() - startOfDay(now).getTime()) / DAY_MS);
}

/** YYYY-MM-DD for today plus `days`, in local time. */
export function isoDateIn(days: number, now = new Date()): string {
  const d = new Date(startOfDay(now).getTime() + days * DAY_MS + DAY_MS / 2);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

/** "Tue, Nov 10". */
export function calendarDate(isoDate: string): string {
  return localDate(isoDate).toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' });
}

function weeks(days: number): string {
  const n = Math.round(days / 7);
  return n <= 1 ? 'in about a week' : `in about ${n} weeks`;
}

/**
 * When something happens, the way people say it: "today", "tomorrow",
 * "Thursday" (2-6 days out), "in about a week", "in about 3 weeks".
 */
export function whenWord(days: number, now = new Date()): string {
  const d = Math.floor(days);
  if (d < 1) return 'today';
  if (d === 1) return 'tomorrow';
  if (d <= 6) return new Date(startOfDay(now).getTime() + d * DAY_MS + DAY_MS / 2).toLocaleDateString(undefined, { weekday: 'long' });
  return weeks(d);
}

/** A count of days from now: "today", "tomorrow", "in 3 days", "in about 4 days" for estimates. */
export function relativeDays(days: number, approx = false): string {
  const d = approx ? Math.round(days) : Math.floor(days);
  if (d < 1) return 'today';
  if (d === 1) return approx ? 'in about a day' : 'tomorrow';
  if (d < 14) return `in ${approx ? 'about ' : ''}${d} days`;
  return weeks(d);
}

export const capitalize = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
