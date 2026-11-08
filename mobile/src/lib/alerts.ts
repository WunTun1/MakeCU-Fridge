import { useSyncExternalStore } from "react";

import { formatAmount } from "@/lib/amount";
import type { Alert, InventoryEntry } from "@/lib/api";
import { goesBadText } from "@/lib/expiry";
import { whenWord } from "@/lib/time";

/** What an alert says, in the app's words: "Goes bad tomorrow", "Runs out Monday", "Only 52 g left". */
export function alertText(
  alert: Alert,
  entry: InventoryEntry | undefined,
): string {
  const days = alert.days;
  switch (alert.reason) {
    case "expiring_soon":
      if (entry) return goesBadText(entry) ?? alert.detail;
      return days == null
        ? alert.detail
        : days < 0
          ? "Expired"
          : `Goes bad ${whenWord(days)}`;
    case "low_days_left":
      return days == null ? alert.detail : `Runs out ${whenWord(days)}`;
    case "low_fraction":
      return entry
        ? `Only ${formatAmount(entry.grams, entry.unit, entry.grams_per_unit, entry.name)} left`
        : "Running low";
    case "staple_out":
      return "You're out";
    default:
      return alert.detail;
  }
}

/** One alert's identity, for "have you seen this one?". */
export const alertKey = (a: Alert) =>
  `${a.reason}:${a.product_id ?? a.product_name}`;

// ----------------------------------------------------- seen alerts (the bell's red number)
const STORE_KEY = "refridge.seenAlerts";
let seen: Set<string> = load();
const listeners = new Set<() => void>();

function load(): Set<string> {
  try {
    return new Set(
      JSON.parse(
        globalThis.localStorage?.getItem(STORE_KEY) ?? "[]",
      ) as string[],
    );
  } catch {
    return new Set();
  }
}

/** Opening the alerts screen marks what's there as seen; the badge counts only what's new since. */
export function markAlertsSeen(keys: string[]): void {
  seen = new Set(keys); // forget alerts that have gone away, so they count as new if they come back
  try {
    globalThis.localStorage?.setItem(STORE_KEY, JSON.stringify([...seen]));
  } catch {
    // not remembered across reloads; the badge still clears for this session
  }
  listeners.forEach((l) => l());
}

export function useSeenAlerts(): Set<string> {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    () => seen,
  );
}
