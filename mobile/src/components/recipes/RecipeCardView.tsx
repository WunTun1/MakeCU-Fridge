import { Image, Pressable, StyleSheet, Text, View } from 'react-native';

import type { RecipeCard } from '@/lib/api';
import { colors } from '@/lib/theme';

const firstTwo = (names: string[]) => names.slice(0, 2).join(', ') + (names.length > 2 ? '…' : '');

/**
 * "You have everything" only when every counted ingredient is there in the amount needed;
 * otherwise "Need 1 of 6: vidalia onion · Short on spinach".
 */
function cardStatus(card: RecipeCard): { text: string; ready: boolean } {
  const short = card.short ?? []; // cards saved in chat history before "short" existed
  const total = card.have_count + card.swaps.length + short.length + card.missing.length;
  if (card.missing.length === 0 && short.length === 0) {
    const swaps = card.swaps.length;
    return { text: swaps ? `Ready with ${swaps} swap${swaps > 1 ? 's' : ''}` : 'You have everything', ready: true };
  }
  const parts = [];
  if (card.missing.length) parts.push(`Need ${card.missing.length} of ${total}: ${firstTwo(card.missing)}`);
  if (short.length) parts.push(`Short on ${firstTwo(short.map((s) => s.name))}`);
  return { text: parts.join(' · '), ready: false };
}

/** "35 g protein · 362 kcal · 40 min" in protein mode, otherwise "40 min · 35 g protein · 362 kcal". */
function metaText(card: RecipeCard, proteinFirst: boolean): string {
  const time = card.minutes != null && `${card.minutes} min`;
  const protein = card.nutrition.protein_g != null && `${Math.round(card.nutrition.protein_g)} g protein`;
  const kcal = card.nutrition.calories != null && `${Math.round(card.nutrition.calories)} kcal`;
  return (proteinFirst ? [protein, kcal, time] : [time, protein, kcal]).filter(Boolean).join(' · ');
}

/** Compact recipe card for chat and suggestion rows. `large` is the fridge-screen size. A card without a photo has no image area. */
export function RecipeCardView({
  card,
  onPress,
  large = false,
  proteinFirst = false,
}: {
  card: RecipeCard;
  onPress: () => void;
  large?: boolean;
  /** Protein mode: the meta line leads with protein. */
  proteinFirst?: boolean;
}) {
  const width = large ? 250 : 210;
  const status = cardStatus(card);
  return (
    <Pressable
      onPress={onPress}
      style={({ pressed }) => [styles.card, { width }, pressed && { opacity: 0.75 }]}
    >
      {card.image_url && <Image source={{ uri: card.image_url }} style={[styles.image, { height: large ? 120 : 100 }]} />}
      <View style={styles.body}>
        <Text style={[styles.name, large && { fontSize: 17 }]} numberOfLines={2}>
          {card.name}
        </Text>
        <Text style={styles.meta} numberOfLines={1}>
          {metaText(card, proteinFirst)}
        </Text>
        <Text style={[styles.status, { color: status.ready ? colors.accent : colors.text }]} numberOfLines={2}>
          {status.text}
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
  body: { padding: 10, gap: 3 },
  name: { color: colors.text, fontSize: 15, fontWeight: '700' },
  meta: { color: colors.muted, fontSize: 13 },
  status: { fontSize: 13, fontWeight: '600' },
  expiring: { color: colors.accent, fontSize: 12 },
});
