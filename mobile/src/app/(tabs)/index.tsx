import FontAwesome from "@expo/vector-icons/FontAwesome";
import { Link, router } from "expo-router";
import {
  Pressable,
  RefreshControl,
  ScrollView,
  Text,
  View,
} from "react-native";

import { InventoryRow } from "@/components/InventoryRow";
import {
  haveCaption,
  RecipeCarousel,
  type CarouselItem,
} from "@/components/RecipeCarousel";
import { ErrorCard, Loading } from "@/components/States";
import { StockDial, StockVerdict } from "@/components/StockDial";
import { TodayCard } from "@/components/TodayCard";
import {
  api,
  type BestRecipe,
  type InventoryEntry,
  type RecipeCard,
} from "@/lib/api";
import { keepsText } from "@/lib/expiry";
import { makeStyles, useColors, useUi } from "@/lib/theme";
import { tripText } from "@/lib/time";
import { useApi } from "@/lib/useApi";

const POLL_MS = 5000;
const ANALYTICS_POLL_MS = 30000;
const CAROUSEL_MAX = 8;

/** Soonest to go bad first; things with no date last, by name. */
function byExpiry(a: InventoryEntry, b: InventoryEntry): number {
  return (
    (a.expires_in_days ?? Infinity) - (b.expires_in_days ?? Infinity) ||
    a.name.localeCompare(b.name)
  );
}

/**
 * Cook tonight's row: the recipe that saves the most food you'd otherwise throw away first
 * (worked out on Tiger Data), then ones you can nearly make, then tonight's other ideas.
 */
function carouselItems(
  best: BestRecipe | null,
  ready: RecipeCard[] | null,
  tonight: RecipeCard[] | null,
): CarouselItem[] {
  const items: CarouselItem[] = [];
  const seen = new Set<number>();
  if (best?.recipe) {
    items.push({
      recipe: best.recipe,
      badge: "Best to cook now",
      caption: best.why[0] ?? haveCaption(best.recipe),
    });
    seen.add(best.recipe.id);
  }
  for (const r of [
    ...(ready ?? []),
    ...(tonight ?? []).filter((t) => !t.leftovers),
  ]) {
    if (seen.has(r.id)) continue;
    seen.add(r.id);
    items.push({ recipe: r, caption: haveCaption(r) });
  }
  return items.slice(0, CAROUSEL_MAX);
}

/** The dial up top: how stocked you are against your own normal. Tap it for the history. */
function StockCard() {
  const ui = useUi();
  const styles = useStyles();
  const c = useColors();
  const stock = useApi(api.stockScore, ANALYTICS_POLL_MS, "stock");
  const s = stock.data;
  return (
    <Link href="/stock" asChild>
      <Pressable
        style={styles.stockCard}
        accessibilityRole="button"
        accessibilityLabel="Stock score. Open the history"
      >
        {s ? (
          <>
            <StockDial score={s.score} size={220} />
            <StockVerdict score={s.score} />
            <View style={[ui.row, { gap: 6, marginTop: 4 }]}>
              {s.source === "tiger" && (
                <FontAwesome name="database" size={11} color={c.muted} />
              )}
              <Text style={ui.muted}>
                {s.source === "tiger" ? "Tiger Data · " : ""}See your stock
                history
              </Text>
              <FontAwesome name="chevron-right" size={10} color={c.muted} />
            </View>
          </>
        ) : (
          <View
            style={{ height: 190 }}
            accessibilityLabel="Loading your stock score"
          />
        )}
      </Pressable>
    </Link>
  );
}

/**
 * Home: how stocked you are (a dial), then what to cook tonight (photos that turn by
 * themselves), then today's log, the fridge, the grocery list and what you have. Alerts live
 * behind the bell, settings behind the gear.
 */
export default function Home() {
  const summary = useApi(api.summary, POLL_MS, "summary");
  const profile = useApi(api.profile);
  const best = useApi(api.bestRecipe, ANALYTICS_POLL_MS, "best");
  const ready = useApi(api.readyRecipes, ANALYTICS_POLL_MS, "ready");
  const tonight = useApi(api.tonight, POLL_MS, "tonight");
  const ui = useUi();
  const styles = useStyles();
  const c = useColors();

  if (summary.loading && !summary.data) return <Loading />;

  const s = summary.data;
  const sorted = s ? [...s.inventory].sort(byExpiry) : [];
  const inventory = sorted.filter((e) => e.location !== "freezer");
  const freezer = sorted.filter((e) => e.location === "freezer");
  const leftovers = inventory.filter((e) => e.leftovers);
  const items = carouselItems(best.data, ready.data, tonight.data);

  return (
    <ScrollView
      style={ui.screen}
      contentContainerStyle={[ui.content, { gap: 16 }]}
      refreshControl={
        <RefreshControl
          refreshing={false}
          onRefresh={summary.reload}
          tintColor={c.accent}
        />
      }
    >
      {summary.error && <ErrorCard message={summary.error} />}

      <StockCard />

      <View style={{ gap: 10 }}>
        <Text style={ui.h2}>Cook tonight</Text>
        <RecipeCarousel items={items} loading={best.loading || ready.loading} />
      </View>

      {leftovers.map((e) => (
        <Pressable
          key={e.product_id}
          onPress={() =>
            router.push({
              pathname: "/item/[id]",
              params: { id: e.product_id },
            })
          }
          style={styles.linkCard}
          accessibilityRole="button"
        >
          <View style={{ flex: 1, gap: 2 }}>
            <Text style={[ui.text, { fontWeight: "600" }]}>
              Eat your leftovers: {e.name.replace(/ leftovers$/, "")}
            </Text>
            <Text style={ui.detail}>{keepsText(e)}</Text>
          </View>
          <FontAwesome name="chevron-right" color={c.textSecondary} />
        </Pressable>
      ))}

      {s && (
        <>
          <View style={{ gap: 10 }}>
            <Text style={ui.h2}>Today</Text>
            <TodayCard
              totals={s.today_intake.totals}
              mealCount={s.today_intake.meal_count}
              profile={profile.data}
            />
          </View>

          <View style={{ gap: 10 }}>
            {s.conditions?.temperature_c != null && (
              <View
                style={[ui.card, ui.row, { justifyContent: "space-between" }]}
              >
                <Text style={ui.detail}>Fridge</Text>
                <Text style={ui.text}>
                  {`${s.conditions.temperature_c.toFixed(1)}°C`}
                  {s.conditions.humidity_pct != null
                    ? `  ·  ${Math.round(s.conditions.humidity_pct)}% humidity`
                    : ""}
                </Text>
              </View>
            )}
            <Link href="/grocery" asChild>
              <Pressable style={styles.linkCard}>
                <View style={{ flex: 1, gap: 2 }}>
                  <Text style={[ui.text, { fontWeight: "600" }]}>
                    Grocery list
                  </Text>
                  <Text style={ui.detail}>
                    {tripText(
                      s.next_trip_date,
                      s.next_trip_in_days,
                      s.covers_until,
                    )}
                  </Text>
                </View>
                <FontAwesome name="chevron-right" color={c.textSecondary} />
              </Pressable>
            </Link>
          </View>

          <View style={{ gap: 10 }}>
            <Text style={ui.h2}>In your kitchen</Text>
            <View style={[ui.card, { paddingVertical: 4 }]}>
              {inventory.length === 0 ? (
                <Text style={[ui.detail, { paddingVertical: 12 }]}>
                  Nothing tracked yet. Add food from Your fridge.
                </Text>
              ) : (
                inventory.map((item, i) => (
                  <InventoryRow
                    key={item.product_id}
                    item={item}
                    last={i === inventory.length - 1}
                    showPlace
                  />
                ))
              )}
            </View>
          </View>

          {freezer.length > 0 && (
            <View style={{ gap: 10 }}>
              <Text style={ui.h2}>Freezer</Text>
              <View style={[ui.card, { paddingVertical: 4 }]}>
                {freezer.map((item, i) => (
                  <InventoryRow
                    key={item.product_id}
                    item={item}
                    last={i === freezer.length - 1}
                  />
                ))}
              </View>
            </View>
          )}
        </>
      )}
    </ScrollView>
  );
}

const useStyles = makeStyles((c) => ({
  stockCard: {
    alignItems: "center",
    gap: 8,
    paddingVertical: 18,
    paddingHorizontal: 16,
    backgroundColor: c.card,
    borderColor: c.border,
    borderWidth: 1,
    borderRadius: 16,
  },
  linkCard: {
    backgroundColor: c.card,
    borderColor: c.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 16,
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
  },
}));
