import { router } from 'expo-router';
import { useRef, useState } from 'react';
import { ScrollView, Text, TextInput, View } from 'react-native';

import { Button } from '@/components/Button';
import { Segmented } from '@/components/Segmented';
import { useSnackbar } from '@/components/Snackbar';
import { countNoun, formatAmount, guessUnit } from '@/lib/amount';
import { api } from '@/lib/api';
import { makeStyles, useColors, useUi } from '@/lib/theme';
import { sentenceCase } from '@/lib/time';
import { refreshAll } from '@/lib/useApi';

const LOCATIONS = [
  { value: 'fridge', label: 'Fridge' },
  { value: 'pantry', label: 'Pantry' },
  { value: 'freezer', label: 'Freezer' },
] as const;
type Location = (typeof LOCATIONS)[number]['value'];

/** What people type amounts in; lb and oz are stored as grams. */
type EntryUnit = 'g' | 'lb' | 'oz' | 'count' | 'ml';
const UNIT_OPTIONS: { value: EntryUnit; label: string }[] = [
  { value: 'g', label: 'g' },
  { value: 'lb', label: 'lb' },
  { value: 'oz', label: 'oz' },
  { value: 'count', label: 'count' },
  { value: 'ml', label: 'ml' },
];

const PLACEHOLDER: Record<EntryUnit, string> = { g: 'e.g. 500', lb: 'e.g. 1', oz: 'e.g. 8', count: 'e.g. 12', ml: 'e.g. 1000' };

/** Under this many g or ml, or over this many pieces, the amount is probably in the wrong unit. */
const FEW_GRAMS = 20;
const MANY_PIECES = 60;
const MEAT = /\b(chicken|beef|pork|turkey|lamb|steak|fish|salmon|shrimp|tuna|cod|tilapia|sausage|bacon|ground|mince)\b/i;

/** "3 bananas", "1 lb", "80 g": an amount in a unit, the way the person would say it. */
function amountWords(q: number, unit: EntryUnit, name: string): string {
  if (unit === 'count') return `${q} ${countNoun(name, q)}`;
  return `${q} ${unit}`;
}

/**
 * An amount that's implausible in its unit ("Bananas 3 g", "Chicken breast 1 g", "Eggs 80") gets a
 * question with the likely meaning and the amount as typed. Null when it looks right.
 */
function unitQuestion(name: string, q: number, unit: EntryUnit): { text: string; other: EntryUnit } | null {
  if ((unit === 'g' || unit === 'ml') && q < FEW_GRAMS) {
    const other: EntryUnit = MEAT.test(name) ? 'lb' : 'count';
    return { text: `${q} ${unit} is very little. Did you mean ${amountWords(q, other, name)}?`, other };
  }
  if (unit === 'count' && q > MANY_PIECES) {
    return { text: `${amountWords(q, 'count', name)} is a lot. Did you mean ${q} g?`, other: 'g' };
  }
  return null;
}

export default function AddItem() {
  const showSnack = useSnackbar();
  const ui = useUi();
  const styles = useStyles();
  const c = useColors();
  const [name, setName] = useState('');
  const [quantity, setQuantity] = useState('');
  const [pickedUnit, setPickedUnit] = useState<EntryUnit | null>(null);
  const [location, setLocation] = useState<Location>('fridge');
  const [status, setStatus] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  /** The amount the person confirmed as typed ("3 g" is what I meant). */
  const [confirmed, setConfirmed] = useState<string | null>(null);
  const inFlight = useRef(false);

  // The unit follows the name ("Milk" -> ml, "Bananas" -> count) until the person picks one.
  const unit = pickedUnit ?? guessUnit(name);
  const trimmed = name.trim();
  const q = Number(quantity.replace(',', '.'));
  const valid = trimmed !== '' && q > 0;
  const key = `${trimmed}|${q}|${unit}`;
  const question = valid && confirmed !== key ? unitQuestion(trimmed, q, unit) : null;

  async function submit() {
    if (!valid) {
      setStatus('Enter a name and an amount.');
      return;
    }
    if (question || inFlight.current) return;
    inFlight.current = true;
    setSaving(true);
    try {
      const added = await api.addItem({ name: trimmed, quantity: q, unit, location });
      const amount = formatAmount(added.grams, added.unit, added.grams_per_unit, trimmed);
      const what = added.unit === 'count' ? amount : `${amount} of ${trimmed}`;
      const where = LOCATIONS.find((l) => l.value === location)!.label;
      const checked = added.checked_off;
      // Bought it, so it comes off the grocery list too; Undo puts both back.
      const undo = () =>
        Promise.all([api.undoAdd(added.item_id), checked && api.checkGrocery(checked.id, false)]).then(refreshAll, () => {});
      showSnack({
        message: `Added ${what} to ${where}${checked ? ` · checked off ${sentenceCase(checked.name)} on your list` : ''}`,
        action: { label: 'Undo', onPress: undo },
      });
      refreshAll();
      if (router.canGoBack()) router.back();
      else router.replace('/');
    } catch (e) {
      setStatus(`Couldn't add it: ${(e as Error).message}`);
      inFlight.current = false;
      setSaving(false);
    }
  }

  return (
    <ScrollView style={ui.screen} contentContainerStyle={ui.content} keyboardShouldPersistTaps="handled">
      <View style={styles.buttonRow}>
        <Button title="Scan a barcode" variant="secondary" onPress={() => router.push('/scan')} />
      </View>

      <Text style={ui.h2}>Or type it in</Text>
      <View style={[ui.card, { gap: 16 }]}>
        <View style={styles.field}>
          <Text style={styles.label}>Name</Text>
          <TextInput
            style={ui.input}
            placeholder="e.g. Eggs"
            placeholderTextColor={c.muted}
            value={name}
            onChangeText={setName}
            accessibilityLabel="Name"
          />
        </View>

        <View style={styles.field}>
          <Text style={styles.label}>Amount</Text>
          <TextInput
            style={ui.input}
            placeholder={PLACEHOLDER[unit]}
            placeholderTextColor={c.muted}
            value={quantity}
            onChangeText={setQuantity}
            keyboardType="decimal-pad"
            accessibilityLabel={`Amount in ${unit}`}
          />
          <Segmented label="Unit" options={UNIT_OPTIONS} value={unit} onChange={setPickedUnit} />
          {question && (
            <View style={styles.question} accessibilityLiveRegion="polite">
              <Text style={ui.detail}>{question.text}</Text>
              <View style={styles.answers}>
                <Button variant="outline" title={amountWords(q, question.other, trimmed)} onPress={() => setPickedUnit(question.other)} />
                <Button variant="outline" title={amountWords(q, unit, trimmed)} onPress={() => setConfirmed(key)} />
              </View>
            </View>
          )}
        </View>

        <View style={styles.field}>
          <Text style={styles.label}>Where</Text>
          <Segmented label="Where" options={[...LOCATIONS]} value={location} onChange={setLocation} />
        </View>

        <View style={styles.buttonRow}>
          <Button title={saving ? 'Adding…' : 'Add'} onPress={submit} disabled={saving || !!question} />
        </View>
        {status && <Text style={ui.detail}>{status}</Text>}
      </View>
    </ScrollView>
  );
}

const useStyles = makeStyles((c, size) => ({
  field: { gap: 8 },
  label: { color: c.text, fontSize: size(15), lineHeight: size(20), fontWeight: '600' },
  question: { gap: 8 },
  answers: { flexDirection: 'row', gap: 8 },
  buttonRow: { flexDirection: 'row' },
}));
