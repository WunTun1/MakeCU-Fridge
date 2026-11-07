import FontAwesome from '@expo/vector-icons/FontAwesome';
import { Image, Pressable, StyleSheet, Text, View } from 'react-native';

import type { RecipeCard } from '@/lib/api';
import { colors } from '@/lib/theme';

/** Compact recipe card for chat and suggestion rows. `large` is the fridge-screen size. */
export function RecipeCardView({
  card,
  onPress,
  large = false,
}: {
  card: RecipeCard;
  onPress: () => void;
  large?: boolean;
}) {
  const total = card.have_count + card.swaps.length + card.missing.length;
  const ready = card.missing.length === 0;
  const width = large ? 250 : 210;
  return (
    <Pressable
      onPress={onPress}
      style={({ pressed }) => [styles.card, { width }, pressed && { opacity: 0.75 }]}
    >
      {card.image_url ? (
        <Image source={{ uri: card.image_url }} style={[styles.image, { height: large ? 120 : 100 }]} />
      ) : (
        <View style={[styles.image, styles.noImage, { height: large ? 120 : 100 }]}>
          <FontAwesome name="cutlery" size={28} color={colors.muted} />
        </View>
      )}
      <View style={styles.body}>
        <Text style={[styles.name, large && { fontSize: 17 }]} numberOfLines={2}>
          {card.name}
        </Text>
        <Text style={styles.meta} numberOfLines={1}>
          {[card.minutes != null && `${card.minutes} min`,
            card.nutrition.protein_g != null && `${Math.round(card.nutrition.protein_g)} g protein`,
            card.nutrition.calories != null && `${Math.round(card.nutrition.calories)} kcal`]
            .filter(Boolean)
            .join(' · ')}
        </Text>
        <Text style={[styles.status, { color: ready ? colors.accent : colors.warn }]} numberOfLines={1}>
          {ready
            ? card.swaps.length ? `Ready with ${card.swaps.length} swap${card.swaps.length > 1 ? 's' : ''}` : 'You have everything'
            : `Need ${card.missing.length} of ${total}: ${card.missing.slice(0, 2).join(', ')}${card.missing.length > 2 ? '…' : ''}`}
        </Text>
        {card.uses_expiring.length > 0 && (
          <Text style={styles.expiring} numberOfLines={1}>
            Uses your {card.uses_expiring.join(', ')}
          </Text>
        )}
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 14,
    overflow: 'hidden',
  },
  image: { width: '100%', backgroundColor: colors.input },
  noImage: { alignItems: 'center', justifyContent: 'center' },
  body: { padding: 10, gap: 3 },
  name: { color: colors.text, fontSize: 15, fontWeight: '700' },
  meta: { color: colors.muted, fontSize: 13 },
  status: { fontSize: 13, fontWeight: '600' },
  expiring: { color: colors.accent, fontSize: 12 },
});
