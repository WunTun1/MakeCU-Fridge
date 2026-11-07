import { formatAmount } from '@/lib/amount';
import type { InventoryEntry } from '@/lib/api';
import { colors, type Palette } from '@/lib/theme';
import { capitalize, whenWord } from '@/lib/time';

/** Goes bad within this many days: red. Within WARN_DAYS: amber. */
const DANGER_DAYS = 1;
const WARN_DAYS = 3;
/** Runs out today or tomorrow: amber. */
const RUNS_OUT_WARN_DAYS = 2;

export type ExpiryTone = 'danger' | 'warn' | null;

export function expiryTone(days: number | null): ExpiryTone {
  if (days == null) return null;
  if (days <= DANGER_DAYS) return 'danger';
  if (days <= WARN_DAYS) return 'warn';
  return null;
}

/**
 * The one color an item gets on every screen (phone and fridge): red when it goes bad
 * today/tomorrow, amber when it goes bad in 2-3 days or runs out today/tomorrow.
 */
export function urgency(item: Pick<InventoryEntry, 'expires_in_days' | 'days_left'>): ExpiryTone {
  return expiryTone(item.expires_in_days) ?? (runsOutSoon(item) ? 'warn' : null);
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
  const text = expiryText(days, item.expiry_estimated);
  const part = soonestPart(item);
  if (!part) return text;
  const plural = item.unit === 'count' && Math.round(item.soonest_batch!.grams / item.grams_per_unit) > 1;
  const verb = days < 0 ? 'expired' : (plural ? 'go' : 'goes') + text.slice('Goes'.length);
  return `${capitalize(part)} ${verb}`;
}

/** "Runs out tomorrow"; when it lasts past its date, "More than you'll use by then". */
export function runsOutText(item: Pick<InventoryEntry, 'days_left' | 'expires_in_days'>): string {
  if (item.days_left == null) return 'No usage history yet';
  if (item.expires_in_days != null && item.days_left > item.expires_in_days) return "More than you'll use by then";
  return `Runs out ${whenWord(item.days_left)}`;
}

export function expiryColor(days: number, palette: Palette = colors): string {
  const tone = expiryTone(days);
  return tone ? palette[tone] : palette.muted;
}
