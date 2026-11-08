import { useEffect, useState } from 'react';
import { Modal, Pressable, Text, TextInput, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { Button } from '@/components/Button';
import { formatAmount } from '@/lib/amount';
import { api, type QuickAdd } from '@/lib/api';
import { makeStyles, useColors, useUi } from '@/lib/theme';
import { sentenceCase } from '@/lib/time';

/** "2 eggs", "Greek yogurt 200 g", "Chili, 1 serving". */
export function portionText(q: QuickAdd): string {
  const amount = formatAmount(q.grams, q.unit, q.grams_per_unit, q.name);
  if (q.name.endsWith(' leftovers')) return `${q.name.replace(/ leftovers$/, '')}, ${amount}`;
  return q.unit === 'count' ? amount : `${sentenceCase(q.name)} ${amount}`;
}

const number = (text: string) => (text.trim() === '' ? null : Number(text.replace(',', '.')));

/**
 * Log food in two ways: a portion of something in the fridge (it comes out of the fridge),
 * or numbers off a label (nutrition only).
 */
export function AddFoodSheet({
  visible,
  onClose,
  onPortion,
  onOther,
}: {
  visible: boolean;
  onClose: () => void;
  onPortion: (q: QuickAdd) => Promise<void>;
  onOther: (entry: { name: string; protein_g: number | null; calories: number | null }) => Promise<void>;
}) {
  const insets = useSafeAreaInsets();
  const styles = useStyles();
  const ui = useUi();
  const [portions, setPortions] = useState<QuickAdd[] | null>(null);
  const [name, setName] = useState('');
  const [protein, setProtein] = useState('');
  const [kcal, setKcal] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!visible) return;
    let cancelled = false;
    api.quickAdds().then((q) => !cancelled && setPortions(q), () => !cancelled && setPortions([]));
    return () => {
      cancelled = true;
    };
  }, [visible]);

  const proteinG = number(protein);
  const calories = number(kcal);
  const valid =
    name.trim() !== '' &&
    (proteinG != null || calories != null) &&
    [proteinG, calories].every((v) => v == null || (Number.isFinite(v) && v >= 0));

  async function run(write: () => Promise<void>) {
    if (busy) return;
    setBusy(true);
    try {
      await write();
      setName('');
      setProtein('');
      setKcal('');
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <Pressable style={styles.backdrop} onPress={onClose} accessibilityLabel="Close" />
      <View style={[styles.sheet, { paddingBottom: 16 + insets.bottom }]}>
        <Text style={styles.title}>Add food</Text>

        <View style={{ gap: 8 }}>
          <Text style={styles.label}>From your fridge</Text>
          {portions?.length === 0 && <Text style={ui.detail}>Nothing in the fridge with 10 g of protein or more.</Text>}
          <View style={styles.chips}>
            {portions?.map((q) => (
              <Pressable
                key={q.product_id}
                disabled={busy}
                onPress={() => run(() => onPortion(q))}
                style={({ pressed }) => [styles.chip, pressed && { opacity: 0.6 }]}
                accessibilityRole="button"
                accessibilityLabel={`Ate ${portionText(q)}, ${q.protein_g} g protein`}
              >
                <Text style={ui.text}>{portionText(q)}</Text>
                <Text style={ui.detail}>{q.protein_g} g protein</Text>
              </Pressable>
            ))}
          </View>
          <Text style={ui.detail}>Takes it out of the fridge and logs it.</Text>
        </View>

        <View style={{ gap: 8 }}>
          <Text style={styles.label}>Other</Text>
          <Field label="Name" value={name} onChange={setName} placeholder="e.g. Protein shake" />
          <View style={[ui.row, { gap: 12 }]}>
            <Field label="Protein (g)" value={protein} onChange={setProtein} placeholder="e.g. 24" numeric />
            <Field label="Calories (kcal)" value={kcal} onChange={setKcal} placeholder="e.g. 120" numeric />
          </View>
          <View style={styles.buttonRow}>
            <Button
              title="Log it"
              disabled={!valid || busy}
              onPress={() => run(() => onOther({ name: name.trim(), protein_g: proteinG, calories }))}
            />
          </View>
        </View>
      </View>
    </Modal>
  );
}

function Field({
  label,
  value,
  onChange,
  placeholder,
  numeric = false,
}: {
  label: string;
  value: string;
  onChange: (text: string) => void;
  placeholder: string;
  numeric?: boolean;
}) {
  const ui = useUi();
  const c = useColors();
  return (
    <View style={{ flex: 1, gap: 4 }}>
      <Text style={ui.detail}>{label}</Text>
      <TextInput
        style={ui.input}
        value={value}
        onChangeText={onChange}
        placeholder={placeholder}
        placeholderTextColor={c.muted}
        keyboardType={numeric ? 'decimal-pad' : 'default'}
        accessibilityLabel={label}
      />
    </View>
  );
}

const useStyles = makeStyles((c, size) => ({
  backdrop: { flex: 1, backgroundColor: '#000a' },
  sheet: {
    backgroundColor: c.card,
    borderTopLeftRadius: 12,
    borderTopRightRadius: 12,
    borderColor: c.border,
    borderWidth: 1,
    padding: 16,
    gap: 24,
  },
  title: { color: c.text, fontSize: size(22), lineHeight: size(28), fontWeight: '700' },
  label: { color: c.text, fontSize: size(17), lineHeight: size(22), fontWeight: '600' },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  chip: {
    minHeight: 48,
    paddingHorizontal: 16,
    paddingVertical: 4,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: c.muted,
    justifyContent: 'center',
  },
  buttonRow: { flexDirection: 'row' },
}));
