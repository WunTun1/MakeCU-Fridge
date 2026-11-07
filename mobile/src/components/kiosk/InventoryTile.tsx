import { useMemo } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { FillBar } from '@/components/FillBar';
import { formatAmount } from '@/lib/amount';
import type { InventoryEntry } from '@/lib/api';
import { expiryTone, expiryWord } from '@/lib/expiry';
import { type Palette, useColors } from '@/lib/theme';
import { capitalize } from '@/lib/time';

/**
 * One item on the fridge screen. The biggest text answers "when does it go
 * bad?"; the amount and fill bar come second.
 */
export function InventoryTile({
  item,
  width,
  height,
  compact,
  onPress,
}: {
  item: InventoryEntry;
  width: number;
  height: number;
  /** The 800x480 panel. */
  compact: boolean;
  onPress: () => void;
}) {
  const colors = useColors();
  const styles = useMemo(() => makeStyles(colors), [colors]);
  const days = item.expires_in_days;
  const tone = expiryTone(days);
  const toneColor = tone ? colors[tone] : null;

  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      style={({ pressed }) => [
        styles.tile,
        { width, height, padding: compact ? 10 : 14 },
        toneColor && { borderColor: toneColor, borderWidth: 2 },
        pressed && { opacity: 0.7 },
      ]}
    >
      <Text style={[styles.name, compact && { fontSize: 16 }]} numberOfLines={compact ? 1 : 2}>
        {item.name}
      </Text>
      <Text
        style={[
          styles.glance,
          compact && { fontSize: 24, lineHeight: 28 },
          days == null ? { color: colors.muted } : toneColor && { color: toneColor },
        ]}
        numberOfLines={2}
      >
        {days == null ? 'No date' : expiryWord(days)}
      </Text>
      <View style={{ flex: 1 }} />
      <Text style={[styles.amount, compact && { fontSize: 15 }]} numberOfLines={1}>
        {capitalize(formatAmount(item.grams, item.unit, item.grams_per_unit, item.name))}
      </Text>
      {item.fill_fraction != null && <FillBar fraction={item.fill_fraction} tone={tone} />}
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
    glance: { color: colors.text, fontSize: 30, lineHeight: 34, fontWeight: '700', marginTop: 4 },
    amount: { color: colors.muted, fontSize: 17, fontWeight: '500' },
  });
