import { Pressable, Text, View } from 'react-native';

import { makeStyles } from '@/lib/theme';

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
  const styles = useStyles();
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

const useStyles = makeStyles((c, size) => ({
  group: {
    flexDirection: 'row',
    borderWidth: 1,
    borderColor: c.muted,
    borderRadius: 8,
    overflow: 'hidden',
  },
  segment: { flex: 1, minHeight: 44, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 8, paddingVertical: 4 },
  divider: { borderLeftWidth: 1, borderLeftColor: c.muted },
  selected: { backgroundColor: c.accent },
  label: { color: c.text, fontSize: size(15), lineHeight: size(20), fontWeight: '600', textAlign: 'center' },
  selectedLabel: { color: c.onAccent },
}));
