import { useMemo } from "react";
import {
  Image,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  View,
  type TextStyle,
} from "react-native";

import { FillBar } from "@/components/FillBar";
import { formatAmount } from "@/lib/amount";
import { API_URL, type InventoryEntry } from "@/lib/api";
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
const GLANCE_SIZE = { regular: [24, 30], compact: [20, 24] } as const;

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
 * One item on the fridge screen. The biggest text answers "when does it go
 * bad?"; the amount and fill bar come second. A `peek` tile is the one cut off at
 * the end of a row: it shows only its border and name, so no text appears sliced.
 */
export function InventoryTile({
  item,
  width,
  height,
  compact,
  peek = false,
  onPress,
}: {
  item: InventoryEntry;
  width: number;
  height: number;
  /** The 800x480 panel. */
  compact: boolean;
  peek?: boolean;
  onPress: () => void;
}) {
  const colors = useColors();
  const styles = useMemo(() => makeStyles(colors), [colors]);
  const days = item.expires_in_days;
  const dateTone = expiryTone(days, item.leftovers);
  const tone = urgency(item);
  const padding = compact ? 10 : 14;
  const border = tone ? 2 : 1;
  const glance =
    days != null
      ? glanceWord(days)
      : item.image_url
        ? "Not identified"
        : "No date";
  const size = glanceSize(glance, width - 2 * (padding + border), compact);

  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={`${item.name}: ${glance}`}
      style={({ pressed }) => [
        styles.tile,
        { width, height, padding },
        tone && { borderColor: colors[tone], borderWidth: border },
        pressed && { opacity: 0.7 },
      ]}
    >
      <Text
        style={[styles.name, compact && { fontSize: 16 }, KEEP_WORDS]}
        numberOfLines={peek || compact ? 1 : 2}
      >
        {item.name}
      </Text>
      {!peek && (
        <>
          <Text
            style={[
              styles.glance,
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
          {/* The camera's photo, for items it couldn't name: shows what was seen instead of a guess. */}
          {item.image_url ? (
            <Image
              source={{ uri: `${API_URL}${item.image_url}` }}
              style={styles.photo}
              resizeMode="cover"
            />
          ) : (
            <View style={{ flex: 1 }} />
          )}
          <Text
            style={[styles.amount, compact && { fontSize: 15 }]}
            numberOfLines={1}
          >
            {/* Seen by the camera but never on the scale: no weight to show, and none is guessed. */}
            {item.grams > 0 ? amountText(item, compact) : "Not weighed"}
          </Text>
          {item.fill_fraction != null && (
            <FillBar fraction={item.fill_fraction} tone={tone} />
          )}
        </>
      )}
    </Pressable>
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
    name: { color: colors.text, fontSize: 18, fontWeight: "700" },
    glance: { color: colors.text, fontWeight: "700", marginTop: 4 },
    amount: { color: colors.muted, fontSize: 17, fontWeight: "500" },
    photo: { flex: 1, minHeight: 40, marginVertical: 8, borderRadius: 10 },
  });
