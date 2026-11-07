import FontAwesome from '@expo/vector-icons/FontAwesome';
import { useState } from 'react';
import { Pressable, StyleSheet, Text, TextInput, View } from 'react-native';

import { colors, ui } from '@/lib/theme';

/** Pick one. The selected chip is filled because the saved value matches it. */
export function ChoiceChips<T extends string>({
  options,
  value,
  onChange,
  label,
}: {
  options: { value: T; label: string }[];
  value: string | null;
  onChange: (value: T) => void;
  label: string;
}) {
  return (
    <View style={styles.wrap} role="radiogroup" accessibilityLabel={label}>
      {options.map((o) => {
        const selected = o.value === value;
        return (
          <Pressable
            key={o.value}
            onPress={() => onChange(o.value)}
            role="radio"
            aria-checked={selected}
            hitSlop={6}
            style={[styles.chip, selected && styles.selected]}
          >
            <Text style={[styles.text, selected && { color: colors.onAccent }]}>{o.label}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}

/**
 * A list someone builds up (allergies, dislikes): each entry is a chip with its own remove
 * button, plus a field to add one. An empty list says so plainly.
 */
export function ListField({
  label,
  values,
  onChange,
}: {
  label: string;
  values: string[];
  onChange: (values: string[]) => void;
}) {
  const [text, setText] = useState('');
  const add = () => {
    const value = text.trim().toLowerCase();
    setText('');
    if (value && !values.includes(value)) onChange([...values, value]);
  };
  return (
    <View style={{ gap: 8 }}>
      {values.length === 0 ? (
        <Text style={ui.muted}>None set</Text>
      ) : (
        <View style={styles.wrap}>
          {values.map((v) => (
            <Pressable
              key={v}
              onPress={() => onChange(values.filter((x) => x !== v))}
              hitSlop={6}
              accessibilityRole="button"
              accessibilityLabel={`Remove ${v}`}
              style={[styles.chip, styles.removable]}
            >
              <Text style={styles.text}>{v}</Text>
              <FontAwesome name="close" size={14} color={colors.muted} />
            </Pressable>
          ))}
        </View>
      )}
      <View style={ui.row}>
        <TextInput
          style={[ui.input, { flex: 1 }]}
          value={text}
          onChangeText={setText}
          onSubmitEditing={add}
          placeholder="e.g. peanuts"
          placeholderTextColor={colors.muted}
          returnKeyType="done"
          accessibilityLabel={`Add to ${label}`}
        />
        <Pressable onPress={add} style={styles.add} accessibilityRole="button" accessibilityLabel={`Add to ${label}`}>
          <Text style={styles.addText}>Add</Text>
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  chip: {
    minHeight: 32,
    paddingHorizontal: 12,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: colors.muted,
    alignItems: 'center',
    justifyContent: 'center',
  },
  removable: { flexDirection: 'row', gap: 8 },
  selected: { backgroundColor: colors.accent, borderColor: colors.accent },
  text: { color: colors.text, fontSize: 15 },
  add: {
    minHeight: 48,
    minWidth: 64,
    paddingHorizontal: 16,
    borderRadius: 8,
    backgroundColor: colors.border,
    alignItems: 'center',
    justifyContent: 'center',
  },
  addText: { color: colors.text, fontSize: 16, fontWeight: '600' },
});
