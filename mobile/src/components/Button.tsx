import { Pressable, StyleSheet, Text } from 'react-native';

import { colors } from '@/lib/theme';

type Variant = 'primary' | 'secondary' | 'danger';

export function Button({
  title,
  onPress,
  variant = 'primary',
  disabled,
}: {
  title: string;
  onPress: () => void;
  variant?: Variant;
  disabled?: boolean;
}) {
  return (
    <Pressable
      onPress={onPress}
      disabled={disabled}
      accessibilityRole="button"
      accessibilityState={{ disabled: !!disabled }}
      style={({ pressed }) => [
        styles.base,
        styles[variant],
        (pressed || disabled) && { opacity: 0.6 },
      ]}
    >
      <Text style={[styles.label, variant === 'secondary' && { color: colors.text }]}>{title}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  base: { borderRadius: 8, minHeight: 48, paddingVertical: 12, paddingHorizontal: 16, alignItems: 'center', justifyContent: 'center', flex: 1 },
  primary: { backgroundColor: colors.accent },
  secondary: { backgroundColor: colors.border },
  danger: { backgroundColor: colors.danger },
  label: { color: colors.onAccent, fontWeight: '600', fontSize: 16 },
});
