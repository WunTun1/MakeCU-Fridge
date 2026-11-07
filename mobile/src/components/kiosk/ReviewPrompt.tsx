import FontAwesome from '@expo/vector-icons/FontAwesome';
import { useState, useMemo } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { api, type ReviewItem } from '@/lib/api';
import { candidateName, describeReview, isUnnamedAdd } from '@/lib/review';
import { type Palette, useColors } from '@/lib/theme';

const MAX_CHOICES = 7;

/**
 * Asks about the oldest open review right at the fridge. Tap-only on purpose:
 * a fridge screen has no keyboard, so names come from the AI's guess plus the
 * products you add most often. Anything else can be answered from the phone app.
 */
export function ReviewPrompt({
  review,
  remaining,
  commonNames,
  onResolved,
}: {
  review: ReviewItem;
  remaining: number;
  commonNames: string[];
  onResolved: () => void;
}) {
  const colors = useColors();
  const styles = useMemo(() => makeStyles(colors), [colors]);
  const [busy, setBusy] = useState(false);
  const unnamed = isUnnamedAdd(review);
  const guess = candidateName(review);
  const choices = [...new Set([guess, ...commonNames].filter((n): n is string => !!n))].slice(0, MAX_CHOICES);

  async function resolve(body: Parameters<typeof api.resolveReview>[1]) {
    setBusy(true);
    try {
      await api.resolveReview(review.id, body);
      onResolved();
    } finally {
      setBusy(false);
    }
  }

  return (
    <View style={styles.card}>
      <View style={styles.titleRow}>
        <FontAwesome name="question-circle" size={22} color={colors.warn} />
        <Text style={styles.title}>{describeReview(review)}</Text>
        {remaining > 1 && <Text style={styles.more}>+{remaining - 1} more</Text>}
      </View>

      <View style={styles.choices}>
        {unnamed &&
          choices.map((name) => (
            <Pressable
              key={name}
              disabled={busy}
              onPress={() => resolve({ action: 'add_confirmed', product_name: name })}
              style={({ pressed }) => [styles.choice, name === guess && styles.guess, pressed && { opacity: 0.6 }]}
            >
              <Text style={[styles.choiceText, name === guess && { color: colors.onAccent }]}>{name}</Text>
            </Pressable>
          ))}
        {review.item_id != null && (
          <Pressable
            disabled={busy}
            onPress={() => resolve({ action: 'remove', item_id: review.item_id! })}
            style={({ pressed }) => [styles.choice, { borderColor: colors.danger }, pressed && { opacity: 0.6 }]}
          >
            <Text style={[styles.choiceText, { color: colors.danger }]}>It was taken out</Text>
          </Pressable>
        )}
        <Pressable
          disabled={busy}
          onPress={() => resolve({ action: 'ignore' })}
          style={({ pressed }) => [styles.choice, styles.dismiss, pressed && { opacity: 0.6 }]}
        >
          <Text style={[styles.choiceText, { color: colors.muted }]}>{unnamed ? 'Something else' : 'Dismiss'}</Text>
        </Pressable>
      </View>
      {unnamed && <Text style={styles.hint}>Not listed? Tap “Something else” and name it from the phone app.</Text>}
    </View>
  );
}

const makeStyles = (colors: Palette) =>
  StyleSheet.create({
    card: {
      backgroundColor: colors.card,
      borderColor: colors.warn,
      borderWidth: 2,
      borderRadius: 18,
      padding: 16,
      gap: 12,
    },
    titleRow: { flexDirection: 'row', alignItems: 'center', gap: 10 },
    title: { color: colors.text, fontSize: 20, fontWeight: '700', flex: 1 },
    more: { color: colors.muted, fontSize: 14 },
    choices: { flexDirection: 'row', flexWrap: 'wrap', gap: 10 },
    choice: {
      minHeight: 52,
      paddingHorizontal: 20,
      justifyContent: 'center',
      borderRadius: 14,
      borderWidth: 1,
      borderColor: colors.border,
      backgroundColor: colors.input,
    },
    guess: { backgroundColor: colors.accent, borderColor: colors.accent },
    dismiss: { backgroundColor: 'transparent' },
    choiceText: { color: colors.text, fontSize: 18, fontWeight: '600' },
    hint: { color: colors.muted, fontSize: 13 },
  });
