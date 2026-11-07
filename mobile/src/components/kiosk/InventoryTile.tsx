import { useMemo } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { FillBar } from '@/components/FillBar';
import type { InventoryEntry } from '@/lib/api';
import { formatGrams, type Palette, useColors } from '@/lib/theme';

export type TileFlag = 'danger' | 'warn' | null;

export function InventoryTile({
  item,
  width,
  height,
  flag,
  note,
  onPress,
}: {
  item: InventoryEntry;
  width: number;
  height: number;
  /** Highlights the tile when the item needs attention. */
  flag: TileFlag;
  /** Replaces the "days left" line, e.g. an alert's detail. */
  note?: string;
  onPress: () => void;
}) {
  const colors = useColors();
  const styles = useMemo(() => makeStyles(colors), [colors]);
  const tone = flag ? colors[flag] : null;
  const compact = height < 120;
  const roomy = height >= 170;

  return (
    <Pressable
      onPress={onPress}
      style={({ pressed }) => [
        styles.tile,
        { width, height, padding: compact ? 10 : 14 },
        tone && { borderColor: tone, borderWidth: 2 },
        pressed && { opacity: 0.7 },
      ]}
    >
      <View>
        <Text style={styles.name} numberOfLines={roomy ? 2 : 1}>
          {item.name}
        </Text>
        <Text style={[styles.amount, compact && { fontSize: 19 }, roomy && { fontSize: 30, marginTop: 4 }]}>
          {formatGrams(item.grams)}
        </Text>
      </View>
      <View>
        {item.fill_fraction != null && <FillBar fraction={item.fill_fraction} />}
        <Text style={[styles.days, tone && { color: tone, fontWeight: '600' }]} numberOfLines={1}>
          {note ?? (item.days_left != null ? `${item.days_left.toFixed(1)} days left` : 'new')}
        </Text>
      </View>
    </Pressable>
  );
}

const makeStyles = (colors: Palette) =>
  StyleSheet.create({
    tile: {
      backgroundColor: colors.card,
      borderColor: colors.border,
      borderWidth: 1,
      borderRadius: 16,
      justifyContent: 'space-between',
    },
    name: { color: colors.text, fontSize: 17, fontWeight: '700' },
    amount: { color: colors.text, fontSize: 22, fontWeight: '300' },
    days: { color: colors.muted, fontSize: 13, marginTop: 4 },
  });
