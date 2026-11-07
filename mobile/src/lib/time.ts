/** "today", "tomorrow", or e.g. "Mon, Nov 9" for a YYYY-MM-DD date. */
export function shortDate(isoDate: string, now = new Date()): string {
  // Parse as a local date so it doesn't shift a day across time zones.
  const [y, m, d] = isoDate.split('-').map(Number);
  const date = new Date(y, m - 1, d);
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const days = Math.round((date.getTime() - today.getTime()) / 86_400_000);
  if (days <= 0) return 'today';
  if (days === 1) return 'tomorrow';
  return date.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' });
}
