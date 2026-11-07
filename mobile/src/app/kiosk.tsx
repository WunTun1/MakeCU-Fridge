/**
 * The fridge-door touchscreen: what's inside, how much, and when it goes bad —
 * glanceable from across the kitchen, touch only (no typing). Recipes and
 * everything else live in the phone app. Built for 7" panels at 1024x600 or
 * 800x480; on a desktop browser it renders inside a simulated panel (see
 * ScreenSimulator). Open http://<backend>:8000/kiosk full-screen (see pi_node/kiosk/).
 */
import FontAwesome from '@expo/vector-icons/FontAwesome';
import { Stack } from 'expo-router';
import { useEffect, useMemo, useState } from 'react';
import { ScrollView, StyleSheet, Text, View, type LayoutChangeEvent } from 'react-native';

import { InventoryTile, type TileFlag } from '@/components/kiosk/InventoryTile';
import { KioskHeader } from '@/components/kiosk/KioskHeader';
import { KioskModal } from '@/components/kiosk/KioskModal';
import { ReviewPrompt } from '@/components/kiosk/ReviewPrompt';
import { ScreenSimulator } from '@/components/kiosk/ScreenSimulator';
import { UsageChart } from '@/components/UsageChart';
import { api, type InventoryEntry, type ProductUsage } from '@/lib/api';
import { expiryText } from '@/lib/expiry';
import { formatGrams, palettes, ThemeContext, useColors, type Palette, type ThemeMode } from '@/lib/theme';
import { useApi } from '@/lib/useApi';

const POLL_MS = 3000;
const GAP = 10;
/** The one shelf with a scale under it (pi_node HX711_PINS); the rest of the fridge isn't weighed. */
const WEIGHED_SHELF = 0;
/** Tiles narrower than this get cramped names; fewer, wider tiles show instead. */
const MIN_TILE_W = 150;
/** When a shelf scrolls, this much of the next tile peeks in to show there's more. */
const PEEK = 0.4;
/** Below this panel width (the 800x480 screen) everything tightens up. */
const COMPACT_W = 900;
/** Goes bad within this many days: red. Within WARN_DAYS: amber. */
const DANGER_DAYS = 1;
const WARN_DAYS = 3;
const THEME_KEY = 'refridge.kiosk.theme';

// The kiosk runs in a browser; localStorage may be missing (native) or blocked.
function loadMode(): ThemeMode {
  try {
    return globalThis.localStorage?.getItem(THEME_KEY) === 'light' ? 'light' : 'dark';
  } catch {
    return 'dark';
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
      const next = m === 'dark' ? 'light' : 'dark';
      saveMode(next);
      return next;
    });

  return (
    <ThemeContext.Provider value={palettes[mode]}>
      <Stack.Screen options={{ headerShown: false }} />
      <ScreenSimulator>
        <KioskScreen mode={mode} onToggleTheme={toggle} />
      </ScreenSimulator>
    </ThemeContext.Provider>
  );
}

/** An inventory entry with how urgently it needs attention. */
type Ranked = { item: InventoryEntry; flag: TileFlag; note?: string };

function KioskScreen({ mode, onToggleTheme }: { mode: ThemeMode; onToggleTheme: () => void }) {
  const colors = useColors();
  const styles = useMemo(() => makeStyles(colors), [colors]);

  const summary = useApi(api.summary, POLL_MS);
  const reviews = useApi(api.review, POLL_MS);
  const common = useApi(() => api.commonProducts(8));

  const [screenW, setScreenW] = useState(0);
  const [selected, setSelected] = useState<InventoryEntry | null>(null);

  const s = summary.data;
  const compact = screenW > 0 && screenW < COMPACT_W;
  const openReviews = reviews.data ?? [];
  const shelves = useMemo(() => groupRows(rankItems(s?.inventory ?? [])), [s?.inventory]);

  return (
    <View style={styles.screen} onLayout={(e: LayoutChangeEvent) => setScreenW(e.nativeEvent.layout.width)}>
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

          {/* The only thing the fridge ever asks: "what is this?" for an item it couldn't name. */}
          {openReviews.length > 0 && (
            <ScrollView style={{ width: compact ? 220 : 270, flexGrow: 0 }}>
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
            </ScrollView>
          )}
        </View>
      )}

      {selected && <ItemModal item={selected} onClose={() => setSelected(null)} />}
    </View>
  );
}

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
  items: Ranked[];
  compact: boolean;
  onOpen: (item: InventoryEntry) => void;
}) {
  const colors = useColors();
  const styles = useMemo(() => makeStyles(colors), [colors]);
  const [row, setRow] = useState({ width: 0, height: 0 });

  // Fit as many readable tiles as the row allows; if there are more, size them so the next one peeks in.
  const fit = Math.max(2, Math.floor((row.width + GAP) / (MIN_TILE_W + GAP)));
  const overflows = items.length > fit;
  const tileW = overflows ? (row.width - GAP * fit) / (fit + PEEK) : (row.width - GAP * (fit - 1)) / fit;

  return (
    <View style={[styles.shelf, compact && { padding: 8, gap: 6 }]}>
      <View style={styles.shelfHeader}>
        <Text style={styles.section}>{title}</Text>
        <Text style={styles.shelfCount}>
          {items.length} {items.length === 1 ? 'item' : 'items'}
          {overflows ? '  ·  swipe for more ›' : ''}
        </Text>
      </View>
      <View style={{ flex: 1 }} onLayout={(e: LayoutChangeEvent) => setRow(e.nativeEvent.layout)}>
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
              contentContainerStyle={{ gap: GAP }}
            >
              {items.map(({ item, flag, note }) => (
                <InventoryTile
                  key={item.product_id}
                  item={item}
                  width={tileW}
                  height={row.height}
                  flag={flag}
                  note={note}
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
function rankItems(inventory: InventoryEntry[]): Ranked[] {
  return inventory
    .map((item): Ranked => {
      const d = item.expires_in_days;
      if (d == null) return { item, flag: null };
      const flag: TileFlag = d <= DANGER_DAYS ? 'danger' : d <= WARN_DAYS ? 'warn' : null;
      return { item, flag, note: expiryText(d, item.expiry_estimated) };
    })
    .sort(
      (a, b) =>
        (a.item.expires_in_days ?? Infinity) - (b.item.expires_in_days ?? Infinity) ||
        a.item.name.localeCompare(b.item.name),
    );
}

type Row = { key: string; title: string; empty: string; items: Ranked[] };

/**
 * Two rows, both always shown: what's on the weighed shelf, and everything
 * else in the fridge. Pantry items aren't in the fridge, so they're left off.
 */
function groupRows(ranked: Ranked[]): Row[] {
  const inFridge = ranked.filter((r) => r.item.location === 'fridge');
  return [
    {
      key: 'shelf',
      title: 'Shelf',
      empty: 'Empty — put something on the shelf.',
      items: inFridge.filter((r) => r.item.shelf === WEIGHED_SHELF),
    },
    {
      key: 'rest',
      title: 'Rest of the fridge',
      empty: 'Nothing else in the fridge.',
      items: inFridge.filter((r) => r.item.shelf !== WEIGHED_SHELF),
    },
  ];
}

function ItemModal({ item, onClose }: { item: InventoryEntry; onClose: () => void }) {
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
  const expiresColor = d == null ? undefined : d <= DANGER_DAYS ? colors.danger : d <= WARN_DAYS ? colors.warn : undefined;
  return (
    <KioskModal visible title={item.name} onClose={onClose}>
      <View style={styles.stats}>
        <Stat label="In the fridge" value={formatGrams(item.grams)} />
        <Stat
          label={item.expiry_estimated ? 'Goes bad (estimate)' : 'Goes bad'}
          value={d == null ? '—' : expiryText(d, item.expiry_estimated).replace(/^Expires /, '')}
          color={expiresColor}
        />
        <Stat label="Runs out" value={item.days_left != null ? `${item.days_left.toFixed(1)} days` : '—'} />
      </View>
      {usage && (
        <>
          <Text style={styles.muted}>How much you&apos;ve used, last two weeks</Text>
          <UsageChart dailyUsage={usage.daily_usage_g} days={14} height={110} />
        </>
      )}
    </KioskModal>
  );
}

function Stat({ label, value, color }: { label: string; value: string; color?: string }) {
  const colors = useColors();
  const styles = useMemo(() => makeStyles(colors), [colors]);
  return (
    <View style={{ alignItems: 'center', flex: 1, gap: 4 }}>
      <Text style={{ color: color ?? colors.text, fontSize: 26, fontWeight: '700', textAlign: 'center' }}>{value}</Text>
      <Text style={styles.muted}>{label}</Text>
    </View>
  );
}

const makeStyles = (colors: Palette) =>
  StyleSheet.create({
    screen: { flex: 1, backgroundColor: colors.bg },
    body: { flex: 1, flexDirection: 'row', padding: 14, gap: 14 },
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
    shelfHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'baseline', paddingHorizontal: 4 },
    section: { color: colors.muted, fontSize: 13, fontWeight: '700', letterSpacing: 1, textTransform: 'uppercase' },
    shelfCount: { color: colors.muted, fontSize: 13 },
    emptyShelf: { flex: 1, alignItems: 'center', justifyContent: 'center' },
    muted: { color: colors.muted, fontSize: 14 },
    stats: { flexDirection: 'row', gap: 8 },
    offline: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: 12 },
    offlineText: { color: colors.muted, fontSize: 20 },
  });
