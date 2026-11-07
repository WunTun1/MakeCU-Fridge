import { Stack, useLocalSearchParams } from 'expo-router';
import { useRef, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';

import { Button } from '@/components/Button';
import { useSnackbar } from '@/components/Snackbar';
import { ErrorCard, Loading } from '@/components/States';
import { Stepper } from '@/components/Stepper';
import { UsageChart } from '@/components/UsageChart';
import { formatAmount, fromGrams, toGrams } from '@/lib/amount';
import { api, type ProductUsage, type StockItem } from '@/lib/api';
import { expiryTone } from '@/lib/expiry';
import { colors, ui } from '@/lib/theme';
import { calendarDate, capitalize, daysUntil, isoDateIn, relativeDays } from '@/lib/time';
import { refreshAll, useApi } from '@/lib/useApi';

type Action = 'used' | 'amount' | 'date';

/** Soonest to go bad first; undated last. Actions start with the item that needs using first. */
const bySoonest = (items: StockItem[]) =>
  [...items].sort((a, b) => (a.expiration_date ?? '9999').localeCompare(b.expiration_date ?? '9999'));

export default function ItemDetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { data, error, loading, reload } = useApi(() => api.usage(Number(id)));
  const showSnack = useSnackbar();
  const [open, setOpen] = useState<Action | null>(null);
  const wasting = useRef(false);

  if (loading && !data) return <Loading />;

  const done = (message: string, undo?: () => Promise<unknown>) => {
    setOpen(null);
    reload();
    refreshAll();
    showSnack({
      message,
      action: undo && { label: 'Undo', onPress: () => undo().then(reload, () => {}) },
    });
  };

  return (
    <ScrollView style={ui.screen} contentContainerStyle={ui.content} keyboardShouldPersistTaps="handled">
      <Stack.Screen options={{ title: data?.name ?? 'Item' }} />
      {error && <ErrorCard message={error} />}
      {data && (
        <>
          <Stats data={data} />

          {data.items.length === 0 ? (
            <Text style={ui.muted}>You don&apos;t have any right now.</Text>
          ) : (
            <View style={styles.grid}>
              <GridButton title="Used some" active={open === 'used'} onPress={() => setOpen(open === 'used' ? null : 'used')} />
              <GridButton
                title="Threw it out"
                onPress={async () => {
                  if (wasting.current) return;
                  wasting.current = true;
                  try {
                    const { event_ids } = await api.waste(data.items.map((i) => i.id));
                    done(`Threw out ${data.name}`, () => api.undoEvents(event_ids));
                  } finally {
                    wasting.current = false;
                  }
                }}
              />
              <GridButton title="Fix amount" active={open === 'amount'} onPress={() => setOpen(open === 'amount' ? null : 'amount')} />
              <GridButton title="Fix date" active={open === 'date'} onPress={() => setOpen(open === 'date' ? null : 'date')} />
            </View>
          )}

          {open === 'used' && <UsedSome data={data} onDone={done} />}
          {open === 'amount' && <FixAmount data={data} onDone={done} />}
          {open === 'date' && <FixDate data={data} onDone={done} />}

          <Text style={ui.h2}>Used per day, last 4 weeks</Text>
          <View style={ui.card}>
            <UsageChart dailyUsage={data.daily_usage_g} unit={data.unit} gramsPerUnit={data.grams_per_unit} name={data.name} />
          </View>
        </>
      )}
    </ScrollView>
  );
}

function Stats({ data }: { data: ProductUsage }) {
  const days = data.expiration_date ? daysUntil(data.expiration_date) : null;
  const tone = expiryTone(days);
  return (
    <View style={[ui.card, styles.stats]}>
      <Stat
        label="Goes bad"
        value={data.expiration_date ? calendarDate(data.expiration_date) : 'No date'}
        sub={days == null ? undefined : days < 0 ? 'Expired' : relativeDays(days, data.expiry_estimated)}
        subColor={tone ? colors[tone] : colors.muted}
      />
      <Stat label="Have" value={formatAmount(data.on_hand_g, data.unit, data.grams_per_unit, data.name)} />
      <Stat label="Runs out" value={data.days_left != null ? capitalize(relativeDays(data.days_left, true)) : 'Not enough history'} />
    </View>
  );
}

function Stat({ label, value, sub, subColor }: { label: string; value: string; sub?: string; subColor?: string }) {
  return (
    <View style={{ flex: 1, gap: 2 }}>
      <Text style={ui.muted}>{label}</Text>
      <Text style={[ui.text, { fontSize: 17, fontWeight: '700' }]}>{value}</Text>
      {sub && <Text style={[ui.muted, { color: subColor, fontWeight: '600' }]}>{sub}</Text>}
    </View>
  );
}

function GridButton({ title, onPress, active = false }: { title: string; onPress: () => void; active?: boolean }) {
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      style={({ pressed }) => [styles.gridButton, active && { borderColor: colors.accent }, pressed && { opacity: 0.6 }]}
    >
      <Text style={[ui.text, { fontWeight: '600' }, active && { color: colors.accent }]}>{title}</Text>
    </Pressable>
  );
}

type PanelProps = { data: ProductUsage; onDone: (message: string, undo?: () => Promise<unknown>) => void };

function UsedSome({ data, onDone }: PanelProps) {
  const step = data.unit === 'count' ? data.grams_per_unit : 50;
  const [grams, setGrams] = useState(Math.min(step, data.on_hand_g));
  const amount = formatAmount(grams, data.unit, data.grams_per_unit, data.name);

  async function save() {
    const eventIds: number[] = [];
    let left = grams;
    for (const item of bySoonest(data.items)) {
      if (left <= 0) break;
      const take = Math.min(item.grams, left);
      const { event_id } = await api.consume(item.id, take);
      if (event_id != null) eventIds.push(event_id);
      left -= take;
    }
    onDone(`Used ${amount}${data.unit === 'count' ? '' : ` of ${data.name}`}`, () => api.undoEvents(eventIds));
  }

  return (
    <View style={[ui.card, { gap: 16 }]}>
      <Text style={ui.text}>How much did you use?</Text>
      <Stepper
        label="used"
        value={amount}
        canMinus={grams - step > 0}
        canPlus={grams + step <= data.on_hand_g + 0.5}
        onMinus={() => setGrams((g) => g - step)}
        onPlus={() => setGrams((g) => g + step)}
      />
      <SaveButton title={`Used ${amount}`} onPress={save} />
    </View>
  );
}

function FixAmount({ data, onDone }: PanelProps) {
  const unitWord = data.unit === 'count' ? 'how many' : data.unit;
  const [text, setText] = useState(String(fromGrams(data.on_hand_g, data.unit, data.grams_per_unit)));

  async function save() {
    const total = toGrams(Number(text.replace(',', '.')), data.unit, data.grams_per_unit);
    if (!(total >= 0)) return;
    // The newest items keep what they have; the one going bad first takes the difference.
    const items = bySoonest(data.items);
    let left = total;
    for (const item of items.slice(1).reverse()) {
      const keep = Math.min(item.grams, left);
      if (keep !== item.grams) await api.updateItem(item.id, { grams: keep });
      left -= keep;
    }
    await api.updateItem(items[0].id, { grams: left });
    const amount = formatAmount(total, data.unit, data.grams_per_unit, data.name);
    onDone(`You have ${amount}${data.unit === 'count' ? '' : ` of ${data.name}`}`);
  }

  return (
    <View style={[ui.card, { gap: 8 }]}>
      <Text style={styles.label}>You have ({unitWord})</Text>
      <TextInput
        style={ui.input}
        value={text}
        onChangeText={setText}
        keyboardType="decimal-pad"
        accessibilityLabel={`Amount in ${data.unit}`}
        selectTextOnFocus
      />
      <SaveButton title="Save amount" onPress={save} />
    </View>
  );
}

const DATE_PICKS = [
  { label: 'Today', days: 0 },
  { label: 'In 3 days', days: 3 },
  { label: 'In a week', days: 7 },
];

function FixDate({ data, onDone }: PanelProps) {
  const [days, setDays] = useState(() => (data.expiration_date ? daysUntil(data.expiration_date) : 3));
  const date = isoDateIn(days);

  async function save() {
    await api.updateItem(bySoonest(data.items)[0].id, { expiration_date: date });
    onDone(`${data.name} goes bad ${calendarDate(date)}`);
  }

  return (
    <View style={[ui.card, { gap: 16 }]}>
      <Text style={ui.text}>When does it go bad?</Text>
      <Stepper
        label="days"
        value={calendarDate(date)}
        canMinus={days > 0}
        canPlus={days < 365}
        onMinus={() => setDays((d) => d - 1)}
        onPlus={() => setDays((d) => d + 1)}
      />
      <View style={[ui.row, { gap: 8 }]}>
        {DATE_PICKS.map((p) => (
          <Pressable
            key={p.label}
            onPress={() => setDays(p.days)}
            style={[styles.chip, p.days === days && { borderColor: colors.accent }]}
          >
            <Text style={[ui.text, { fontSize: 15 }, p.days === days && { color: colors.accent }]}>{p.label}</Text>
          </Pressable>
        ))}
      </View>
      <SaveButton title="Save date" onPress={save} />
    </View>
  );
}

/** A primary button that ignores taps while its request is in flight. */
function SaveButton({ title, onPress }: { title: string; onPress: () => Promise<void> }) {
  const [busy, setBusy] = useState(false);
  const inFlight = useRef(false);
  return (
    <View style={{ flexDirection: 'row' }}>
      <Button
        title={title}
        disabled={busy}
        onPress={async () => {
          if (inFlight.current) return;
          inFlight.current = true;
          setBusy(true);
          try {
            await onPress();
          } finally {
            inFlight.current = false;
            setBusy(false);
          }
        }}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  stats: { flexDirection: 'row', gap: 12 },
  grid: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  gridButton: {
    flexBasis: '48%',
    flexGrow: 1,
    minHeight: 48,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: colors.muted,
    backgroundColor: colors.card,
    alignItems: 'center',
    justifyContent: 'center',
  },
  label: { color: colors.text, fontSize: 13, fontWeight: '600' },
  chip: {
    minHeight: 44,
    paddingHorizontal: 12,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: colors.muted,
    justifyContent: 'center',
  },
});
