import { Pressable, Text } from 'react-native';

import type { RecipeCard } from '@/lib/api';
import { makeStyles, useTextScale } from '@/lib/theme';

/** At Large text "30 min · 22 g protein · 764 kcal" needs two lines; at Default it fits in one. */
const metaLines = (scale: number) => (scale > 1 ? 2 : 1);

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

/** "45 min", "4 h", "1 h 30 min". */
function duration(min: number): string {
  const h = Math.floor(min / 60);
  const m = min % 60;
  if (h === 0) return `${m} min`;
  return m === 0 ? `${h} h` : `${h} h ${m} min`;
}

/** "17 min", or "17 min + 4 h marinating" when the steps call for waiting. Null when unknown. */
export function minutesText(r: Pick<RecipeCard, 'minutes' | 'inactive_min' | 'inactive_verb'>): string | null {
  if (r.minutes == null) return null;
  const wait = r.inactive_min ? ` + ${duration(r.inactive_min)}${r.inactive_verb ? ` ${r.inactive_verb}` : ''}` : '';
  return `${r.minutes} min${wait}`;
}

/** "35 g protein · 362 kcal · 40 min" in protein mode, otherwise "40 min · 35 g protein · 362 kcal". */
function metaText(card: RecipeCard, proteinFirst: boolean): string {
  const time = minutesText(card);
  const protein = card.nutrition.protein_g != null && `${Math.round(card.nutrition.protein_g)} g protein`;
  const kcal = card.nutrition.calories != null && `${Math.round(card.nutrition.calories).toLocaleString()} kcal`;
  return (proteinFirst ? [protein, kcal, time] : [time, protein, kcal]).filter(Boolean).join(' · ');
}

/**
 * A recipe in the Cook tonight row or under a chat reply. Text only (the photo is on the recipe
 * page) and one fixed height, so a row of cards never leaves gaps or jumps.
 */
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
  const scale = useTextScale();
  const lines = buyLines(card);
  const buy = [lines.buy, lines.short && (lines.buy ? lines.short.toLowerCase() : lines.short)].filter(Boolean).join(' · ');
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      style={({ pressed }) => [styles.card, pressed && { opacity: 0.75 }]}
    >
      <Text style={styles.name} numberOfLines={2}>
        {card.name}
      </Text>
      <Text style={styles.detail} numberOfLines={metaLines(scale)}>
        {metaText(card, proteinFirst)}
      </Text>
      <Text style={[styles.detail, lines.ready && styles.ready]} numberOfLines={2}>
        {buy}
      </Text>
      {card.uses_expiring.length > 0 && (
        <Text style={styles.detail} numberOfLines={1}>
          Uses your {card.uses_expiring.join(', ')}
        </Text>
      )}
    </Pressable>
  );
}

/**
 * Shared with the other cards in the Cook tonight row. 264 wide, and tall enough for a 2-line title,
 * the meta line, a 2-line Buy line and "Uses your" (160 at Default text, 208 at Large).
 */
export const useRecipeCardStyles = makeStyles((c, size) => ({
  card: {
    width: 264,
    height: 2 * 16 + 2 * size(22) + 4 + (3 + metaLines(size(20) / 20)) * size(20),
    padding: 16,
    backgroundColor: c.card,
    borderColor: c.border,
    borderWidth: 1,
    borderRadius: 12,
    overflow: 'hidden',
  },
  name: { color: c.text, fontSize: size(17), lineHeight: size(22), fontWeight: '600', marginBottom: 4 },
  detail: { color: c.textSecondary, fontSize: size(15), lineHeight: size(20) },
  ready: { color: c.accent, fontWeight: '600' },
}));
