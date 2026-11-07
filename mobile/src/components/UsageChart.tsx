import { StyleSheet, Text, View } from 'react-native';

import { colors, formatGrams, ui } from '@/lib/theme';

function lastNDays(n: number): string[] {
  const today = new Date();
  return Array.from({ length: n }, (_, i) => {
    const d = new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate() - (n - 1 - i)));
    return d.toISOString().slice(0, 10);
  });
}

/** Daily usage bars from /api/products/{id}/usage's `daily_usage_g`. */
export function UsageChart({
  dailyUsage,
  days = 28,
  height = 120,
}: {
  dailyUsage: Record<string, number>;
  days?: number;
  height?: number;
}) {
  const labels = lastNDays(days);
  const values = labels.map((d) => dailyUsage[d] ?? 0);
  const max = Math.max(...values, 1);

  return (
    <View>
      <View style={[styles.chart, { height }]}>
        {values.map((v, i) => (
          <View key={labels[i]} style={styles.slot}>
            <View style={[styles.bar, { height: (v / max) * height }]} />
          </View>
        ))}
      </View>
      <View style={[ui.row, { justifyContent: 'space-between', marginTop: 6 }]}>
        <Text style={ui.muted}>{labels[0].slice(5)}</Text>
        <Text style={ui.muted}>peak {formatGrams(max)}/day</Text>
        <Text style={ui.muted}>today</Text>
      </View>
    </View>
  );
}

export function averagePerDay(dailyUsage: Record<string, number>, days = 28): number {
  return lastNDays(days).reduce((sum, d) => sum + (dailyUsage[d] ?? 0), 0) / days;
}

const styles = StyleSheet.create({
  chart: { flexDirection: 'row', alignItems: 'flex-end', gap: 2 },
  slot: { flex: 1, height: '100%', justifyContent: 'flex-end' },
  bar: { backgroundColor: colors.accent, borderRadius: 2, minHeight: 1 },
});
