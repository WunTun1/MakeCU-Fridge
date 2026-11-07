import FontAwesome from '@expo/vector-icons/FontAwesome';
import { Link } from 'expo-router';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import type { Macros, Profile } from '@/lib/api';
import { colors, ui } from '@/lib/theme';

const mealsText = (n: number) => (n === 1 ? '1 meal' : `${n} meals`);

/**
 * Today's intake as one tappable card that opens the full log. The goal decides the headline:
 * protein in protein mode, calories otherwise; the other one is the muted line.
 */
export function TodayCard({ totals, mealCount, profile }: { totals: Macros; mealCount: number; profile: Profile | null }) {
  const protein = Math.round(totals.protein_g || 0);
  const kcal = Math.round(totals.calories || 0);
  const headline = profile?.protein_mode
    ? { label: 'Protein', value: protein, goal: profile.daily_protein_g, unit: 'g', other: `${kcal.toLocaleString()} kcal` }
    : { label: 'Calories', value: kcal, goal: profile?.daily_calories, unit: 'kcal', other: `${protein} g protein` };
  const amount = headline.goal
    ? `${headline.value.toLocaleString()} of ${Math.round(headline.goal).toLocaleString()} ${headline.unit}`
    : `${headline.value.toLocaleString()} ${headline.unit}`;
  const pct = headline.goal ? Math.min(headline.value / headline.goal, 1) * 100 : 0;

  return (
    <Link href="/today" asChild>
      <Pressable style={styles.card} accessibilityRole="button" accessibilityLabel={`Today: ${headline.label} ${amount}. Open the log`}>
        <View style={{ flex: 1, gap: 8 }}>
          <View style={styles.headline}>
            <Text style={styles.label}>{headline.label}</Text>
            <Text style={styles.amount}>{amount}</Text>
          </View>
          {headline.goal ? (
            <View style={styles.track}>
              <View style={[styles.fill, { width: `${pct}%` }]} />
            </View>
          ) : null}
          <Text style={ui.muted}>
            {headline.other} · {mealsText(mealCount)}
          </Text>
        </View>
        <FontAwesome name="chevron-right" color={colors.muted} />
      </Pressable>
    </Link>
  );
}

// Children of <Link asChild> must get one style object — expo-router throws on style arrays.
const styles = StyleSheet.create({
  card: {
    ...StyleSheet.flatten(ui.card),
    padding: 16,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
  },
  headline: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'baseline', gap: 8 },
  label: { color: colors.text, fontSize: 17, lineHeight: 22, fontWeight: '600' },
  amount: { color: colors.text, fontSize: 20, lineHeight: 24, fontWeight: '700' },
  track: { height: 8, borderRadius: 4, backgroundColor: colors.border, overflow: 'hidden' },
  fill: { height: '100%', backgroundColor: colors.accent },
});
