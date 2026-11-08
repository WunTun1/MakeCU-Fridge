import { useRef, useState, type ComponentRef, type ReactNode } from "react";
import {
  type NativeScrollEvent,
  type NativeSyntheticEvent,
  Modal,
  Pressable,
  ScrollView,
  Text,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { countNoun, type Unit } from "@/lib/amount";
import { makeStyles } from "@/lib/theme";

const ROW = 44;
const VISIBLE = 5;

const range = (from: number, to: number, step: number) =>
  Array.from(
    { length: Math.floor((to - from) / step) + 1 },
    (_, i) => from + i * step,
  );

const trim1 = (n: number) => (Math.round(n * 10) / 10).toString();

/** What the wheel offers, in the food's own unit: eggs by the one, cheese by the gram, milk by the ml. */
function options(unit: Unit): number[] {
  if (unit === "count") return range(1, 36, 1);
  if (unit === "ml") return [...range(50, 1000, 50), ...range(1250, 4000, 250)];
  return [
    ...range(25, 500, 25),
    ...range(600, 2000, 100),
    ...range(2500, 5000, 500),
  ];
}

/** How the list shows it: "6", "300 g", "1.5 kg", "750 ml", "2 L". */
export function label(v: number, unit: Unit): string {
  if (unit === "count") return String(v);
  const [small, big] = unit === "ml" ? ["ml", "L"] : ["g", "kg"];
  return v >= 1000 ? `${trim1(v / 1000)} ${big}` : `${v} ${small}`;
}

/** "300 g", "1.5 kg", "2 L", "6" back to the wheel's unit; null when it isn't one of those. */
function parse(text: string | null, unit: Unit): number | null {
  const m = text
    ?.trim()
    .toLowerCase()
    .match(/^(?:about\s+)?(\d+(?:\.\d+)?)\s*([a-z]*)/);
  if (!m) return null;
  const n = Number(m[1]);
  const scale: Record<string, number> = { kg: 1000, l: 1000, g: 1, ml: 1 };
  return unit === "count" ? n : n * (scale[m[2]] ?? 1);
}

/**
 * For what you have: 0 up to well past it, finer for small amounts, with exactly what you have
 * on the wheel so it can start there.
 */
export function stockOptions(unit: Unit, have: number): number[] {
  if (unit === "count") return range(0, Math.max(Math.ceil(have) + 12, 24), 1);
  const top = Math.max(have * 2, 500);
  const step = top <= 500 ? 5 : top <= 2000 ? 10 : 50;
  const exact = Math.round(have);
  return [...new Set([...range(0, top, step), exact])].sort((a, b) => a - b);
}

/** The option nearest a value, or a sensible middle when there's nothing to start from. */
export function startIndex(
  values: number[],
  current: number | null,
  unit: Unit,
): number {
  const target = current ?? (unit === "count" ? 1 : unit === "ml" ? 500 : 250);
  let best = 0;
  values.forEach((v, i) => {
    if (Math.abs(v - target) < Math.abs(values[best] - target)) best = i;
  });
  return best;
}

/**
 * A spin wheel in a sheet from the bottom: spin it or tap a row, then Done. `footer` sits under
 * the wheel and sees the value it's on. Mount it when it opens, so it starts at `start`.
 */
export function WheelSheet({
  title,
  values,
  start,
  format,
  onDone,
  onClose,
  footer,
  canSave = () => true,
}: {
  title: string;
  values: number[];
  start: number;
  /** A row's text; `selected` for the one in the middle ("24 eggs" there, "23" around it). */
  format: (v: number, selected: boolean) => string;
  onDone: (v: number) => void;
  onClose: () => void;
  footer?: (v: number) => ReactNode;
  canSave?: (v: number) => boolean;
}) {
  const styles = useStyles();
  const insets = useSafeAreaInsets();
  const ref = useRef<ComponentRef<typeof ScrollView>>(null);
  const [index, setIndex] = useState(start);
  const settle = useRef<ReturnType<typeof setTimeout> | null>(null);
  const value = values[index];
  const ok = canSave(value);

  const jump = (i: number, animated: boolean) => {
    setIndex(i);
    ref.current?.scrollTo({ y: i * ROW, animated });
  };

  // Follow the spin, then snap to the nearest row once it stops (the web has no snapping of its own).
  const onScroll = (e: NativeSyntheticEvent<NativeScrollEvent>) => {
    const i = Math.max(
      0,
      Math.min(
        values.length - 1,
        Math.round(e.nativeEvent.contentOffset.y / ROW),
      ),
    );
    setIndex(i);
    if (settle.current) clearTimeout(settle.current);
    settle.current = setTimeout(() => jump(i, true), 140);
  };

  return (
    <Modal visible transparent animationType="slide" onRequestClose={onClose}>
      <Pressable
        style={styles.backdrop}
        onPress={onClose}
        accessibilityLabel="Close"
      />
      <View style={[styles.sheet, { paddingBottom: 16 + insets.bottom }]}>
        <View style={styles.bar}>
          <Pressable
            onPress={onClose}
            hitSlop={8}
            style={styles.barButton}
            accessibilityRole="button"
          >
            <Text style={styles.cancel}>Cancel</Text>
          </Pressable>
          <Text style={styles.title} numberOfLines={1}>
            {title}
          </Text>
          <Pressable
            onPress={() => ok && onDone(value)}
            disabled={!ok}
            hitSlop={8}
            style={styles.barButton}
            accessibilityRole="button"
          >
            <Text style={[styles.done, !ok && { opacity: 0.35 }]}>Done</Text>
          </Pressable>
        </View>
        <View style={styles.wheel}>
          <View style={styles.band} pointerEvents="none" />
          <ScrollView
            ref={ref}
            showsVerticalScrollIndicator={false}
            snapToInterval={ROW}
            decelerationRate="fast"
            onScroll={onScroll}
            scrollEventThrottle={16}
            onLayout={() =>
              ref.current?.scrollTo({ y: index * ROW, animated: false })
            }
            contentContainerStyle={{
              paddingVertical: ROW * Math.floor(VISIBLE / 2),
            }}
            accessibilityLabel={title}
          >
            {values.map((v, i) => {
              const away = Math.abs(i - index);
              return (
                <Pressable
                  key={v}
                  onPress={() => jump(i, true)}
                  style={styles.row}
                >
                  <Text
                    style={[
                      styles.value,
                      i === index && styles.selected,
                      { opacity: away === 0 ? 1 : away === 1 ? 0.55 : 0.3 },
                    ]}
                  >
                    {format(v, i === index)}
                  </Text>
                </Pressable>
              );
            })}
          </ScrollView>
        </View>
        {footer?.(value)}
      </View>
    </Modal>
  );
}

/** How much to buy, for a grocery list row. */
export function AmountWheel({
  name,
  unit,
  current,
  onDone,
  onClose,
}: {
  name: string;
  unit: Unit;
  /** The amount shown now ("300 g"), to start the wheel there. */
  current: string | null;
  onDone: (amount: string) => void;
  onClose: () => void;
}) {
  const values = options(unit);
  return (
    <WheelSheet
      title={name}
      values={values}
      start={startIndex(values, parse(current, unit), unit)}
      format={(v, selected) =>
        selected && unit === "count"
          ? `${v} ${countNoun(name, v)}`
          : label(v, unit)
      }
      onDone={(v) => onDone(label(v, unit))}
      onClose={onClose}
    />
  );
}

const useStyles = makeStyles((c, size) => ({
  backdrop: { flex: 1, backgroundColor: "rgba(0,0,0,0.35)" },
  sheet: {
    backgroundColor: c.card,
    borderTopLeftRadius: 20,
    borderTopRightRadius: 20,
    paddingHorizontal: 16,
  },
  bar: {
    flexDirection: "row",
    alignItems: "center",
    minHeight: 56,
    gap: 8,
  },
  barButton: { minWidth: 64, minHeight: 44, justifyContent: "center" },
  cancel: { color: c.textSecondary, fontSize: size(16) },
  done: {
    color: c.accent,
    fontSize: size(16),
    fontWeight: "700",
    textAlign: "right",
  },
  title: {
    flex: 1,
    textAlign: "center",
    color: c.text,
    fontSize: size(17),
    fontWeight: "700",
  },
  wheel: { height: ROW * VISIBLE, justifyContent: "center" },
  band: {
    position: "absolute",
    left: 0,
    right: 0,
    top: ROW * Math.floor(VISIBLE / 2),
    height: ROW,
    borderRadius: 10,
    backgroundColor: c.input,
  },
  row: { height: ROW, alignItems: "center", justifyContent: "center" },
  value: { color: c.text, fontSize: size(20) },
  selected: { fontWeight: "700" },
}));
