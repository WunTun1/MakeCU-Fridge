import FontAwesome from '@expo/vector-icons/FontAwesome';
import { useEffect, useState, type ComponentProps } from 'react';
import { ActivityIndicator, Image, Pressable, StyleSheet, Text, View } from 'react-native';

import { Button } from '@/components/Button';
import { api, type RecipeDetail, type RecipeLine } from '@/lib/api';
import { colors } from '@/lib/theme';

const SERVING_CHOICES = [1, 2, 3];

/**
 * Everything needed to cook a recipe: what you have, what to swap, what to buy,
 * steps (swaps already written in), and "I made this". `large` = fridge screen.
 */
export function RecipeDetailView({ recipeId, large = false }: { recipeId: number; large?: boolean }) {
  const [recipe, setRecipe] = useState<RecipeDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [servings, setServings] = useState(1);
  const [status, setStatus] = useState<string | null>(null);
  const [rated, setRated] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api
      .recipe(recipeId)
      .then((r) => !cancelled && setRecipe(r))
      .catch((e) => !cancelled && setError((e as Error).message));
    return () => {
      cancelled = true;
    };
  }, [recipeId]);

  if (error) return <Text style={styles.muted}>Couldn&apos;t load this recipe: {error}</Text>;
  if (!recipe) return <ActivityIndicator color={colors.accent} style={{ margin: 24 }} />;

  const n = recipe.nutrition;
  const big = large ? 1.15 : 1;

  async function cooked() {
    setBusy(true);
    try {
      const result = await api.cooked(recipeId, servings);
      const used = result.used.map((u) => u.item).filter((v, i, a) => a.indexOf(v) === i);
      setStatus(`Logged ${servings} serving${servings > 1 ? 's' : ''}.${used.length ? ` Updated: ${used.join(', ')}.` : ''}`);
    } catch (e) {
      setStatus(`Couldn't log it: ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  async function rate(liked: boolean) {
    setRated(liked);
    await api.rate(recipeId, liked).catch(() => setRated(null));
  }

  return (
    <View style={{ gap: 14 }}>
      {recipe.image_url && <Image source={{ uri: recipe.image_url }} style={[styles.hero, { height: large ? 200 : 180 }]} />}

      <View style={styles.stats}>
        {recipe.minutes != null && <Stat icon="clock-o" text={`${recipe.minutes} min`} big={big} />}
        {recipe.servings != null && <Stat icon="users" text={`Serves ${Math.round(recipe.servings)}`} big={big} />}
        {n.calories != null && <Stat icon="fire" text={`${Math.round(n.calories)} kcal`} big={big} />}
        {n.protein_g != null && <Stat icon="bolt" text={`${Math.round(n.protein_g)} g protein`} big={big} />}
      </View>
      <Text style={styles.muted}>Nutrition is per serving, from the recipe source.</Text>

      {recipe.reasons.length > 0 && (
        <View style={{ gap: 4 }}>
          {recipe.reasons.map((r) => (
            <Text key={r} style={[styles.reason, { fontSize: 15 * big }]}>• {r}</Text>
          ))}
        </View>
      )}

      <Text style={[styles.section, { fontSize: 13 * big }]}>Ingredients</Text>
      <View style={{ gap: 8 }}>
        {recipe.ingredients.map((line, i) => (
          <IngredientRow key={`${line.name}-${i}`} line={line} big={big} />
        ))}
      </View>

      <Text style={[styles.section, { fontSize: 13 * big }]}>Steps</Text>
      <View style={{ gap: 10 }}>
        {recipe.steps.map((step, i) => (
          <View key={i} style={styles.stepRow}>
            <Text style={[styles.stepNum, { fontSize: 15 * big }]}>{i + 1}</Text>
            <Text style={[styles.text, { fontSize: 16 * big, flex: 1, lineHeight: 22 * big }]}>{step}</Text>
          </View>
        ))}
      </View>

      <View style={styles.cookBox}>
        <Text style={[styles.text, { fontSize: 16 * big }]}>Servings you ate</Text>
        <View style={styles.row}>
          {SERVING_CHOICES.map((s) => (
            <Pressable
              key={s}
              onPress={() => setServings(s)}
              style={[styles.choice, s === servings && { borderColor: colors.accent, backgroundColor: colors.input }]}
            >
              <Text style={[styles.text, s === servings && { color: colors.accent }]}>{s}</Text>
            </Pressable>
          ))}
        </View>
        <Button title="I made this" onPress={cooked} disabled={busy} />
        {status && <Text style={styles.muted}>{status}</Text>}
      </View>

      <View style={[styles.row, { justifyContent: 'center', gap: 24 }]}>
        <Pressable onPress={() => rate(true)} hitSlop={12} style={styles.thumb}>
          <FontAwesome name="thumbs-up" size={28 * big} color={rated === true ? colors.accent : colors.muted} />
        </Pressable>
        <Pressable onPress={() => rate(false)} hitSlop={12} style={styles.thumb}>
          <FontAwesome name="thumbs-down" size={28 * big} color={rated === false ? colors.danger : colors.muted} />
        </Pressable>
      </View>
      <Text style={[styles.muted, { textAlign: 'center' }]}>
        {rated === null ? 'Rate it to tune future suggestions' : 'Thanks — suggestions will adapt'}
      </Text>
    </View>
  );
}

const STATUS: Record<RecipeLine['status'], { label: string; color: string }> = {
  have: { label: 'Have', color: colors.accent },
  swap: { label: 'Swap', color: colors.warn },
  missing: { label: 'Buy', color: colors.danger },
  staple: { label: 'Pantry', color: colors.muted },
};

function IngredientRow({ line, big }: { line: RecipeLine; big: number }) {
  const s = STATUS[line.status];
  return (
    <View style={styles.ingRow}>
      <Text style={[styles.badge, { color: s.color, borderColor: s.color, fontSize: 12 * big }]}>{s.label}</Text>
      <View style={{ flex: 1 }}>
        <Text style={[styles.text, { fontSize: 16 * big }]}>
          {line.amount ? <Text style={styles.muted}>{line.amount} </Text> : null}
          {line.status === 'swap' ? (
            <>
              <Text style={styles.struck}>{line.name}</Text> → {line.use}
            </>
          ) : (
            line.name
          )}
        </Text>
        {line.note && <Text style={[styles.muted, { fontSize: 13 * big }]}>{line.note}</Text>}
      </View>
    </View>
  );
}

function Stat({ icon, text, big }: { icon: ComponentProps<typeof FontAwesome>['name']; text: string; big: number }) {
  return (
    <View style={styles.stat}>
      <FontAwesome name={icon} size={15 * big} color={colors.muted} />
      <Text style={[styles.text, { fontSize: 15 * big }]}>{text}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  hero: { width: '100%', borderRadius: 14, backgroundColor: colors.input },
  stats: { flexDirection: 'row', flexWrap: 'wrap', gap: 14 },
  stat: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  text: { color: colors.text, fontSize: 16 },
  muted: { color: colors.muted, fontSize: 13 },
  reason: { color: colors.accent },
  section: { color: colors.muted, fontWeight: '700', letterSpacing: 1, textTransform: 'uppercase' },
  ingRow: { flexDirection: 'row', gap: 10, alignItems: 'flex-start' },
  badge: { borderWidth: 1, borderRadius: 6, paddingHorizontal: 6, paddingVertical: 2, fontWeight: '700', minWidth: 56, textAlign: 'center' },
  struck: { textDecorationLine: 'line-through', color: colors.muted },
  stepRow: { flexDirection: 'row', gap: 10 },
  stepNum: { color: colors.accent, fontWeight: '700', width: 22 },
  cookBox: { backgroundColor: colors.card, borderColor: colors.border, borderWidth: 1, borderRadius: 14, padding: 14, gap: 10 },
  row: { flexDirection: 'row', gap: 10 },
  choice: { borderWidth: 1, borderColor: colors.border, borderRadius: 10, paddingVertical: 10, paddingHorizontal: 20 },
  thumb: { padding: 8 },
});
