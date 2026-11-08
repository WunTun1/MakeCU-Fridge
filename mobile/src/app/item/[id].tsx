import { Stack, useLocalSearchParams } from "expo-router";
import { useRef, useState } from "react";
import FontAwesome from "@expo/vector-icons/FontAwesome";
import {
  Pressable,
  ScrollView,
  Text,
  View,
  type StyleProp,
  type TextStyle,
} from "react-native";

import {
  label,
  stockOptions,
  startIndex,
  WheelSheet,
} from "@/components/AmountWheel";
import { Button } from "@/components/Button";
import { Segmented } from "@/components/Segmented";
import { useSnackbar } from "@/components/Snackbar";
import { ErrorCard, Loading } from "@/components/States";
import { Stepper } from "@/components/Stepper";
import { UsageChart } from "@/components/UsageChart";
import { countNoun, formatAmount, fromGrams, toGrams } from "@/lib/amount";
import { api, type ProductUsage, type StockItem } from "@/lib/api";
import {
  expiryText,
  expiryTone,
  expiryWord,
  LIKELY_WASTED,
  likelyWasted,
} from "@/lib/expiry";
import { makeStyles, useColors, useUi } from "@/lib/theme";
import {
  calendarDate,
  capitalize,
  isoDateIn,
  monthName,
  shiftDate,
  whenWord,
} from "@/lib/time";
import { refreshAll, useApi } from "@/lib/useApi";

/** What's open: the amount wheel, or Fix date for one package. */
type Action = "amount" | { date: number };

/** Soonest to go bad first; undated last. Actions start with the item that needs using first. */
const bySoonest = (items: StockItem[]) =>
  [...items].sort((a, b) =>
    (a.expiration_date ?? "9999").localeCompare(b.expiration_date ?? "9999"),
  );

export default function ItemDetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { data, error, loading, reload } = useApi(() => api.usage(Number(id)));
  const showSnack = useSnackbar();
  const [open, setOpen] = useState<Action | null>(null);
  const busy = useRef(false);
  const ui = useUi();
  const styles = useStyles();

  if (loading && !data) return <Loading />;

  const done = (message: string, undo?: () => Promise<unknown>) => {
    setOpen(null);
    reload();
    refreshAll();
    showSnack({
      message,
      action: undo && {
        label: "Undo",
        onPress: () =>
          undo().then(
            () => (reload(), refreshAll()),
            () => {},
          ),
      },
    });
  };

  /** One write at a time: a second tap while the first is in flight does nothing. */
  const once = (write: () => Promise<void>) => async () => {
    if (busy.current) return;
    busy.current = true;
    try {
      await write();
    } catch (e) {
      showSnack({ message: `Couldn't save: ${(e as Error).message}` });
    } finally {
      busy.current = false;
    }
  };

  return (
    <ScrollView
      style={ui.screen}
      contentContainerStyle={ui.content}
      keyboardShouldPersistTaps="handled"
    >
      <Stack.Screen options={{ title: data?.name ?? "Item" }} />
      {error && <ErrorCard message={error} />}
      {data && (
        <>
          <Stats data={data} />

          {data.items.length === 0 ? (
            <Text style={ui.detail}>You don&apos;t have any right now.</Text>
          ) : (
            <>
              {data.recipe_id != null && (
                <View style={styles.buttonRow}>
                  <Button
                    title="Ate one serving"
                    onPress={once(async () => {
                      const eaten = await api.eat(data.product_id);
                      const protein =
                        eaten.protein_g != null
                          ? ` · ${Math.round(eaten.protein_g)} g protein`
                          : "";
                      done(
                        `Logged 1 serving of ${recipeName(data.name)}${protein}`,
                        () => api.undoMeal(eaten.meal_id),
                      );
                    })}
                  />
                </View>
              )}
              <View style={[ui.card, styles.actions]}>
                <ActionRow
                  icon="sliders"
                  title="Change amount"
                  onPress={() => setOpen("amount")}
                />
                {data.items.some((i) => i.location === "fridge") && (
                  <ActionRow
                    icon="snowflake-o"
                    title="Move to freezer"
                    divider
                    onPress={once(async () => {
                      const moved = await api.freeze(data.product_id);
                      const amount = formatAmount(
                        moved.grams,
                        data.unit,
                        data.grams_per_unit,
                        data.name,
                      );
                      const what =
                        data.unit === "count"
                          ? amount
                          : `${amount} ${data.name.toLowerCase()}`;
                      done(
                        `Moved ${what} to the freezer · good until around ${monthName(moved.expiration_date)}`,
                        () => api.undoEvents(moved.event_ids),
                      );
                    })}
                  />
                )}
              </View>
            </>
          )}

          {open === "amount" && (
            <ChangeAmount
              data={data}
              onDone={done}
              onClose={() => setOpen(null)}
            />
          )}

          {data.items.length > 0 && (
            <>
              <Text style={ui.h2}>
                {data.items.length === 1
                  ? "Package"
                  : `Packages (${data.items.length})`}
              </Text>
              <View style={[ui.card, { paddingVertical: 4 }]}>
                {bySoonest(data.items).map((item, i) => {
                  const fixing =
                    typeof open === "object" && open?.date === item.id;
                  return (
                    <View key={item.id} style={i > 0 && styles.packageDivider}>
                      <PackageRow
                        data={data}
                        item={item}
                        fixing={fixing}
                        onFix={() => setOpen(fixing ? null : { date: item.id })}
                      />
                      {fixing && (
                        <FixDate data={data} item={item} onDone={done} />
                      )}
                    </View>
                  );
                })}
              </View>
            </>
          )}

          {data.recipe_id == null && (
            <>
              <Text style={ui.h2}>Used per day, last 4 weeks</Text>
              <View style={ui.card}>
                <UsageChart
                  dailyUsage={data.daily_usage_g}
                  unit={data.unit}
                  gramsPerUnit={data.grams_per_unit}
                  name={data.name}
                />
              </View>
            </>
          )}
        </>
      )}
    </ScrollView>
  );
}

/** "Greek Stuffed Chicken leftovers" -> "Greek Stuffed Chicken". */
const recipeName = (productName: string) =>
  productName.replace(/ leftovers$/, "");

/** All of it is frozen: it keeps for months, so the date is said as a month. */
const allFrozen = (data: ProductUsage) =>
  data.items.length > 0 && data.items.every((i) => i.location === "freezer");

/** The third stat: leftovers keep until a day; otherwise what you'll likely waste, or when it runs out. */
function thirdStat(
  data: ProductUsage,
): { label: string; value: string } | null {
  const days = data.expires_in_days;
  if (data.recipe_id != null)
    return days == null
      ? null
      : {
          label: "Keeps until",
          value: days < 0 ? "Past it" : capitalize(whenWord(days)),
        };
  const wasted = likelyWasted(data);
  if (wasted) return { label: LIKELY_WASTED, value: wasted };
  return data.days_left == null
    ? null
    : { label: "Runs out", value: capitalize(whenWord(data.days_left)) };
}

function Stats({ data }: { data: ProductUsage }) {
  const ui = useUi();
  const styles = useStyles();
  const c = useColors();
  const days = data.expires_in_days;
  const leftovers = data.recipe_id != null;
  const tone = expiryTone(days, leftovers);
  const third = thirdStat(data);
  const around = data.expiry_estimated && !leftovers ? "Around " : "";
  return (
    <View style={[ui.card, styles.stats]}>
      {allFrozen(data) && data.expiration_date ? (
        <Stat
          label="Good until"
          value={`Around ${monthName(data.expiration_date)}`}
          sub="In the freezer"
        />
      ) : (
        <Stat
          label="Goes bad"
          value={days == null ? "No date" : expiryWord(days)}
          valueStyle={[styles.glanceValue, tone && { color: c[tone] }]}
          sub={
            data.expiration_date
              ? `${around}${calendarDate(data.expiration_date)}`
              : undefined
          }
        />
      )}
      <Stat
        label="Amount"
        value={formatAmount(
          data.on_hand_g,
          data.unit,
          data.grams_per_unit,
          data.name,
        )}
      />
      {third && <Stat label={third.label} value={third.value} />}
    </View>
  );
}

function Stat({
  label,
  value,
  sub,
  valueStyle,
}: {
  label: string;
  value: string;
  sub?: string;
  valueStyle?: StyleProp<TextStyle>;
}) {
  const ui = useUi();
  const styles = useStyles();
  return (
    <View style={{ flex: 1, gap: 2 }}>
      <Text style={ui.muted}>{label}</Text>
      <Text style={[styles.statValue, valueStyle]}>{value}</Text>
      {sub && <Text style={ui.detail}>{sub}</Text>}
    </View>
  );
}

/** A row in the actions card: icon, title, chevron, like a settings list. */
function ActionRow({
  icon,
  title,
  onPress,
  divider = false,
}: {
  icon: React.ComponentProps<typeof FontAwesome>["name"];
  title: string;
  onPress: () => void;
  divider?: boolean;
}) {
  const ui = useUi();
  const styles = useStyles();
  const c = useColors();
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      style={({ pressed }) => [
        styles.actionRow,
        divider && styles.packageDivider,
        pressed && { opacity: 0.6 },
      ]}
    >
      <View style={styles.actionIcon}>
        <FontAwesome name={icon} size={16} color={c.accent} />
      </View>
      <Text style={[ui.text, { flex: 1, fontWeight: "600" }]}>{title}</Text>
      <FontAwesome name="chevron-right" size={12} color={c.muted} />
    </Pressable>
  );
}

type PanelProps = {
  data: ProductUsage;
  onDone: (message: string, undo?: () => Promise<unknown>) => void;
};

/** "Goes bad tomorrow · Sun, Nov 8", or "In the freezer · good until around August". */
function packageWhen(item: StockItem, days: number | null): string {
  if (item.location === "freezer") {
    return item.expiration_date
      ? `In the freezer · good until around ${monthName(item.expiration_date)}`
      : "In the freezer";
  }
  return days == null
    ? "No date"
    : `${expiryText(days, item.expiry_estimated)} · ${calendarDate(item.expiration_date!)}`;
}

/** One package (an add): how much is left of it, when it goes bad, and its own Fix date. */
function PackageRow({
  data,
  item,
  fixing,
  onFix,
}: {
  data: ProductUsage;
  item: StockItem;
  fixing: boolean;
  onFix: () => void;
}) {
  const ui = useUi();
  const styles = useStyles();
  const c = useColors();
  const days = item.expires_in_days;
  const tone = expiryTone(days, data.recipe_id != null);
  return (
    <View style={styles.packageRow}>
      <View style={{ flex: 1, gap: 2 }}>
        <Text style={ui.text}>
          {capitalize(
            formatAmount(item.grams, data.unit, data.grams_per_unit, data.name),
          )}
        </Text>
        <Text
          style={[
            ui.detail,
            tone && item.location !== "freezer" && { color: c[tone] },
          ]}
        >
          {packageWhen(item, days)}
        </Text>
      </View>
      <Pressable
        onPress={onFix}
        style={styles.textButton}
        accessibilityRole="button"
        accessibilityLabel="Fix the date on this package"
      >
        <Text style={styles.link}>{fixing ? "Cancel" : "Fix date"}</Text>
      </Pressable>
    </View>
  );
}

type Why = "used" | "wasted" | "fix";

const WHY: { value: Why; label: string }[] = [
  { value: "used", label: "Used" },
  { value: "wasted", label: "Threw out" },
  { value: "fix", label: "Fixing" },
];

/**
 * Spin to what you have now. Less than before asks why, so used, thrown out and a plain
 * correction each count the right way; more is a correction.
 */
function ChangeAmount({
  data,
  onDone,
  onClose,
}: PanelProps & { onClose: () => void }) {
  const ui = useUi();
  const styles = useStyles();
  const [why, setWhy] = useState<Why>("used");
  const have = fromGrams(data.on_hand_g, data.unit, data.grams_per_unit);
  const values = stockOptions(data.unit, have);
  const start = startIndex(values, have, data.unit);
  const of = data.unit === "count" ? "" : ` of ${data.name}`;
  const fmt = (grams: number) =>
    formatAmount(grams, data.unit, data.grams_per_unit, data.name);

  /** Takes `grams` from the packages going bad first. */
  async function takeSoonest(
    grams: number,
    take: (id: number, g: number) => Promise<number[]>,
  ) {
    const ids: number[] = [];
    let left = grams;
    for (const item of bySoonest(data.items)) {
      if (left <= 0.5) break;
      const g = Math.min(item.grams, left);
      ids.push(...(await take(item.id, g)));
      left -= g;
    }
    return ids;
  }

  /** A plain correction: the newest packages keep what they have, the soonest takes the difference. */
  async function setTotal(total: number) {
    const items = bySoonest(data.items);
    let left = total;
    for (const item of items.slice(1).reverse()) {
      const keep = Math.min(item.grams, left);
      if (keep !== item.grams) await api.updateItem(item.id, { grams: keep });
      left -= keep;
    }
    await api.updateItem(items[0].id, { grams: left });
  }

  async function save(v: number) {
    const total = toGrams(v, data.unit, data.grams_per_unit);
    const less = data.on_hand_g - total;
    try {
      if (less > 0.5 && why === "used") {
        const ids = await takeSoonest(less, async (id, g) => {
          const { event_id } = await api.consume(id, g);
          return event_id == null ? [] : [event_id];
        });
        onDone(`Used ${fmt(less)}${of}`, () => api.undoEvents(ids));
      } else if (less > 0.5 && why === "wasted") {
        const ids = await takeSoonest(
          less,
          async (id, g) => (await api.waste([id], [g])).event_ids,
        );
        onDone(`Threw out ${fmt(less)}${of}`, () => api.undoEvents(ids));
      } else {
        await setTotal(total);
        onDone(`${capitalize(fmt(total))}${of}`);
      }
    } catch (e) {
      onDone(`Couldn't save: ${(e as Error).message}`);
    }
  }

  return (
    <WheelSheet
      title={data.name}
      values={values}
      start={start}
      format={(v, selected) =>
        selected && data.unit === "count"
          ? `${v} ${countNoun(data.name, v)}`
          : label(v, data.unit)
      }
      canSave={(v) => v !== values[start]}
      onDone={save}
      onClose={onClose}
      footer={(v) => (
        <View style={styles.why}>
          {v < values[start] ? (
            <Segmented
              label="Why"
              options={WHY}
              value={why}
              onChange={setWhy}
            />
          ) : (
            <Text style={[ui.muted, { textAlign: "center" }]}>
              {v > values[start] ? "More than recorded" : "Spin to change"}
            </Text>
          )}
        </View>
      )}
    />
  );
}

const DATE_PICKS = [
  { label: "Today", days: 0 },
  { label: "In 3 days", days: 3 },
  { label: "In a week", days: 7 },
];

function FixDate({ data, item, onDone }: PanelProps & { item: StockItem }) {
  const ui = useUi();
  const styles = useStyles();
  const c = useColors();
  const known = item.expiration_date != null && item.expires_in_days != null;
  const [days, setDays] = useState(() => (known ? item.expires_in_days! : 3));
  // Counted from the package's own date, so the household's day (not this phone's) is kept.
  const date = known
    ? shiftDate(item.expiration_date!, days - item.expires_in_days!)
    : isoDateIn(days);

  async function save() {
    await api.updateItem(item.id, { expiration_date: date });
    const amount = formatAmount(
      item.grams,
      data.unit,
      data.grams_per_unit,
      data.name,
    );
    onDone(
      `${capitalize(amount)}${data.unit === "count" ? "" : ` of ${data.name}`} goes bad ${calendarDate(date)}`,
    );
  }

  return (
    <View style={{ gap: 16, paddingBottom: 12 }}>
      <Text style={ui.text}>When does it go bad?</Text>
      <Stepper
        minusLabel="A day earlier"
        plusLabel="A day later"
        value={calendarDate(date)}
        canMinus={days > 0}
        canPlus={days < 365}
        onMinus={() => setDays((d) => d - 1)}
        onPlus={() => setDays((d) => d + 1)}
      />
      <View style={[ui.row, { gap: 8 }]}>
        {DATE_PICKS.map((p) => (
          <Pressable
            key={p.label}
            onPress={() => setDays(p.days)}
            style={[styles.chip, p.days === days && { borderColor: c.accent }]}
          >
            <Text style={[ui.text, p.days === days && { color: c.accent }]}>
              {p.label}
            </Text>
          </Pressable>
        ))}
      </View>
      <SaveButton title="Save date" onPress={save} />
    </View>
  );
}

/** A primary button that ignores taps while its request is in flight. */
function SaveButton({
  title,
  onPress,
}: {
  title: string;
  onPress: () => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const inFlight = useRef(false);
  return (
    <View style={{ flexDirection: "row" }}>
      <Button
        title={title}
        disabled={busy}
        onPress={async () => {
          if (inFlight.current) return;
          inFlight.current = true;
          setBusy(true);
          try {
            await onPress();
          } finally {
            inFlight.current = false;
            setBusy(false);
          }
        }}
      />
    </View>
  );
}

const useStyles = makeStyles((c, size) => ({
  stats: { flexDirection: "row", gap: 12 },
  statValue: {
    color: c.text,
    fontSize: size(17),
    lineHeight: size(22),
    fontWeight: "700",
  },
  glanceValue: { fontSize: size(20), lineHeight: size(24) },
  buttonRow: { flexDirection: "row" },
  actions: { paddingVertical: 0 },
  actionRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    minHeight: 52,
  },
  actionIcon: {
    width: 30,
    height: 30,
    borderRadius: 8,
    backgroundColor: c.input,
    alignItems: "center",
    justifyContent: "center",
  },
  why: { minHeight: 52, justifyContent: "center", marginTop: 8 },
  packageRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    minHeight: 56,
    paddingVertical: 8,
  },
  packageDivider: { borderTopColor: c.border, borderTopWidth: 1 },
  textButton: {
    minHeight: 44,
    minWidth: 44,
    justifyContent: "center",
    paddingHorizontal: 8,
  },
  link: { color: c.accent, fontSize: size(15), fontWeight: "600" },
  chip: {
    minHeight: 44,
    paddingHorizontal: 12,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: c.muted,
    justifyContent: "center",
  },
}));
