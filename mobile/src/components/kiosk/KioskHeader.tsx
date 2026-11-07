import FontAwesome from '@expo/vector-icons/FontAwesome';
import { type ComponentProps, useMemo } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import type { Conditions } from '@/lib/api';
import { type Palette, type ThemeMode, useColors } from '@/lib/theme';
import { useNow } from '@/lib/useNow';

const FRIDGE_TOO_WARM_C = 7;

export function KioskHeader({
  conditions,
  doorOpen,
  mode,
  onToggleTheme,
  compact = false,
}: {
  conditions: Conditions | null;
  doorOpen: boolean;
  mode: ThemeMode;
  onToggleTheme: () => void;
  /** Tighter sizing for the 800x480 panel. */
  compact?: boolean;
}) {
  const colors = useColors();
  const styles = useMemo(() => makeStyles(colors), [colors]);
  const now = new Date(useNow());
  const temp = conditions?.temperature_c;
  const warm = temp != null && temp > FRIDGE_TOO_WARM_C;

  return (
    <View style={[styles.bar, compact && styles.barCompact]}>
      <View>
        <Text style={[styles.time, compact && { fontSize: 24 }]}>
          {now.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}
        </Text>
        <Text style={styles.date}>
          {now.toLocaleDateString(undefined, {
            weekday: compact ? 'short' : 'long',
            month: compact ? 'short' : 'long',
            day: 'numeric',
          })}
        </Text>
      </View>

      <View style={[styles.chips, compact && { gap: 6 }]}>
        <Chip
          icon={doorOpen ? 'unlock' : 'lock'}
          label={doorOpen ? 'Door open' : 'Door closed'}
          tone={doorOpen ? 'warn' : 'ok'}
          compact={compact}
        />
        {temp != null && (
          <Chip icon="thermometer-half" label={`${temp.toFixed(1)}°C`} tone={warm ? 'danger' : 'ok'} compact={compact} />
        )}
        {conditions?.humidity_pct != null && (
          <Chip icon="tint" label={`${Math.round(conditions.humidity_pct)}%`} tone="ok" compact={compact} />
        )}
        <Pressable
          onPress={onToggleTheme}
          accessibilityRole="button"
          accessibilityLabel={mode === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
          style={({ pressed }) => [
            styles.chip,
            styles.toggle,
            compact && styles.chipCompact,
            compact && { minHeight: 40 },
            pressed && { opacity: 0.6 },
          ]}
        >
          <FontAwesome name={mode === 'dark' ? 'sun-o' : 'moon-o'} size={compact ? 15 : 18} color={colors.text} />
          <Text style={[styles.chipText, compact && { fontSize: 14 }]}>{mode === 'dark' ? 'Light' : 'Dark'}</Text>
        </Pressable>
      </View>
    </View>
  );
}

type Tone = 'ok' | 'warn' | 'danger';

function Chip({
  icon,
  label,
  tone,
  compact,
}: {
  icon: ComponentProps<typeof FontAwesome>['name'];
  label: string;
  tone: Tone;
  compact: boolean;
}) {
  const colors = useColors();
  const styles = useMemo(() => makeStyles(colors), [colors]);
  const TONE: Record<Tone, string> = {
    ok: colors.muted,
    warn: colors.warn,
    danger: colors.danger,
  };
  return (
    <View style={[styles.chip, compact && styles.chipCompact, tone !== 'ok' && { borderColor: TONE[tone] }]}>
      <FontAwesome name={icon} size={compact ? 15 : 18} color={TONE[tone]} />
      <Text style={[styles.chipText, compact && { fontSize: 14 }, tone !== 'ok' && { color: TONE[tone] }]}>{label}</Text>
    </View>
  );
}

const makeStyles = (colors: Palette) =>
  StyleSheet.create({
    bar: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      paddingHorizontal: 20,
      paddingVertical: 10,
      borderBottomColor: colors.border,
      borderBottomWidth: 1,
    },
    barCompact: { paddingHorizontal: 12, paddingVertical: 6 },
    time: { color: colors.text, fontSize: 30, fontWeight: '700' },
    date: { color: colors.muted, fontSize: 14 },
    chips: {
      flexDirection: 'row',
      gap: 10,
      flexWrap: 'wrap',
      justifyContent: 'flex-end',
      flexShrink: 1,
    },
    chip: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 8,
      paddingHorizontal: 14,
      paddingVertical: 10,
      borderRadius: 999,
      borderWidth: 1,
      borderColor: colors.border,
      backgroundColor: colors.card,
    },
    chipCompact: { paddingHorizontal: 10, paddingVertical: 7, gap: 6 },
    toggle: { minHeight: 48, borderColor: colors.muted },
    chipText: { color: colors.text, fontSize: 16, fontWeight: '600' },
  });
