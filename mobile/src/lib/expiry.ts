import { formatAmount } from '@/lib/amount';
import type { InventoryEntry } from '@/lib/api';
import { capitalize, whenWord } from '@/lib/time';

/** Goes bad within this many days: red. Within WARN_DAYS: amber. */
const DANGER_DAYS = 1;
const WARN_DAYS = 3;
/** Runs out today or tomorrow: amber. */
const RUNS_OUT_WARN_DAYS = 2;

export type ExpiryTone = 'danger' | 'warn' | null;

/** Fresh leftovers are no alarm: they turn red the day before they go, and are never amber. */
export function expiryTone(days: number | null, leftovers = false): ExpiryTone {
  if (days == null) return null;
  if (days <= DANGER_DAYS) return 'danger';
  if (leftovers) return null;
  if (days <= WARN_DAYS) return 'warn';
  return null;
}

/**
 * The one color an item gets on every screen (phone and fridge): red when it goes bad
 * today/tomorrow, amber when it goes bad in 2-3 days or runs out today/tomorrow.
 */
export function urgency(item: Pick<InventoryEntry, 'expires_in_days' | 'days_left'> & { leftovers?: boolean }): ExpiryTone {
  return expiryTone(item.expires_in_days, item.leftovers) ?? (!item.leftovers && runsOutSoon(item) ? 'warn' : null);
}

export const runsOutSoon = (item: Pick<InventoryEntry, 'days_left'>) =>
  item.days_left != null && item.days_left < RUNS_OUT_WARN_DAYS;

/** The one-word answer to "when does it go bad?": "Expired", "Today", "Tomorrow", "Thursday", "In about a week". */
export function expiryWord(days: number): string {
  return days < 0 ? 'Expired' : capitalize(whenWord(days));
}

/** The fridge screen's big word: like expiryWord, but "In 2 weeks" without "about" so it fits one line. */
export function glanceWord(days: number): string {
  if (days < 7) return expiryWord(days);
  const weeks = Math.round(days / 7);
  return weeks <= 1 ? 'In a week' : `In ${weeks} weeks`;
}

/** "Goes bad tomorrow", "Goes bad around Thursday" (an estimate), "Expired". */
export function expiryText(days: number, estimated: boolean): string {
  if (days < 0) return 'Expired';
  const around = estimated && days >= 2 && days <= 6 ? 'around ' : '';
  return `Goes bad ${around}${whenWord(days)}`;
}

/** The older package, when newer ones are there too: "1 L" of 3 L. Null when it's all one batch. */
export function soonestPart(item: InventoryEntry): string | null {
  const batch = item.soonest_batch;
  if (!batch || batch.grams >= item.grams - 0.5) return null;
  return formatAmount(batch.grams, item.unit, item.grams_per_unit, item.name);
}

/** "Goes bad Monday", or "1 L goes bad Monday" when only the older package does. Null without a date. */
export function goesBadText(item: InventoryEntry): string | null {
  const days = item.expires_in_days;
  if (days == null) return null;
  // Leftovers keep a fixed 3 days (USDA), so their date is never "around".
  const text = expiryText(days, item.expiry_estimated && !item.leftovers);
  const part = soonestPart(item);
  if (!part) return text;
  const plural = item.unit === 'count' && Math.round(item.soonest_batch!.grams / item.grams_per_unit) > 1;
  const verb = days < 0 ? 'expired' : (plural ? 'go' : 'goes') + text.slice('Goes'.length);
  return `${capitalize(part)} ${verb}`;
}

type Stock = Pick<InventoryEntry, 'unit' | 'grams_per_unit' | 'name' | 'days_left' | 'likely_wasted_g'>;

/** The stat label for what you won't finish before it goes bad, the same on every screen. */
export const LIKELY_WASTED = 'Likely to spoil';

/**
 * How much you won't have used by the day it goes bad, at your usual rate: "1.2 kg" (always an
 * estimate, so shown with "about"). The server works it out; null when you'll finish it first.
 */
function wastedAmount(item: Stock): string | null {
  if (item.likely_wasted_g == null) return null;
  // A non-breaking space keeps "48 ml" on one line.
  return formatAmount(item.likely_wasted_g, item.unit, item.grams_per_unit, item.name).replace(/^about /, '').replace(' ', '\u00a0');
}

/** The stat value under LIKELY_WASTED: "About 1.2 kg". */
export function likelyWasted(item: Stock): string | null {
  const amount = wastedAmount(item);
  return amount && `About ${amount}`;
}

/**
 * "Runs out tomorrow", or "You'll likely throw away about 1.2 kg" when it outlasts its date.
 * Null without usage history: there's nothing true to say yet.
 */
export function runsOutText(item: Stock): string | null {
  const amount = wastedAmount(item);
  if (amount) return `You'll likely throw away about ${amount}`;
  return item.days_left == null ? null : `Runs out ${whenWord(item.days_left)}`;
}

/** Leftovers: "3 servings · keeps until Tuesday". */
export function keepsText(item: Pick<InventoryEntry, 'grams' | 'unit' | 'grams_per_unit' | 'name' | 'expires_in_days'>): string {
  const amount = formatAmount(item.grams, item.unit, item.grams_per_unit, item.name);
  const days = item.expires_in_days;
  if (days == null) return amount;
  return `${amount} · ${days < 0 ? 'past its keep-by day' : `keeps until ${whenWord(days)}`}`;
}
