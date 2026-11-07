import { StyleSheet, Text, View } from 'react-native';

import { formatAmount, type Unit } from '@/lib/amount';
import { calendarDate } from '@/lib/time';
import { ui, useColors } from '@/lib/theme';

const MIN_DAYS = 7;

function lastNDays(n: number): string[] {
  const today = new Date();
  return Array.from({ length: n }, (_, i) => {
    const d = new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate() - (n - 1 - i)));
    return d.toISOString().slice(0, 10);
  });
}

/** Days from the first day with any usage (within `days`) up to today, at least a week. */
function trimmedDays(dailyUsage: Record<string, number>, days: number): string[] {
  const all = lastNDays(days);
  const first = all.findIndex((d) => (dailyUsage[d] ?? 0) > 0);
  return first < 0 ? all.slice(-MIN_DAYS) : all.slice(Math.min(first, days - MIN_DAYS));
}

/** Daily usage bars from /api/products/{id}/usage's `daily_usage_g`. */
export function UsageChart({
  dailyUsage,
  days = 28,
  height = 120,
  unit = 'g',
  gramsPerUnit = 1,
  name,
}: {
  dailyUsage: Record<string, number>;
  days?: number;
  height?: number;
  unit?: Unit;
  gramsPerUnit?: number;
  name?: string;
}) {
  const c = useColors();
  const muted = [ui.muted, { color: c.muted }];
  const labels = trimmedDays(dailyUsage, days);
  const values = labels.map((d) => dailyUsage[d] ?? 0);
  const max = Math.max(...values, 1);

  return (
    <View>
      <View style={[styles.chart, { height }]}>
        {values.map((v, i) => (
          <View key={labels[i]} style={styles.slot}>
            <View style={[styles.bar, { height: (v / max) * height, backgroundColor: c.muted }]} />
          </View>
        ))}
      </View>
      <View style={[ui.row, { justifyContent: 'space-between', marginTop: 8 }]}>
        <Text style={muted}>{calendarDate(labels[0])}</Text>
        <Text style={muted}>most in a day: {formatAmount(max, unit, gramsPerUnit, name)}</Text>
        <Text style={muted}>today</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  chart: { flexDirection: 'row', alignItems: 'flex-end', gap: 2 },
  slot: { flex: 1, height: '100%', justifyContent: 'flex-end' },
  bar: { borderRadius: 2, minHeight: 1 },
});
