import { StyleSheet, View } from 'react-native';

import type { ExpiryTone } from '@/lib/expiry';
import { useColors } from '@/lib/theme';

/** How full something is. Neutral unless the item is flagged; a bar never borrows the accent. */
export function FillBar({ fraction, tone = null }: { fraction: number; tone?: ExpiryTone }) {
  const c = useColors();
  const pct = Math.max(0, Math.min(fraction, 1)) * 100;
  return (
    <View style={[styles.track, { backgroundColor: c.border }]}>
      <View style={[styles.fill, { width: `${pct}%`, backgroundColor: tone ? c[tone] : c.muted }]} />
    </View>
  );
}

const styles = StyleSheet.create({
  track: { height: 6, width: '100%', borderRadius: 4, overflow: 'hidden', marginTop: 4 },
  fill: { height: '100%' },
});
