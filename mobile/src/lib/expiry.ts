import { colors } from '@/lib/theme';

/** "Expired", "Expires today", "Expires ~tomorrow", "Expires in ~4 days" — "~" marks an estimate. */
export function expiryText(days: number, estimated: boolean): string {
  const approx = estimated ? '~' : '';
  if (days < 0) return 'Expired';
  if (days === 0) return `Expires ${approx}today`;
  if (days === 1) return `Expires ${approx}tomorrow`;
  return `Expires in ${approx}${days} days`;
}

export function expiryColor(days: number): string {
  if (days <= 1) return colors.danger;
  if (days <= 3) return colors.warn;
  return colors.muted;
}
