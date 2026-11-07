import FontAwesome from '@expo/vector-icons/FontAwesome';
import type { ComponentProps } from 'react';
import { StyleSheet, Text, View } from 'react-native';

import type { Activity } from '@/lib/api';
import { colors, formatGrams } from '@/lib/theme';
import { timeAgo } from '@/lib/time';
import { useNow } from '@/lib/useNow';

const VERB: Record<Activity['event_type'], { text: string; icon: ComponentProps<typeof FontAwesome>['name']; color: string }> = {
  add: { text: 'added', icon: 'plus-circle', color: colors.accent },
  remove: { text: 'taken out', icon: 'minus-circle', color: colors.muted },
  consume: { text: 'used', icon: 'cutlery', color: colors.text },
  return: { text: 'put back', icon: 'undo', color: colors.accent },
  waste: { text: 'thrown out', icon: 'trash', color: colors.danger },
};

export function ActivityFeed({ items }: { items: Activity[] }) {
  const now = useNow();
  if (items.length === 0) return <Text style={styles.empty}>Nothing yet today.</Text>;
  return (
    <View style={{ gap: 10 }}>
      {items.map((a) => {
        const v = VERB[a.event_type];
        return (
          <View key={a.id} style={styles.row}>
            <FontAwesome name={v.icon} size={18} color={v.color} style={{ width: 22 }} />
            <Text style={styles.text} numberOfLines={1}>
              <Text style={{ fontWeight: '700' }}>{a.product_name}</Text> {v.text}
              {a.event_type !== 'remove' ? ` · ${formatGrams(Math.abs(a.grams_delta))}` : ''}
            </Text>
            <Text style={styles.when}>{timeAgo(a.occurred_at, now)}</Text>
          </View>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  text: { color: colors.text, fontSize: 16, flex: 1 },
  when: { color: colors.muted, fontSize: 13 },
  empty: { color: colors.muted, fontSize: 15 },
});
