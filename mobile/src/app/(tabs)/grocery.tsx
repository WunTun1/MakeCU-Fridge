import FontAwesome from '@expo/vector-icons/FontAwesome';
import { router, useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, Text, TextInput, View } from 'react-native';

import { Button } from '@/components/Button';
import { Segmented } from '@/components/Segmented';
import { useSnackbar } from '@/components/Snackbar';
import { ErrorCard } from '@/components/States';
import { formatAmount } from '@/lib/amount';
import { api, type GroceryEntry, type GroceryList, type Horizon, type UseFirst } from '@/lib/api';
import { likelyWasted } from '@/lib/expiry';
import { makeStyles, useColors, useUi } from '@/lib/theme';
import { sentenceCase, tripText, whenWord } from '@/lib/time';
import { useAddToGrocery } from '@/lib/useAddToGrocery';
import { useApi } from '@/lib/useApi';

const HORIZONS: { value: Horizon; label: string }[] = [
  { value: null, label: 'Auto' },
  { value: 1, label: 'Tomorrow' },
  { value: 3, label: 'In 3 days' },
  { value: 7, label: 'In a week' },
];

const sameName = (a: string, b: string) => a.trim().toLowerCase() === b.trim().toLowerCase();

/** Why it's on the list, in words: "Runs out Monday · You use about 250 ml a day". */
function reasonFor(entry: GroceryEntry): string {
  const p = entry.plan;
  const parts = [entry.source === 'manual' ? 'Added by you' : entry.source === 'recipe' ? `For ${entry.recipe_name ?? 'a recipe'}` : ''];
  if (p) {
    const rate = formatAmount(p.rate_g_per_day, entry.unit, entry.grams_per_unit, entry.name).replace(/^about /, '');
    parts.push(
      p.on_hand_g <= 0 || p.runs_out_in_days == null ? "You're out" : `Runs out ${whenWord(p.runs_out_in_days)}`,
      `You use about ${rate} a day`,
    );
  }
  return parts.filter(Boolean).join(' · ');
}

/** How much a count is bought in: "12" eggs; anything else as it's measured, "700 g", "1 L". */
function buyAmount(grams: number, unit: GroceryEntry['unit'], gramsPerUnit: number, name: string): string {
  return unit === 'count' ? String(Math.round(grams / gramsPerUnit)) : formatAmount(grams, unit, gramsPerUnit, name);
}

/** "Apples · 6", "Milk · 2 L": the amount you gave, else what the plan wants to buy. */
function titleFor(entry: GroceryEntry): string {
  const p = entry.plan;
  const amount = entry.amount ?? (p && buyAmount(p.buy_grams, entry.unit, entry.grams_per_unit, entry.name));
  return amount ? `${sentenceCase(entry.name)} · ${amount}` : sentenceCase(entry.name);
}

export default function Grocery() {
  const [list, setList] = useState<GroceryList | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const unlock = useApi(api.unlock);
  const showSnack = useSnackbar();
  const ui = useUi();
  const styles = useStyles();
  const c = useColors();

  const run = useCallback(async (request: () => Promise<GroceryList>) => {
    setBusy(true);
    try {
      setList(await request());
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }, []);

  const reload = useCallback(() => {
    run(api.grocery);
  }, [run]);
  useFocusEffect(reload);
  const addToGrocery = useAddToGrocery(reload);

  if (!list) {
    return (
      <View style={[ui.screen, ui.content]}>
        {error ? <ErrorCard message={error} /> : <ActivityIndicator color={c.accent} style={{ marginTop: 48 }} />}
      </View>
    );
  }

  const setHorizon = (h: Horizon) => {
    setList({ ...list, trip_in_days: h });
    run(() => api.setHorizon(h));
  };

  const toggle = (entry: GroceryEntry) => {
    setList({ ...list, items: list.items.map((i) => (i.id === entry.id ? { ...i, checked: !i.checked } : i)) });
    api.checkGrocery(entry.id, !entry.checked).catch(() => run(api.grocery));
  };

  const remove = (entry: GroceryEntry) => {
    setList({ ...list, items: list.items.filter((i) => i.id !== entry.id) });
    const name = sentenceCase(entry.name);
    api.hideGrocery(entry.id, true).then(
      () =>
        showSnack({
          message: entry.source === 'plan' ? `Removed ${name} for this trip` : `Removed ${name}`,
          action: { label: 'Undo', onPress: () => run(() => api.hideGrocery(entry.id, false).then(api.grocery)) },
        }),
      () => run(api.grocery),
    );
  };

  const add = (names: string[], extra?: { recipe_id: number; recipe_name: string }) =>
    run(() => api.addToGrocery({ names, source: extra ? 'recipe' : 'manual', ...extra }).then(api.grocery));

  const open = list.items.filter((i) => !i.checked);
  const inCart = list.items.filter((i) => i.checked);

  return (
    <ScrollView style={ui.screen} contentContainerStyle={ui.content} keyboardShouldPersistTaps="handled">
      <View style={{ gap: 8 }}>
        <Text style={styles.fieldLabel}>Next shopping trip</Text>
        <Segmented label="Next shopping trip" options={HORIZONS} value={list.trip_in_days} onChange={setHorizon} />
        <View style={styles.progressTrack}>{busy && <View style={styles.progress} />}</View>
        <Text style={ui.text}>{tripText(list.trip_date, list.trip_days_away, list.covers_until)}</Text>
      </View>

      {error && <ErrorCard message={error} />}

      {list.use_first.length > 0 && (
        <View>
          <Text style={ui.h2}>Use first</Text>
          {list.use_first.map((u) => (
            <UseFirstRow
              key={u.product_id}
              row={u}
              onAdd={(amount) => addToGrocery(`${u.name} ${amount}`, `${amount} ${u.name.toLowerCase()}`)}
            />
          ))}
        </View>
      )}

      <View style={[ui.card, { paddingVertical: 4 }, busy && { opacity: 0.6 }]}>
        <AddRow onAdd={(name) => add([name])} />
        {open.length === 0 && inCart.length === 0 && <Text style={[ui.detail, styles.row]}>Nothing to buy yet.</Text>}
        {open.map((entry) => (
          <GroceryRow key={entry.id} entry={entry} onToggle={() => toggle(entry)} onRemove={() => remove(entry)} />
        ))}
        {inCart.length > 0 && (
          <>
            <View style={styles.cartHeader}>
              <Text style={[ui.detail, { fontWeight: '600' }]}>In the cart ({inCart.length})</Text>
              <Pressable onPress={() => run(() => api.clearCheckedGrocery().then(api.grocery))} hitSlop={8} style={styles.textButton}>
                <Text style={styles.link}>Clear checked</Text>
              </Pressable>
            </View>
            {inCart.map((entry) => (
              <GroceryRow key={entry.id} entry={entry} onToggle={() => toggle(entry)} onRemove={() => remove(entry)} />
            ))}
          </>
        )}
      </View>

      {unlock.data && unlock.data.length > 0 && (
        <>
          <Text style={ui.h2}>One item away</Text>
          <Text style={ui.detail}>Buying one of these completes recipes you&apos;d likely cook</Text>
          {unlock.data.map((u) => {
            const onList = u.buy.every((b) => list.items.some((i) => sameName(i.name, b)));
            const label = u.buy.join(' and ');
            return (
              <View key={u.buy.join('+')} style={[ui.card, { gap: 8 }]}>
                <Text style={[ui.text, { fontWeight: '700' }]}>{sentenceCase(label)}</Text>
                <Text style={ui.detail}>
                  Completes {u.unlocks} recipe{u.unlocks === 1 ? '' : 's'}: {u.examples.join(', ')}
                </Text>
                <View style={[ui.row, { gap: 16 }]}>
                  <Button
                    variant="outline"
                    title={onList ? 'On your list' : `Add ${label} to list`}
                    disabled={onList || busy}
                    onPress={() => add(u.buy, { recipe_id: u.recipe_ids[0], recipe_name: u.examples[0] })}
                  />
                  {u.recipe_ids[0] != null && (
                    <Pressable
                      onPress={() => router.push({ pathname: '/recipe/[id]', params: { id: u.recipe_ids[0] } })}
                      style={styles.textButton}
                    >
                      <Text style={styles.link}>See recipe</Text>
                    </Pressable>
                  )}
                </View>
              </View>
            );
          })}
        </>
      )}
    </ScrollView>
  );
}

/** "Chicken breast / About 413 g goes bad Monday", the same words as Home; "Add 700 g" if you need more anyway. */
function UseFirstRow({ row, onAdd }: { row: UseFirst; onAdd: (amount: string) => void }) {
  const ui = useUi();
  const styles = useStyles();
  const grams = row.restock_g;
  const amount = grams != null ? buyAmount(grams, row.unit, row.grams_per_unit, row.name) : null;
  const label = grams != null ? formatAmount(grams, row.unit, row.grams_per_unit, row.name) : null;
  return (
    <View style={styles.useFirst}>
      <Pressable
        onPress={() => router.push({ pathname: '/item/[id]', params: { id: row.product_id } })}
        style={styles.useFirstText}
        accessibilityRole="link"
      >
        <Text style={ui.text}>{sentenceCase(row.name)}</Text>
        <Text style={ui.detail}>
          {likelyWasted(row)} goes bad {whenWord(row.expires_in_days)}
        </Text>
      </Pressable>
      {amount && (
        <Pressable onPress={() => onAdd(amount)} style={styles.textButton} accessibilityRole="button">
          <Text style={styles.link}>Add {label}</Text>
        </Pressable>
      )}
    </View>
  );
}

function AddRow({ onAdd }: { onAdd: (name: string) => void }) {
  const [text, setText] = useState('');
  const ui = useUi();
  const styles = useStyles();
  const c = useColors();
  const submit = () => {
    if (!text.trim()) return;
    onAdd(text.trim());
    setText('');
  };
  return (
    <View style={[styles.row, ui.divider]}>
      <TextInput
        style={[ui.input, { flex: 1 }]}
        placeholder="e.g. apples 6"
        placeholderTextColor={c.muted}
        value={text}
        onChangeText={setText}
        onSubmitEditing={submit}
        returnKeyType="done"
        accessibilityLabel="Add an item"
      />
      <Pressable onPress={submit} style={styles.addButton} accessibilityRole="button" accessibilityLabel="Add to list">
        <FontAwesome name="plus" size={20} color={c.onAccent} />
      </Pressable>
    </View>
  );
}

function GroceryRow({ entry, onToggle, onRemove }: { entry: GroceryEntry; onToggle: () => void; onRemove: () => void }) {
  const done = entry.checked;
  const name = sentenceCase(entry.name);
  const ui = useUi();
  const styles = useStyles();
  const c = useColors();
  return (
    <Pressable
      onPress={onToggle}
      role="checkbox"
      aria-checked={done}
      style={[styles.row, done && { opacity: 0.6 }]}
    >
      <FontAwesome name={done ? 'check-square' : 'square-o'} size={24} color={done ? c.accent : c.textSecondary} />
      <View style={{ flex: 1 }}>
        <Text style={[ui.text, done && { textDecorationLine: 'line-through' }]}>{titleFor(entry)}</Text>
        <Text style={ui.detail}>{reasonFor(entry)}</Text>
      </View>
      <Pressable
        onPress={onRemove}
        style={styles.remove}
        accessibilityRole="button"
        accessibilityLabel={`Remove ${name}`}
      >
        <FontAwesome name="close" size={20} color={c.textSecondary} />
      </Pressable>
    </Pressable>
  );
}

const useStyles = makeStyles((c, size) => ({
  row: { flexDirection: 'row', alignItems: 'center', gap: 12, minHeight: 48, paddingVertical: 8 },
  cartHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    borderTopColor: c.border,
    borderTopWidth: 1,
    marginTop: 4,
    paddingTop: 4,
  },
  fieldLabel: { color: c.text, fontSize: size(15), lineHeight: size(20), fontWeight: '600' },
  remove: { width: 44, height: 44, alignItems: 'center', justifyContent: 'center' },
  textButton: { minHeight: 44, justifyContent: 'center', paddingHorizontal: 4 },
  useFirst: { flexDirection: 'row', alignItems: 'center', gap: 12, marginTop: 8 },
  useFirstText: { flex: 1, minHeight: 44, justifyContent: 'center' },
  link: { color: c.accent, fontSize: size(15), fontWeight: '600' },
  addButton: {
    width: 48,
    height: 48,
    borderRadius: 8,
    backgroundColor: c.accent,
    alignItems: 'center',
    justifyContent: 'center',
  },
  progressTrack: { height: 2, overflow: 'hidden' },
  progress: { height: 2, backgroundColor: c.accent },
}));
