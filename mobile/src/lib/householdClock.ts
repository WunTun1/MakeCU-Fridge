/**
 * The household's clock, taken from the backend. The fridge screen runs on a Pi with no
 * internet (and no clock battery), so its own clock and time zone can't be trusted; the
 * kiosk syncs this from every summary. Until something syncs it — the phone app never
 * does — it's simply this device's clock.
 */
let offsetMs = 0;
let utcOffsetMin: number | null = null;

/** From the server: its current time (ISO, UTC) and the household's UTC offset in minutes. */
export function syncHouseholdClock(
  serverTimeIso: string,
  utcOffsetMinutes: number,
): void {
  const server = Date.parse(serverTimeIso);
  if (Number.isNaN(server)) return;
  offsetMs = server - Date.now();
  utcOffsetMin = utcOffsetMinutes;
}

/** Milliseconds since the epoch, by the server's clock (for comparing with server timestamps). */
export function householdEpochMs(): number {
  return Date.now() + offsetMs;
}

/**
 * Now, as a Date whose local fields (hours, weekday, date…) read as the household's wall
 * clock — so toLocaleTimeString() and getDay() show the right time and day whatever
 * time zone this device thinks it's in.
 */
export function householdNow(): Date {
  if (utcOffsetMin == null) return new Date();
  const wall = new Date(Date.now() + offsetMs + utcOffsetMin * 60_000);
  return new Date(
    wall.getUTCFullYear(),
    wall.getUTCMonth(),
    wall.getUTCDate(),
    wall.getUTCHours(),
    wall.getUTCMinutes(),
    wall.getUTCSeconds(),
  );
}
