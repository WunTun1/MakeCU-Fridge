/**
 * The fridge-door touchscreen: what's inside, how much, and when it goes bad —
 * glanceable from across the kitchen, touch only (no typing). Recipes, chat,
 * and everything else live in the phone app. Designed at 1024x600; scales to
 * 800x480 and 1280x800 panels. Open http://<backend>:8000/kiosk full-screen
 * (see pi_node/kiosk/).
 */
import FontAwesome from '@expo/vector-icons/FontAwesome';
import { Stack } from 'expo-router';
import { useEffect, useState } from 'react';
import { ScrollView, StyleSheet, Text, View, type LayoutChangeEvent } from 'react-native';

import { InventoryTile } from '@/components/kiosk/InventoryTile';
import { KioskHeader } from '@/components/kiosk/KioskHeader';
import { KioskModal } from '@/components/kiosk/KioskModal';
import { ReviewPrompt } from '@/components/kiosk/ReviewPrompt';
import { UsageChart } from '@/components/UsageChart';
import { api, type InventoryEntry, type ProductUsage } from '@/lib/api';
import { expiryColor, expiryText } from '@/lib/expiry';
import { colors, formatGrams } from '@/lib/theme';
import { useApi } from '@/lib/useApi';

const POLL_MS = 3000;
const GRID_GAP = 12;

/** Soonest to go bad first; things with no known expiry after, alphabetically. */
function byExpiry(a: InventoryEntry, b: InventoryEntry): number {
  const da = a.expires_in_days ?? Infinity;
  const db = b.expires_in_days ?? Infinity;
  return da - db || a.name.localeCompare(b.name);
}

export default function Kiosk() {
  const summary = useApi(api.summary, POLL_MS);
  const reviews = useApi(api.review, POLL_MS);
  const common = useApi(() => api.commonProducts(8));

  const [gridWidth, setGridWidth] = useState(0);
  const [selected, setSelected] = useState<InventoryEntry | null>(null);

  const s = summary.data;
  const columns = gridWidth >= 900 ? 5 : gridWidth >= 640 ? 4 : 3;
  const tileWidth = gridWidth ? (gridWidth - GRID_GAP * (columns - 1)) / columns : 0;
  const fridge = (s?.inventory ?? []).filter((i) => i.location === 'fridge').sort(byExpiry);
  const openReviews = reviews.data ?? [];

  return (
    <View style={styles.screen}>
      <Stack.Screen options={{ headerShown: false }} />
      <KioskHeader conditions={s?.conditions ?? null} doorOpen={s?.door_open ?? false} nextTrip={s?.next_trip_date ?? null} />

      {summary.error && !s ? (
        <View style={styles.offline}>
          <FontAwesome name="plug" size={40} color={colors.muted} />
          <Text style={styles.offlineText}>Connecting to ReFridge…</Text>
        </View>
      ) : (
        <ScrollView style={{ flex: 1 }} contentContainerStyle={styles.body}>
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

          <View style={styles.grid} onLayout={(e: LayoutChangeEvent) => setGridWidth(e.nativeEvent.layout.width)}>
            {tileWidth > 0 &&
              fridge.map((item) => (
                <InventoryTile key={item.product_id} item={item} width={tileWidth} onPress={() => setSelected(item)} />
              ))}
            {s && fridge.length === 0 && <Text style={styles.empty}>The fridge is empty.</Text>}
          </View>
        </ScrollView>
      )}

      {selected && <ItemModal item={selected} onClose={() => setSelected(null)} />}
    </View>
  );
}

function ItemModal({ item, onClose }: { item: InventoryEntry; onClose: () => void }) {
  const [usage, setUsage] = useState<ProductUsage | null>(null);
  useEffect(() => {
    let cancelled = false;
    api.usage(item.product_id).then((u) => !cancelled && setUsage(u)).catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [item.product_id]);

  return (
    <KioskModal visible title={item.name} onClose={onClose}>
      <View style={styles.stats}>
        <Stat label="In the fridge" value={formatGrams(item.grams)} />
        <Stat
          label={item.expiry_estimated ? 'Goes bad (estimate)' : 'Goes bad'}
          value={item.expires_in_days == null ? '—' : expiryText(item.expires_in_days, item.expiry_estimated).replace(/^Expires /, '')}
          color={item.expires_in_days == null ? undefined : expiryColor(item.expires_in_days)}
        />
        <Stat label="Runs out" value={item.days_left != null ? `${item.days_left.toFixed(1)} days` : '—'} />
      </View>
      {usage && (
        <>
          <Text style={styles.muted}>How much you&apos;ve used, last two weeks</Text>
          <UsageChart dailyUsage={usage.daily_usage_g} days={14} height={140} />
        </>
      )}
    </KioskModal>
  );
}

function Stat({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <View style={{ alignItems: 'center', flex: 1, gap: 4 }}>
      <Text style={{ color: color ?? colors.text, fontSize: 28, fontWeight: '700', textAlign: 'center' }}>{value}</Text>
      <Text style={styles.muted}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.bg },
  body: { padding: 16, gap: 14 },
  grid: { flexDirection: 'row', flexWrap: 'wrap', gap: GRID_GAP },
  empty: { color: colors.muted, fontSize: 20, padding: 24 },
  muted: { color: colors.muted, fontSize: 14 },
  stats: { flexDirection: 'row', gap: 8 },
  offline: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: 12 },
  offlineText: { color: colors.muted, fontSize: 20 },
});
