import FontAwesome from '@expo/vector-icons/FontAwesome';
import { Link, Stack, router } from 'expo-router';
import { Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';

import { FillBar } from '@/components/FillBar';
import { RecipeCardView, useRecipeCardStyles } from '@/components/recipes/RecipeCardView';
import { ErrorCard, Loading } from '@/components/States';
import { TodayCard } from '@/components/TodayCard';
import { formatAmount } from '@/lib/amount';
import { api, type Alert, type InventoryEntry, type RecipeCard } from '@/lib/api';
import { expiryTone, goesBadText, keepsText, runsOutText, urgency, type ExpiryTone } from '@/lib/expiry';
import { makeStyles, useColors, useUi } from '@/lib/theme';
import { capitalize, monthName, tripText, whenWord } from '@/lib/time';
import { useApi } from '@/lib/useApi';

const POLL_MS = 5000;
/** Fewer Cook tonight ideas than this and the row offers to ask for more. */
const ENOUGH_IDEAS = 2;
const MORE_IDEAS_PROMPT = 'What can I make without shopping?';

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
      return days == null ? alert.detail : `Runs out ${whenWord(days)}`;
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
  const ui = useUi();
  const styles = useStyles();
  const c = useColors();

  if (summary.loading && !summary.data) return <Loading />;

  const s = summary.data;
  const sorted = s ? [...s.inventory].sort(byExpiry) : [];
  const inventory = sorted.filter((e) => e.location !== 'freezer');
  const freezer = sorted.filter((e) => e.location === 'freezer');
  const leftovers = inventory.filter((e) => e.leftovers);
  // Alerts are about what's outside the freezer.
  const entryFor = (productId: number | null) => inventory.find((e) => e.product_id === productId);
  const proteinFirst = profile.data?.protein_mode ?? false;

  return (
    <ScrollView
      style={ui.screen}
      contentContainerStyle={ui.content}
      refreshControl={<RefreshControl refreshing={false} onRefresh={summary.reload} tintColor={c.accent} />}
    >
      <Stack.Screen options={{ headerRight: () => <AddFoodButton /> }} />

      {summary.error && <ErrorCard message={summary.error} />}

      {s && s.review_queue_count > 0 && (
        <Link href="/review" asChild>
          <Pressable style={styles.reviewBanner}>
            <Text style={[ui.text, { flex: 1 }]}>
              {s.review_queue_count === 1 ? '1 fridge change needs' : `${s.review_queue_count} fridge changes need`} an answer
            </Text>
            <FontAwesome name="chevron-right" color={c.warn} />
          </Pressable>
        </Link>
      )}

      {s && (
        <>
          <Text style={ui.h2}>Alerts</Text>
          {s.alerts.length === 0 ? (
            <View style={ui.card}>
              <Text style={ui.detail}>Nothing needs attention.</Text>
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

          <Text style={ui.h2}>Today</Text>
          <TodayCard totals={s.today_intake.totals} mealCount={s.today_intake.meal_count} profile={profile.data} />

          <Text style={ui.h2}>Cook tonight</Text>
          {proteinFirst && <Text style={[ui.muted, styles.caption]}>Highest protein first</Text>}
          <CookTonight leftovers={leftovers} ideas={ideas.data} loading={ideas.loading} proteinFirst={proteinFirst} />

          {s.conditions?.temperature_c != null && (
            <View style={[ui.card, ui.row, { justifyContent: 'space-between' }]}>
              <Text style={ui.detail}>Fridge</Text>
              <Text style={ui.text}>
                {`${s.conditions.temperature_c.toFixed(1)}°C`}
                {s.conditions.humidity_pct != null ? `  ·  ${Math.round(s.conditions.humidity_pct)}% RH` : ''}
              </Text>
            </View>
          )}

          <Link href="/grocery" asChild>
            <Pressable style={styles.linkCard}>
              <View style={{ flex: 1, gap: 4 }}>
                <Text style={[ui.text, { fontWeight: '600' }]}>Grocery list</Text>
                <Text style={ui.detail}>{tripText(s.next_trip_date, s.next_trip_in_days, s.covers_until)}</Text>
              </View>
              <FontAwesome name="chevron-right" color={c.textSecondary} />
            </Pressable>
          </Link>

          <Text style={ui.h2}>Inventory</Text>
          <View style={ui.card}>
            {inventory.length === 0 ? (
              <Text style={ui.detail}>Nothing tracked yet. Add something with Add food.</Text>
            ) : (
              inventory.map((item, i) => <InventoryRow key={item.product_id} item={item} last={i === inventory.length - 1} />)
            )}
          </View>

          {freezer.length > 0 && (
            <>
              <Text style={ui.h2}>Freezer</Text>
              <View style={ui.card}>
                {freezer.map((item, i) => (
                  <InventoryRow key={item.product_id} item={item} last={i === freezer.length - 1} />
                ))}
              </View>
            </>
          )}
        </>
      )}
    </ScrollView>
  );
}

function AddFoodButton() {
  const styles = useStyles();
  const c = useColors();
  return (
    <Pressable
      onPress={() => router.push('/add')}
      style={({ pressed }) => [styles.addButton, pressed && { opacity: 0.6 }]}
      accessibilityRole="button"
    >
      <FontAwesome name="plus" size={16} color={c.accent} />
      <Text style={styles.addLabel}>Add food</Text>
    </Pressable>
  );
}

/**
 * Leftovers first (they're the answer to "what's for supper"), then recipes you can make now,
 * then ones needing 1 or 2 things. With fewer than 2 recipes, it ends with "Ask for more ideas".
 */
function CookTonight({
  leftovers,
  ideas,
  loading,
  proteinFirst,
}: {
  leftovers: InventoryEntry[];
  ideas: RecipeCard[] | null;
  loading: boolean;
  proteinFirst: boolean;
}) {
  const ui = useUi();
  const styles = useStyles();
  const recipes = ideas ?? [];
  if (loading && !ideas && leftovers.length === 0) {
    return (
      <View style={ui.card}>
        <Text style={ui.detail}>Finding recipes for what you have…</Text>
      </View>
    );
  }
  return (
    <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.carousel}>
      {leftovers.map((e) => (
        <LeftoversCard key={e.product_id} entry={e} />
      ))}
      {recipes.map((r) => (
        <RecipeCardView
          key={r.id}
          card={r}
          proteinFirst={proteinFirst}
          onPress={() => router.push({ pathname: '/recipe/[id]', params: { id: r.id } })}
        />
      ))}
      {recipes.length < ENOUGH_IDEAS && (
        <Pressable
          onPress={() => router.push({ pathname: '/chat', params: { ask: MORE_IDEAS_PROMPT } })}
          style={styles.moreIdeas}
          accessibilityRole="button"
        >
          <Text style={styles.link}>Ask for more ideas</Text>
        </Pressable>
      )}
    </ScrollView>
  );
}

/** "Eat your leftovers" / Greek Stuffed Chicken / 3 servings · keeps until Tuesday. Opens the item, where eating one is the first action. */
function LeftoversCard({ entry }: { entry: InventoryEntry }) {
  const styles = useRecipeCardStyles();
  const ui = useUi();
  return (
    <Pressable
      onPress={() => router.push({ pathname: '/item/[id]', params: { id: entry.product_id } })}
      style={({ pressed }) => [styles.card, pressed && { opacity: 0.75 }]}
      accessibilityRole="button"
    >
      <View style={styles.body}>
        <Text style={[ui.h2, { marginTop: 0 }]}>Eat your leftovers</Text>
        <Text style={ui.text}>{entry.name.replace(/ leftovers$/, '')}</Text>
        <Text style={styles.detail}>{keepsText(entry)}</Text>
      </View>
    </Pressable>
  );
}

/** Same color the item gets everywhere else; an alert with no item (fridge too warm, out of a staple) is amber. */
const alertTone = (entry: InventoryEntry | undefined): ExpiryTone => (entry ? urgency(entry) : 'warn');

function AlertRow({ alert, text, tone }: { alert: Alert; text: string; tone: ExpiryTone }) {
  const ui = useUi();
  const styles = useStyles();
  const c = useColors();
  const style = StyleSheet.flatten([styles.alert, { borderLeftColor: tone ? c[tone] : c.border }]);
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
        <FontAwesome name="chevron-right" color={c.textSecondary} />
      </Pressable>
    </Link>
  );
}

/**
 * A freezer row says how long it keeps; leftovers say how many servings and until when; anything
 * else when it goes bad, and when it runs out (or how much you'll likely throw away).
 */
function rowLines(item: InventoryEntry): { goesBad: string | null; tone: ExpiryTone; second: string | null } {
  if (item.location === 'freezer') {
    const date = item.soonest_batch?.expiration_date;
    return { goesBad: date ? `Good until around ${monthName(date)}` : null, tone: null, second: null };
  }
  if (item.leftovers) return { goesBad: keepsText(item), tone: expiryTone(item.expires_in_days, true), second: null };
  return { goesBad: goesBadText(item), tone: expiryTone(item.expires_in_days), second: runsOutText(item) };
}

// Children of <Link asChild> must get one style object — expo-router throws on style arrays.
function InventoryRow({ item, last }: { item: InventoryEntry; last: boolean }) {
  const ui = useUi();
  const styles = useStyles();
  const c = useColors();
  const { goesBad, tone, second } = rowLines(item);
  return (
    <Link href={{ pathname: '/item/[id]', params: { id: item.product_id } }} asChild>
      <Pressable style={StyleSheet.flatten([styles.invRow, !last && ui.divider])}>
        <View style={{ flex: 1, gap: 2 }}>
          <Text style={[ui.text, { fontWeight: '600' }]}>{item.name}</Text>
          {goesBad && <Text style={[ui.detail, tone && { color: c[tone] }]}>{goesBad}</Text>}
          {second && <Text style={ui.detail}>{second}</Text>}
        </View>
        {!item.leftovers && (
          <View style={styles.amount}>
            <Text style={[ui.text, { textAlign: 'right' }]}>
              {capitalize(formatAmount(item.grams, item.unit, item.grams_per_unit, item.name))}
            </Text>
            {item.fill_fraction != null && item.location !== 'freezer' && <FillBar fraction={item.fill_fraction} tone={urgency(item)} />}
          </View>
        )}
      </Pressable>
    </Link>
  );
}

const useStyles = makeStyles((c, size) => ({
  alert: {
    backgroundColor: c.card,
    borderColor: c.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 16,
    borderLeftWidth: 4,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  reviewBanner: {
    backgroundColor: c.card,
    borderColor: c.warn,
    borderWidth: 1,
    borderRadius: 12,
    padding: 16,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  linkCard: {
    backgroundColor: c.card,
    borderColor: c.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 16,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  invRow: { flexDirection: 'row', alignItems: 'center', paddingVertical: 12, gap: 12 },
  amount: { width: size(96), alignItems: 'flex-end' },
  caption: { marginTop: -4 },
  carousel: { gap: 12, alignItems: 'flex-start' },
  moreIdeas: { minHeight: 44, justifyContent: 'center', paddingHorizontal: 8 },
  link: { color: c.accent, fontSize: size(15), lineHeight: size(20), fontWeight: '600' },
  addButton: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    minHeight: 44,
    paddingHorizontal: 12,
    marginRight: 8,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: c.accent,
  },
  addLabel: { color: c.accent, fontSize: size(15), fontWeight: '600' },
}));
