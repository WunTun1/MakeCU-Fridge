import FontAwesome from "@expo/vector-icons/FontAwesome";
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
import { ErrorCard, Loading } from "@/components/States";
import { api, type InventoryEntry } from "@/lib/api";
import { makeStyles, useColors, useUi } from "@/lib/theme";
import { useAddToGrocery } from "@/lib/useAddToGrocery";
import { useApi } from "@/lib/useApi";

const POLL_MS = 5000;

type Sort = "bad" | "out" | "name";
type Place = "all" | InventoryEntry["location"];

const SORTS: { value: Sort; label: string }[] = [
  { value: "bad", label: "Goes bad soonest" },
  { value: "out", label: "Runs out soonest" },
  { value: "name", label: "A–Z" },
];
const PLACES: { value: Place; label: string }[] = [
  { value: "all", label: "All" },
  { value: "fridge", label: "Fridge" },
  { value: "pantry", label: "Pantry" },
  { value: "freezer", label: "Freezer" },
];

const last = (n: number | null) => n ?? Infinity; // no date or no forecast: at the end
const ORDER: Record<Sort, (a: InventoryEntry, b: InventoryEntry) => number> = {
  bad: (a, b) =>
    last(a.expires_in_days) - last(b.expires_in_days) ||
    a.name.localeCompare(b.name),
  out: (a, b) =>
    last(a.days_left) - last(b.days_left) || a.name.localeCompare(b.name),
  name: (a, b) => a.name.localeCompare(b.name),
};

/**
 * Everything you have, in one list you scroll: each food, how much, when it goes bad.
 * Search on top; the filter button beside it sorts (goes bad soonest, runs out soonest,
 * A–Z) and narrows to the fridge, pantry or freezer.
 */
export default function Browse() {
  const ui = useUi();
  const c = useColors();
  const styles = useStyles();
  const summary = useApi(api.summary, POLL_MS);
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<Sort>("bad");
  const [place, setPlace] = useState<Place>("all");
  const [filtersOpen, setFiltersOpen] = useState(false);

  const q = query.trim().toLowerCase();
  const filtered = place !== "all" || sort !== "bad";
  const items = (summary.data?.inventory ?? [])
    .filter((i) => place === "all" || i.location === place)
    .filter((i) => !q || i.name.toLowerCase().includes(q))
    .sort(ORDER[sort]);

  return (
    <ScrollView
      style={ui.screen}
      contentContainerStyle={ui.content}
      keyboardShouldPersistTaps="handled"
      refreshControl={
        <RefreshControl
          refreshing={false}
          onRefresh={summary.reload}
          tintColor={c.accent}
        />
      }
    >
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
          onPress={() => setFiltersOpen((o) => !o)}
          accessibilityRole="button"
          accessibilityLabel="Sort and filter"
          accessibilityState={{ expanded: filtersOpen }}
          style={({ pressed }) => [
            styles.filterButton,
            (filtersOpen || filtered) && styles.filterOn,
            pressed && { opacity: 0.7 },
          ]}
        >
          <FontAwesome
            name="sliders"
            size={20}
            color={filtersOpen || filtered ? c.onAccent : c.textSecondary}
          />
        </Pressable>
      </View>

      {filtersOpen && (
        <View style={[ui.card, { gap: 12 }]}>
          <Text style={ui.label}>Sort by</Text>
          <ChoiceChips
            options={SORTS}
            value={sort}
            onChange={setSort}
            label="Sort by"
          />
          <Text style={ui.label}>Show</Text>
          <ChoiceChips
            options={PLACES}
            value={place}
            onChange={setPlace}
            label="Show"
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
            Nothing here yet. Put something in the fridge, or add it with Add
            food.
          </Text>
        )
      ) : (
        <>
          <Text style={ui.muted}>
            {items.length === 1 ? "1 item" : `${items.length} items`} ·{" "}
            {SORTS.find((s) => s.value === sort)?.label.toLowerCase()}
          </Text>
          <View style={[ui.card, { paddingVertical: 4 }]}>
            {items.map((item, i) => (
              <InventoryRow
                key={`${item.product_id}-${item.location}`}
                item={item}
                last={i === items.length - 1}
                showPlace={place === "all"}
              />
            ))}
          </View>
        </>
      )}
    </ScrollView>
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

const useStyles = makeStyles((c) => ({
  searchRow: { flexDirection: "row", alignItems: "center", gap: 10 },
  filterButton: {
    width: 44,
    height: 44,
    borderRadius: 12,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: c.input,
  },
  filterOn: { backgroundColor: c.accent },
}));
