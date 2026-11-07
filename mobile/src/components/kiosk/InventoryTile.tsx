import { Pressable, StyleSheet, Text } from 'react-native';

import { FillBar } from '@/components/FillBar';
import type { InventoryEntry } from '@/lib/api';
import { expiryColor, expiryText } from '@/lib/expiry';
import { colors, formatGrams } from '@/lib/theme';

const LOW_DAYS = 2;
const EXPIRING_DAYS = 1;

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
  const expiring = item.expires_in_days != null && item.expires_in_days <= EXPIRING_DAYS;
  const border = expiring ? colors.danger : low ? colors.warn : undefined;
  return (
    <Pressable
      onPress={onPress}
      style={({ pressed }) => [styles.tile, { width }, border && { borderColor: border }, pressed && { opacity: 0.7 }]}
    >
      <Text style={styles.name} numberOfLines={2}>
        {item.name}
      </Text>
      <Text style={styles.amount}>{formatGrams(item.grams)}</Text>
      {item.fill_fraction != null && <FillBar fraction={item.fill_fraction} />}
      <Text style={[styles.line, low && { color: colors.warn }]}>
        {item.days_left != null ? `Runs out in ${item.days_left.toFixed(1)} days` : 'New'}
      </Text>
      {item.expires_in_days != null && (
        <Text style={[styles.line, { color: expiryColor(item.expires_in_days) }]}>
          {expiryText(item.expires_in_days, item.expiry_estimated)}
        </Text>
      )}
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
  line: { color: colors.muted, fontSize: 14 },
});
