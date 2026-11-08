/**
 * The fridge-door screen: what's inside, how much, and when it goes bad —
 * glanceable from across the kitchen. Display only: nothing on it is touched or
 * clicked, so everything that needs a person (naming an item the camera couldn't,
 * recipes, details) happens in the phone app. Rows with more items than fit
 * scroll through them on their own. Built for 7" panels at 1024x600 or 800x480;
 * on a desktop browser it renders inside a simulated panel (see ScreenSimulator).
 * Open http://<backend>:8000/kiosk full-screen (see pi_node/kiosk/).
 */
import FontAwesome from "@expo/vector-icons/FontAwesome";
import { Stack } from "expo-router";
import { useEffect, useMemo, useState } from "react";
import {
  Animated,
  Easing,
  StyleSheet,
  Text,
  View,
  type LayoutChangeEvent,
} from "react-native";

import { InventoryTile } from "@/components/kiosk/InventoryTile";
import { KioskHeader } from "@/components/kiosk/KioskHeader";
import { ScreenSimulator } from "@/components/kiosk/ScreenSimulator";
import {
  api,
  type Alert,
  type InventoryEntry,
  type RecipeCard,
} from "@/lib/api";
import { expiryText, expiryTone } from "@/lib/expiry";
import { syncHouseholdClock } from "@/lib/householdClock";
import {
  palettes,
  TextScaleContext,
  ThemeContext,
  useColors,
  type Palette,
} from "@/lib/theme";
import { useApi } from "@/lib/useApi";

const POLL_MS = 3000;
/** Recipe ideas only change when the inventory does; no need to poll as often. */
const RECIPE_IDEAS = 2;
/** Recipe ideas are built around the newest things: up to this many Shelf items, soonest to go bad first. */
const RECIPE_SHELF_ITEMS = 4;
/** "Updating…" stays up at least this long, so a fast refresh is still noticeable. */
const MIN_UPDATING_MS = 900;
/** The screen's one spacing unit: every gap, margin and panel padding is this, so both columns share a grid. */
const GRID = { regular: 12, compact: 8 };
/** The one shelf with a scale under it (pi_node HX711_PINS); the rest of the fridge isn't weighed. */
const WEIGHED_SHELF = 0;
/** Every tile is this wide, in both rows, so the columns of tiles line up: 3 fit across a row on either panel, so a row rolls from its 4th item. Fits "Wednesday" at glance size. */
const TILE_W = { regular: 176, compact: 148 };
/** A row with more items than fit rolls sideways at this speed, endlessly: slow enough to read while it moves. */
const ROLL_PX_PER_S = 24;
/** Heads up lists only this many lines, the most urgent: short enough to read at a glance and never scroll. */
const HEADS_UP_ITEMS = 3;
/** Below this panel width (the 800x480 screen) everything tightens up. */
const COMPACT_W = 900;
/** Backend alerts the box shows on top. Expiry is covered by the item list, so expiring_soon isn't repeated. */
const SHOWN_ALERTS: Alert["reason"][] = [
  "fridge_temp_high",
  "staple_out",
  "low_days_left",
  "low_fraction",
];

export default function Kiosk() {
  return (
    // Always the light theme: nobody is at the screen to switch it.
    <ThemeContext.Provider value={palettes.light}>
      {/* The phone's Large text setting doesn't apply here: the fridge screen has its own type scale. */}
      <TextScaleContext.Provider value={1}>
        <Stack.Screen options={{ headerShown: false }} />
        <ScreenSimulator>
          <KioskScreen />
        </ScreenSimulator>
      </TextScaleContext.Provider>
    </ThemeContext.Provider>
  );
}

function KioskScreen() {
  const colors = useColors();
  const styles = useMemo(() => makeStyles(colors), [colors]);

  const summary = useApi(api.summary, POLL_MS);

  const [screenW, setScreenW] = useState(0);

  const s = summary.data;
  if (s?.server_time != null && s.utc_offset_minutes != null) {
    syncHouseholdClock(s.server_time, s.utc_offset_minutes);
  }
  const compact = screenW > 0 && screenW < COMPACT_W;
  const grid = compact ? GRID.compact : GRID.regular;
  // Items the camera couldn't name stay off this screen (and out of its alerts) until
  // someone names them in the phone app.
  const inventory = useMemo(
    () => (s?.inventory ?? []).filter(isNamed),
    [s?.inventory],
  );
  const alerts = useMemo(() => {
    const unnamed = new Set(
      (s?.inventory ?? []).filter((i) => !isNamed(i)).map((i) => i.product_id),
    );
    return (s?.alerts ?? []).filter(
      (a) => a.product_id == null || !unnamed.has(a.product_id),
    );
  }, [s?.inventory, s?.alerts]);
  const recipes = useRecipeIdeas(s ? inventory : undefined);
  const shelves = useMemo(() => groupRows(bySoonest(inventory)), [inventory]);

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
        compact={compact}
      />

      {summary.error && !s ? (
        <View style={styles.offline}>
          <FontAwesome name="plug" size={40} color={colors.muted} />
          <Text style={styles.offlineText}>Connecting to ReFridge…</Text>
        </View>
      ) : (
        <View style={[styles.body, { padding: grid, gap: grid }]}>
          <View style={[styles.column, { gap: grid }]}>
            {s &&
              shelves.map((shelf) => (
                <Shelf
                  key={shelf.key}
                  title={shelf.title}
                  empty={shelf.empty}
                  items={shelf.items}
                  compact={compact}
                  grid={grid}
                />
              ))}
          </View>

          {/* Two boxes, each the height of the row beside it, so their edges line up across the screen. */}
          <View
            style={[styles.side, { width: compact ? 220 : 270, gap: grid }]}
          >
            <HeadsUp inventory={inventory} alerts={alerts} grid={grid} />
            <RecipeIdeas
              recipes={(recipes.ideas ?? []).slice(
                0,
                compact ? 1 : RECIPE_IDEAS,
              )}
              updating={recipes.updating}
              grid={grid}
            />
          </View>
        </View>
      )}
    </View>
  );
}

/**
 * The few things worth a look right now, most urgent first — never more than
 * HEADS_UP_ITEMS, so it always fits without scrolling. The full list is the rows.
 */
function HeadsUp({
  inventory,
  alerts,
  grid,
}: {
  inventory: InventoryEntry[];
  alerts: Alert[];
  grid: number;
}) {
  const colors = useColors();
  const styles = useMemo(() => makeStyles(colors), [colors]);
  const top = headsUpLines(inventory, alerts).slice(0, HEADS_UP_ITEMS);

  return (
    <View style={[styles.panel, { padding: grid }]}>
      <Text style={styles.section}>Heads up</Text>
      {top.length === 0 ? (
        <Text style={styles.muted}>Nothing to worry about.</Text>
      ) : (
        top.map((line) => (
          <View key={line.key} style={styles.alertRow}>
            <View
              style={[styles.dot, { backgroundColor: colors[line.tone] }]}
            />
            <Text style={styles.alertText} numberOfLines={2}>
              <Text style={{ fontWeight: "700" }}>{line.title}</Text> ·{" "}
              {line.detail}
            </Text>
          </View>
        ))
      )}
    </View>
  );
}

type HeadsUpLine = {
  key: string;
  title: string;
  detail: string;
  tone: "danger" | "warn" | "good";
  /** Ranks the lines: lower is more urgent. */
  rank: number;
};

/**
 * Everything Heads up could say, most urgent first: the fridge running warm, then food
 * going bad today or tomorrow (soonest first), things running out, and then whatever
 * goes bad next.
 */
function headsUpLines(
  inventory: InventoryEntry[],
  alerts: Alert[],
): HeadsUpLine[] {
  const lines: HeadsUpLine[] = [];
  for (const [i, a] of alerts
    .filter((a) => SHOWN_ALERTS.includes(a.reason))
    .entries()) {
    const warm = a.reason === "fridge_temp_high";
    lines.push({
      key: `alert-${a.reason}-${a.product_id}-${i}`,
      title: a.product_name,
      detail: a.detail,
      tone: warm ? "danger" : "warn",
      rank: warm ? 0 : runningOutRank(a),
    });
  }
  for (const item of inventory) {
    const d = item.expires_in_days;
    if (item.location === "freezer" || d == null) continue; // frozen food keeps for months
    const tone = expiryTone(d, item.leftovers);
    lines.push({
      key: `item-${item.product_id}`,
      title: item.name,
      detail: lowerFirst(
        expiryText(d, item.expiry_estimated && !item.leftovers),
      ),
      tone: tone ?? "good",
      rank: (d <= 1 ? 1 : 4) + Math.max(d, -1) / 1000, // soonest first within each group
    });
  }
  return lines.sort(
    (a, b) => a.rank - b.rank || a.title.localeCompare(b.title),
  );
}

/** Out of a staple first, then whatever runs out soonest, then "getting low" — all after food going bad. */
function runningOutRank(a: Alert): number {
  if (a.reason === "staple_out") return 3;
  if (a.reason === "low_days_left")
    return 3.1 + Math.max(a.days ?? 0, 0) / 1000;
  return 3.5;
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
    .filter((i) => i.location === "fridge" && i.shelf === WEIGHED_SHELF)
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
  grid,
}: {
  recipes: RecipeCard[];
  updating: boolean;
  grid: number;
}) {
  const colors = useColors();
  const styles = useMemo(() => makeStyles(colors), [colors]);
  return (
    <View style={[styles.panel, { padding: grid }]}>
      <View style={styles.panelHeader}>
        <Text style={styles.section}>Recipe ideas</Text>
        {updating && <Text style={styles.updating}>Updating…</Text>}
      </View>
      {updating && <UpdatingBar />}
      {recipes.length === 0 && !updating && (
        <Text style={styles.muted}>
          Ideas show up once there&apos;s food in the fridge.
        </Text>
      )}
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

/**
 * One shelf: a row of tiles, soonest to go bad on the left. When more items are
 * on it than fit, the row rolls slowly sideways, endlessly: the list is drawn twice
 * back to back, so its end flows straight into its start again.
 */
function Shelf({
  title,
  empty,
  items,
  compact,
  grid,
}: {
  title: string;
  /** Shown when the row has nothing in it. */
  empty: string;
  items: InventoryEntry[];
  compact: boolean;
  grid: number;
}) {
  const colors = useColors();
  const styles = useMemo(() => makeStyles(colors), [colors]);
  const [row, setRow] = useState({ width: 0, height: 0 });
  const [offset] = useState(() => new Animated.Value(0));

  const tileW = compact ? TILE_W.compact : TILE_W.regular;
  const cycle = items.length * (tileW + grid); // one full pass of the list, its trailing gap included
  // Tiles roll inside the box's padding: they disappear and reappear the same distance
  // from the border as they sit when still.
  const rolls = row.width > 0 && cycle - grid > row.width;
  useEffect(() => {
    offset.setValue(0);
    if (!rolls) return;
    const loop = Animated.loop(
      Animated.timing(offset, {
        toValue: -cycle,
        duration: (cycle / ROLL_PX_PER_S) * 1000,
        easing: Easing.linear,
        useNativeDriver: false,
      }),
    );
    loop.start();
    return () => loop.stop();
  }, [rolls, cycle, offset]);
  const drawn = rolls ? [...items, ...items] : items;

  return (
    <View style={[styles.shelf, { padding: grid, gap: grid * 0.75 }]}>
      <View style={styles.shelfHeader}>
        <Text style={styles.section}>{title}</Text>
        <Text style={styles.shelfCount}>
          {items.length === 0
            ? ""
            : items.length === 1
              ? "1 item"
              : `${items.length} items, soonest to go bad first`}
        </Text>
      </View>
      <View
        style={{
          flex: 1,
          minWidth: 0,
          overflow: "hidden",
        }}
        onLayout={(e: LayoutChangeEvent) => setRow(e.nativeEvent.layout)}
      >
        {items.length === 0 ? (
          <View style={styles.emptyShelf}>
            <Text style={styles.muted}>{empty}</Text>
          </View>
        ) : (
          row.width > 0 && (
            <Animated.View
              style={{
                flexDirection: "row",
                gap: grid,
                alignSelf: "flex-start",
                transform: [{ translateX: offset }],
              }}
            >
              {drawn.map((item, i) => (
                <InventoryTile
                  key={`${item.product_id}-${i}`}
                  item={item}
                  width={tileW}
                  height={row.height}
                  compact={compact}
                />
              ))}
            </Animated.View>
          )
        )}
      </View>
    </View>
  );
}

/**
 * Whether the item has a real name. The camera bench adds an item it couldn't name
 * with a photo of it; those wait in the phone app until someone names them.
 */
function isNamed(item: InventoryEntry): boolean {
  return !item.image_url;
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
 * Two rows, both always shown: what's on the weighed shelf, and everything else
 * you have — the rest of the fridge, the pantry and the freezer.
 */
function groupRows(ranked: InventoryEntry[]): Row[] {
  const onShelf = (item: InventoryEntry) =>
    item.location === "fridge" && item.shelf === WEIGHED_SHELF;
  return [
    {
      key: "shelf",
      title: "Shelf",
      empty: "Empty — put something on the shelf.",
      items: ranked.filter(onShelf),
    },
    {
      key: "rest",
      title: "Everything else",
      empty: "Nothing else at the moment.",
      items: ranked.filter((item) => !onShelf(item)),
    },
  ];
}

const makeStyles = (colors: Palette) =>
  StyleSheet.create({
    screen: { flex: 1, backgroundColor: colors.bg },
    body: { flex: 1, flexDirection: "row" },
    // minWidth/minHeight 0: a column never grows to fit a rolling row (or list) — it clips it instead.
    column: { flex: 1, minWidth: 0, minHeight: 0 },
    // Fixed width, never squeezed (no `flex`: on the web `flex: 0` would zero the width).
    side: { flexShrink: 0, minHeight: 0 },
    shelf: {
      flex: 1,
      minWidth: 0,
      minHeight: 0,
      borderRadius: 16,
      overflow: "hidden", // tiles rolling past are clipped by the rounded border
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
    panel: {
      flex: 1,
      minHeight: 0,
      overflow: "hidden",
      backgroundColor: colors.input,
      borderColor: colors.border,
      borderWidth: 1,
      borderRadius: 16,
      gap: 8,
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
