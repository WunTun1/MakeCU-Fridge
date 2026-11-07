import { StyleSheet, View } from 'react-native';

import { useColors } from '@/lib/theme';

export function FillBar({ fraction }: { fraction: number }) {
  const c = useColors();
  const pct = Math.max(0, Math.min(fraction, 1)) * 100;
  return (
    <View style={[styles.track, { backgroundColor: c.border }]}>
      <View style={[styles.fill, { width: `${pct}%`, backgroundColor: c.accent }]} />
    </View>
  );
}

const styles = StyleSheet.create({
  track: { height: 6, width: '100%', borderRadius: 4, overflow: 'hidden', marginTop: 4 },
  fill: { height: '100%' },
});
