import FontAwesome from '@expo/vector-icons/FontAwesome';
import type { ComponentProps } from 'react';
import { StyleSheet, Text, View } from 'react-native';

import type { Conditions } from '@/lib/api';
import { colors } from '@/lib/theme';
import { shortDate } from '@/lib/time';
import { useNow } from '@/lib/useNow';

const FRIDGE_TOO_WARM_C = 7;

export function KioskHeader({
  conditions,
  doorOpen,
  nextTrip,
}: {
  conditions: Conditions | null;
  doorOpen: boolean;
  nextTrip: string | null;
}) {
  const now = new Date(useNow());
  const temp = conditions?.temperature_c;
  const warm = temp != null && temp > FRIDGE_TOO_WARM_C;

  return (
    <View style={styles.bar}>
      <View>
        <Text style={styles.time}>{now.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}</Text>
        <Text style={styles.date}>{now.toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric' })}</Text>
      </View>

      <View style={styles.chips}>
        <Chip icon={doorOpen ? 'unlock' : 'lock'} label={doorOpen ? 'Door open' : 'Door closed'} tone={doorOpen ? 'warn' : 'ok'} />
        <Chip
          icon="thermometer-half"
          label={temp != null ? `${temp.toFixed(1)}°C` : '—'}
          tone={warm ? 'danger' : 'ok'}
        />
        {conditions?.humidity_pct != null && <Chip icon="tint" label={`${Math.round(conditions.humidity_pct)}%`} tone="ok" />}
        <Chip icon="shopping-cart" label={nextTrip ? `Shop ${shortDate(nextTrip, now)}` : 'Stocked up'} tone="ok" />
      </View>
    </View>
  );
}

type Tone = 'ok' | 'warn' | 'danger';
const TONE: Record<Tone, string> = { ok: colors.muted, warn: colors.warn, danger: colors.danger };

function Chip({ icon, label, tone }: { icon: ComponentProps<typeof FontAwesome>['name']; label: string; tone: Tone }) {
  return (
    <View style={[styles.chip, tone !== 'ok' && { borderColor: TONE[tone] }]}>
      <FontAwesome name={icon} size={18} color={TONE[tone]} />
      <Text style={[styles.chipText, tone !== 'ok' && { color: TONE[tone] }]}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  bar: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 20,
    paddingVertical: 10,
    borderBottomColor: colors.border,
    borderBottomWidth: 1,
  },
  time: { color: colors.text, fontSize: 30, fontWeight: '700' },
  date: { color: colors.muted, fontSize: 14 },
  chips: { flexDirection: 'row', gap: 10, flexWrap: 'wrap', justifyContent: 'flex-end', flexShrink: 1 },
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
  chipText: { color: colors.text, fontSize: 16, fontWeight: '600' },
});
