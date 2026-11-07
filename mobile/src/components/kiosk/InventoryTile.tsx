import { useMemo } from 'react';
import { Platform, Pressable, StyleSheet, Text, View, type TextStyle } from 'react-native';

import { FillBar } from '@/components/FillBar';
import { formatAmount } from '@/lib/amount';
import type { InventoryEntry } from '@/lib/api';
import { expiryTone, glanceWord, runsOutSoon, soonestPart, urgency } from '@/lib/expiry';
import { type Palette, useColors } from '@/lib/theme';
import { capitalize, shortWeekday } from '@/lib/time';

/** Average glyph width of the bold system font, as a share of the font size. */
const GLYPH_W = 0.62;
const GLANCE_SIZE = { regular: [24, 30], compact: [20, 24] } as const;

/** Words wrap only at spaces. react-native-web's Text defaults to breaking inside words. */
const KEEP_WORDS = Platform.select<TextStyle>({
  web: { wordBreak: 'keep-all', overflowWrap: 'normal', wordWrap: 'normal' } as TextStyle,
  default: {},
});

/** The biggest size at which the glance value's longest word still fits the tile on one line. */
function glanceSize(text: string, contentW: number, compact: boolean): number {
  const [min, max] = compact ? GLANCE_SIZE.compact : GLANCE_SIZE.regular;
  const longest = Math.max(...text.split(' ').map((w) => w.length));
  return Math.max(min, Math.min(max, Math.floor(contentW / (GLYPH_W * longest))));
}

/** "3 L · 1 L by Mon" when only the older package goes bad soon (the wide panel has room for it). */
function amountText(item: InventoryEntry, compact: boolean): string {
  const total = capitalize(formatAmount(item.grams, item.unit, item.grams_per_unit, item.name));
  const part = compact ? null : soonestPart(item);
  const parts = [part ? `${total} · ${part} by ${shortWeekday(item.soonest_batch!.expiration_date)}` : total];
  if (runsOutSoon(item)) parts.push('low');
  return parts.join(' · ');
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
  const dateTone = expiryTone(days);
  const tone = urgency(item);
  const padding = compact ? 10 : 14;
  const border = tone ? 2 : 1;
  const glance = days == null ? 'No date' : glanceWord(days);
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
      <Text style={[styles.name, compact && { fontSize: 16 }, KEEP_WORDS]} numberOfLines={peek || compact ? 1 : 2}>
        {item.name}
      </Text>
      {!peek && (
        <>
          <Text
            style={[
              styles.glance,
              { fontSize: size, lineHeight: size + 4 },
              KEEP_WORDS,
              days == null ? { color: colors.muted } : dateTone && { color: colors[dateTone] },
            ]}
            numberOfLines={2}
          >
            {glance}
          </Text>
          <View style={{ flex: 1 }} />
          <Text style={[styles.amount, compact && { fontSize: 15 }]} numberOfLines={1}>
            {amountText(item, compact)}
          </Text>
          {item.fill_fraction != null && <FillBar fraction={item.fill_fraction} tone={tone} />}
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
    name: { color: colors.text, fontSize: 18, fontWeight: '700' },
    glance: { color: colors.text, fontWeight: '700', marginTop: 4 },
    amount: { color: colors.muted, fontSize: 17, fontWeight: '500' },
  });
