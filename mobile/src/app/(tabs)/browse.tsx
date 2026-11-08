import FontAwesome from "@expo/vector-icons/FontAwesome";
import { Link, router } from "expo-router";
import { useState } from "react";
import {
  Pressable,
  RefreshControl,
  ScrollView,
  Text,
  View,
} from "react-native";

import { Button } from "@/components/Button";
import { ChoiceChips } from "@/components/Chips";
import { InventoryRow } from "@/components/InventoryRow";
import { SearchField } from "@/components/SearchField";
import { BAND_TEXT, bandColor, bandOf } from "@/components/StockDial";
import { ErrorCard, Loading } from "@/components/States";
import { api, type InventoryEntry } from "@/lib/api";
import { makeStyles, useColors, useUi } from "@/lib/theme";
import { useAddToGrocery } from "@/lib/useAddToGrocery";
import { useApi } from "@/lib/useApi";

const POLL_MS = 5000;
const FAB = 56;

type Sort = "soon" | "late" | "most" | "least";

const SORTS: { value: Sort; label: string }[] = [
  { value: "soon", label: "Expiring first" },
  { value: "late", label: "Expiring last" },
  { value: "most", label: "Most" },
  { value: "least", label: "Least" },
];

const dateOr = (n: number | null, none: number) => n ?? none; // no date: at the end either way
const ORDER: Record<Sort, (a: InventoryEntry, b: InventoryEntry) => number> = {
  soon: (a, b) =>
    dateOr(a.expires_in_days, Infinity) - dateOr(b.expires_in_days, Infinity) ||
    a.name.localeCompare(b.name),
  late: (a, b) =>
    dateOr(b.expires_in_days, -Infinity) -
      dateOr(a.expires_in_days, -Infinity) || a.name.localeCompare(b.name),
  most: (a, b) => b.grams - a.grams || a.name.localeCompare(b.name),
  least: (a, b) => a.grams - b.grams || a.name.localeCompare(b.name),
};

/**
 * Your fridge: everything you have in one list — how much, and the date it should go bad.
 * Tap a food to correct its amount or date. Search on top with a sort button beside it; a
 * bar for anything the camera couldn't name; + in the corner to add food by hand.
 */
export default function YourFridge() {
  const ui = useUi();
  const c = useColors();
  const styles = useStyles();
  const summary = useApi(api.summary, POLL_MS, "summary");
  const unnamed = useApi(api.unidentified, POLL_MS, "unidentified");
  const stock = useApi(api.stockScore, 30000, "stock");
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<Sort>("soon");
  const [sortOpen, setSortOpen] = useState(false);

  const q = query.trim().toLowerCase();
  const items = (summary.data?.inventory ?? [])
    .filter((i) => !i.image_url) // unnamed camera sightings are named first (the bar above)
    .filter((i) => !q || i.name.toLowerCase().includes(q))
    .sort(ORDER[sort]);
  const toName = unnamed.data?.length ?? 0;

  return (
    <View style={ui.screen}>
      <ScrollView
        style={ui.screen}
        contentContainerStyle={[ui.content, { paddingBottom: FAB + 32 }]}
        keyboardShouldPersistTaps="handled"
        refreshControl={
          <RefreshControl
            refreshing={false}
            onRefresh={summary.reload}
            tintColor={c.accent}
          />
        }
      >
        {toName > 0 && (
          <Link href="/identify" asChild>
            <Pressable style={styles.nameBar} accessibilityRole="button">
              <FontAwesome name="camera" size={15} color={c.accent} />
              <Text style={[ui.text, { flex: 1 }]}>
                <Text style={{ fontWeight: "700" }}>
                  {toName === 1 ? "1 item" : `${toName} items`}
                </Text>{" "}
                the camera couldn&apos;t name
              </Text>
              <Text style={styles.link}>Name</Text>
              <FontAwesome name="chevron-right" size={12} color={c.accent} />
            </Pressable>
          </Link>
        )}

        <View style={styles.searchRow}>
          <View style={{ flex: 1 }}>
            <SearchField
              value={query}
              onChange={setQuery}
              placeholder="Search your food"
              label="Search your food"
            />
          </View>
          <Pressable
            onPress={() => setSortOpen((o) => !o)}
            accessibilityRole="button"
            accessibilityLabel="Sort"
            accessibilityState={{ expanded: sortOpen }}
            style={({ pressed }) => [
              styles.sortButton,
              (sortOpen || sort !== "soon") && styles.sortOn,
              pressed && { opacity: 0.7 },
            ]}
          >
            <FontAwesome
              name="sliders"
              size={20}
              color={sortOpen || sort !== "soon" ? c.onAccent : c.textSecondary}
            />
          </Pressable>
        </View>
        {stock.data && (
          <StockLine
            score={stock.data.score}
            atRisk={stock.data.at_risk}
            fromTiger={stock.data.source === "tiger"}
          />
        )}

        {sortOpen && (
          <View style={[ui.card, { gap: 12 }]}>
            <Text style={ui.label}>Sort by</Text>
            <ChoiceChips
              options={SORTS}
              value={sort}
              onChange={(v) => {
                setSort(v);
                setSortOpen(false);
              }}
              label="Sort by"
            />
          </View>
        )}

        {summary.error && <ErrorCard message={summary.error} />}
        {summary.loading && !summary.data ? (
          <Loading />
        ) : items.length === 0 ? (
          q ? (
            <NotHere query={query.trim()} />
          ) : (
            <Text style={ui.detail}>
              Nothing here yet. Put something in the fridge, or add it with +.
            </Text>
          )
        ) : (
          <>
            <View style={styles.countRow}>
              <Text style={ui.muted}>
                {items.length === 1 ? "1 item" : `${items.length} items`} ·{" "}
                {SORTS.find((s) => s.value === sort)?.label.toLowerCase()}
              </Text>
              <Text style={ui.muted}>Tap to edit</Text>
            </View>
            <View style={[ui.card, { paddingVertical: 4 }]}>
              {items.map((item, i) => (
                <InventoryRow
                  key={`${item.product_id}-${item.location}`}
                  item={item}
                  last={i === items.length - 1}
                  showPlace
                  showDate
                />
              ))}
            </View>
          </>
        )}
      </ScrollView>

      <Pressable
        onPress={() => router.push("/add")}
        accessibilityRole="button"
        accessibilityLabel="Add food"
        style={({ pressed }) => [
          styles.fab,
          { bottom: 16 }, // same as from the side; the tab bar already clears the home indicator
          pressed && { opacity: 0.85 },
        ]}
      >
        <FontAwesome name="plus" size={24} color={c.onAccent} />
      </Pressable>
    </View>
  );
}

/** One line from the stock analysis: balanced or not, and how much is likely to spoil. Opens the dial. */
function StockLine({
  score,
  atRisk,
  fromTiger,
}: {
  score: number;
  atRisk: { name: string; at_risk_g: number }[];
  fromTiger: boolean;
}) {
  const ui = useUi();
  const c = useColors();
  const styles = useStyles();
  const band = bandOf(score);
  const waste = atRisk.reduce((sum, f) => sum + f.at_risk_g, 0);
  return (
    <Link href="/stock" asChild>
      <Pressable style={styles.insight} accessibilityRole="button">
        <View style={[styles.dot, { backgroundColor: bandColor(band, c) }]} />
        <Text style={[ui.text, { flex: 1 }]} numberOfLines={1}>
          <Text style={{ fontWeight: "700" }}>{BAND_TEXT[band].title}</Text>
          {waste > 0
            ? ` · ${waste >= 1000 ? `${(waste / 1000).toFixed(1)} kg` : `${Math.round(waste)} g`} likely to spoil`
            : ""}
        </Text>
        {fromTiger && <FontAwesome name="database" size={11} color={c.muted} />}
        {fromTiger && <Text style={ui.muted}>Tiger Data</Text>}
        <FontAwesome name="chevron-right" size={11} color={c.muted} />
      </Pressable>
    </Link>
  );
}

/** Nothing found: say so, and offer the next step. */
function NotHere({ query }: { query: string }) {
  const ui = useUi();
  const addToGrocery = useAddToGrocery();
  const name = query.toLowerCase();
  return (
    <View style={{ gap: 8 }}>
      <Text style={ui.detail}>You don&apos;t have any {name}.</Text>
      <View style={{ flexDirection: "row" }}>
        <Button
          variant="outline"
          title={`Add ${name} to grocery list`}
          onPress={() => addToGrocery(name, name)}
        />
      </View>
    </View>
  );
}

const useStyles = makeStyles((c, size) => ({
  nameBar: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    minHeight: 44,
    paddingHorizontal: 14,
    paddingVertical: 10,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: c.accent,
    backgroundColor: c.card,
  },
  link: { color: c.accent, fontSize: size(15), fontWeight: "700" },
  insight: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    minHeight: 44,
    paddingHorizontal: 14,
    borderRadius: 12,
    backgroundColor: c.card,
    borderWidth: 1,
    borderColor: c.border,
  },
  dot: { width: 10, height: 10, borderRadius: 5 },
  searchRow: { flexDirection: "row", alignItems: "center", gap: 10 },
  sortButton: {
    width: 44,
    height: 44,
    borderRadius: 12,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: c.input,
  },
  sortOn: { backgroundColor: c.accent },
  countRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    paddingHorizontal: 4,
  },
  fab: {
    position: "absolute",
    right: 16,
    width: FAB,
    height: FAB,
    borderRadius: FAB / 2,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: c.accent,
    shadowColor: "#000",
    shadowOpacity: 0.2,
    shadowRadius: 8,
    shadowOffset: { width: 0, height: 3 },
    elevation: 5,
  },
}));
