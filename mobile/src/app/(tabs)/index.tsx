import FontAwesome from '@expo/vector-icons/FontAwesome';
import { Link, Stack, router } from 'expo-router';
import { Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';

import { FillBar } from '@/components/FillBar';
import { ErrorCard, Loading } from '@/components/States';
import { api, type Alert, type InventoryEntry, type Macros, type Profile } from '@/lib/api';
import { colors, formatGrams, ui } from '@/lib/theme';
import { useApi } from '@/lib/useApi';

const POLL_MS = 5000;
const URGENT: Alert['reason'][] = ['staple_out', 'expiring_soon', 'fridge_temp_high'];

export default function Home() {
  const summary = useApi(api.summary, POLL_MS);
  const profile = useApi(api.profile);

  if (summary.loading && !summary.data) return <Loading />;

  const s = summary.data;
  return (
    <ScrollView
      style={ui.screen}
      contentContainerStyle={ui.content}
      refreshControl={
        <RefreshControl refreshing={false} onRefresh={summary.reload} tintColor={colors.accent} />
      }
    >
      <Stack.Screen
        options={{
          headerRight: () => (
            <Pressable onPress={() => router.push('/add')} hitSlop={12} style={{ paddingHorizontal: 16 }}>
              <FontAwesome name="plus" size={20} color={colors.accent} />
            </Pressable>
          ),
        }}
      />

      {summary.error && <ErrorCard message={summary.error} />}

      {s && s.review_queue_count > 0 && (
        <Link href="/review" asChild>
          <Pressable style={[ui.card, styles.reviewBanner]}>
            <Text style={ui.text}>
              {s.review_queue_count} fridge change{s.review_queue_count > 1 ? 's' : ''} need a quick answer
            </Text>
            <FontAwesome name="chevron-right" color={colors.warn} />
          </Pressable>
        </Link>
      )}

      {s && (
        <>
          <Text style={ui.h2}>Alerts</Text>
          {s.alerts.length === 0 ? (
            <View style={ui.card}>
              <Text style={ui.muted}>Nothing needs attention.</Text>
            </View>
          ) : (
            s.alerts.map((a, i) => (
              <View
                key={`${a.product_id}-${a.reason}-${i}`}
                style={[ui.card, styles.alert, URGENT.includes(a.reason) && { borderLeftColor: colors.danger }]}
              >
                <Text style={ui.text}>
                  <Text style={{ fontWeight: '700' }}>{a.product_name}</Text> — {a.detail}
                </Text>
              </View>
            ))
          )}

          {s.conditions && (
            <View style={[ui.card, ui.row, { justifyContent: 'space-between' }]}>
              <Text style={ui.muted}>Fridge</Text>
              <Text style={ui.text}>
                {s.conditions.temperature_c != null ? `${s.conditions.temperature_c.toFixed(1)}°C` : '—'}
                {s.conditions.humidity_pct != null ? `  ·  ${Math.round(s.conditions.humidity_pct)}% RH` : ''}
              </Text>
            </View>
          )}

          <Text style={ui.h2}>Next trip</Text>
          <View style={ui.card}>
            <Text style={ui.text}>
              {s.next_trip_date ? `Suggested: ${s.next_trip_date}` : 'No trip needed in the next two weeks.'}
            </Text>
          </View>

          <Text style={ui.h2}>Today</Text>
          <IntakeCard totals={s.today_intake.totals} profile={profile.data} />

          <Text style={ui.h2}>Inventory</Text>
          <View style={ui.card}>
            {s.inventory.length === 0 ? (
              <Text style={ui.muted}>Nothing tracked yet — add something with the + button.</Text>
            ) : (
              s.inventory.map((item, i) => (
                <InventoryRow key={item.product_id} item={item} last={i === s.inventory.length - 1} />
              ))
            )}
          </View>
        </>
      )}
    </ScrollView>
  );
}

function IntakeCard({ totals, profile }: { totals: Macros; profile: Profile | null }) {
  const rows: { label: string; value: number; goal: number | null | undefined; unit: string }[] = [
    { label: 'Calories', value: totals.calories, goal: profile?.daily_calories, unit: 'kcal' },
    { label: 'Protein', value: totals.protein_g, goal: profile?.daily_protein_g, unit: 'g' },
    { label: 'Carbs', value: totals.carbs_g, goal: profile?.daily_carbs_g, unit: 'g' },
    { label: 'Fat', value: totals.fat_g, goal: profile?.daily_fat_g, unit: 'g' },
  ];
  return (
    <View style={[ui.card, { gap: 10 }]}>
      {rows.map((r) => (
        <View key={r.label}>
          <View style={[ui.row, { justifyContent: 'space-between' }]}>
            <Text style={ui.text}>{r.label}</Text>
            <Text style={ui.muted}>
              {Math.round(r.value || 0)}
              {r.goal ? ` / ${Math.round(r.goal)}` : ''} {r.unit}
            </Text>
          </View>
          {r.goal ? <FillBar fraction={(r.value || 0) / r.goal} /> : null}
        </View>
      ))}
    </View>
  );
}

function InventoryRow({ item, last }: { item: InventoryEntry; last: boolean }) {
  return (
    <Link href={{ pathname: '/item/[id]', params: { id: item.product_id } }} asChild>
      <Pressable style={[styles.invRow, !last && ui.divider]}>
        <View style={{ flex: 1 }}>
          <Text style={ui.text}>{item.name}</Text>
          <Text style={ui.muted}>
            {item.days_left != null ? `${item.days_left.toFixed(1)} days left` : 'no usage history yet'}
          </Text>
        </View>
        <View style={{ width: 90, alignItems: 'flex-end' }}>
          <Text style={ui.text}>{formatGrams(item.grams)}</Text>
          {item.fill_fraction != null && <FillBar fraction={item.fill_fraction} />}
        </View>
      </Pressable>
    </Link>
  );
}

const styles = StyleSheet.create({
  alert: { borderLeftWidth: 4, borderLeftColor: colors.warn },
  reviewBanner: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', borderColor: colors.warn },
  invRow: { flexDirection: 'row', alignItems: 'center', paddingVertical: 10, gap: 12 },
});
