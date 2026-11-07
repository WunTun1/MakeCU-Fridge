import { colors, type Palette } from '@/lib/theme';
import { capitalize, whenWord } from '@/lib/time';

/** Goes bad within this many days: red. Within WARN_DAYS: amber. */
const DANGER_DAYS = 1;
const WARN_DAYS = 3;

export type ExpiryTone = 'danger' | 'warn' | null;

export function expiryTone(days: number | null): ExpiryTone {
  if (days == null) return null;
  if (days <= DANGER_DAYS) return 'danger';
  if (days <= WARN_DAYS) return 'warn';
  return null;
}

/** The one-word answer to "when does it go bad?": "Expired", "Today", "Tomorrow", "Thursday", "In about a week". */
export function expiryWord(days: number): string {
  return days < 0 ? 'Expired' : capitalize(whenWord(days));
}

/** "Goes bad tomorrow", "Goes bad around Thursday" (an estimate), "Expired". */
export function expiryText(days: number, estimated: boolean): string {
  if (days < 0) return 'Expired';
  const around = estimated && days >= 2 && days <= 6 ? 'around ' : '';
  return `Goes bad ${around}${whenWord(days)}`;
}

export function expiryColor(days: number, palette: Palette = colors): string {
  const tone = expiryTone(days);
  return tone ? palette[tone] : palette.muted;
}
