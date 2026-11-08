import { Image, Pressable, Text, View } from 'react-native';

import type { RecipeCard } from '@/lib/api';
import { makeStyles } from '@/lib/theme';

/**
 * What it takes to cook it now: "Nothing to buy", or "Buy feta cheese, cottage cheese", plus
 * "Short on frozen spinach" when something you have isn't enough.
 */
export function buyLines(card: RecipeCard): { buy: string; ready: boolean; short: string | null } {
  const short = card.short ?? []; // cards saved in chat history before "short" existed
  return {
    buy: card.missing.length ? `Buy ${card.missing.join(', ')}` : short.length ? '' : 'Nothing to buy',
    ready: card.missing.length === 0 && short.length === 0,
    short: short.length ? `Short on ${short.map((s) => s.name).join(', ')}` : null,
  };
}

/** "35 g protein · 362 kcal · 40 min" in protein mode, otherwise "40 min · 35 g protein · 362 kcal". */
function metaText(card: RecipeCard, proteinFirst: boolean): string {
  const time = card.minutes != null && `${card.minutes} min`;
  const protein = card.nutrition.protein_g != null && `${Math.round(card.nutrition.protein_g)} g protein`;
  const kcal = card.nutrition.calories != null && `${Math.round(card.nutrition.calories)} kcal`;
  return (proteinFirst ? [protein, kcal, time] : [time, protein, kcal]).filter(Boolean).join(' · ');
}

/** Compact recipe card for chat and suggestion rows. A card without a photo has no image area. */
export function RecipeCardView({
  card,
  onPress,
  proteinFirst = false,
}: {
  card: RecipeCard;
  onPress: () => void;
  /** Protein mode: the meta line leads with protein. */
  proteinFirst?: boolean;
}) {
  const styles = useRecipeCardStyles();
  const lines = buyLines(card);
  return (
    <Pressable onPress={onPress} style={({ pressed }) => [styles.card, pressed && { opacity: 0.75 }]}>
      {card.image_url && <Image source={{ uri: card.image_url }} style={styles.image} />}
      <View style={styles.body}>
        <Text style={styles.name} numberOfLines={3}>
          {card.name}
        </Text>
        <Text style={styles.detail}>{metaText(card, proteinFirst)}</Text>
        {lines.buy !== '' && <Text style={[styles.detail, lines.ready && styles.ready]}>{lines.buy}</Text>}
        {lines.short && <Text style={styles.detail}>{lines.short}</Text>}
        {card.uses_expiring.length > 0 && <Text style={styles.detail}>Uses your {card.uses_expiring.join(', ')}</Text>}
      </View>
    </Pressable>
  );
}

/** Shared with the other cards in the Cook tonight row. */
export const useRecipeCardStyles = makeStyles((c, size) => ({
  card: {
    width: size(230),
    backgroundColor: c.card,
    borderColor: c.border,
    borderWidth: 1,
    borderRadius: 12,
    overflow: 'hidden',
  },
  image: { width: '100%', height: 100, backgroundColor: c.input },
  body: { padding: 12, gap: 4 },
  name: { color: c.text, fontSize: size(15), lineHeight: size(20), fontWeight: '700' },
  detail: { color: c.textSecondary, fontSize: size(15), lineHeight: size(20) },
  ready: { color: c.accent, fontWeight: '600' },
}));
