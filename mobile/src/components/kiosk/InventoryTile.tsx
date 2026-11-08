import { useMemo } from "react";
import { Platform, StyleSheet, Text, View, type TextStyle } from "react-native";

import { FillBar } from "@/components/FillBar";
import { formatAmount } from "@/lib/amount";
import type { InventoryEntry } from "@/lib/api";
import {
  expiryTone,
  glanceWord,
  runsOutSoon,
  soonestPart,
  urgency,
} from "@/lib/expiry";
import { type Palette, useColors } from "@/lib/theme";
import { byDay, capitalize } from "@/lib/time";

/** Average glyph width of the bold system font, as a share of the font size. */
const GLYPH_W = 0.62;
const GLANCE_SIZE = { regular: [21, 26], compact: [17, 21] } as const;

/** Words wrap only at spaces. react-native-web's Text defaults to breaking inside words. */
const KEEP_WORDS = Platform.select<TextStyle>({
  web: {
    wordBreak: "keep-all",
    overflowWrap: "normal",
    wordWrap: "normal",
  } as TextStyle,
  default: {},
});

/** The biggest size at which the glance value's longest word still fits the tile on one line. */
function glanceSize(text: string, contentW: number, compact: boolean): number {
  const [min, max] = compact ? GLANCE_SIZE.compact : GLANCE_SIZE.regular;
  const longest = Math.max(...text.split(" ").map((w) => w.length));
  return Math.max(
    min,
    Math.min(max, Math.floor(contentW / (GLYPH_W * longest))),
  );
}

/** "3 L · 1 L by Mon" ("by Dec 1" past the next 6 days) when only the older package goes bad soon; the wide panel has room for it. */
function amountText(item: InventoryEntry, compact: boolean): string {
  const total = capitalize(
    formatAmount(item.grams, item.unit, item.grams_per_unit, item.name),
  );
  const part = compact ? null : soonestPart(item);
  const parts = [
    part
      ? `${total} · ${part} by ${byDay(item.soonest_batch!.expires_in_days, item.soonest_batch!.expiration_date)}`
      : total,
  ];
  if (runsOutSoon(item)) parts.push("low");
  return parts.join(" · ");
}

/**
 * One item on the fridge screen — display only, nothing to tap. The biggest text
 * answers "when does it go bad?"; the amount and fill bar come second.
 */
export function InventoryTile({
  item,
  width,
  height,
  compact,
}: {
  item: InventoryEntry;
  width: number;
  height: number;
  /** The 800x480 panel. */
  compact: boolean;
}) {
  const colors = useColors();
  const styles = useMemo(() => makeStyles(colors), [colors]);
  const days = item.expires_in_days;
  const dateTone = expiryTone(days, item.leftovers);
  const tone = urgency(item);
  const padding = compact ? 8 : 12;
  const border = tone ? 2 : 1;
  const glance = days != null ? glanceWord(days) : "No date";
  const size = glanceSize(glance, width - 2 * (padding + border), compact);

  return (
    <View
      accessibilityLabel={`${item.name}: ${glance}`}
      style={[
        styles.tile,
        { width, height, padding },
        tone && { borderColor: colors[tone], borderWidth: border },
      ]}
    >
      <Text
        style={[
          styles.name,
          styles.fixed,
          compact && { fontSize: 14 },
          KEEP_WORDS,
        ]}
        numberOfLines={compact ? 1 : 2}
      >
        {item.name}
      </Text>
      <Text
        style={[
          styles.glance,
          styles.fixed,
          { fontSize: size, lineHeight: size + 4 },
          KEEP_WORDS,
          days == null
            ? { color: colors.muted }
            : dateTone && { color: colors[dateTone] },
        ]}
        numberOfLines={2}
      >
        {glance}
      </Text>
      <View style={{ flex: 1 }} />
      <Text
        style={[styles.amount, styles.fixed, compact && { fontSize: 13 }]}
        numberOfLines={1}
      >
        {/* On a shelf without a scale: no weight to show, and none is guessed. */}
        {item.grams > 0 ? amountText(item, compact) : "Not weighed"}
      </Text>
      {item.fill_fraction != null && (
        <FillBar fraction={item.fill_fraction} tone={tone} />
      )}
    </View>
  );
}

const makeStyles = (colors: Palette) =>
  StyleSheet.create({
    tile: {
      backgroundColor: colors.card,
      borderColor: colors.border,
      borderWidth: 1,
      borderRadius: 12,
    },
    name: { color: colors.text, fontSize: 16, fontWeight: "700" },
    glance: { color: colors.text, fontWeight: "700", marginTop: 4 },
    amount: { color: colors.muted, fontSize: 15, fontWeight: "500" },
    // Text never gives way: a squashed line would spill over its neighbours.
    fixed: { flexShrink: 0 },
  });
