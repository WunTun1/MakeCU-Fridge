import FontAwesome from '@expo/vector-icons/FontAwesome';
import { Stack } from 'expo-router';
import { useCallback, useEffect, useRef, useState } from 'react';
import { ActivityIndicator, Image, Pressable, Text, View } from 'react-native';

import { Button } from '@/components/Button';
import { CookSheet, usesAll } from '@/components/recipes/CookSheet';
import { useSnackbar } from '@/components/Snackbar';
import { formatAmount } from '@/lib/amount';
import { api, type CookLine, type Made, type RecipeDetail, type RecipeLine } from '@/lib/api';
import { makeStyles, useColors, type Palette } from '@/lib/theme';
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

/** "35 g protein · 362 kcal · 40 min · Serves 4": one line, protein first. */
function metaLine(r: RecipeDetail): string {
  const n = r.nutrition;
  return [
    n.protein_g != null && `${Math.round(n.protein_g)} g protein`,
    n.calories != null && `${Math.round(n.calories)} kcal`,
    r.minutes != null && `${r.minutes} min`,
    r.servings != null && `Serves ${Math.round(r.servings)}`,
  ]
    .filter(Boolean)
    .join(' · ');
}

/**
 * Everything needed to cook a recipe: what you have, what to swap, what to buy
 * (one tap puts it on the grocery list), steps with swaps written in, and "I made this".
 * Leftovers from an earlier cook come first: eating one logs it without touching the ingredients.
 */
export function RecipeDetailView({ recipeId }: { recipeId: number }) {
  const showSnack = useSnackbar();
  const styles = useStyles();
  const c = useColors();
  const [recipe, setRecipe] = useState<RecipeDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [onList, setOnList] = useState<Set<string>>(new Set());
  const [sheetOpen, setSheetOpen] = useState(false);
  const [rated, setRated] = useState<boolean | null>(null);
  const logging = useRef(false);

  /** Badges, leftovers and "Logged today" all come from the server, so it reloads after every change. */
  const load = useCallback(
    () =>
      api.recipe(recipeId).then(
        (r) => {
          setRecipe(r);
          setOnList(new Set(r.on_grocery_list));
        },
        (e) => setError((e as Error).message),
      ),
    [recipeId],
  );

  useEffect(() => {
    load();
  }, [load]);

  if (error) return <Text style={styles.detail}>Couldn&apos;t load this recipe: {error}</Text>;
  if (!recipe) return <ActivityIndicator color={c.accent} style={{ margin: 24 }} />;

  const loggedMeal = recipe.logged_meal_id;
  const left = recipe.leftovers;
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

  /** One write at a time; afterwards this page and every other screen reload. */
  async function write(run: () => Promise<{ message: string; undo: () => Promise<unknown> }>) {
    if (logging.current) return;
    logging.current = true;
    try {
      const { message, undo } = await run();
      await load();
      refreshAll();
      showSnack({
        message,
        action: { label: 'Undo', onPress: () => undo().then(() => (load(), refreshAll()), () => {}) },
      });
    } catch (e) {
      showSnack({ message: `Couldn't log it: ${(e as Error).message}` });
    } finally {
      logging.current = false;
    }
  }

  const log = (made: Made, servingsEaten: number) =>
    write(async () => {
      const result = await api.cooked(recipeId, made, servingsEaten);
      setSheetOpen(false);
      return { message: usedSummary(result.consumptions), undo: () => api.undoMeal(result.meal_id) };
    });

  const eatLeftover = (productId: number, name: string) =>
    write(async () => {
      const eaten = await api.eat(productId);
      const protein = eaten.protein_g != null ? ` · ${Math.round(eaten.protein_g)} g protein` : '';
      return { message: `Logged 1 serving of ${name}${protein}`, undo: () => api.undoMeal(eaten.meal_id) };
    });

  async function rate(liked: boolean) {
    setRated(liked);
    await api.rate(recipeId, liked).catch(() => setRated(null));
  }

  return (
    <View style={{ gap: 16 }}>
      <Stack.Screen options={{ title: '' }} />
      {recipe.image_url && <Image source={{ uri: recipe.image_url }} style={styles.hero} />}

      <Text style={styles.title} numberOfLines={3}>
        {recipe.name}
      </Text>

      <Text style={styles.meta}>{metaLine(recipe)}</Text>
      <Text style={styles.muted}>
        {recipe.servings != null
          ? 'Nutrition per serving, from the recipe source.'
          : 'Nutrition per serving, from the recipe source. Serving count not listed.'}
      </Text>

      {recipe.reasons.length > 0 && (
        <View style={{ gap: 4 }}>
          {recipe.reasons.map((r) => (
            <Text key={r} style={styles.detail}>
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
            <Text style={[styles.text, { flex: 1 }]}>{step}</Text>
          </View>
        ))}
      </View>

      <View style={styles.cookBox}>
        {left && (
          <>
            <Text style={styles.text}>
              You have {left.servings === 1 ? '1 serving' : `${left.servings} servings`} left over
            </Text>
            <View style={styles.buttonRow}>
              <Button title="Ate one serving" onPress={() => eatLeftover(left.product_id, recipe.name)} />
            </View>
          </>
        )}
        <View style={styles.buttonRow}>
          <Button
            title={loggedMeal != null ? 'Logged today' : 'I made this'}
            variant={left ? 'secondary' : 'primary'}
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
          <FontAwesome name="thumbs-up" size={28} color={rated === true ? c.accent : c.textSecondary} />
        </Pressable>
        <Pressable onPress={() => rate(false)} hitSlop={12} style={styles.thumb} accessibilityLabel="Not for me">
          <FontAwesome name="thumbs-down" size={28} color={rated === false ? c.danger : c.textSecondary} />
        </Pressable>
      </View>
      <Text style={[styles.detail, { textAlign: 'center' }]}>
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

type Badge = { label: string; color: string; border: string | null; check?: boolean };

/**
 * Have is the common case, so it's neutral with a check. Short is amber, Buy is the accent
 * (it's tappable). Red is never used here: red means "goes bad today or tomorrow".
 * Staples (salt, oil, water from the pasta) say "Pantry" with no border.
 */
function badgeFor(status: RecipeLine['status'], listed: boolean, c: Palette): Badge {
  if (listed && (status === 'missing' || status === 'short')) return { label: 'On list', color: c.textSecondary, border: c.border };
  switch (status) {
    case 'have':
      return { label: 'Have', color: c.textSecondary, border: c.border, check: true };
    case 'swap':
      return { label: 'Swap', color: c.text, border: c.muted };
    case 'short':
      return { label: 'Short', color: c.warn, border: c.warn };
    case 'missing':
      return { label: 'Buy', color: c.accent, border: c.accent };
    default:
      return { label: 'Pantry', color: c.textSecondary, border: null };
  }
}

function IngredientRow({ line, listed, onBuy }: { line: RecipeLine; listed: boolean; onBuy: () => void }) {
  const styles = useStyles();
  const c = useColors();
  const b = badgeFor(line.status, listed, c);
  const badge = (
    <View style={[styles.badge, b.border ? { borderColor: b.border } : styles.plainBadge]}>
      {b.check && <FontAwesome name="check" size={12} color={b.color} />}
      <Text style={[styles.badgeText, { color: b.color }]}>{b.label}</Text>
    </View>
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
        <Text style={styles.text}>
          {line.amount ? `${line.amount} ` : null}
          {line.use ? (
            <>
              <Text style={styles.struck}>{line.name}</Text> → {line.use}
            </>
          ) : (
            line.name
          )}
          {line.on_hand ? <Text style={{ color: c.warn }}> · you have {line.on_hand}</Text> : null}
        </Text>
        {line.note && <Text style={styles.detail}>{line.note}</Text>}
      </View>
    </View>
  );
}

const useStyles = makeStyles((c, size) => ({
  hero: { width: '100%', height: 180, borderRadius: 12, backgroundColor: c.input },
  title: { color: c.text, fontSize: size(22), lineHeight: size(28), fontWeight: '700' },
  meta: { color: c.text, fontSize: size(15), lineHeight: size(20) },
  text: { color: c.text, fontSize: size(16), lineHeight: size(22) },
  detail: { color: c.textSecondary, fontSize: size(15), lineHeight: size(20) },
  muted: { color: c.muted, fontSize: size(13), lineHeight: size(18) },
  section: { color: c.textSecondary, fontSize: size(13), fontWeight: '700', letterSpacing: 1, textTransform: 'uppercase' },
  ingRow: { flexDirection: 'row', gap: 12, alignItems: 'flex-start' },
  badge: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 4,
    minHeight: size(24),
    minWidth: size(72),
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 8,
  },
  plainBadge: { borderColor: 'transparent' },
  badgeText: { fontSize: size(13), lineHeight: size(16), fontWeight: '600' },
  struck: { textDecorationLine: 'line-through', color: c.textSecondary },
  stepRow: { flexDirection: 'row', gap: 12 },
  stepNum: { color: c.accent, fontWeight: '700', width: size(24), fontSize: size(15), lineHeight: size(22) },
  cookBox: { gap: 8 },
  buttonRow: { flexDirection: 'row', minHeight: 48 },
  textButton: { minHeight: 44, alignSelf: 'center', justifyContent: 'center', paddingHorizontal: 8 },
  link: { color: c.accent, fontSize: size(15), fontWeight: '600' },
  row: { flexDirection: 'row', gap: 12 },
  thumb: { padding: 8 },
}));
