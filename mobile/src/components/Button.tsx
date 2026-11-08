import { Pressable, Text } from 'react-native';

import { makeStyles } from '@/lib/theme';

type Variant = 'primary' | 'secondary' | 'danger' | 'outline';

/** Filled accent for the one main action; outline (accent border and text) for quieter ones. */
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
  const styles = useStyles();
  return (
    <Pressable
      onPress={onPress}
      disabled={disabled}
      accessibilityRole="button"
      accessibilityState={{ disabled: !!disabled }}
      style={({ pressed }) => [styles.base, styles[variant], (pressed || disabled) && { opacity: 0.6 }]}
    >
      <Text style={[styles.label, styles[`${variant}Label`]]}>{title}</Text>
    </Pressable>
  );
}

const useStyles = makeStyles((c, size) => ({
  base: {
    borderRadius: 8,
    minHeight: 48,
    paddingVertical: 12,
    paddingHorizontal: 16,
    alignItems: 'center',
    justifyContent: 'center',
    flex: 1,
  },
  primary: { backgroundColor: c.accent },
  secondary: { backgroundColor: c.border },
  danger: { backgroundColor: c.danger },
  outline: { borderWidth: 1, borderColor: c.accent, minHeight: 44, paddingVertical: 8 },
  label: { fontWeight: '600', fontSize: size(16), lineHeight: size(20), textAlign: 'center' },
  primaryLabel: { color: c.onAccent },
  secondaryLabel: { color: c.text },
  dangerLabel: { color: c.onAccent },
  outlineLabel: { color: c.accent, fontSize: size(15) },
}));
