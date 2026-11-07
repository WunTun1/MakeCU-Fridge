import FontAwesome from '@expo/vector-icons/FontAwesome';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { colors } from '@/lib/theme';

/** − value + with 48 px buttons. */
export function Stepper({
  value,
  onMinus,
  onPlus,
  canMinus,
  canPlus,
  minusLabel,
  plusLabel,
}: {
  value: string;
  onMinus: () => void;
  onPlus: () => void;
  canMinus: boolean;
  canPlus: boolean;
  /** For screen readers: "Fewer servings", "More servings". */
  minusLabel: string;
  plusLabel: string;
}) {
  return (
    <View style={styles.row}>
      <StepButton icon="minus" label={minusLabel} disabled={!canMinus} onPress={onMinus} />
      <Text style={styles.value}>{value}</Text>
      <StepButton icon="plus" label={plusLabel} disabled={!canPlus} onPress={onPlus} />
    </View>
  );
}

function StepButton({
  icon,
  label,
  disabled,
  onPress,
}: {
  icon: 'plus' | 'minus';
  label: string;
  disabled: boolean;
  onPress: () => void;
}) {
  return (
    <Pressable
      onPress={onPress}
      disabled={disabled}
      accessibilityRole="button"
      accessibilityLabel={label}
      style={[styles.button, disabled && { opacity: 0.4 }]}
    >
      <FontAwesome name={icon} size={16} color={colors.text} />
    </Pressable>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'center', gap: 16 },
  value: { color: colors.text, fontSize: 20, fontWeight: '700', minWidth: 24, textAlign: 'center' },
  button: {
    width: 48,
    height: 48,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: colors.muted,
    alignItems: 'center',
    justifyContent: 'center',
  },
});
