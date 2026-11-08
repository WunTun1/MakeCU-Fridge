/**
 * The fridge-door touchscreen: what's inside, how much, and when it goes bad —
 * glanceable from across the kitchen, touch only (no typing). Recipes and
 * everything else live in the phone app. Built for 7" panels at 1024x600 or
 * 800x480; on a desktop browser it renders inside a simulated panel (see
 * ScreenSimulator). Open http://<backend>:8000/kiosk full-screen (see pi_node/kiosk/).
 */
import FontAwesome from "@expo/vector-icons/FontAwesome";
import { Stack } from "expo-router";
import { useEffect, useMemo, useState } from "react";
import {
  Animated,
  Easing,
  ScrollView,
  StyleSheet,
  Text,
  View,
  type LayoutChangeEvent,
  type NativeScrollEvent,
  type NativeSyntheticEvent,
} from "react-native";

import { InventoryTile } from "@/components/kiosk/InventoryTile";
import { KioskHeader } from "@/components/kiosk/KioskHeader";
import { KioskModal } from "@/components/kiosk/KioskModal";
import { ReviewPrompt } from "@/components/kiosk/ReviewPrompt";
import { ScreenSimulator } from "@/components/kiosk/ScreenSimulator";
import { UsageChart } from "@/components/UsageChart";
import { formatAmount } from "@/lib/amount";
import {
  api,
  type Alert,
  type InventoryEntry,
  type ProductUsage,
  type RecipeCard,
} from "@/lib/api";
import {
  expiryText,
  expiryTone,
  expiryWord,
  LIKELY_WASTED,
  likelyWasted,
} from "@/lib/expiry";
import {
  palettes,
  TextScaleContext,
  ThemeContext,
  useColors,
  type Palette,
  type ThemeMode,
} from "@/lib/theme";
import { capitalize, whenWord } from "@/lib/time";
import { useApi } from "@/lib/useApi";

const POLL_MS = 3000;
/** Recipe ideas only change when the inventory does; no need to poll as often. */
const RECIPE_IDEAS = 2;
/** Recipe ideas are built around the newest things: up to this many Shelf items, soonest to go bad first. */
const RECIPE_SHELF_ITEMS = 4;
/** "Updating…" stays up at least this long, so a fast refresh is still noticeable. */
const MIN_UPDATING_MS = 900;
const GAP = 10;
/** The one shelf with a scale under it (pi_node HX711_PINS); the rest of the fridge isn't weighed. */
const WEIGHED_SHELF = 0;
/** Narrower tiles can't fit "Wednesday" at glance size; fewer, wider tiles show instead. */
const MIN_TILE_W = { regular: 210, compact: 175 };
/** This share of one more tile peeks in at the end of every row, so a row that scrolls shows there's more. */
const PEEK = 0.4;
/** Below this panel width (the 800x480 screen) everything tightens up. */
const COMPACT_W = 900;
const THEME_KEY = "refridge.kiosk.theme";
/** How many items the Heads up box lists (soonest to go bad first), leaving room for recipe ideas below. */
const HEADS_UP_ITEMS = 4;
const HEADS_UP_ITEMS_COMPACT = 3;
/** Backend alerts the box shows on top. Expiry is covered by the item list, so expiring_soon isn't repeated. */
const SHOWN_ALERTS: Alert["reason"][] = [
  "fridge_temp_high",
  "staple_out",
  "low_days_left",
  "low_fraction",
];

// The kiosk runs in a browser; localStorage may be missing (native) or blocked.
function loadMode(): ThemeMode {
  try {
    return globalThis.localStorage?.getItem(THEME_KEY) === "light"
      ? "light"
      : "dark";
  } catch {
    return "dark";
  }
}

function saveMode(mode: ThemeMode) {
  try {
    globalThis.localStorage?.setItem(THEME_KEY, mode);
  } catch {
    // Not remembered across reloads; the toggle still works.
  }
}

export default function Kiosk() {
  const [mode, setMode] = useState<ThemeMode>(loadMode);
  const toggle = () =>
    setMode((m) => {
      const next = m === "dark" ? "light" : "dark";
      saveMode(next);
      return next;
    });

  return (
    <ThemeContext.Provider value={palettes[mode]}>
      {/* The phone's Large text setting doesn't apply here: the fridge screen has its own type scale. */}
      <TextScaleContext.Provider value={1}>
        <Stack.Screen options={{ headerShown: false }} />
        <ScreenSimulator>
          <KioskScreen mode={mode} onToggleTheme={toggle} />
        </ScreenSimulator>
      </TextScaleContext.Provider>
    </ThemeContext.Provider>
  );
}

function KioskScreen({
  mode,
  onToggleTheme,
}: {
  mode: ThemeMode;
  onToggleTheme: () => void;
}) {
  const colors = useColors();
  const styles = useMemo(() => makeStyles(colors), [colors]);

  const summary = useApi(api.summary, POLL_MS);
  const reviews = useApi(api.review, POLL_MS);
  const common = useApi(() => api.commonProducts(8));
  const recipes = useRecipeIdeas(summary.data?.inventory);

  const [screenW, setScreenW] = useState(0);
  const [selected, setSelected] = useState<InventoryEntry | null>(null);

  const s = summary.data;
  const compact = screenW > 0 && screenW < COMPACT_W;
  const openReviews = reviews.data ?? [];
  const shelves = useMemo(
    () => groupRows(bySoonest(s?.inventory ?? [])),
    [s?.inventory],
  );

  return (
    <View
      style={styles.screen}
      onLayout={(e: LayoutChangeEvent) =>
        setScreenW(e.nativeEvent.layout.width)
      }
    >
      <KioskHeader
        conditions={s?.conditions ?? null}
        doorOpen={s?.door_open ?? false}
        mode={mode}
        onToggleTheme={onToggleTheme}
        compact={compact}
      />

      {summary.error && !s ? (
        <View style={styles.offline}>
          <FontAwesome name="plug" size={40} color={colors.muted} />
          <Text style={styles.offlineText}>Connecting to ReFridge…</Text>
        </View>
      ) : (
        <View style={[styles.body, compact && { padding: 10, gap: 10 }]}>
          <View style={[styles.shelves, compact && { gap: 10 }]}>
            {s &&
              shelves.map((shelf) => (
                <Shelf
                  key={shelf.key}
                  title={shelf.title}
                  empty={shelf.empty}
                  items={shelf.items}
                  compact={compact}
                  onOpen={setSelected}
                />
              ))}
          </View>

          <ScrollView
            style={{ width: compact ? 220 : 270, flexGrow: 0 }}
            contentContainerStyle={{ gap: compact ? 10 : 12 }}
          >
            {/* The only thing the fridge ever asks: "what is this?" for an item it couldn't name. */}
            {openReviews.length > 0 && (
              <ReviewPrompt
                key={openReviews[openReviews.length - 1].id}
                review={openReviews[openReviews.length - 1]}
                remaining={openReviews.length}
                commonNames={(common.data ?? []).map((p) => p.name)}
                onResolved={() => {
                  reviews.reload();
                  summary.reload();
                }}
              />
            )}
            {s && (
              <HeadsUp
                inventory={s.inventory}
                alerts={s.alerts}
                compact={compact}
              />
            )}
            {((recipes.ideas?.length ?? 0) > 0 || recipes.updating) && (
              <RecipeIdeas
                recipes={(recipes.ideas ?? []).slice(
                  0,
                  compact ? 1 : RECIPE_IDEAS,
                )}
                updating={recipes.updating}
              />
            )}
          </ScrollView>
        </View>
      )}

      {selected && (
        <ItemModal item={selected} onClose={() => setSelected(null)} />
      )}
    </View>
  );
}

/**
 * One tile width for the whole screen, from the row width alone (never the item count),
 * so every row lines up: as many tiles as fit at the minimum width, plus a peek.
 */
function tileLayout(
  rowW: number,
  compact: boolean,
): { width: number; fit: number } {
  const min = compact ? MIN_TILE_W.compact : MIN_TILE_W.regular;
  for (let fit = Math.floor((rowW + GAP) / (min + GAP)); fit > 1; fit--) {
    const width = (rowW - GAP * fit) / (fit + PEEK);
    if (width >= min) return { width, fit };
  }
  return { width: (rowW - GAP) / (1 + PEEK), fit: 1 };
}

/** "How long is it good for": every fridge item, soonest to go bad first, plus any other alerts. */
function HeadsUp({
  inventory,
  alerts,
  compact,
}: {
  inventory: InventoryEntry[];
  alerts: Alert[];
  compact: boolean;
}) {
  const colors = useColors();
  const styles = useMemo(() => makeStyles(colors), [colors]);
  const other = alerts
    .filter((a) => SHOWN_ALERTS.includes(a.reason))
    .slice(0, 3);
  const items = inventory
    .filter((i) => i.location === "fridge" && i.expires_in_days != null)
    .sort(
      (a, b) =>
        a.expires_in_days! - b.expires_in_days! || a.name.localeCompare(b.name),
    );
  const shown = items.slice(
    0,
    Math.max(
      (compact ? HEADS_UP_ITEMS_COMPACT : HEADS_UP_ITEMS) - other.length,
      1,
    ),
  );

  return (
    <View style={styles.panel}>
      <Text style={styles.section}>Heads up</Text>
      {other.map((a, i) => (
        <View key={`${a.reason}-${a.product_id}-${i}`} style={styles.alertRow}>
          <View
            style={[
              styles.dot,
              {
                backgroundColor:
                  a.reason === "fridge_temp_high" ? colors.danger : colors.warn,
              },
            ]}
          />
          <Text style={styles.alertText} numberOfLines={2}>
            <Text style={{ fontWeight: "700" }}>{a.product_name}</Text> ·{" "}
            {a.detail}
          </Text>
        </View>
      ))}
      {shown.map((item) => {
        const d = item.expires_in_days!;
        const tone = expiryTone(d, item.leftovers);
        const color = tone ? colors[tone] : colors.good;
        return (
          <View key={item.product_id} style={styles.alertRow}>
            <View style={[styles.dot, { backgroundColor: color }]} />
            <Text style={styles.alertText} numberOfLines={2}>
              <Text style={{ fontWeight: "700" }}>{item.name}</Text> ·{" "}
              {lowerFirst(
                expiryText(d, item.expiry_estimated && !item.leftovers),
              )}
            </Text>
          </View>
        );
      })}
      {items.length > shown.length && (
        <Text style={styles.muted}>
          +{items.length - shown.length} more on the shelves
        </Text>
      )}
      {other.length === 0 && items.length === 0 && (
        <Text style={styles.muted}>Nothing to worry about.</Text>
      )}
    </View>
  );
}

/**
 * Recipe ideas that follow what was just put in: searched around the Shelf items (soonest to go
 * bad first), or everything you have when the Shelf is empty. Re-fetched whenever the fridge's
 * contents change; `updating` is true meanwhile (and for at least MIN_UPDATING_MS).
 */
function useRecipeIdeas(inventory: InventoryEntry[] | undefined) {
  const [shown, setShown] = useState<{
    key: string;
    ideas: RecipeCard[];
  } | null>(null);
  const loaded = inventory != null;
  const contents = (inventory ?? [])
    .map((i) => `${i.product_id}:${i.grams}`)
    .join(",");
  const shelfQuery = (inventory ?? [])
    .filter(
      (i) =>
        i.location === "fridge" && i.shelf === WEIGHED_SHELF && !i.image_url,
    ) // no unnamed items
    .sort(
      (a, b) =>
        (a.expires_in_days ?? Infinity) - (b.expires_in_days ?? Infinity),
    )
    .slice(0, RECIPE_SHELF_ITEMS)
    .map((i) => i.name)
    .join(" ");
  // What the ideas should be for: when this differs from what's shown, they're updating.
  const key = `${contents}|${shelfQuery}`;

  useEffect(() => {
    if (!loaded) return;
    let cancelled = false;
    const started = Date.now();
    api
      .suggestRecipes({ q: shelfQuery || undefined, limit: RECIPE_IDEAS })
      .catch(() => null) // backend hiccup: keep showing the last ideas
      .then((r) => {
        setTimeout(
          () =>
            !cancelled &&
            setShown((prev) => ({ key, ideas: r ?? prev?.ideas ?? [] })),
          Math.max(0, MIN_UPDATING_MS - (Date.now() - started)),
        );
      });
    return () => {
      cancelled = true;
    };
  }, [loaded, key, shelfQuery]);

  return {
    ideas: shown?.ideas ?? null,
    updating: loaded && shown?.key !== key,
  };
}

/** A thin bar with a segment sliding across it: "working on it". */
function UpdatingBar() {
  const colors = useColors();
  const styles = useMemo(() => makeStyles(colors), [colors]);
  const [slide] = useState(() => new Animated.Value(0));
  useEffect(() => {
    const loop = Animated.loop(
      Animated.timing(slide, {
        toValue: 1,
        duration: 900,
        easing: Easing.inOut(Easing.quad),
        useNativeDriver: false,
      }),
    );
    loop.start();
    return () => loop.stop();
  }, [slide]);
  const left = useMemo(
    () =>
      slide.interpolate({ inputRange: [0, 1], outputRange: ["-35%", "100%"] }),
    [slide],
  );
  return (
    <View style={styles.barTrack}>
      <Animated.View style={[styles.barSegment, { left }]} />
    </View>
  );
}

/** A couple of recipe names, the ones that use up food going bad first (the full recipes are in the phone app). */
function RecipeIdeas({
  recipes,
  updating,
}: {
  recipes: RecipeCard[];
  updating: boolean;
}) {
  const colors = useColors();
  const styles = useMemo(() => makeStyles(colors), [colors]);
  return (
    <View style={styles.panel}>
      <View style={styles.panelHeader}>
        <Text style={styles.section}>Recipe ideas</Text>
        {updating && <Text style={styles.updating}>Updating…</Text>}
      </View>
      {updating && <UpdatingBar />}
      {recipes.map((r) => (
        <View
          key={r.id}
          style={[styles.recipeRow, updating && { opacity: 0.45 }]}
        >
          <FontAwesome
            name="cutlery"
            size={15}
            color={colors.accent}
            style={{ marginTop: 3, width: 16 }}
          />
          <View style={{ flex: 1, gap: 2 }}>
            <Text style={styles.recipeName} numberOfLines={2}>
              {r.name}
            </Text>
            {r.uses_expiring.length > 0 ? (
              <Text
                style={[styles.recipeNote, { color: colors.warn }]}
                numberOfLines={1}
              >
                Uses up {r.uses_expiring.join(", ")}
              </Text>
            ) : null}
            <Text style={styles.recipeNote} numberOfLines={1}>
              {r.missing.length === 0
                ? "You have everything"
                : `Need ${r.missing.join(", ")}`}
            </Text>
          </View>
        </View>
      ))}
    </View>
  );
}

/** "Goes bad Monday" -> "goes bad Monday", to follow the item's name. */
const lowerFirst = (s: string) => s.charAt(0).toLowerCase() + s.slice(1);

/** One shelf: a row of tiles you swipe sideways, soonest to go bad on the left. */
function Shelf({
  title,
  empty,
  items,
  compact,
  onOpen,
}: {
  title: string;
  /** Shown when the row has nothing in it. */
  empty: string;
  items: InventoryEntry[];
  compact: boolean;
  onOpen: (item: InventoryEntry) => void;
}) {
  const colors = useColors();
  const styles = useMemo(() => makeStyles(colors), [colors]);
  const [row, setRow] = useState({ width: 0, height: 0 });
  const [first, setFirst] = useState(0);

  const { width: tileW, fit } = tileLayout(row.width, compact);
  const overflows = items.length > fit;
  const onScroll = (e: NativeSyntheticEvent<NativeScrollEvent>) =>
    setFirst(Math.round(e.nativeEvent.contentOffset.x / (tileW + GAP)));

  return (
    <View style={[styles.shelf, compact && { padding: 8, gap: 6 }]}>
      <View style={styles.shelfHeader}>
        <Text style={styles.section}>{title}</Text>
        <Text style={styles.shelfCount}>
          {items.length === 0
            ? ""
            : items.length === 1
              ? "1 item"
              : `${items.length} items, soonest to go bad first`}
          {overflows ? "  ·  swipe for more ›" : ""}
        </Text>
      </View>
      <View
        style={{ flex: 1 }}
        onLayout={(e: LayoutChangeEvent) => setRow(e.nativeEvent.layout)}
      >
        {items.length === 0 ? (
          <View style={styles.emptyShelf}>
            <Text style={styles.muted}>{empty}</Text>
          </View>
        ) : (
          row.width > 0 && (
            <ScrollView
              horizontal
              showsHorizontalScrollIndicator={false}
              snapToInterval={tileW + GAP}
              decelerationRate="fast"
              onScroll={onScroll}
              scrollEventThrottle={100}
              contentContainerStyle={{ gap: GAP }}
            >
              {items.map((item, i) => (
                <InventoryTile
                  key={item.product_id}
                  item={item}
                  width={tileW}
                  height={row.height}
                  compact={compact}
                  peek={overflows && i === first + fit}
                  onPress={() => onOpen(item)}
                />
              ))}
            </ScrollView>
          )
        )}
      </View>
    </View>
  );
}

/** Soonest to go bad first; things with no known expiry after, by name. */
function bySoonest(inventory: InventoryEntry[]): InventoryEntry[] {
  return [...inventory].sort(
    (a, b) =>
      (a.expires_in_days ?? Infinity) - (b.expires_in_days ?? Infinity) ||
      a.name.localeCompare(b.name),
  );
}

type Row = {
  key: string;
  title: string;
  empty: string;
  items: InventoryEntry[];
};

/**
 * Two rows, both always shown: what's on the weighed shelf, and everything
 * else in the fridge. Pantry items aren't in the fridge, so they're left off.
 */
function groupRows(ranked: InventoryEntry[]): Row[] {
  const inFridge = ranked.filter((item) => item.location === "fridge");
  return [
    {
      key: "shelf",
      title: "Shelf",
      empty: "Empty — put something on the shelf.",
      items: inFridge.filter((item) => item.shelf === WEIGHED_SHELF),
    },
    {
      key: "rest",
      title: "Rest of the fridge",
      empty: "Nothing else in the fridge.",
      items: inFridge.filter((item) => item.shelf !== WEIGHED_SHELF),
    },
  ];
}

function ItemModal({
  item,
  onClose,
}: {
  item: InventoryEntry;
  onClose: () => void;
}) {
  const colors = useColors();
  const styles = useMemo(() => makeStyles(colors), [colors]);
  const [usage, setUsage] = useState<ProductUsage | null>(null);
  useEffect(() => {
    let cancelled = false;
    api
      .usage(item.product_id)
      .then((u) => !cancelled && setUsage(u))
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [item.product_id]);

  const d = item.expires_in_days;
  const tone = expiryTone(d, item.leftovers);
  const wasted = item.leftovers ? null : likelyWasted(item);
  return (
    <KioskModal visible title={item.name} onClose={onClose}>
      <View style={styles.stats}>
        <Stat
          label={item.expiry_estimated ? "Goes bad (estimate)" : "Goes bad"}
          value={d == null ? "No date" : expiryWord(d)}
          color={d == null ? colors.muted : tone ? colors[tone] : undefined}
        />
        <Stat
          label="Have"
          value={
            item.grams > 0
              ? capitalize(
                  formatAmount(
                    item.grams,
                    item.unit,
                    item.grams_per_unit,
                    item.name,
                  ),
                )
              : "Not weighed"
          }
        />
        {wasted ? (
          <Stat label={LIKELY_WASTED} value={wasted} />
        ) : (
          !item.leftovers &&
          item.days_left != null && (
            <Stat
              label="Runs out"
              value={capitalize(whenWord(item.days_left))}
            />
          )
        )}
      </View>
      {usage && (
        <>
          <Text style={styles.muted}>Used per day, last 2 weeks</Text>
          <UsageChart
            dailyUsage={usage.daily_usage_g}
            days={14}
            height={110}
            unit={usage.unit}
            gramsPerUnit={usage.grams_per_unit}
            name={usage.name}
          />
        </>
      )}
    </KioskModal>
  );
}

function Stat({
  label,
  value,
  color,
}: {
  label: string;
  value: string;
  color?: string;
}) {
  const colors = useColors();
  const styles = useMemo(() => makeStyles(colors), [colors]);
  return (
    <View style={{ alignItems: "center", flex: 1, gap: 4 }}>
      <Text
        style={{
          color: color ?? colors.text,
          fontSize: 26,
          fontWeight: "700",
          textAlign: "center",
        }}
      >
        {value}
      </Text>
      <Text style={styles.muted}>{label}</Text>
    </View>
  );
}

const makeStyles = (colors: Palette) =>
  StyleSheet.create({
    screen: { flex: 1, backgroundColor: colors.bg },
    body: { flex: 1, flexDirection: "row", padding: 14, gap: 14 },
    shelves: { flex: 1, gap: 12 },
    shelf: {
      flex: 1,
      gap: 8,
      padding: 10,
      borderRadius: 18,
      borderWidth: 1,
      borderColor: colors.border,
      backgroundColor: colors.input,
    },
    shelfHeader: {
      flexDirection: "row",
      justifyContent: "space-between",
      alignItems: "baseline",
      paddingHorizontal: 4,
    },
    section: {
      color: colors.muted,
      fontSize: 13,
      fontWeight: "700",
      letterSpacing: 1,
      textTransform: "uppercase",
    },
    shelfCount: { color: colors.muted, fontSize: 13 },
    emptyShelf: { flex: 1, alignItems: "center", justifyContent: "center" },
    muted: { color: colors.muted, fontSize: 14 },
    stats: { flexDirection: "row", gap: 8 },
    panel: {
      backgroundColor: colors.card,
      borderColor: colors.border,
      borderWidth: 1,
      borderRadius: 16,
      padding: 12,
      gap: 10,
    },
    alertRow: { flexDirection: "row", alignItems: "center", gap: 10 },
    dot: { width: 10, height: 10, borderRadius: 5 },
    alertText: { color: colors.text, fontSize: 15, flex: 1 },
    recipeRow: { flexDirection: "row", gap: 10 },
    panelHeader: {
      flexDirection: "row",
      justifyContent: "space-between",
      alignItems: "baseline",
    },
    updating: { color: colors.accent, fontSize: 13, fontWeight: "600" },
    barTrack: {
      height: 4,
      borderRadius: 2,
      overflow: "hidden",
      backgroundColor: colors.border,
    },
    barSegment: {
      position: "absolute",
      top: 0,
      bottom: 0,
      width: "35%",
      borderRadius: 2,
      backgroundColor: colors.accent,
    },
    recipeName: { color: colors.text, fontSize: 15, fontWeight: "700" },
    recipeNote: { color: colors.muted, fontSize: 13 },
    offline: {
      flex: 1,
      alignItems: "center",
      justifyContent: "center",
      gap: 12,
    },
    offlineText: { color: colors.muted, fontSize: 20 },
  });
