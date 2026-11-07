import { router } from 'expo-router';
import { useRef, useState } from 'react';
import { ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';

import { Button } from '@/components/Button';
import { Segmented } from '@/components/Segmented';
import { useSnackbar } from '@/components/Snackbar';
import { formatAmount, guessUnit, type Unit } from '@/lib/amount';
import { api } from '@/lib/api';
import { colors, ui } from '@/lib/theme';
import { sentenceCase } from '@/lib/time';
import { refreshAll } from '@/lib/useApi';

const LOCATIONS = [
  { value: 'fridge', label: 'Fridge' },
  { value: 'pantry', label: 'Pantry' },
  { value: 'freezer', label: 'Freezer' },
] as const;
type Location = (typeof LOCATIONS)[number]['value'];

const UNIT_OPTIONS: { value: Unit; label: string }[] = [
  { value: 'g', label: 'g' },
  { value: 'count', label: 'count' },
  { value: 'ml', label: 'ml' },
];

const PLACEHOLDER: Record<Unit, string> = { g: 'e.g. 500', count: 'e.g. 12', ml: 'e.g. 1000' };

export default function AddItem() {
  const showSnack = useSnackbar();
  const [name, setName] = useState('');
  const [quantity, setQuantity] = useState('');
  const [pickedUnit, setPickedUnit] = useState<Unit | null>(null);
  const [location, setLocation] = useState<Location>('fridge');
  const [status, setStatus] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const inFlight = useRef(false);

  // The unit follows the name ("Milk" -> ml) until the person picks one.
  const unit = pickedUnit ?? guessUnit(name);

  async function submit() {
    const q = Number(quantity.replace(',', '.'));
    const trimmed = name.trim();
    if (!trimmed || !(q > 0)) {
      setStatus('Enter a name and an amount.');
      return;
    }
    if (inFlight.current) return;
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
      <Button title="Scan a barcode" variant="secondary" onPress={() => router.push('/scan')} />

      <Text style={ui.h2}>Or type it in</Text>
      <View style={[ui.card, { gap: 16 }]}>
        <View style={styles.field}>
          <Text style={styles.label}>Name</Text>
          <TextInput
            style={ui.input}
            placeholder="e.g. Eggs"
            placeholderTextColor={colors.muted}
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
            placeholderTextColor={colors.muted}
            value={quantity}
            onChangeText={setQuantity}
            keyboardType="decimal-pad"
            accessibilityLabel={`Amount in ${unit}`}
          />
          <Segmented label="Unit" options={UNIT_OPTIONS} value={unit} onChange={setPickedUnit} />
        </View>

        <View style={styles.field}>
          <Text style={styles.label}>Where</Text>
          <Segmented label="Where" options={[...LOCATIONS]} value={location} onChange={setLocation} />
        </View>

        <Button title={saving ? 'Adding…' : 'Add'} onPress={submit} disabled={saving} />
        {status && <Text style={ui.muted}>{status}</Text>}
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  field: { gap: 8 },
  label: { color: colors.text, fontSize: 13, fontWeight: '600' },
});
