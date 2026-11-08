import { Link } from "expo-router";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { FillBar } from "@/components/FillBar";
import { formatAmount } from "@/lib/amount";
import type { InventoryEntry } from "@/lib/api";
import {
  expiryTone,
  goesBadText,
  keepsText,
  runsOutText,
  urgency,
  type ExpiryTone,
} from "@/lib/expiry";
import { makeStyles, useColors, useUi } from "@/lib/theme";
import { calendarDate, capitalize, monthName } from "@/lib/time";

/**
 * A freezer row says how long it keeps; leftovers say how many servings and until when; anything
 * else when it goes bad, and when it runs out (or how much you'll likely throw away).
 */
function rowLines(item: InventoryEntry): {
  goesBad: string | null;
  tone: ExpiryTone;
  second: string | null;
} {
  if (item.location === "freezer") {
    const date = item.soonest_batch?.expiration_date;
    return {
      goesBad: date ? `Good until around ${monthName(date)}` : null,
      tone: null,
      second: null,
    };
  }
  if (item.leftovers)
    return {
      goesBad: keepsText(item),
      tone: expiryTone(item.expires_in_days, true),
      second: null,
    };
  return {
    goesBad: goesBadText(item),
    tone: expiryTone(item.expires_in_days),
    second: runsOutText(item),
  };
}

// Children of <Link asChild> must get one style object — expo-router throws on style arrays.
export function InventoryRow({
  item,
  last,
  showPlace = false,
  showDate = false,
}: {
  item: InventoryEntry;
  last: boolean;
  /** In a list mixing places (Browse): say "Pantry" / "Freezer" after the name; the fridge goes unsaid. */
  showPlace?: boolean;
  /** Your fridge: the expected date itself ("· Mon, Nov 9"), and "No date yet" when there isn't one. */
  showDate?: boolean;
}) {
  const ui = useUi();
  const styles = useStyles();
  const c = useColors();
  const { goesBad, tone, second } = rowLines(item);
  const amount = item.leftovers
    ? null
    : capitalize(
        formatAmount(item.grams, item.unit, item.grams_per_unit, item.name),
      );
  const date =
    showDate &&
    item.location !== "freezer" &&
    item.soonest_batch?.expiration_date
      ? calendarDate(item.soonest_batch.expiration_date)
      : null;
  return (
    <Link
      href={{ pathname: "/item/[id]", params: { id: item.product_id } }}
      asChild
    >
      <Pressable
        style={StyleSheet.flatten([styles.invRow, !last && ui.divider])}
      >
        <View style={styles.top}>
          <Text style={[ui.text, styles.name]} numberOfLines={1}>
            {item.name}
            {showPlace && item.location !== "fridge" && (
              <Text style={[ui.muted, { fontWeight: "400" }]}>
                {item.location === "pantry" ? "  · Pantry" : "  · Freezer"}
              </Text>
            )}
          </Text>
          {amount && <Text style={styles.amount}>{amount}</Text>}
        </View>
        {goesBad && (
          <Text style={[ui.detail, tone && { color: c[tone] }]}>
            {goesBad}
            {date ? ` · ${date}` : ""}
          </Text>
        )}
        {showDate && !goesBad && (
          <Text style={ui.muted}>No date yet · tap to add one</Text>
        )}
        {second && <Text style={ui.muted}>{second}</Text>}
        {item.fill_fraction != null &&
          item.location !== "freezer" &&
          !item.leftovers && (
            <View style={styles.bar}>
              <FillBar fraction={item.fill_fraction} tone={urgency(item)} />
            </View>
          )}
      </Pressable>
    </Link>
  );
}

const useStyles = makeStyles((c, size) => ({
  invRow: { paddingVertical: 12, paddingHorizontal: 4, gap: 3 },
  top: { flexDirection: "row", alignItems: "baseline", gap: 12 },
  name: { flex: 1, fontWeight: "600" },
  amount: {
    color: c.text,
    fontSize: size(15),
    lineHeight: size(20),
    fontWeight: "600",
    textAlign: "right",
  },
  bar: { marginTop: 2 },
}));
