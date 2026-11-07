import { useEffect, useState } from 'react';
import { ActivityIndicator, Modal, Pressable, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { Button } from '@/components/Button';
import { Stepper } from '@/components/Stepper';
import { formatAmount } from '@/lib/amount';
import { api, type CookLine } from '@/lib/api';
import { colors, ui } from '@/lib/theme';
import { capitalize } from '@/lib/time';

const MAX_SERVINGS = 12;

/** Whether a line takes everything there is (within a gram). */
export const usesAll = (line: CookLine) => line.grams_used >= line.grams_on_hand - 1;

/** "Chicken breast: 400 g of 683 g", "Baby spinach: all 150 g". */
function lineText(line: CookLine): string {
  const amount = (g: number) => formatAmount(g, line.unit, line.grams_per_unit, line.item);
  const name = capitalize(line.item.toLowerCase());
  return usesAll(line) ? `${name}: all ${amount(line.grams_on_hand)}` : `${name}: ${amount(line.grams_used)} of ${amount(line.grams_on_hand)}`;
}

/** Confirm "I made this": pick servings and see exactly what comes out of the fridge first. */
export function CookSheet({
  recipeId,
  recipeName,
  visible,
  onClose,
  onLog,
}: {
  recipeId: number;
  recipeName: string;
  visible: boolean;
  onClose: () => void;
  onLog: (servings: number) => Promise<void>;
}) {
  const insets = useSafeAreaInsets();
  const [servings, setServings] = useState(1);
  const [lines, setLines] = useState<CookLine[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [logging, setLogging] = useState(false);

  useEffect(() => {
    if (!visible) return;
    let cancelled = false;
    api
      .cookPreview(recipeId, servings)
      .then((l) => !cancelled && (setLines(l), setError(null)))
      .catch((e) => !cancelled && setError((e as Error).message));
    return () => {
      cancelled = true;
    };
  }, [recipeId, servings, visible]);

  async function log() {
    setLogging(true);
    try {
      await onLog(servings);
    } finally {
      setLogging(false);
    }
  }

  const plural = servings === 1 ? 'serving' : 'servings';

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <Pressable style={styles.backdrop} onPress={onClose} accessibilityLabel="Close" />
      <View style={[styles.sheet, { paddingBottom: 16 + insets.bottom }]}>
        <Text style={styles.title} numberOfLines={2}>
          Log {recipeName}?
        </Text>

        <View style={[ui.row, { justifyContent: 'space-between' }]}>
          <Text style={ui.text}>Servings</Text>
          <Stepper
            label="servings"
            value={String(servings)}
            canMinus={servings > 1}
            canPlus={servings < MAX_SERVINGS}
            onMinus={() => setServings((s) => s - 1)}
            onPlus={() => setServings((s) => s + 1)}
          />
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

        <View style={{ minHeight: 48, flexDirection: 'row' }}>
          <Button title={logging ? 'Logging…' : `Log ${servings} ${plural}`} onPress={log} disabled={logging || !lines} />
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
});
