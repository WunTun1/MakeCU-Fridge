import FontAwesome from '@expo/vector-icons/FontAwesome';
import { useState } from 'react';
import { Modal, Pressable, ScrollView, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { AddFoodSheet, portionText } from '@/components/AddFoodSheet';
import { Button } from '@/components/Button';
import { useSnackbar } from '@/components/Snackbar';
import { ErrorCard, Loading } from '@/components/States';
import { api, type Meal, type QuickAdd } from '@/lib/api';
import { makeStyles, useColors, useUi } from '@/lib/theme';
import { capitalize, clockTime } from '@/lib/time';
import { refreshAll, useApi } from '@/lib/useApi';

const round = (n: number | null | undefined) => Math.round(n ?? 0);

/** "1 serving · 35 g protein · 362 kcal · 12:40 PM". */
function mealLine(m: Meal): string {
  const servings = Math.round(m.servings * 10) / 10;
  return [
    servings === 1 ? '1 serving' : `${servings} servings`,
    m.protein_g != null && `${round(m.protein_g)} g protein`,
    m.calories != null && `${round(m.calories)} kcal`,
    clockTime(m.occurred_at),
  ]
    .filter(Boolean)
    .join(' · ');
}

/** Everything eaten today, with a way to take a wrong entry off and to add food. */
export default function Today() {
  const meals = useApi(api.meals);
  const profile = useApi(api.profile);
  const showSnack = useSnackbar();
  const ui = useUi();
  const styles = useStyles();
  const c = useColors();
  const [adding, setAdding] = useState(false);
  /** A meal cooked with "I made this": its x asks which undo is meant. */
  const [removing, setRemoving] = useState<Meal | null>(null);

  if (meals.loading && !meals.data) return <Loading />;

  const list = [...(meals.data ?? [])].reverse();
  const total = (key: 'protein_g' | 'calories' | 'carbs_g' | 'fat_g') => list.reduce((sum, m) => sum + (m[key] ?? 0), 0);
  const p = profile.data;

  const changed = (message: string, undo: () => Promise<unknown>) => {
    meals.reload();
    refreshAll();
    showSnack({ message, action: { label: 'Undo', onPress: () => undo().then(() => (meals.reload(), refreshAll()), () => {}) } });
  };

  /** Off today's log only; the fridge stays as it is. */
  async function removeFromLog(m: Meal) {
    setRemoving(null);
    try {
      const removed = await api.deleteMeal(m.id);
      changed(`Removed ${m.name ?? 'the meal'} from today`, () => api.addMeal({ ...removed, name: removed.name ?? 'Meal' }));
    } catch (e) {
      showSnack({ message: `Couldn't remove it: ${(e as Error).message}` });
    }
  }

  /** The cooking too: the ingredients go back and its leftovers go away. */
  async function undoCooking(m: Meal) {
    setRemoving(null);
    try {
      await api.undoMeal(m.id);
      meals.reload();
      refreshAll();
      showSnack({ message: `Took back cooking ${m.name ?? 'the meal'}` });
    } catch (e) {
      showSnack({ message: `Couldn't undo it: ${(e as Error).message}` });
    }
  }

  async function addPortion(q: QuickAdd) {
    const eaten = await api.eat(q.product_id, q.grams);
    setAdding(false);
    changed(`Logged ${portionText(q)} · took it from the fridge`, () => api.undoMeal(eaten.meal_id));
  }

  async function addOther(entry: { name: string; protein_g: number | null; calories: number | null }) {
    const { meal_id } = await api.addMeal(entry);
    setAdding(false);
    const protein = entry.protein_g != null ? ` · ${round(entry.protein_g)} g protein` : '';
    changed(`Logged ${entry.name}${protein}`, () => api.deleteMeal(meal_id));
  }

  return (
    <ScrollView style={ui.screen} contentContainerStyle={ui.content}>
      {meals.error && <ErrorCard message={meals.error} />}

      <View style={[ui.card, { gap: 12 }]}>
        <Total label="Protein" value={round(total('protein_g'))} goal={p?.daily_protein_g} unit="g" />
        <Total label="Calories" value={round(total('calories'))} goal={p?.daily_calories} unit="kcal" />
        <Text style={ui.detail}>
          Carbs {round(total('carbs_g'))} g · Fat {round(total('fat_g'))} g
        </Text>
      </View>

      <View style={styles.buttonRow}>
        <Button title="Add food" variant="secondary" onPress={() => setAdding(true)} />
      </View>

      <Text style={ui.h2}>{list.length === 1 ? '1 meal' : `${list.length} meals`}</Text>
      <View style={[ui.card, { paddingVertical: 4 }]}>
        {list.length === 0 ? (
          <Text style={[ui.detail, { paddingVertical: 12 }]}>Nothing logged yet today.</Text>
        ) : (
          list.map((m, i) => (
            <View key={m.id} style={[styles.mealRow, i > 0 && styles.divider]}>
              <View style={{ flex: 1, gap: 2 }}>
                <Text style={ui.text}>{m.name ?? 'Meal'}</Text>
                <Text style={ui.detail}>{mealLine(m)}</Text>
              </View>
              <Pressable
                onPress={() => (m.cook_undo ? setRemoving(m) : removeFromLog(m))}
                style={styles.remove}
                accessibilityRole="button"
                accessibilityLabel={`Remove ${m.name ?? 'this meal'} from today`}
              >
                <FontAwesome name="close" size={20} color={c.textSecondary} />
              </Pressable>
            </View>
          ))
        )}
      </View>
      <Text style={ui.muted}>General wellness info, not medical advice.</Text>

      <AddFoodSheet visible={adding} onClose={() => setAdding(false)} onPortion={addPortion} onOther={addOther} />
      <RemoveCookedSheet meal={removing} onClose={() => setRemoving(null)} onLogOnly={removeFromLog} onCooking={undoCooking} />
    </ScrollView>
  );
}

/** For a meal cooked with "I made this": take it off the log only, or undo the cooking too. */
function RemoveCookedSheet({
  meal,
  onClose,
  onLogOnly,
  onCooking,
}: {
  meal: Meal | null;
  onClose: () => void;
  onLogOnly: (m: Meal) => void;
  onCooking: (m: Meal) => void;
}) {
  const insets = useSafeAreaInsets();
  const ui = useUi();
  const styles = useStyles();
  return (
    <Modal visible={meal != null} transparent animationType="slide" onRequestClose={onClose}>
      <Pressable style={styles.backdrop} onPress={onClose} accessibilityLabel="Close" />
      {meal && (
        <View style={[styles.sheet, { paddingBottom: 16 + insets.bottom }]}>
          <Text style={styles.title}>Remove {meal.name ?? 'this meal'}?</Text>
          <View style={{ gap: 8 }}>
            <View style={styles.buttonRow}>
              <Button title="Remove from today's log" variant="outline" onPress={() => onLogOnly(meal)} />
            </View>
            <Text style={ui.detail}>Takes off the nutrition only. The fridge stays as it is.</Text>
          </View>
          <View style={{ gap: 8 }}>
            <View style={styles.buttonRow}>
              <Button title="Undo cooking it too" variant="outline" onPress={() => onCooking(meal)} />
            </View>
            {meal.cook_undo && <Text style={ui.detail}>{capitalize(meal.cook_undo)}</Text>}
          </View>
        </View>
      )}
    </Modal>
  );
}

function Total({ label, value, goal, unit }: { label: string; value: number; goal: number | null | undefined; unit: string }) {
  const styles = useStyles();
  return (
    <View style={styles.total}>
      <Text style={styles.label}>{label}</Text>
      <Text style={styles.amount}>
        {value.toLocaleString()}
        {goal ? ` of ${Math.round(goal).toLocaleString()}` : ''} {unit}
      </Text>
    </View>
  );
}

const useStyles = makeStyles((c, size) => ({
  total: { flexDirection: 'row', alignItems: 'baseline', justifyContent: 'space-between', gap: 8 },
  label: { color: c.text, fontSize: size(17), lineHeight: size(22), fontWeight: '600' },
  amount: { color: c.text, fontSize: size(20), lineHeight: size(24), fontWeight: '700', flexShrink: 1, textAlign: 'right' },
  buttonRow: { flexDirection: 'row' },
  mealRow: { flexDirection: 'row', alignItems: 'center', gap: 12, minHeight: 56, paddingVertical: 8 },
  divider: { borderTopColor: c.border, borderTopWidth: 1 },
  remove: { width: 44, height: 44, alignItems: 'center', justifyContent: 'center' },
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
}));
