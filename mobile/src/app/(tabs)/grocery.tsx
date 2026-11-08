import FontAwesome from "@expo/vector-icons/FontAwesome";
import { router, useFocusEffect } from "expo-router";
import { useCallback, useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  Text,
  TextInput,
  View,
} from "react-native";

import { useSnackbar } from "@/components/Snackbar";
import { ErrorCard } from "@/components/States";
import { formatAmount } from "@/lib/amount";
import {
  api,
  type GroceryEntry,
  type GroceryList,
  type InventoryEntry,
} from "@/lib/api";
import { makeStyles, useColors, useUi } from "@/lib/theme";
import { capitalize, sentenceCase, whenWord } from "@/lib/time";
import { useApi } from "@/lib/useApi";

/** "Running low": runs out within this many days, or this little of the package left. */
const LOW_DAYS = 4;
const LOW_FRACTION = 0.25;

const sameName = (a: string, b: string) =>
  a.trim().toLowerCase() === b.trim().toLowerCase();

/** "Apples · 6", "Milk · 2 L": the amount given, else what the restock plan would buy. */
function titleFor(entry: GroceryEntry): string {
  const p = entry.plan;
  const amount =
    entry.amount ??
    (p &&
      (entry.unit === "count"
        ? String(Math.round(p.buy_grams / entry.grams_per_unit))
        : formatAmount(
            p.buy_grams,
            entry.unit,
            entry.grams_per_unit,
            entry.name,
          )));
  return amount
    ? `${sentenceCase(entry.name)} · ${amount}`
    : sentenceCase(entry.name);
}

/** Food you're about to run out of, soonest first (leftovers and the freezer aside). */
function runningLow(inventory: InventoryEntry[]): InventoryEntry[] {
  return inventory
    .filter((i) => !i.leftovers && i.location !== "freezer")
    .filter(
      (i) =>
        (i.days_left != null && i.days_left <= LOW_DAYS) ||
        (i.fill_fraction != null && i.fill_fraction <= LOW_FRACTION),
    )
    .sort(
      (a, b) =>
        (a.days_left ?? Infinity) - (b.days_left ?? Infinity) ||
        a.name.localeCompare(b.name),
    );
}

type Section = {
  key: string;
  title: string;
  recipeId: number | null;
  items: GroceryEntry[];
};

/** The list by where it came from: each recipe, then what you added. Checked items go to "In the cart". */
function sections(items: GroceryEntry[]): Section[] {
  const out: Section[] = [];
  for (const e of items) {
    if (e.checked || e.source === "plan") continue; // the restock plan shows as "Running low" above
    const key =
      e.source === "recipe"
        ? `recipe-${e.recipe_id ?? e.recipe_name}`
        : "manual";
    let s = out.find((x) => x.key === key);
    if (!s) {
      s =
        e.source === "recipe"
          ? {
              key,
              title: `For ${e.recipe_name ?? "a recipe"}`,
              recipeId: e.recipe_id,
              items: [],
            }
          : { key, title: "Added by you", recipeId: null, items: [] };
      out.push(s);
    }
    s.items.push(e);
  }
  // Recipes first (in the order they were added), what you typed last.
  return [
    ...out.filter((s) => s.key !== "manual"),
    ...out.filter((s) => s.key === "manual"),
  ];
}

/**
 * Grocery: a row of what you're about to run out of (add any with one tap), then your list —
 * what recipes need, grouped by recipe, and what you added — with what's in the cart at the end.
 */
export default function Grocery() {
  const [list, setList] = useState<GroceryList | null>(null);
  const [error, setError] = useState<string | null>(null);
  const summary = useApi(api.summary, 5000);
  const showSnack = useSnackbar();
  const ui = useUi();
  const styles = useStyles();
  const c = useColors();

  const run = useCallback(async (request: () => Promise<GroceryList>) => {
    try {
      setList(await request());
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);
  const reload = useCallback(() => {
    run(api.grocery);
  }, [run]);
  useFocusEffect(reload);

  if (!list) {
    return (
      <View style={[ui.screen, ui.content]}>
        {error ? (
          <ErrorCard message={error} />
        ) : (
          <ActivityIndicator color={c.accent} style={{ marginTop: 48 }} />
        )}
      </View>
    );
  }

  const onList = (name: string) =>
    list.items.some(
      (i) => !i.checked && i.source !== "plan" && sameName(i.name, name),
    ); // plan rows aren't shown
  const add = (names: string[]) =>
    run(() => api.addToGrocery({ names, source: "manual" }).then(api.grocery));

  const toggle = (entry: GroceryEntry) => {
    setList({
      ...list,
      items: list.items.map((i) =>
        i.id === entry.id ? { ...i, checked: !i.checked } : i,
      ),
    });
    api.checkGrocery(entry.id, !entry.checked).catch(reload);
  };

  const remove = (entry: GroceryEntry) => {
    setList({ ...list, items: list.items.filter((i) => i.id !== entry.id) });
    api.hideGrocery(entry.id, true).then(
      () =>
        showSnack({
          message: `Removed ${sentenceCase(entry.name)}`,
          action: {
            label: "Undo",
            onPress: () =>
              run(() => api.hideGrocery(entry.id, false).then(api.grocery)),
          },
        }),
      reload,
    );
  };

  const low = runningLow(summary.data?.inventory ?? []);
  const groups = sections(list.items);
  const inCart = list.items.filter((i) => i.checked);
  const empty = groups.length === 0 && inCart.length === 0;

  return (
    <ScrollView
      style={ui.screen}
      contentContainerStyle={ui.content}
      keyboardShouldPersistTaps="handled"
    >
      {low.length > 0 && (
        <>
          <View>
            <Text style={ui.h2}>Running low</Text>
            <Text style={ui.muted}>About to run out in your kitchen</Text>
          </View>
          <ScrollView
            horizontal
            showsHorizontalScrollIndicator={false}
            style={styles.bleed}
            contentContainerStyle={styles.carousel}
          >
            {low.map((item) => (
              <LowCard
                key={`${item.product_id}-${item.location}`}
                item={item}
                listed={onList(item.name)}
                onAdd={() => add([item.name])}
              />
            ))}
          </ScrollView>
        </>
      )}

      {error && <ErrorCard message={error} />}

      <View style={styles.listHeader}>
        <Text style={ui.h2}>Your list</Text>
        {inCart.length > 0 && (
          <Pressable
            onPress={() =>
              run(() => api.clearCheckedGrocery().then(api.grocery))
            }
            hitSlop={8}
            style={styles.textButton}
          >
            <Text style={styles.link}>Clear checked</Text>
          </Pressable>
        )}
      </View>

      <AddRow onAdd={(name) => add([name])} />

      {empty && (
        <Text style={ui.detail}>
          Nothing to buy yet. On a recipe, tap the green button to add what it
          needs — or type an item above.
        </Text>
      )}

      {groups.map((g) => (
        <View key={g.key} style={{ gap: 6 }}>
          {g.recipeId != null ? (
            <Pressable
              onPress={() =>
                router.push({
                  pathname: "/recipe/[id]",
                  params: { id: g.recipeId! },
                })
              }
              accessibilityRole="link"
              style={styles.groupTitle}
            >
              <Text style={[styles.groupText, { flex: 1 }]} numberOfLines={1}>
                {g.title}
              </Text>
              <FontAwesome
                name="chevron-right"
                size={12}
                color={c.textSecondary}
              />
            </Pressable>
          ) : (
            <Text style={[styles.groupText, styles.groupTitle]}>{g.title}</Text>
          )}
          <View style={[ui.card, { paddingVertical: 2 }]}>
            {g.items.map((entry, i) => (
              <GroceryRow
                key={entry.id}
                entry={entry}
                last={i === g.items.length - 1}
                onToggle={() => toggle(entry)}
                onRemove={() => remove(entry)}
              />
            ))}
          </View>
        </View>
      ))}

      {inCart.length > 0 && (
        <View style={{ gap: 6 }}>
          <Text style={[styles.groupText, styles.groupTitle]}>
            In the cart ({inCart.length})
          </Text>
          <View style={[ui.card, { paddingVertical: 2 }]}>
            {inCart.map((entry, i) => (
              <GroceryRow
                key={entry.id}
                entry={entry}
                last={i === inCart.length - 1}
                onToggle={() => toggle(entry)}
                onRemove={() => remove(entry)}
              />
            ))}
          </View>
        </View>
      )}
    </ScrollView>
  );
}

/** One food you're about to run out of: when, how much is left, and Add. */
function LowCard({
  item,
  listed,
  onAdd,
}: {
  item: InventoryEntry;
  listed: boolean;
  onAdd: () => void;
}) {
  const ui = useUi();
  const styles = useStyles();
  const c = useColors();
  const when =
    item.days_left != null && item.days_left <= LOW_DAYS
      ? `Runs out ${whenWord(item.days_left)}`
      : "Almost gone";
  return (
    <View style={styles.low}>
      <Text style={[ui.text, { fontWeight: "600" }]} numberOfLines={2}>
        {item.name}
      </Text>
      <Text style={[styles.lowWhen, { color: c.warn }]} numberOfLines={1}>
        {when}
      </Text>
      <Text style={ui.muted} numberOfLines={1}>
        {capitalize(
          formatAmount(item.grams, item.unit, item.grams_per_unit, item.name),
        )}{" "}
        left
      </Text>
      <View style={{ flex: 1 }} />
      <Pressable
        onPress={onAdd}
        disabled={listed}
        accessibilityRole="button"
        accessibilityLabel={
          listed
            ? `${item.name} is on your list`
            : `Add ${item.name} to your list`
        }
        style={({ pressed }) => [
          styles.lowButton,
          listed && styles.lowListed,
          pressed && { opacity: 0.8 },
        ]}
      >
        <FontAwesome
          name={listed ? "check" : "plus"}
          size={14}
          color={listed ? c.good : "#ffffff"}
        />
        <Text style={[styles.lowButtonText, listed && { color: c.good }]}>
          {listed ? "On list" : "Add"}
        </Text>
      </Pressable>
    </View>
  );
}

function AddRow({ onAdd }: { onAdd: (name: string) => void }) {
  const [text, setText] = useState("");
  const styles = useStyles();
  const c = useColors();
  const submit = () => {
    if (!text.trim()) return;
    onAdd(text.trim());
    setText("");
  };
  return (
    <View style={styles.addRow}>
      <TextInput
        style={styles.addInput}
        placeholder="Add an item, e.g. apples 6"
        placeholderTextColor={c.muted}
        value={text}
        onChangeText={setText}
        onSubmitEditing={submit}
        returnKeyType="done"
        accessibilityLabel="Add an item"
      />
      <Pressable
        onPress={submit}
        style={styles.addButton}
        accessibilityRole="button"
        accessibilityLabel="Add to list"
      >
        <FontAwesome name="plus" size={18} color="#ffffff" />
      </Pressable>
    </View>
  );
}

function GroceryRow({
  entry,
  last,
  onToggle,
  onRemove,
}: {
  entry: GroceryEntry;
  last: boolean;
  onToggle: () => void;
  onRemove: () => void;
}) {
  const done = entry.checked;
  const ui = useUi();
  const styles = useStyles();
  const c = useColors();
  return (
    <Pressable
      onPress={onToggle}
      role="checkbox"
      aria-checked={done}
      style={[styles.row, !last && ui.divider, done && { opacity: 0.55 }]}
    >
      <View style={[styles.check, done && styles.checkDone]}>
        {done && <FontAwesome name="check" size={13} color="#ffffff" />}
      </View>
      <Text
        style={[
          ui.text,
          { flex: 1 },
          done && { textDecorationLine: "line-through" },
        ]}
      >
        {titleFor(entry)}
      </Text>
      <Pressable
        onPress={onRemove}
        style={styles.remove}
        accessibilityRole="button"
        accessibilityLabel={`Remove ${sentenceCase(entry.name)}`}
      >
        <FontAwesome name="close" size={18} color={c.muted} />
      </Pressable>
    </Pressable>
  );
}

const useStyles = makeStyles((c, size) => ({
  // The row runs to the screen's edges, while its first card lines up with the content.
  bleed: { marginHorizontal: -16 },
  carousel: { gap: 12, paddingHorizontal: 16 },
  low: {
    width: 156,
    minHeight: size(20) * 2 + size(20) + size(18) + 70,
    padding: 12,
    gap: 4,
    backgroundColor: c.card,
    borderColor: c.border,
    borderWidth: 1,
    borderRadius: 14,
  },
  lowWhen: { fontSize: size(14), lineHeight: size(19), fontWeight: "600" },
  lowButton: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    minHeight: 36,
    marginTop: 8,
    borderRadius: 999,
    backgroundColor: c.good,
  },
  lowListed: { backgroundColor: c.card, borderWidth: 1, borderColor: c.good },
  lowButtonText: { color: "#ffffff", fontSize: size(14), fontWeight: "700" },
  listHeader: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  addRow: { flexDirection: "row", alignItems: "center", gap: 10 },
  addInput: {
    flex: 1,
    minHeight: 44,
    paddingHorizontal: 14,
    borderRadius: 12,
    backgroundColor: c.input,
    color: c.text,
    fontSize: size(16),
  },
  addButton: {
    width: 44,
    height: 44,
    borderRadius: 12,
    backgroundColor: c.good,
    alignItems: "center",
    justifyContent: "center",
  },
  groupTitle: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    marginTop: 6,
    paddingHorizontal: 4,
  },
  groupText: {
    color: c.textSecondary,
    fontSize: size(13),
    lineHeight: size(18),
    fontWeight: "700",
    textTransform: "uppercase",
    letterSpacing: 0.5,
  },
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    minHeight: 48,
    paddingVertical: 6,
    paddingHorizontal: 12,
  },
  check: {
    width: 22,
    height: 22,
    borderRadius: 6,
    borderWidth: 2,
    borderColor: c.muted,
    alignItems: "center",
    justifyContent: "center",
  },
  checkDone: { backgroundColor: c.good, borderColor: c.good },
  remove: {
    width: 40,
    height: 40,
    alignItems: "center",
    justifyContent: "center",
  },
  textButton: { minHeight: 36, justifyContent: "center", paddingHorizontal: 4 },
  link: { color: c.accent, fontSize: size(15), fontWeight: "600" },
}));
