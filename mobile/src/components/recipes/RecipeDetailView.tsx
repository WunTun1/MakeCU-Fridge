import FontAwesome from "@expo/vector-icons/FontAwesome";
import { Stack, router } from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  Text,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { Button } from "@/components/Button";
import { RecipePhoto } from "@/components/RecipePhoto";
import { CookSheet, usesAll } from "@/components/recipes/CookSheet";
import { useSnackbar, useSnackbarClearance } from "@/components/Snackbar";
import { formatAmount } from "@/lib/amount";
import {
  api,
  type CookLine,
  type Made,
  type RecipeDetail,
  type RecipeLine,
} from "@/lib/api";
import { makeStyles, useColors, useUi, type Palette } from "@/lib/theme";
import { refreshAll } from "@/lib/useApi";

/** "Used 400 g chicken breast, all the spinach". */
function usedSummary(lines: CookLine[]): string {
  if (lines.length === 0) return "Logged it. Nothing you track was used.";
  const parts = lines.map((l) => {
    const name = l.item.toLowerCase();
    if (usesAll(l)) return `all the ${name}`;
    const amount = formatAmount(l.grams_used, l.unit, l.grams_per_unit, l.item);
    return l.unit === "count" ? amount : `${amount} ${name}`;
  });
  return `Used ${parts.join(", ")}`;
}

/** "45 min", "1 hr 5 min". */
function duration(min: number): string {
  const h = Math.floor(min / 60);
  const m = Math.round(min % 60);
  return h ? `${h} hr${m ? ` ${m} min` : ""}` : `${m} min`;
}

/**
 * How long: "Prep" (hands-on, from the source) and "Total" (plus marinating, chilling, rising)
 * when there's waiting; otherwise the one number, as "Time".
 */
function times(r: RecipeDetail): { label: string; value: string }[] {
  const prep = r.minutes ?? 0;
  const total = prep + (r.inactive_min ?? 0);
  if (!total) return [];
  if (!prep || total === prep)
    return [{ label: "Time", value: duration(total) }];
  return [
    { label: "Prep", value: duration(prep) },
    { label: "Total", value: duration(total) },
  ];
}

const capitalize = (t: string) => t.charAt(0).toUpperCase() + t.slice(1);

type Tone = "have" | "more" | "need" | "pantry" | "allergy";

/** Green: you have it (or a stand-in). Yellow: some, not enough. Red: buy it, or an allergen. */
function toneOf({ status, allergy }: RecipeLine): Tone {
  if (allergy) return "allergy";
  if (status === "have" || status === "swap") return "have";
  if (status === "short") return "more";
  if (status === "missing") return "need";
  return "pantry";
}

function toneColor(tone: Tone, c: Palette): string {
  return tone === "have"
    ? c.good
    : tone === "more"
      ? c.warn
      : tone === "pantry"
        ? c.border
        : c.danger;
}

/**
 * A recipe the way you'd want it while deciding and cooking: the photo, how long it takes,
 * every ingredient marked green (have it), yellow (need a bit more) or red (need to buy) with
 * its amount, then the steps. "Add to grocery list" stays at the bottom, in the middle, so
 * what's missing is one tap from the Grocery tab. "I made this" logs the meal.
 */
export function RecipeDetailView({ recipeId }: { recipeId: number }) {
  const showSnack = useSnackbar();
  const styles = useStyles();
  const ui = useUi();
  const c = useColors();
  const [barHeight, setBarHeight] = useState(0);
  useSnackbarClearance(barHeight);
  const [recipe, setRecipe] = useState<RecipeDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [onList, setOnList] = useState<Set<string>>(new Set());
  const [sheetOpen, setSheetOpen] = useState(false);
  const [rated, setRated] = useState<boolean | null>(null);
  const logging = useRef(false);

  /** Statuses, leftovers and "Logged today" all come from the server, so it reloads after every change. */
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

  if (error) {
    return (
      <View style={[ui.screen, ui.content]}>
        <Text style={styles.detail}>
          Couldn&apos;t load this recipe: {error}
        </Text>
      </View>
    );
  }
  if (!recipe) {
    return (
      <View style={ui.screen}>
        <ActivityIndicator color={c.accent} style={{ margin: 24 }} />
      </View>
    );
  }

  const left = recipe.leftovers;
  const allergyLines = new Set(
    recipe.ingredients.filter((l) => l.allergy).map((l) => l.name),
  );
  const needed = [...recipe.missing, ...recipe.short.map((s) => s.name)].filter(
    (n) => !allergyLines.has(n),
  );
  const toBuy = needed.filter((m) => !onList.has(m));
  const counted = recipe.ingredients.filter((l) => l.status !== "staple");
  const haveCount = counted.filter((l) => toneOf(l) === "have").length;

  async function addToList(names: string[]) {
    if (!recipe || names.length === 0) return;
    setOnList((prev) => new Set([...prev, ...names]));
    try {
      // Each with the amount the recipe calls for ("1/2 cup"), so the list says how much to get.
      const amountOf = (n: string) =>
        recipe.ingredients.find((l) => l.name === n)?.amount ?? null;
      await api.addToGrocery({
        names,
        source: "recipe",
        recipe_id: recipe.id,
        recipe_name: recipe.name,
        amounts: names.map(amountOf),
      });
      refreshAll();
      showSnack({
        message:
          names.length === 1
            ? `Added ${names[0].toLowerCase()} to your grocery list`
            : `Added ${names.length} items to your grocery list`,
        action: { label: "View list", onPress: () => router.push("/grocery") },
      });
    } catch (e) {
      setOnList((prev) => new Set([...prev].filter((x) => !names.includes(x))));
      showSnack({
        message: `Couldn't add to the list: ${(e as Error).message}`,
      });
    }
  }

  /** One write at a time; afterwards this page and every other screen reload. */
  async function write(
    run: () => Promise<{ message: string; undo: () => Promise<unknown> }>,
  ) {
    if (logging.current) return;
    logging.current = true;
    try {
      const { message, undo } = await run();
      await load();
      refreshAll();
      showSnack({
        message,
        action: {
          label: "Undo",
          onPress: () =>
            undo().then(
              () => (load(), refreshAll()),
              () => {},
            ),
        },
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
      return {
        message: usedSummary(result.consumptions),
        undo: () => api.undoMeal(result.meal_id),
      };
    });

  const eatLeftover = (productId: number, name: string) =>
    write(async () => {
      const eaten = await api.eat(productId);
      const protein =
        eaten.protein_g != null
          ? ` · ${Math.round(eaten.protein_g)} g protein`
          : "";
      return {
        message: `Logged 1 serving of ${name}${protein}`,
        undo: () => api.undoMeal(eaten.meal_id),
      };
    });

  async function rate(liked: boolean) {
    setRated(liked);
    await api.rate(recipeId, liked).catch(() => setRated(null));
  }

  const n = recipe.nutrition;
  const facts = [
    ...times(recipe),
    ...(recipe.servings != null
      ? [{ label: "Serves", value: String(Math.round(recipe.servings)) }]
      : []),
    ...(n.protein_g != null
      ? [{ label: "Protein", value: `${Math.round(n.protein_g)} g` }]
      : []),
    ...(n.calories != null
      ? [{ label: "Calories", value: Math.round(n.calories).toLocaleString() }]
      : []),
  ];

  return (
    <View style={ui.screen}>
      <Stack.Screen options={{ title: "" }} />
      <ScrollView contentContainerStyle={{ paddingBottom: barHeight + 24 }}>
        <RecipePhoto uri={recipe.image_url} style={styles.hero} />

        <View style={[ui.content, { gap: 20 }]}>
          <Text style={styles.title}>{recipe.name}</Text>

          {facts.length > 0 && (
            <View style={styles.facts}>
              {facts.map((f, i) => (
                <View
                  key={f.label}
                  style={[styles.fact, i > 0 && styles.factDivider]}
                >
                  <Text style={styles.factValue}>{f.value}</Text>
                  <Text style={styles.factLabel}>{f.label}</Text>
                </View>
              ))}
            </View>
          )}

          {recipe.allergens.map((a) => (
            <View
              key={a.allergy}
              style={styles.allergy}
              accessibilityRole="alert"
            >
              <Text style={styles.text}>
                Contains {a.allergy}
                {a.lines.length > 0 ? `: ${a.lines.join(", ")}` : ""}. You
                listed {a.allergy} as an allergy.
              </Text>
            </View>
          ))}

          {left && (
            <View style={[ui.card, { gap: 8 }]}>
              <Text style={styles.text}>
                You have{" "}
                {left.servings === 1
                  ? "1 serving"
                  : `${left.servings} servings`}{" "}
                left over
              </Text>
              <View style={styles.buttonRow}>
                <Button
                  title="Ate one serving"
                  variant="outline"
                  onPress={() => eatLeftover(left.product_id, recipe.name)}
                />
              </View>
            </View>
          )}

          <View style={{ gap: 10 }}>
            <View style={styles.sectionRow}>
              <Text style={styles.section}>Ingredients</Text>
              {counted.length > 0 && (
                <Text style={styles.muted}>
                  You have {haveCount} of {counted.length}
                </Text>
              )}
            </View>
            <View style={styles.legend}>
              <Legend color={c.good} label="Have it" />
              <Legend color={c.warn} label="Need more" />
              <Legend color={c.danger} label="Need to buy" />
            </View>
            <View style={[ui.card, { paddingVertical: 4 }]}>
              {recipe.ingredients.map((line, i) => (
                <IngredientRow
                  key={`${line.name}-${i}`}
                  line={line}
                  listed={onList.has(line.name)}
                  last={i === recipe.ingredients.length - 1}
                />
              ))}
            </View>
          </View>

          <View style={{ gap: 12 }}>
            <Text style={styles.section}>Steps</Text>
            {recipe.steps.map((step, i) => (
              <View key={i} style={styles.stepRow}>
                <View style={styles.stepNum}>
                  <Text style={styles.stepNumText}>{i + 1}</Text>
                </View>
                <Text style={[styles.text, { flex: 1 }]}>{step}</Text>
              </View>
            ))}
          </View>

          <View style={{ gap: 8 }}>
            {recipe.logged_meal_id != null && (
              <Text style={[styles.detail, { textAlign: "center" }]}>
                Logged today
              </Text>
            )}
            <View style={styles.buttonRow}>
              <Button
                title={
                  recipe.logged_meal_id != null ? "Log it again" : "I made this"
                }
                variant="outline"
                onPress={() => setSheetOpen(true)}
              />
            </View>
          </View>

          <View style={[styles.row, { justifyContent: "center", gap: 24 }]}>
            <Pressable
              onPress={() => rate(true)}
              hitSlop={12}
              style={styles.thumb}
              accessibilityLabel="I liked it"
            >
              <FontAwesome
                name="thumbs-up"
                size={28}
                color={rated === true ? c.accent : c.textSecondary}
              />
            </Pressable>
            <Pressable
              onPress={() => rate(false)}
              hitSlop={12}
              style={styles.thumb}
              accessibilityLabel="Not for me"
            >
              <FontAwesome
                name="thumbs-down"
                size={28}
                color={rated === false ? c.danger : c.textSecondary}
              />
            </Pressable>
          </View>
          <Text
            style={[styles.detail, { textAlign: "center", marginTop: -12 }]}
          >
            {rated === null
              ? "Rate it to tune future suggestions"
              : "Thanks. Suggestions will adapt."}
          </Text>
        </View>
      </ScrollView>

      <GroceryBar
        toBuy={toBuy.length}
        needed={needed.length}
        onAdd={() => addToList(toBuy)}
        onHeight={setBarHeight}
      />

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

/** The green button that's always at the bottom, in the middle: what's missing goes on the grocery list. */
function GroceryBar({
  toBuy,
  needed,
  onAdd,
  onHeight,
}: {
  toBuy: number;
  needed: number;
  onAdd: () => void;
  onHeight: (px: number) => void;
}) {
  const styles = useStyles();
  const c = useColors();
  const insets = useSafeAreaInsets();
  const done = toBuy === 0;
  const label =
    needed === 0
      ? "You have everything"
      : done
        ? "On your grocery list"
        : `Add ${toBuy} to grocery list`;
  return (
    <View
      style={[styles.bar, { paddingBottom: 12 + insets.bottom }]}
      onLayout={(e) => onHeight(Math.round(e.nativeEvent.layout.height))}
    >
      <Pressable
        onPress={onAdd}
        disabled={done}
        accessibilityRole="button"
        accessibilityState={{ disabled: done }}
        style={({ pressed }) => [
          styles.groceryButton,
          done && styles.groceryDone,
          pressed && { opacity: 0.85 },
        ]}
      >
        <FontAwesome
          name={done ? "check" : "shopping-cart"}
          size={18}
          color={done ? c.accent : c.onAccent}
        />
        <Text style={[styles.groceryLabel, done && { color: c.accent }]}>
          {label}
        </Text>
      </Pressable>
    </View>
  );
}

function Legend({ color, label }: { color: string; label: string }) {
  const styles = useStyles();
  return (
    <View style={styles.legendItem}>
      <View style={[styles.dot, { backgroundColor: color }]} />
      <Text style={styles.muted}>{label}</Text>
    </View>
  );
}

/** One ingredient: a colored dot (green / yellow / red), the name, its amount, and what to know about it. */
function IngredientRow({
  line,
  listed,
  last,
}: {
  line: RecipeLine;
  listed: boolean;
  last: boolean;
}) {
  const styles = useStyles();
  const ui = useUi();
  const c = useColors();
  const tone = toneOf(line);
  const color = toneColor(tone, c);
  const note =
    tone === "allergy"
      ? { text: "Allergy", color: c.danger }
      : line.use
        ? { text: `Use your ${line.use.toLowerCase()} instead`, color: c.good }
        : tone === "more"
          ? {
              text: line.on_hand
                ? `Have ${line.on_hand}, need more`
                : "Need a bit more",
              color: c.warn,
            }
          : tone === "need"
            ? { text: "Need to buy", color: c.danger }
            : tone === "pantry"
              ? { text: "Pantry staple", color: c.muted }
              : line.using
                ? {
                    text: `Using your ${line.using.toLowerCase()}`,
                    color: c.textSecondary,
                  }
                : null;
  return (
    <View style={[styles.ingRow, !last && ui.divider]}>
      <View style={[styles.dot, styles.ingDot, { backgroundColor: color }]} />
      <View style={{ flex: 1, gap: 2 }}>
        <Text
          style={[
            styles.text,
            { fontWeight: "600" },
            line.use ? styles.struck : null,
          ]}
        >
          {capitalize(line.name)}
        </Text>
        {note && (
          <Text style={[styles.note, { color: note.color }]}>{note.text}</Text>
        )}
        {line.note && <Text style={styles.muted}>{line.note}</Text>}
        {listed && (tone === "need" || tone === "more") && (
          <Text style={[styles.note, { color: c.textSecondary }]}>
            On your grocery list
          </Text>
        )}
      </View>
      {line.amount && <Text style={styles.amount}>{line.amount}</Text>}
    </View>
  );
}

const useStyles = makeStyles((c, size) => ({
  hero: { width: "100%", height: 260, backgroundColor: c.input },
  title: {
    color: c.text,
    fontSize: size(24),
    lineHeight: size(30),
    fontWeight: "700",
  },
  text: { color: c.text, fontSize: size(16), lineHeight: size(22) },
  detail: { color: c.textSecondary, fontSize: size(15), lineHeight: size(20) },
  muted: { color: c.muted, fontSize: size(13), lineHeight: size(18) },
  note: { fontSize: size(14), lineHeight: size(19) },
  section: {
    color: c.text,
    fontSize: size(18),
    lineHeight: size(24),
    fontWeight: "700",
  },
  sectionRow: {
    flexDirection: "row",
    alignItems: "baseline",
    justifyContent: "space-between",
  },
  facts: {
    flexDirection: "row",
    backgroundColor: c.card,
    borderColor: c.border,
    borderWidth: 1,
    borderRadius: 14,
    paddingVertical: 12,
  },
  fact: { flex: 1, alignItems: "center", gap: 2 },
  factDivider: { borderLeftColor: c.border, borderLeftWidth: 1 },
  factValue: {
    color: c.text,
    fontSize: size(16),
    lineHeight: size(22),
    fontWeight: "700",
  },
  factLabel: {
    color: c.muted,
    fontSize: size(12),
    lineHeight: size(16),
    textTransform: "uppercase",
    letterSpacing: 0.5,
  },
  legend: { flexDirection: "row", gap: 16, flexWrap: "wrap" },
  legendItem: { flexDirection: "row", alignItems: "center", gap: 6 },
  dot: { width: 10, height: 10, borderRadius: 5 },
  ingDot: { marginTop: size(6) },
  ingRow: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: 12,
    paddingVertical: 12,
    paddingHorizontal: 12,
  },
  amount: {
    color: c.textSecondary,
    fontSize: size(15),
    lineHeight: size(22),
    textAlign: "right",
    maxWidth: "40%",
  },
  struck: { textDecorationLine: "line-through", color: c.textSecondary },
  stepRow: { flexDirection: "row", gap: 12, alignItems: "flex-start" },
  stepNum: {
    width: size(28),
    height: size(28),
    borderRadius: size(14),
    backgroundColor: c.input,
    alignItems: "center",
    justifyContent: "center",
  },
  stepNumText: { color: c.text, fontWeight: "700", fontSize: size(14) },
  allergy: {
    borderWidth: 1,
    borderColor: c.danger,
    borderRadius: 12,
    padding: 16,
  },
  buttonRow: { flexDirection: "row", minHeight: 48 },
  bar: {
    position: "absolute",
    left: 0,
    right: 0,
    bottom: 0,
    paddingHorizontal: 16,
    paddingTop: 12,
    alignItems: "center",
    backgroundColor: c.bg,
    borderTopColor: c.border,
    borderTopWidth: 1,
  },
  groceryButton: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 10,
    minHeight: 52,
    minWidth: 260,
    paddingHorizontal: 28,
    borderRadius: 999,
    backgroundColor: c.accent,
  },
  groceryDone: {
    backgroundColor: c.card,
    borderWidth: 1,
    borderColor: c.accent,
  },
  groceryLabel: { color: c.onAccent, fontSize: size(16), fontWeight: "700" },
  row: { flexDirection: "row", gap: 12 },
  thumb: { padding: 8 },
}));
