/**
 * The fridge-door touchscreen. Landscape, glanceable from across the kitchen,
 * tap-only (no keyboard on a fridge). Designed at 1024x600; scales to
 * 800x480 and 1280x800 panels. Open http://<backend>:8000/kiosk in a
 * full-screen browser (see pi_node/kiosk/).
 */
import FontAwesome from '@expo/vector-icons/FontAwesome';
import { Stack } from 'expo-router';
import { useEffect, useState, type ReactNode } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View, type LayoutChangeEvent } from 'react-native';

import { FillBar } from '@/components/FillBar';
import { ActivityFeed } from '@/components/kiosk/ActivityFeed';
import { InventoryTile } from '@/components/kiosk/InventoryTile';
import { KioskHeader } from '@/components/kiosk/KioskHeader';
import { KioskModal } from '@/components/kiosk/KioskModal';
import { ReviewPrompt } from '@/components/kiosk/ReviewPrompt';
import { averagePerDay, UsageChart } from '@/components/UsageChart';
import { api, type Alert, type ProductUsage, type Profile } from '@/lib/api';
import { colors, formatGrams } from '@/lib/theme';
import { useApi } from '@/lib/useApi';

const POLL_MS = 3000;
const GRID_GAP = 12;
const MEAL_PROMPT =
  "Suggest one quick meal I can make right now from what's in my fridge, using anything expiring soon first. " +
  'Keep it short: the dish name, ingredients with grams, and its macros.';
const URGENT: Alert['reason'][] = ['staple_out', 'expiring_soon', 'fridge_temp_high'];

export default function Kiosk() {
  const summary = useApi(api.summary, POLL_MS);
  const reviews = useApi(api.review, POLL_MS);
  const activity = useApi(() => api.activity(6), POLL_MS);
  const common = useApi(() => api.commonProducts(8));
  const profile = useApi(api.profile);

  const [gridWidth, setGridWidth] = useState(0);
  const [selectedProduct, setSelectedProduct] = useState<number | null>(null);
  const [mealOpen, setMealOpen] = useState(false);

  const s = summary.data;
  const columns = gridWidth >= 640 ? 4 : 3;
  const tileWidth = gridWidth ? (gridWidth - GRID_GAP * (columns - 1)) / columns : 0;
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
        <View style={styles.body}>
          <ScrollView style={{ flex: 2 }} contentContainerStyle={{ gap: 14 }}>
            {openReviews.length > 0 && (
              <ReviewPrompt
                key={openReviews[openReviews.length - 1].id}
                review={openReviews[openReviews.length - 1]}
                remaining={openReviews.length}
                commonNames={(common.data ?? []).map((p) => p.name)}
                onResolved={() => {
                  reviews.reload();
                  summary.reload();
                  activity.reload();
                }}
              />
            )}

            <Text style={styles.section}>In the fridge</Text>
            <View style={styles.grid} onLayout={(e: LayoutChangeEvent) => setGridWidth(e.nativeEvent.layout.width)}>
              {tileWidth > 0 &&
                s?.inventory.map((item) => (
                  <InventoryTile key={item.product_id} item={item} width={tileWidth} onPress={() => setSelectedProduct(item.product_id)} />
                ))}
              {s?.inventory.length === 0 && <Text style={styles.muted}>Empty — put something in.</Text>}
            </View>
          </ScrollView>

          <ScrollView style={{ flex: 1 }} contentContainerStyle={{ gap: 14 }}>
            {s && s.alerts.length > 0 && (
              <Panel title="Heads up">
                {s.alerts.slice(0, 4).map((a, i) => (
                  <View key={`${a.reason}-${a.product_id}-${i}`} style={styles.alertRow}>
                    <View style={[styles.dot, { backgroundColor: URGENT.includes(a.reason) ? colors.danger : colors.warn }]} />
                    <Text style={styles.alertText} numberOfLines={2}>
                      <Text style={{ fontWeight: '700' }}>{a.product_name}</Text> · {a.detail}
                    </Text>
                  </View>
                ))}
              </Panel>
            )}

            {s && (
              <Panel title="Today">
                <Progress label="Calories" value={s.today_intake.totals.calories} goal={profile.data?.daily_calories} unit="kcal" />
                <Progress label="Protein" value={s.today_intake.totals.protein_g} goal={profile.data?.daily_protein_g} unit="g" />
              </Panel>
            )}

            <Panel title="Recently">
              <ActivityFeed items={activity.data ?? []} />
            </Panel>

            <Pressable onPress={() => setMealOpen(true)} style={({ pressed }) => [styles.mealButton, pressed && { opacity: 0.8 }]}>
              <FontAwesome name="cutlery" size={22} color={colors.onAccent} />
              <Text style={styles.mealButtonText}>What can I cook?</Text>
            </Pressable>
          </ScrollView>
        </View>
      )}

      {selectedProduct != null && <ProductModal productId={selectedProduct} onClose={() => setSelectedProduct(null)} />}
      {mealOpen && <MealModal onClose={() => setMealOpen(false)} />}
    </View>
  );
}

function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <View style={styles.panel}>
      <Text style={styles.panelTitle}>{title}</Text>
      {children}
    </View>
  );
}

function Progress({ label, value, goal, unit }: { label: string; value: number; goal: Profile['daily_calories'] | undefined; unit: string }) {
  return (
    <View>
      <View style={styles.progressRow}>
        <Text style={styles.progressLabel}>{label}</Text>
        <Text style={styles.muted}>
          {Math.round(value || 0)}
          {goal ? ` / ${Math.round(goal)}` : ''} {unit}
        </Text>
      </View>
      {goal ? <FillBar fraction={(value || 0) / goal} /> : null}
    </View>
  );
}

function ProductModal({ productId, onClose }: { productId: number; onClose: () => void }) {
  const [usage, setUsage] = useState<ProductUsage | null>(null);
  useEffect(() => {
    let cancelled = false;
    api.usage(productId).then((u) => !cancelled && setUsage(u)).catch(() => {});
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
          <UsageChart dailyUsage={usage.daily_usage_g} days={14} height={140} />
        </>
      )}
    </KioskModal>
  );
}

function MealModal({ onClose }: { onClose: () => void }) {
  const [reply, setReply] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    api
      .chat(MEAL_PROMPT)
      .then((r) => !cancelled && setReply(r.reply))
      .catch((e) => !cancelled && setReply(`Couldn't reach the assistant: ${(e as Error).message}`));
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <KioskModal visible title="What can I cook?" onClose={onClose}>
      <Text style={styles.mealText}>{reply ?? 'Checking your fridge and goals…'}</Text>
      <Text style={styles.muted}>General wellness info, not medical advice. Open the phone app to chat or log the meal.</Text>
    </KioskModal>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <View style={{ alignItems: 'center', flex: 1 }}>
      <Text style={{ color: colors.text, fontSize: 30, fontWeight: '700' }}>{value}</Text>
      <Text style={styles.muted}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.bg },
  body: { flex: 1, flexDirection: 'row', padding: 16, gap: 16 },
  section: { color: colors.muted, fontSize: 14, fontWeight: '700', letterSpacing: 1, textTransform: 'uppercase' },
  grid: { flexDirection: 'row', flexWrap: 'wrap', gap: GRID_GAP },
  muted: { color: colors.muted, fontSize: 14 },
  panel: { backgroundColor: colors.card, borderColor: colors.border, borderWidth: 1, borderRadius: 16, padding: 14, gap: 10 },
  panelTitle: { color: colors.muted, fontSize: 13, fontWeight: '700', letterSpacing: 1, textTransform: 'uppercase' },
  alertRow: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  dot: { width: 10, height: 10, borderRadius: 5 },
  alertText: { color: colors.text, fontSize: 16, flex: 1 },
  progressRow: { flexDirection: 'row', justifyContent: 'space-between' },
  progressLabel: { color: colors.text, fontSize: 16 },
  mealButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 12,
    minHeight: 64,
    borderRadius: 16,
    backgroundColor: colors.accent,
  },
  mealButtonText: { color: colors.onAccent, fontSize: 20, fontWeight: '700' },
  mealText: { color: colors.text, fontSize: 18, lineHeight: 26 },
  stats: { flexDirection: 'row' },
  offline: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: 12 },
  offlineText: { color: colors.muted, fontSize: 20 },
});
