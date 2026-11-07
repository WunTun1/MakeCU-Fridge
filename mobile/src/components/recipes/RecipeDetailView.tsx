import FontAwesome from '@expo/vector-icons/FontAwesome';
import { Stack } from 'expo-router';
import { useEffect, useRef, useState, type ComponentProps } from 'react';
import { ActivityIndicator, Image, Pressable, StyleSheet, Text, View } from 'react-native';

import { Button } from '@/components/Button';
import { CookSheet, usesAll } from '@/components/recipes/CookSheet';
import { useSnackbar } from '@/components/Snackbar';
import { formatAmount } from '@/lib/amount';
import { api, type CookLine, type Made, type RecipeDetail, type RecipeLine } from '@/lib/api';
import { colors } from '@/lib/theme';
import { refreshAll } from '@/lib/useApi';

/** "Used 400 g chicken breast, all the spinach". */
function usedSummary(lines: CookLine[]): string {
  if (lines.length === 0) return 'Logged it. Nothing you track was used.';
  const parts = lines.map((l) => {
    const name = l.item.toLowerCase();
    if (usesAll(l)) return `all the ${name}`;
    const amount = formatAmount(l.grams_used, l.unit, l.grams_per_unit, l.item);
    return l.unit === 'count' ? amount : `${amount} ${name}`;
  });
  return `Used ${parts.join(', ')}`;
}

/**
 * Everything needed to cook a recipe: what you have, what to swap, what to buy
 * (one tap puts it on the grocery list), steps with swaps written in, and "I made this".
 */
export function RecipeDetailView({ recipeId }: { recipeId: number }) {
  const showSnack = useSnackbar();
  const [recipe, setRecipe] = useState<RecipeDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [onList, setOnList] = useState<Set<string>>(new Set());
  const [sheetOpen, setSheetOpen] = useState(false);
  const [loggedMeal, setLoggedMeal] = useState<number | null>(null);
  const [rated, setRated] = useState<boolean | null>(null);
  const logging = useRef(false);

  useEffect(() => {
    let cancelled = false;
    api
      .recipe(recipeId)
      .then((r) => {
        if (cancelled) return;
        setRecipe(r);
        setOnList(new Set(r.on_grocery_list));
      })
      .catch((e) => !cancelled && setError((e as Error).message));
    return () => {
      cancelled = true;
    };
  }, [recipeId]);

  if (error) return <Text style={styles.muted}>Couldn&apos;t load this recipe: {error}</Text>;
  if (!recipe) return <ActivityIndicator color={colors.accent} style={{ margin: 24 }} />;

  const n = recipe.nutrition;
  const needed = [...recipe.missing, ...recipe.short.map((s) => s.name)];
  const toBuy = needed.filter((m) => !onList.has(m));

  async function addToList(names: string[]) {
    if (!recipe || names.length === 0) return;
    setOnList((prev) => new Set([...prev, ...names]));
    try {
      await api.addToGrocery({ names, source: 'recipe', recipe_id: recipe.id, recipe_name: recipe.name });
    } catch (e) {
      setOnList((prev) => new Set([...prev].filter((x) => !names.includes(x))));
      showSnack({ message: `Couldn't add to the list: ${(e as Error).message}` });
    }
  }

  async function log(made: Made, servingsEaten: number) {
    if (logging.current) return;
    logging.current = true;
    try {
      const result = await api.cooked(recipeId, made, servingsEaten);
      setSheetOpen(false);
      setLoggedMeal(result.meal_id);
      refreshAll();
      showSnack({
        message: usedSummary(result.consumptions),
        action: {
          label: 'Undo',
          onPress: () =>
            api.undoMeal(result.meal_id).then(() => {
              setLoggedMeal(null);
              refreshAll();
            }, () => {}),
        },
      });
    } catch (e) {
      showSnack({ message: `Couldn't log it: ${(e as Error).message}` });
    } finally {
      logging.current = false;
    }
  }

  async function rate(liked: boolean) {
    setRated(liked);
    await api.rate(recipeId, liked).catch(() => setRated(null));
  }

  return (
    <View style={{ gap: 16 }}>
      <Stack.Screen options={{ title: recipe.name }} />
      {recipe.image_url && <Image source={{ uri: recipe.image_url }} style={styles.hero} />}

      <Text style={styles.title} numberOfLines={3}>
        {recipe.name}
      </Text>

      <View style={styles.stats}>
        {recipe.minutes != null && <Stat icon="clock-o" text={`${recipe.minutes} min`} />}
        {recipe.servings != null && <Stat icon="users" text={`Serves ${Math.round(recipe.servings)}`} />}
        {n.calories != null && <Stat icon="fire" text={`${Math.round(n.calories)} kcal`} />}
        {n.protein_g != null && <Stat icon="bolt" text={`${Math.round(n.protein_g)} g protein`} />}
      </View>
      <Text style={styles.muted}>
        {recipe.servings != null
          ? 'Nutrition per serving, from the recipe source.'
          : 'Nutrition per serving, from the recipe source. Serving count not listed.'}
      </Text>

      {recipe.reasons.length > 0 && (
        <View style={{ gap: 4 }}>
          {recipe.reasons.map((r) => (
            <Text key={r} style={styles.reason}>
              {r}
            </Text>
          ))}
        </View>
      )}

      <Text style={styles.section}>Ingredients</Text>
      <View style={{ gap: 8 }}>
        {recipe.ingredients.map((line, i) => (
          <IngredientRow
            key={`${line.name}-${i}`}
            line={line}
            listed={onList.has(line.name)}
            onBuy={() => addToList([line.name])}
          />
        ))}
      </View>
      {needed.length > 0 && (
        <View style={styles.buttonRow}>
          <Button
            variant="secondary"
            title={toBuy.length === 0 ? 'On your grocery list' : `Add ${toBuy.length} to grocery list`}
            disabled={toBuy.length === 0}
            onPress={() => addToList(toBuy)}
          />
        </View>
      )}

      <Text style={styles.section}>Steps</Text>
      <View style={{ gap: 12 }}>
        {recipe.steps.map((step, i) => (
          <View key={i} style={styles.stepRow}>
            <Text style={styles.stepNum}>{i + 1}</Text>
            <Text style={[styles.text, { flex: 1, lineHeight: 22 }]}>{step}</Text>
          </View>
        ))}
      </View>

      <View style={styles.cookBox}>
        <View style={styles.buttonRow}>
          <Button
            title={loggedMeal != null ? 'Logged today' : 'I made this'}
            onPress={() => setSheetOpen(true)}
            disabled={loggedMeal != null}
          />
        </View>
        {loggedMeal != null && (
          <Pressable onPress={() => setSheetOpen(true)} style={styles.textButton}>
            <Text style={styles.link}>Log again</Text>
          </Pressable>
        )}
      </View>

      <View style={[styles.row, { justifyContent: 'center', gap: 24 }]}>
        <Pressable onPress={() => rate(true)} hitSlop={12} style={styles.thumb} accessibilityLabel="I liked it">
          <FontAwesome name="thumbs-up" size={28} color={rated === true ? colors.accent : colors.muted} />
        </Pressable>
        <Pressable onPress={() => rate(false)} hitSlop={12} style={styles.thumb} accessibilityLabel="Not for me">
          <FontAwesome name="thumbs-down" size={28} color={rated === false ? colors.danger : colors.muted} />
        </Pressable>
      </View>
      <Text style={[styles.muted, { textAlign: 'center' }]}>
        {rated === null ? 'Rate it to tune future suggestions' : 'Thanks. Suggestions will adapt.'}
      </Text>

      <CookSheet
        recipeId={recipeId}
        recipeName={recipe.name}
        servings={recipe.servings}
        nutrition={recipe.nutrition}
        visible={sheetOpen}
        onClose={() => setSheetOpen(false)}
        onLog={log}
      />
    </View>
  );
}

type Badge = { label: string; color: string; border: string; check?: boolean };

/**
 * Have is the common case, so it's neutral with a check. Short is amber, Buy is the accent
 * (it's tappable). Red is never used here: red means "goes bad today or tomorrow".
 * Staples (salt, oil, water from the pasta) get no badge.
 */
function badgeFor(status: RecipeLine['status'], listed: boolean): Badge | null {
  if (listed && (status === 'missing' || status === 'short')) return { label: 'On list', color: colors.muted, border: colors.border };
  switch (status) {
    case 'have':
      return { label: 'Have', color: colors.muted, border: colors.border, check: true };
    case 'swap':
      return { label: 'Swap', color: colors.text, border: colors.muted };
    case 'short':
      return { label: 'Short', color: colors.warn, border: colors.warn };
    case 'missing':
      return { label: 'Buy', color: colors.accent, border: colors.accent };
    default:
      return null;
  }
}

function IngredientRow({ line, listed, onBuy }: { line: RecipeLine; listed: boolean; onBuy: () => void }) {
  const b = badgeFor(line.status, listed);
  const badge = b ? (
    <View style={[styles.badge, { borderColor: b.border }]}>
      {b.check && <FontAwesome name="check" size={11} color={b.color} />}
      <Text style={[styles.badgeText, { color: b.color }]}>{b.label}</Text>
    </View>
  ) : (
    <View style={styles.noBadge} />
  );
  return (
    <View style={styles.ingRow}>
      {line.status === 'missing' && !listed ? (
        <Pressable
          onPress={onBuy}
          hitSlop={{ top: 11, bottom: 11, left: 8, right: 8 }}
          accessibilityRole="button"
          accessibilityLabel={`Add ${line.name} to the grocery list`}
        >
          {badge}
        </Pressable>
      ) : (
        badge
      )}
      <View style={{ flex: 1 }}>
        <Text style={[styles.text, line.status === 'staple' && { color: colors.muted }]}>
          {line.amount ? <Text style={styles.muted}>{line.amount} </Text> : null}
          {line.use ? (
            <>
              <Text style={styles.struck}>{line.name}</Text> → {line.use}
            </>
          ) : (
            line.name
          )}
          {line.on_hand ? <Text style={{ color: colors.warn }}> · you have {line.on_hand}</Text> : null}
        </Text>
        {line.note && <Text style={styles.muted}>{line.note}</Text>}
      </View>
    </View>
  );
}

function Stat({ icon, text }: { icon: ComponentProps<typeof FontAwesome>['name']; text: string }) {
  return (
    <View style={styles.stat}>
      <FontAwesome name={icon} size={15} color={colors.muted} />
      <Text style={[styles.text, { fontSize: 15 }]}>{text}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  hero: { width: '100%', height: 180, borderRadius: 12, backgroundColor: colors.input },
  title: { color: colors.text, fontSize: 22, lineHeight: 28, fontWeight: '700' },
  stats: { flexDirection: 'row', flexWrap: 'wrap', gap: 16 },
  stat: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  text: { color: colors.text, fontSize: 16 },
  muted: { color: colors.muted, fontSize: 13 },
  reason: { color: colors.accent, fontSize: 15 },
  section: { color: colors.muted, fontSize: 13, fontWeight: '700', letterSpacing: 1, textTransform: 'uppercase' },
  ingRow: { flexDirection: 'row', gap: 12, alignItems: 'flex-start' },
  badge: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 4,
    height: 22,
    minWidth: 68,
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 8,
  },
  badgeText: { fontSize: 12, lineHeight: 16, fontWeight: '600' },
  noBadge: { minWidth: 68 },
  struck: { textDecorationLine: 'line-through', color: colors.muted },
  stepRow: { flexDirection: 'row', gap: 12 },
  stepNum: { color: colors.accent, fontWeight: '700', width: 24, fontSize: 15 },
  cookBox: { gap: 4 },
  buttonRow: { flexDirection: 'row', minHeight: 48 },
  textButton: { minHeight: 44, alignSelf: 'center', justifyContent: 'center', paddingHorizontal: 8 },
  link: { color: colors.accent, fontSize: 15, fontWeight: '600' },
  row: { flexDirection: 'row', gap: 12 },
  thumb: { padding: 8 },
});
