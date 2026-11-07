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
import { expiryText, expiryTone, LEFT_WHEN_BAD, leftWhenBad } from '@/lib/expiry';
import { colors, ui } from '@/lib/theme';
import { calendarDate, capitalize, daysUntil, isoDateIn, monthName, relativeDays, whenWord } from '@/lib/time';
import { refreshAll, useApi } from '@/lib/useApi';

/** A panel that's open: one of the actions, or Fix date for one package. */
type Action = 'used' | 'amount' | { date: number };

/** Soonest to go bad first; undated last. Actions start with the item that needs using first. */
const bySoonest = (items: StockItem[]) =>
  [...items].sort((a, b) => (a.expiration_date ?? '9999').localeCompare(b.expiration_date ?? '9999'));

export default function ItemDetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { data, error, loading, reload } = useApi(() => api.usage(Number(id)));
  const showSnack = useSnackbar();
  const [open, setOpen] = useState<Action | null>(null);
  const busy = useRef(false);

  if (loading && !data) return <Loading />;

  const done = (message: string, undo?: () => Promise<unknown>) => {
    setOpen(null);
    reload();
    refreshAll();
    showSnack({
      message,
      action: undo && { label: 'Undo', onPress: () => undo().then(() => (reload(), refreshAll()), () => {}) },
    });
  };

  /** One write at a time: a second tap while the first is in flight does nothing. */
  const once = (write: () => Promise<void>) => async () => {
    if (busy.current) return;
    busy.current = true;
    try {
      await write();
    } catch (e) {
      showSnack({ message: `Couldn't save: ${(e as Error).message}` });
    } finally {
      busy.current = false;
    }
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
            <>
              {data.recipe_id != null && (
                <View style={styles.buttonRow}>
                  <Button
                    title="Ate one serving"
                    onPress={once(async () => {
                      const eaten = await api.eat(data.product_id);
                      const protein = eaten.protein_g != null ? ` · ${Math.round(eaten.protein_g)} g protein` : '';
                      done(`Logged 1 serving of ${recipeName(data.name)}${protein}`, () => api.undoMeal(eaten.meal_id));
                    })}
                  />
                </View>
              )}
              <View style={styles.grid}>
                <GridButton title="Used some" active={open === 'used'} onPress={() => setOpen(open === 'used' ? null : 'used')} />
                <GridButton
                  title="Threw it out"
                  onPress={once(async () => {
                    const { event_ids } = await api.waste(data.items.map((i) => i.id));
                    done(`Threw out ${data.name}`, () => api.undoEvents(event_ids));
                  })}
                />
                {data.items.some((i) => i.location === 'fridge') && (
                  <GridButton
                    title="Move to freezer"
                    onPress={once(async () => {
                      const moved = await api.freeze(data.product_id);
                      const amount = formatAmount(moved.grams, data.unit, data.grams_per_unit, data.name);
                      const what = data.unit === 'count' ? amount : `${amount} ${data.name.toLowerCase()}`;
                      done(`Moved ${what} to the freezer · good until around ${monthName(moved.expiration_date)}`, () =>
                        api.undoEvents(moved.event_ids),
                      );
                    })}
                  />
                )}
                <GridButton title="Fix amount" active={open === 'amount'} onPress={() => setOpen(open === 'amount' ? null : 'amount')} />
              </View>
            </>
          )}

          {open === 'used' && <UsedSome data={data} onDone={done} />}
          {open === 'amount' && <FixAmount data={data} onDone={done} />}

          {data.items.length > 0 && (
            <>
              <Text style={ui.h2}>{data.items.length === 1 ? 'Package' : `Packages (${data.items.length})`}</Text>
              <View style={[ui.card, { paddingVertical: 4 }]}>
                {bySoonest(data.items).map((item, i) => {
                  const fixing = typeof open === 'object' && open?.date === item.id;
                  return (
                    <View key={item.id} style={i > 0 && styles.packageDivider}>
                      <PackageRow
                        data={data}
                        item={item}
                        fixing={fixing}
                        onFix={() => setOpen(fixing ? null : { date: item.id })}
                      />
                      {fixing && <FixDate data={data} item={item} onDone={done} />}
                    </View>
                  );
                })}
              </View>
            </>
          )}

          {data.recipe_id == null && (
            <>
              <Text style={ui.h2}>Used per day, last 4 weeks</Text>
              <View style={ui.card}>
                <UsageChart dailyUsage={data.daily_usage_g} unit={data.unit} gramsPerUnit={data.grams_per_unit} name={data.name} />
              </View>
            </>
          )}
        </>
      )}
    </ScrollView>
  );
}

/** "Greek Stuffed Chicken leftovers" -> "Greek Stuffed Chicken". */
const recipeName = (productName: string) => productName.replace(/ leftovers$/, '');

/** All of it is frozen: it keeps for months, so the date is said as a month. */
const allFrozen = (data: ProductUsage) => data.items.length > 0 && data.items.every((i) => i.location === 'freezer');

function Stats({ data }: { data: ProductUsage }) {
  const days = data.expiration_date ? daysUntil(data.expiration_date) : null;
  const tone = expiryTone(days);
  const left = leftWhenBad({ ...data, grams: data.on_hand_g, expires_in_days: days });
  const runsOut = data.days_left == null ? 'Not enough history' : capitalize(whenWord(data.days_left));
  return (
    <View style={[ui.card, styles.stats]}>
      {allFrozen(data) && data.expiration_date ? (
        <Stat label="Good until" value={`Around ${monthName(data.expiration_date)}`} sub="In the freezer" subColor={colors.muted} />
      ) : (
        <Stat
          label="Goes bad"
          value={data.expiration_date ? calendarDate(data.expiration_date) : 'No date'}
          sub={days == null ? undefined : days < 0 ? 'Expired' : relativeDays(days, data.expiry_estimated)}
          subColor={tone ? colors[tone] : colors.muted}
        />
      )}
      <Stat label="Have" value={formatAmount(data.on_hand_g, data.unit, data.grams_per_unit, data.name)} />
      {left ? <Stat label={LEFT_WHEN_BAD} value={left} /> : <Stat label="Runs out" value={runsOut} />}
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

/** "Goes bad tomorrow · Sun, Nov 8", or "In the freezer · good until around August". */
function packageWhen(item: StockItem, days: number | null): string {
  if (item.location === 'freezer') {
    return item.expiration_date ? `In the freezer · good until around ${monthName(item.expiration_date)}` : 'In the freezer';
  }
  return days == null ? 'No date' : `${expiryText(days, item.expiry_estimated)} · ${calendarDate(item.expiration_date!)}`;
}

/** One package (an add): how much is left of it, when it goes bad, and its own Fix date. */
function PackageRow({ data, item, fixing, onFix }: { data: ProductUsage; item: StockItem; fixing: boolean; onFix: () => void }) {
  const days = item.expiration_date ? daysUntil(item.expiration_date) : null;
  const tone = expiryTone(days);
  return (
    <View style={styles.packageRow}>
      <View style={{ flex: 1, gap: 2 }}>
        <Text style={ui.text}>{capitalize(formatAmount(item.grams, data.unit, data.grams_per_unit, data.name))}</Text>
        <Text style={[ui.muted, tone && item.location !== 'freezer' && { color: colors[tone] }]}>
          {packageWhen(item, days)}
        </Text>
      </View>
      <Pressable
        onPress={onFix}
        style={styles.textButton}
        accessibilityRole="button"
        accessibilityLabel="Fix the date on this package"
      >
        <Text style={styles.link}>{fixing ? 'Cancel' : 'Fix date'}</Text>
      </Pressable>
    </View>
  );
}

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
        minusLabel="Used less"
        plusLabel="Used more"
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

function FixDate({ data, item, onDone }: PanelProps & { item: StockItem }) {
  const [days, setDays] = useState(() => (item.expiration_date ? daysUntil(item.expiration_date) : 3));
  const date = isoDateIn(days);

  async function save() {
    await api.updateItem(item.id, { expiration_date: date });
    const amount = formatAmount(item.grams, data.unit, data.grams_per_unit, data.name);
    onDone(`${capitalize(amount)}${data.unit === 'count' ? '' : ` of ${data.name}`} goes bad ${calendarDate(date)}`);
  }

  return (
    <View style={{ gap: 16, paddingBottom: 12 }}>
      <Text style={ui.text}>When does it go bad?</Text>
      <Stepper
        minusLabel="A day earlier"
        plusLabel="A day later"
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
  buttonRow: { flexDirection: 'row' },
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
  packageRow: { flexDirection: 'row', alignItems: 'center', gap: 12, minHeight: 56, paddingVertical: 8 },
  packageDivider: { borderTopColor: colors.border, borderTopWidth: 1 },
  textButton: { minHeight: 44, minWidth: 44, justifyContent: 'center', paddingHorizontal: 8 },
  link: { color: colors.accent, fontSize: 15, fontWeight: '600' },
  chip: {
    minHeight: 44,
    paddingHorizontal: 12,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: colors.muted,
    justifyContent: 'center',
  },
});
