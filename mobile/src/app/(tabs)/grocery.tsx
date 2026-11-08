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

import { AmountWheel } from "@/components/AmountWheel";
import { useSnackbar } from "@/components/Snackbar";
import { ErrorCard } from "@/components/States";
import { formatAmount } from "@/lib/amount";
import {
  api,
  type GroceryEntry,
  type GroceryList,
  type InventoryEntry,
  type RestockItem,
} from "@/lib/api";
import { makeStyles, useColors, useUi } from "@/lib/theme";
import { capitalize, sentenceCase, whenWord } from "@/lib/time";
import { useApi } from "@/lib/useApi";

/** "Running low": runs out within this many days, or this little of the package left. */
const LOW_DAYS = 4;
const LOW_FRACTION = 0.25;

const sameName = (a: string, b: string) =>
  a.trim().toLowerCase() === b.trim().toLowerCase();

/** How much to get: the amount given ("6", "1/2 cup"), else what the restock plan would buy. */
function amountFor(entry: GroceryEntry): string | null {
  if (entry.amount) return entry.amount;
  const p = entry.plan;
  if (!p) return null;
  return entry.unit === "count"
    ? String(Math.round(p.buy_grams / entry.grams_per_unit))
    : formatAmount(p.buy_grams, entry.unit, entry.grams_per_unit, entry.name);
}

/** "About 2 L", "12": what the eating analysis says to buy — about a week's worth. */
function buyText(r: RestockItem): string {
  return r.unit === "count"
    ? String(Math.round(r.restock_g / r.grams_per_unit))
    : formatAmount(r.restock_g, r.unit, r.grams_per_unit, r.name);
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
  const [editing, setEditing] = useState<GroceryEntry | null>(null);
  const summary = useApi(api.summary, 5000, "summary");
  const restock = useApi(api.restockReport, 30000, "restock");
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
  const add = (names: string[], amounts?: (string | null)[]) =>
    run(() =>
      api.addToGrocery({ names, source: "manual", amounts }).then(api.grocery),
    );
  /** Tapping "On list" again takes it back off. */
  const unlist = (name: string) => {
    const rows = list.items.filter(
      (i) => !i.checked && i.source !== "plan" && sameName(i.name, name),
    );
    setList({ ...list, items: list.items.filter((i) => !rows.includes(i)) });
    Promise.all(rows.map((r) => api.hideGrocery(r.id, true))).catch(reload);
  };
  const setAmount = (entry: GroceryEntry, amount: string) => {
    setList({
      ...list,
      items: list.items.map((i) => (i.id === entry.id ? { ...i, amount } : i)),
    });
    api.setGroceryAmount(entry.id, amount).catch(reload);
  };
  const clearList = () => {
    const rows = list.items.filter((i) => i.source !== "plan");
    setList({ ...list, items: list.items.filter((i) => !rows.includes(i)) });
    Promise.all(rows.map((r) => api.hideGrocery(r.id, true))).then(
      () =>
        showSnack({
          message: "List cleared",
          action: {
            label: "Undo",
            onPress: () =>
              run(() =>
                Promise.all(rows.map((r) => api.hideGrocery(r.id, false))).then(
                  api.grocery,
                ),
              ),
          },
        }),
      reload,
    );
  };
  const buyFor = (productId: number) => {
    const r = restock.data?.items.find((x) => x.product_id === productId);
    return r ? buyText(r) : null;
  };

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
                buy={buyFor(item.product_id)}
                listed={onList(item.name)}
                onAdd={() =>
                  onList(item.name)
                    ? unlist(item.name)
                    : add([item.name], [buyFor(item.product_id)])
                }
              />
            ))}
          </ScrollView>
        </>
      )}

      {error && <ErrorCard message={error} />}

      <View style={styles.listHeader}>
        <Text style={ui.h2}>Your list</Text>
        {!empty && (
          <Pressable
            onPress={clearList}
            hitSlop={8}
            style={styles.textButton}
            accessibilityRole="button"
          >
            <Text style={styles.link}>Clear list</Text>
          </Pressable>
        )}
      </View>

      <AddRow onAdd={(name) => add([name])} />

      {empty && <Text style={ui.muted}>Empty</Text>}

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
                onAmount={() => setEditing(entry)}
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

      {editing && (
        <AmountWheel
          name={sentenceCase(editing.name)}
          unit={editing.unit}
          current={amountFor(editing)}
          onClose={() => setEditing(null)}
          onDone={(amount) => {
            setAmount(editing, amount);
            setEditing(null);
          }}
        />
      )}

      {restock.data && restock.data.items.length > 0 && (
        <YourEating
          items={restock.data.items}
          fromTiger={restock.data.source === "tiger"}
          onList={onList}
          onAdd={(r) =>
            onList(r.name) ? unlist(r.name) : add([r.name], [buyText(r)])
          }
        />
      )}
    </ScrollView>
  );
}

/**
 * Your eating: how fast you go through each food over the last two weeks (a small bar per
 * day), this week against last, and when to restock how much — the analysis runs on Tiger Data.
 */
function YourEating({
  items,
  fromTiger,
  onList,
  onAdd,
}: {
  items: RestockItem[];
  fromTiger: boolean;
  onList: (name: string) => boolean;
  onAdd: (r: RestockItem) => void;
}) {
  const ui = useUi();
  const styles = useStyles();
  const c = useColors();
  return (
    <View style={{ gap: 8, marginTop: 8 }}>
      <View style={styles.listHeader}>
        <Text style={ui.h2}>Your eating</Text>
        {fromTiger && (
          <View style={[ui.row, { gap: 6 }]}>
            <FontAwesome name="database" size={11} color={c.muted} />
            <Text style={ui.muted}>Insights by Tiger Data</Text>
          </View>
        )}
      </View>
      <Text style={ui.muted}>From what you used over the last two weeks</Text>
      <View style={[ui.card, { paddingVertical: 2 }]}>
        {items.slice(0, 6).map((r, i, shown) => {
          const listed = onList(r.name);
          const rate = formatAmount(
            r.rate_g_per_day,
            r.unit,
            r.grams_per_unit,
            r.name,
          ).replace(/^about /i, "");
          const when =
            r.restock_in_days == null
              ? null
              : r.restock_in_days <= 0
                ? "Restock today"
                : `Restock ${whenWord(r.restock_in_days)}`;
          const peak = Math.max(...r.series, 1);
          return (
            <View
              key={r.product_id}
              style={[styles.eatRow, i < shown.length - 1 && ui.divider]}
            >
              <View style={{ flex: 1, gap: 4 }}>
                <Text
                  style={[ui.text, { fontWeight: "600" }]}
                  numberOfLines={1}
                >
                  {r.name}
                </Text>
                <Text style={ui.detail} numberOfLines={1}>
                  About {rate} a day
                </Text>
                {r.trend_pct != null && r.trend_pct !== 0 && (
                  <Text style={ui.muted}>
                    {`${r.trend_pct > 0 ? "▲" : "▼"} ${Math.abs(r.trend_pct)}% vs last week`}
                  </Text>
                )}
                <View
                  style={styles.spark}
                  accessibilityLabel={`Daily use over ${r.series.length} days`}
                >
                  {r.series.map((v, d) => (
                    <View
                      key={d}
                      style={[
                        styles.sparkBar,
                        {
                          height: 2 + (v / peak) * 22,
                          backgroundColor:
                            d >= r.series.length - 7 ? c.accent : c.border,
                        },
                      ]}
                    />
                  ))}
                </View>
                {when && (
                  <Text
                    style={[ui.text, { color: c.warn, fontWeight: "600" }]}
                    numberOfLines={1}
                  >
                    {when} · about {buyText(r)}
                  </Text>
                )}
              </View>
              <Pressable
                onPress={() => onAdd(r)}
                accessibilityRole="button"
                accessibilityLabel={
                  listed
                    ? `${r.name} is on your list. Tap to take it off`
                    : `Add ${buyText(r)} ${r.name} to your list`
                }
                style={({ pressed }) => [
                  styles.smallButton,
                  listed && styles.lowListed,
                  pressed && { opacity: 0.8 },
                ]}
              >
                <FontAwesome
                  name={listed ? "check" : "plus"}
                  size={12}
                  color={listed ? c.accent : c.onAccent}
                />
                <Text
                  style={[
                    styles.smallButtonText,
                    listed && { color: c.accent },
                  ]}
                >
                  {listed ? "On list" : "Add"}
                </Text>
              </Pressable>
            </View>
          );
        })}
      </View>
    </View>
  );
}

/** One food you're about to run out of: when, how much is left, and Add. */
function LowCard({
  item,
  buy,
  listed,
  onAdd,
}: {
  item: InventoryEntry;
  /** What to buy, from the eating analysis ("about 2 L"). */
  buy: string | null;
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
      {buy && (
        <Text style={ui.muted} numberOfLines={1}>
          Get {buy}
        </Text>
      )}
      <View style={{ flex: 1 }} />
      <Pressable
        onPress={onAdd}
        accessibilityRole="button"
        accessibilityLabel={
          listed
            ? `${item.name} is on your list. Tap to take it off`
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
          color={listed ? c.accent : c.onAccent}
        />
        <Text style={[styles.lowButtonText, listed && { color: c.accent }]}>
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
        <FontAwesome name="plus" size={18} color={c.onAccent} />
      </Pressable>
    </View>
  );
}

function GroceryRow({
  entry,
  last,
  onToggle,
  onRemove,
  onAmount,
}: {
  entry: GroceryEntry;
  last: boolean;
  onToggle: () => void;
  onRemove: () => void;
  /** Tap the amount to spin a new one; not offered once it's in the cart. */
  onAmount?: () => void;
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
        {done && <FontAwesome name="check" size={13} color={c.onAccent} />}
      </View>
      <Text
        style={[
          ui.text,
          { flex: 1 },
          done && { textDecorationLine: "line-through" },
        ]}
        numberOfLines={2}
      >
        {sentenceCase(entry.name)}
      </Text>
      {onAmount ? (
        <Pressable
          onPress={onAmount}
          hitSlop={6}
          style={styles.amountButton}
          accessibilityRole="button"
          accessibilityLabel={`Amount of ${sentenceCase(entry.name)}: ${amountFor(entry) ?? "not set"}`}
        >
          <Text
            style={[
              styles.amountLabel,
              !amountFor(entry) && { color: c.muted },
            ]}
            numberOfLines={1}
          >
            {amountFor(entry) ?? "Amount"}
          </Text>
        </Pressable>
      ) : (
        amountFor(entry) && (
          <Text
            style={[
              styles.amount,
              done && { textDecorationLine: "line-through" },
            ]}
          >
            {amountFor(entry)}
          </Text>
        )
      )}
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
    backgroundColor: c.accent,
  },
  lowListed: { backgroundColor: c.card, borderWidth: 1, borderColor: c.accent },
  lowButtonText: { color: c.onAccent, fontSize: size(14), fontWeight: "700" },
  amountButton: {
    flexShrink: 0,
    minWidth: 44,
    minHeight: 36,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: 10,
    borderRadius: 8,
    backgroundColor: c.input,
  },
  amountLabel: { color: c.text, fontSize: size(15), fontWeight: "700" },
  amount: {
    color: c.text,
    fontSize: size(15),
    fontWeight: "700",
    maxWidth: "40%",
    textAlign: "right",
  },
  eatRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    paddingVertical: 12,
    paddingHorizontal: 12,
  },
  spark: {
    flexDirection: "row",
    alignItems: "flex-end",
    gap: 2,
    height: 26,
    marginTop: 2,
  },
  sparkBar: { width: 6, borderRadius: 2 },
  smallButton: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    minHeight: 36,
    paddingHorizontal: 12,
    borderRadius: 999,
    backgroundColor: c.accent,
  },
  smallButtonText: { color: c.onAccent, fontSize: size(14), fontWeight: "700" },
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
    backgroundColor: c.accent,
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
  checkDone: { backgroundColor: c.accent, borderColor: c.accent },
  remove: {
    width: 40,
    height: 40,
    alignItems: "center",
    justifyContent: "center",
  },
  textButton: { minHeight: 36, justifyContent: "center", paddingHorizontal: 4 },
  link: { color: c.accent, fontSize: size(15), fontWeight: "600" },
}));
