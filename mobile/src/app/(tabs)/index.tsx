import FontAwesome from '@expo/vector-icons/FontAwesome';
import { Link, Stack, router } from 'expo-router';
import { Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';

import { FillBar } from '@/components/FillBar';
import { RecipeCardView } from '@/components/recipes/RecipeCardView';
import { ErrorCard, Loading } from '@/components/States';
import { formatAmount } from '@/lib/amount';
import { api, type Alert, type InventoryEntry, type Macros, type Profile } from '@/lib/api';
import { expiryTone, goesBadText, runsOutText, urgency, type ExpiryTone } from '@/lib/expiry';
import { colors, ui } from '@/lib/theme';
import { capitalize, tripText, whenWord } from '@/lib/time';
import { useApi } from '@/lib/useApi';

const POLL_MS = 5000;

/** Soonest to go bad first; things with no date last, by name. */
function byExpiry(a: InventoryEntry, b: InventoryEntry): number {
  return (a.expires_in_days ?? Infinity) - (b.expires_in_days ?? Infinity) || a.name.localeCompare(b.name);
}

function alertText(alert: Alert, entry: InventoryEntry | undefined): string {
  const days = alert.days;
  switch (alert.reason) {
    case 'expiring_soon':
      if (entry) return goesBadText(entry) ?? alert.detail;
      return days == null ? alert.detail : days < 0 ? 'Expired' : `Goes bad ${whenWord(days)}`;
    case 'low_days_left':
      return days == null ? alert.detail : runsOutText({ days_left: days, expires_in_days: null });
    case 'low_fraction':
      return entry ? `Only ${formatAmount(entry.grams, entry.unit, entry.grams_per_unit, entry.name)} left` : 'Running low';
    case 'staple_out':
      return "You're out";
    default:
      return alert.detail;
  }
}

export default function Home() {
  const summary = useApi(api.summary, POLL_MS);
  const profile = useApi(api.profile);
  // No query: the engine searches by what's in the fridge, expiring items first.
  const ideas = useApi(api.tonight, undefined, 'tonight');

  if (summary.loading && !summary.data) return <Loading />;

  const s = summary.data;
  const inventory = s ? [...s.inventory].sort(byExpiry) : [];
  const entryFor = (productId: number | null) => s?.inventory.find((e) => e.product_id === productId);

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
            <Pressable
              onPress={() => router.push('/add')}
              hitSlop={12}
              style={{ paddingHorizontal: 16 }}
              accessibilityRole="button"
              accessibilityLabel="Add an item"
            >
              <FontAwesome name="plus" size={20} color={colors.accent} />
            </Pressable>
          ),
        }}
      />

      {summary.error && <ErrorCard message={summary.error} />}

      {s && s.review_queue_count > 0 && (
        <Link href="/review" asChild>
          <Pressable style={StyleSheet.flatten([ui.card, styles.reviewBanner])}>
            <Text style={ui.text}>
              {s.review_queue_count === 1 ? '1 fridge change needs' : `${s.review_queue_count} fridge changes need`} an answer
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
              <AlertRow
                key={`${a.product_id}-${a.reason}-${i}`}
                alert={a}
                text={alertText(a, entryFor(a.product_id))}
                tone={alertTone(entryFor(a.product_id))}
              />
            ))
          )}

          <View style={[ui.row, { justifyContent: 'space-between' }]}>
            <Text style={ui.h2}>Cook tonight</Text>
            <Link href="/chat" style={{ color: colors.accent, fontSize: 14 }}>
              Ask for something else →
            </Link>
          </View>
          {ideas.data && ideas.data.length > 0 ? (
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 10 }}>
              {ideas.data.map((r) => (
                <RecipeCardView
                  key={r.id}
                  card={r}
                  onPress={() => router.push({ pathname: '/recipe/[id]', params: { id: r.id } })}
                />
              ))}
            </ScrollView>
          ) : (
            <View style={ui.card}>
              <Text style={ui.muted}>{ideas.loading ? 'Finding recipes for what you have…' : 'Add a few items to get ideas.'}</Text>
            </View>
          )}

          {s.conditions?.temperature_c != null && (
            <View style={[ui.card, ui.row, { justifyContent: 'space-between' }]}>
              <Text style={ui.muted}>Fridge</Text>
              <Text style={ui.text}>
                {`${s.conditions.temperature_c.toFixed(1)}°C`}
                {s.conditions.humidity_pct != null ? `  ·  ${Math.round(s.conditions.humidity_pct)}% RH` : ''}
              </Text>
            </View>
          )}

          <Link href="/grocery" asChild>
            <Pressable style={StyleSheet.flatten([ui.card, styles.linkCard])}>
              <View style={{ flex: 1, gap: 2 }}>
                <Text style={[ui.text, { fontWeight: '600' }]}>Grocery list</Text>
                <Text style={ui.muted}>{tripText(s.next_trip_date, s.covers_until)}</Text>
              </View>
              <FontAwesome name="chevron-right" color={colors.muted} />
            </Pressable>
          </Link>

          <Text style={ui.h2}>Today</Text>
          <IntakeCard totals={s.today_intake.totals} profile={profile.data} />

          <Text style={ui.h2}>Inventory</Text>
          <View style={ui.card}>
            {inventory.length === 0 ? (
              <Text style={ui.muted}>Nothing tracked yet. Add something with the + button.</Text>
            ) : (
              inventory.map((item, i) => <InventoryRow key={item.product_id} item={item} last={i === inventory.length - 1} />)
            )}
          </View>
        </>
      )}
    </ScrollView>
  );
}

/** Same color the item gets everywhere else; an alert with no item (fridge too warm, out of a staple) is amber. */
const alertTone = (entry: InventoryEntry | undefined): ExpiryTone => (entry ? urgency(entry) : 'warn');

function AlertRow({ alert, text, tone }: { alert: Alert; text: string; tone: ExpiryTone }) {
  const style = StyleSheet.flatten([ui.card, styles.alert, { borderLeftColor: tone ? colors[tone] : colors.border }]);
  const body = (
    <Text style={[ui.text, { flex: 1 }]}>
      <Text style={{ fontWeight: '700' }}>{alert.product_name}</Text> · {text}
    </Text>
  );
  if (alert.product_id == null) return <View style={style}>{body}</View>;
  return (
    <Link href={{ pathname: '/item/[id]', params: { id: alert.product_id } }} asChild>
      <Pressable style={style}>
        {body}
        <FontAwesome name="chevron-right" color={colors.muted} />
      </Pressable>
    </Link>
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

// Children of <Link asChild> must get one style object — expo-router throws on style arrays.
function InventoryRow({ item, last }: { item: InventoryEntry; last: boolean }) {
  const goesBad = goesBadText(item);
  const dateTone = expiryTone(item.expires_in_days);
  return (
    <Link href={{ pathname: '/item/[id]', params: { id: item.product_id } }} asChild>
      <Pressable style={StyleSheet.flatten([styles.invRow, !last && ui.divider])}>
        <View style={{ flex: 1, gap: 2 }}>
          <Text style={[ui.text, { fontWeight: '600' }]}>{item.name}</Text>
          {goesBad && <Text style={[ui.text, { fontSize: 13 }, dateTone && { color: colors[dateTone] }]}>{goesBad}</Text>}
          <Text style={ui.muted}>{runsOutText(item)}</Text>
        </View>
        <View style={{ width: 96, alignItems: 'flex-end' }}>
          <Text style={ui.text}>{capitalize(formatAmount(item.grams, item.unit, item.grams_per_unit, item.name))}</Text>
          {item.fill_fraction != null && <FillBar fraction={item.fill_fraction} tone={urgency(item)} />}
        </View>
      </Pressable>
    </Link>
  );
}

const styles = StyleSheet.create({
  alert: { borderLeftWidth: 4, flexDirection: 'row', alignItems: 'center', gap: 8 },
  reviewBanner: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', borderColor: colors.warn },
  linkCard: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  invRow: { flexDirection: 'row', alignItems: 'center', paddingVertical: 10, gap: 12 },
});
