/**
 * The fridge-door touchscreen. Landscape, glanceable from across the kitchen,
 * tap-only (no keyboard on a fridge). Built for 7" panels at 1024x600 or
 * 800x480; on a desktop browser it renders inside a simulated panel (see
 * ScreenSimulator). Open http://<backend>:8000/kiosk in a full-screen browser
 * (see pi_node/kiosk/).
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
import { averagePerDay, UsageChart } from '@/components/UsageChart';
import { api, type Alert, type InventoryEntry, type ProductUsage } from '@/lib/api';
import { formatGrams, palettes, ThemeContext, useColors, type Palette, type ThemeMode } from '@/lib/theme';
import { shortDate } from '@/lib/time';
import { useApi } from '@/lib/useApi';

const POLL_MS = 3000;
/** Recipes only change when the inventory does; no need to poll as often. */
const RECIPE_POLL_MS = 30_000;
const GAP = 10;
/** The one shelf with a scale under it (pi_node HX711_PINS); the rest of the fridge isn't weighed. */
const WEIGHED_SHELF = 0;
/** Tiles narrower than this get cramped names; fewer, wider tiles show instead. */
const MIN_TILE_W = 150;
/** When a shelf scrolls, this much of the next tile peeks in to show there's more. */
const PEEK = 0.4;
/** Below this panel width (the 800x480 screen) everything tightens up. */
const COMPACT_W = 900;
const LOW_DAYS = 2;
const THEME_KEY = 'refridge.kiosk.theme';
const URGENT: Alert['reason'][] = ['staple_out', 'expiring_soon', 'fridge_temp_high'];

/** "expires 2026-11-08" -> "expires tomorrow": short enough to fit on a tile. */
const friendly = (detail: string) => detail.replace(/\d{4}-\d{2}-\d{2}/, (iso) => shortDate(iso));

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
type Ranked = { item: InventoryEntry; flag: TileFlag; note?: string; rank: number };

function KioskScreen({ mode, onToggleTheme }: { mode: ThemeMode; onToggleTheme: () => void }) {
  const colors = useColors();
  const styles = useMemo(() => makeStyles(colors), [colors]);

  const summary = useApi(api.summary, POLL_MS);
  const reviews = useApi(api.review, POLL_MS);
  const common = useApi(() => api.commonProducts(8));
  const recipes = useApi(() => api.suggestedRecipes(2), RECIPE_POLL_MS);

  const [screenW, setScreenW] = useState(0);
  const [selectedProduct, setSelectedProduct] = useState<number | null>(null);

  const s = summary.data;
  const compact = screenW > 0 && screenW < COMPACT_W;
  const openReviews = reviews.data ?? [];
  const alerts = useMemo(() => s?.alerts ?? [], [s?.alerts]);
  const suggestions = recipes.data ?? [];
  const showSide = openReviews.length > 0 || alerts.length > 0 || suggestions.length > 0;
  const shelves = useMemo(() => groupRows(rankItems(s?.inventory ?? [], alerts)), [s?.inventory, alerts]);

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
                  onOpen={setSelectedProduct}
                />
              ))}
          </View>

          {showSide && (
            <ScrollView style={{ width: compact ? 220 : 270, flexGrow: 0 }} contentContainerStyle={{ gap: compact ? 10 : 12 }}>
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
              {alerts.length > 0 && (
                <View style={styles.panel}>
                  <Text style={styles.panelTitle}>Heads up</Text>
                  {alerts.slice(0, 5).map((a, i) => (
                    <View key={`${a.reason}-${a.product_id}-${i}`} style={styles.alertRow}>
                      <View style={[styles.dot, { backgroundColor: URGENT.includes(a.reason) ? colors.danger : colors.warn }]} />
                      <Text style={styles.alertText} numberOfLines={2}>
                        <Text style={{ fontWeight: '700' }}>{a.product_name}</Text> · {friendly(a.detail)}
                      </Text>
                    </View>
                  ))}
                </View>
              )}
              {suggestions.length > 0 && (
                <View style={styles.panel}>
                  <Text style={styles.panelTitle}>Recipe ideas</Text>
                  {suggestions.map((r) => (
                    <View key={r.name} style={styles.recipeRow}>
                      <FontAwesome name="cutlery" size={16} color={colors.accent} style={{ marginTop: 3, width: 18 }} />
                      <View style={{ flex: 1 }}>
                        <Text style={styles.recipeName} numberOfLines={2}>
                          {r.name}
                        </Text>
                        <Text style={styles.recipeUses} numberOfLines={2}>
                          {r.uses.map((u, i) => (
                            <Text key={u} style={r.uses_soon.includes(u) ? { color: colors.warn, fontWeight: '700' } : undefined}>
                              {i > 0 ? ', ' : ''}
                              {u}
                            </Text>
                          ))}
                        </Text>
                      </View>
                    </View>
                  ))}
                </View>
              )}
            </ScrollView>
          )}
        </View>
      )}

      {selectedProduct != null && <ProductModal productId={selectedProduct} onClose={() => setSelectedProduct(null)} />}
    </View>
  );
}

/** One shelf: a row of tiles you swipe sideways, most urgent on the left. */
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
  onOpen: (productId: number) => void;
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
                  onPress={() => onOpen(item.product_id)}
                />
              ))}
            </ScrollView>
          )
        )}
      </View>
    </View>
  );
}

/**
 * Priority, highest first: urgent alerts (out of a staple, expiring), then
 * other alerts and items running low, then everything else; ties go to
 * whichever runs out soonest.
 */
function rankItems(inventory: InventoryEntry[], alerts: Alert[]): Ranked[] {
  const byProduct = new Map<number, Alert>();
  for (const a of alerts) {
    if (a.product_id == null) continue;
    const prev = byProduct.get(a.product_id);
    if (!prev || (URGENT.includes(a.reason) && !URGENT.includes(prev.reason))) byProduct.set(a.product_id, a);
  }
  return inventory
    .map((item): Ranked => {
      const alert = byProduct.get(item.product_id);
      if (alert) {
        const urgent = URGENT.includes(alert.reason);
        return { item, flag: urgent ? 'danger' : 'warn', note: friendly(alert.detail), rank: urgent ? 0 : 1 };
      }
      if (item.days_left != null && item.days_left <= LOW_DAYS) return { item, flag: 'warn', rank: 1 };
      return { item, flag: null, rank: 2 };
    })
    .sort((a, b) => a.rank - b.rank || (a.item.days_left ?? Infinity) - (b.item.days_left ?? Infinity));
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

function ProductModal({ productId, onClose }: { productId: number; onClose: () => void }) {
  const colors = useColors();
  const styles = useMemo(() => makeStyles(colors), [colors]);
  const [usage, setUsage] = useState<ProductUsage | null>(null);
  useEffect(() => {
    let cancelled = false;
    api
      .usage(productId)
      .then((u) => !cancelled && setUsage(u))
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [productId]);

  return (
    <KioskModal visible title={usage?.name ?? '…'} onClose={onClose}>
      {usage && (
        <>
          <View style={styles.stats}>
            <Stat label="On hand" value={formatGrams(usage.on_hand_g)} />
            <Stat label="Days left" value={usage.days_left != null ? usage.days_left.toFixed(1) : '—'} />
            <Stat label="Per day" value={formatGrams(averagePerDay(usage.daily_usage_g, 14))} />
          </View>
          <Text style={styles.muted}>Last two weeks</Text>
          <UsageChart dailyUsage={usage.daily_usage_g} days={14} height={110} />
        </>
      )}
    </KioskModal>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  const colors = useColors();
  const styles = useMemo(() => makeStyles(colors), [colors]);
  return (
    <View style={{ alignItems: 'center', flex: 1 }}>
      <Text style={{ color: colors.text, fontSize: 28, fontWeight: '700' }}>{value}</Text>
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
    panel: { backgroundColor: colors.card, borderColor: colors.border, borderWidth: 1, borderRadius: 16, padding: 12, gap: 10 },
    panelTitle: { color: colors.muted, fontSize: 13, fontWeight: '700', letterSpacing: 1, textTransform: 'uppercase' },
    alertRow: { flexDirection: 'row', alignItems: 'center', gap: 10 },
    dot: { width: 10, height: 10, borderRadius: 5 },
    alertText: { color: colors.text, fontSize: 15, flex: 1 },
    recipeRow: { flexDirection: 'row', gap: 10 },
    recipeName: { color: colors.text, fontSize: 16, fontWeight: '700' },
    recipeUses: { color: colors.muted, fontSize: 13, marginTop: 2 },
    stats: { flexDirection: 'row' },
    offline: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: 12 },
    offlineText: { color: colors.muted, fontSize: 20 },
  });
