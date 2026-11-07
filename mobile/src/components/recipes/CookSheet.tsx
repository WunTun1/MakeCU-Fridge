import { useEffect, useState } from 'react';
import { ActivityIndicator, Modal, Pressable, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { Button } from '@/components/Button';
import { Segmented } from '@/components/Segmented';
import { Stepper } from '@/components/Stepper';
import { formatAmount } from '@/lib/amount';
import { api, type CookLine, type Made, type Nutrition } from '@/lib/api';
import { colors, ui } from '@/lib/theme';
import { capitalize, whenWord } from '@/lib/time';

const MAX_SERVINGS = 12;
/** Cooked leftovers keep this long in the fridge (same as the backend's LEFTOVER_DAYS). */
const LEFTOVER_DAYS = 3;
const MADE_OPTIONS: { value: Made; label: string }[] = [
  { value: 1, label: 'Full recipe' },
  { value: 0.5, label: 'Half' },
];

/** Whether a line takes everything there is (within a gram). */
export const usesAll = (line: CookLine) => line.grams_used >= line.grams_on_hand - 1;

/** "Chicken breast: 400 g of 683 g", "Baby spinach: all 150 g". */
function lineText(line: CookLine): string {
  const amount = (g: number) => formatAmount(g, line.unit, line.grams_per_unit, line.item);
  const name = capitalize(line.item.toLowerCase());
  return usesAll(line) ? `${name}: all ${amount(line.grams_on_hand)}` : `${name}: ${amount(line.grams_used)} of ${amount(line.grams_on_hand)}`;
}

/** "Makes 4 servings" for what was cooked, or that the recipe doesn't say. */
function yieldText(servings: number | null, made: Made): string {
  if (!servings) return "The recipe doesn't say how many it serves";
  const n = Math.max(1, Math.round(servings * made));
  return `Makes ${n} serving${n === 1 ? '' : 's'}`;
}

/** "3 servings left over. They'll keep until Tuesday." Null when nothing is left or the yield is unknown. */
function leftoverText(servings: number | null, made: Made, eaten: number): string | null {
  const left = servings ? Math.round(servings * made - eaten) : 0;
  if (left < 1) return null;
  const until = capitalize(whenWord(LEFTOVER_DAYS));
  return left === 1 ? `1 serving left over. It'll keep until ${until}.` : `${left} servings left over. They'll keep until ${until}.`;
}

/** "Logs 1,780 kcal and 104 g protein". */
function nutritionText(n: Nutrition, servings: number): string | null {
  const parts = [
    n.calories != null && `${Math.round(n.calories * servings).toLocaleString()} kcal`,
    n.protein_g != null && `${Math.round(n.protein_g * servings)} g protein`,
  ].filter(Boolean);
  return parts.length ? `Logs ${parts.join(' and ')}` : null;
}

/**
 * Confirm "I made this". Two separate questions: how much was cooked (that leaves the
 * fridge) and how much you ate (that goes in today's nutrition).
 */
export function CookSheet({
  recipeId,
  recipeName,
  servings,
  nutrition,
  visible,
  onClose,
  onLog,
}: {
  recipeId: number;
  recipeName: string;
  /** How many the full recipe serves; null when the source doesn't say. */
  servings: number | null;
  /** Per serving. */
  nutrition: Nutrition;
  visible: boolean;
  onClose: () => void;
  onLog: (made: Made, servingsEaten: number) => Promise<void>;
}) {
  const insets = useSafeAreaInsets();
  const [made, setMade] = useState<Made>(1);
  const [eaten, setEaten] = useState(1);
  const [lines, setLines] = useState<CookLine[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [logging, setLogging] = useState(false);

  useEffect(() => {
    if (!visible) return;
    let cancelled = false;
    api
      .cookPreview(recipeId, made)
      .then((l) => !cancelled && (setLines(l), setError(null)))
      .catch((e) => !cancelled && setError((e as Error).message));
    return () => {
      cancelled = true;
    };
  }, [recipeId, made, visible]);

  async function log() {
    setLogging(true);
    try {
      await onLog(made, eaten);
    } finally {
      setLogging(false);
    }
  }

  const logs = nutritionText(nutrition, eaten);
  const leftover = leftoverText(servings, made, eaten);

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <Pressable style={styles.backdrop} onPress={onClose} accessibilityLabel="Close" />
      <View style={[styles.sheet, { paddingBottom: 16 + insets.bottom }]}>
        <Text style={styles.title} numberOfLines={2}>
          Log {recipeName}?
        </Text>

        <View style={styles.question}>
          <Text style={styles.label}>How much did you make?</Text>
          <Segmented label="How much did you make?" options={MADE_OPTIONS} value={made} onChange={setMade} />
          <Text style={ui.muted}>{yieldText(servings, made)}</Text>
        </View>

        <View style={{ gap: 4 }}>
          <Text style={ui.muted}>This takes from your fridge and pantry:</Text>
          {error && <Text style={ui.muted}>Couldn&apos;t work it out: {error}</Text>}
          {!lines && !error && <ActivityIndicator color={colors.accent} style={{ alignSelf: 'flex-start' }} />}
          {lines?.length === 0 && <Text style={ui.text}>Nothing you track. It only logs the meal.</Text>}
          {lines?.map((line) => (
            <Text key={line.product_id} style={ui.text}>
              {lineText(line)}
            </Text>
          ))}
        </View>

        <View style={styles.question}>
          <View style={[ui.row, { justifyContent: 'space-between' }]}>
            <Text style={styles.label}>How much did you eat?</Text>
            <Stepper
              minusLabel="Fewer servings"
              plusLabel="More servings"
              value={`${eaten}`}
              canMinus={eaten > 1}
              canPlus={eaten < MAX_SERVINGS}
              onMinus={() => setEaten((s) => s - 1)}
              onPlus={() => setEaten((s) => s + 1)}
            />
          </View>
          <Text style={ui.muted}>
            {eaten === 1 ? '1 serving' : `${eaten} servings`}
            {logs ? `. ${logs}` : ''}
          </Text>
          {leftover && <Text style={ui.muted}>{leftover}</Text>}
        </View>

        <View style={{ minHeight: 48, flexDirection: 'row' }}>
          <Button title={logging ? 'Logging…' : 'Log it'} onPress={log} disabled={logging || !lines} />
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: '#000a' },
  sheet: {
    backgroundColor: colors.card,
    borderTopLeftRadius: 12,
    borderTopRightRadius: 12,
    borderColor: colors.border,
    borderWidth: 1,
    padding: 16,
    gap: 16,
  },
  title: { color: colors.text, fontSize: 22, lineHeight: 28, fontWeight: '700' },
  question: { gap: 8 },
  label: { color: colors.text, fontSize: 17, lineHeight: 22, fontWeight: '600' },
});
