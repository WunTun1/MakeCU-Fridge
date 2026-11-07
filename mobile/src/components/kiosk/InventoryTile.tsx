import { Pressable, StyleSheet, Text } from 'react-native';

import { FillBar } from '@/components/FillBar';
import type { InventoryEntry } from '@/lib/api';
import { colors, formatGrams } from '@/lib/theme';

const LOW_DAYS = 2;

export function InventoryTile({
  item,
  width,
  onPress,
}: {
  item: InventoryEntry;
  width: number;
  onPress: () => void;
}) {
  const low = item.days_left != null && item.days_left <= LOW_DAYS;
  return (
    <Pressable
      onPress={onPress}
      style={({ pressed }) => [styles.tile, { width }, low && { borderColor: colors.warn }, pressed && { opacity: 0.7 }]}
    >
      <Text style={styles.name} numberOfLines={1}>
        {item.name}
      </Text>
      <Text style={styles.amount}>{formatGrams(item.grams)}</Text>
      {item.fill_fraction != null && <FillBar fraction={item.fill_fraction} />}
      <Text style={[styles.days, low && { color: colors.warn }]}>
        {item.days_left != null ? `${item.days_left.toFixed(1)} days left` : 'new'}
      </Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  tile: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 16,
    padding: 14,
    gap: 4,
    minHeight: 112,
  },
  name: { color: colors.text, fontSize: 18, fontWeight: '700' },
  amount: { color: colors.text, fontSize: 22, fontWeight: '300' },
  days: { color: colors.muted, fontSize: 14, marginTop: 4 },
});
