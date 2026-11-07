import { Pressable, StyleSheet, Text, View } from 'react-native';

import { colors } from '@/lib/theme';

/** One choice out of a few, all visible. The selected segment is filled with the accent. */
export function Segmented<T extends string | number | null>({
  options,
  value,
  onChange,
  label,
}: {
  options: { value: T; label: string }[];
  value: T;
  onChange: (value: T) => void;
  /** Read by screen readers for the whole group. */
  label: string;
}) {
  return (
    <View style={styles.group} role="radiogroup" accessibilityLabel={label}>
      {options.map((o, i) => {
        const selected = o.value === value;
        return (
          <Pressable
            key={String(o.value)}
            onPress={() => onChange(o.value)}
            role="radio"
            aria-checked={selected}
            style={[styles.segment, i > 0 && styles.divider, selected && styles.selected]}
          >
            <Text style={[styles.label, selected && styles.selectedLabel]}>{o.label}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  group: {
    flexDirection: 'row',
    borderWidth: 1,
    borderColor: colors.muted,
    borderRadius: 8,
    overflow: 'hidden',
  },
  segment: { flex: 1, minHeight: 44, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 8 },
  divider: { borderLeftWidth: 1, borderLeftColor: colors.muted },
  selected: { backgroundColor: colors.accent },
  label: { color: colors.text, fontSize: 15, fontWeight: '600' },
  selectedLabel: { color: colors.onAccent },
});
