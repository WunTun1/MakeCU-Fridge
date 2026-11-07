import { StyleSheet, View } from 'react-native';

import { colors } from '@/lib/theme';

export function FillBar({ fraction }: { fraction: number }) {
  const pct = Math.max(0, Math.min(fraction, 1)) * 100;
  return (
    <View style={styles.track}>
      <View style={[styles.fill, { width: `${pct}%` }]} />
    </View>
  );
}

const styles = StyleSheet.create({
  track: { height: 6, width: '100%', backgroundColor: colors.border, borderRadius: 4, overflow: 'hidden', marginTop: 4 },
  fill: { height: '100%', backgroundColor: colors.accent },
});
