import { useMemo } from 'react';
import { Image, Pressable, StyleSheet, Text, View } from 'react-native';

import { FillBar } from '@/components/FillBar';
import { API_URL, type InventoryEntry } from '@/lib/api';
import { formatGrams, type Palette, useColors } from '@/lib/theme';

/** Border colour: going bad soon (danger/warn), fine for a while (good), or unknown (null). */
export type TileFlag = 'danger' | 'warn' | 'good' | null;

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
        {/* How long it's good for sits right under the name, where the eye lands first. */}
        <Text style={[styles.days, tone && flag !== 'good' && { color: tone }]} numberOfLines={2}>
          {note ?? (item.days_left != null ? `${item.days_left.toFixed(1)} days left` : 'new')}
        </Text>
        {item.grams > 0 ? (
          <Text style={[styles.amount, compact && { fontSize: 19 }, roomy && { fontSize: 30, marginTop: 4 }]}>
            {formatGrams(item.grams)}
          </Text>
        ) : (
          // Seen by the camera but never on the scale: no weight to show, and none is guessed.
          <Text style={styles.notWeighed}>Not weighed</Text>
        )}
      </View>
      {/* The camera's photo, for items it couldn't name: shows what was seen instead of a guess. */}
      {item.image_url ? <Image source={{ uri: `${API_URL}${item.image_url}` }} style={styles.photo} resizeMode="cover" /> : null}
      {item.fill_fraction != null && <FillBar fraction={item.fill_fraction} />}
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
    photo: { flex: 1, minHeight: 40, marginTop: 8, borderRadius: 10 },
    notWeighed: { color: colors.muted, fontSize: 14, marginTop: 4 },
    days: { color: colors.text, fontSize: 15, fontWeight: '700', marginTop: 4 },
  });
