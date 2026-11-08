import FontAwesome from "@expo/vector-icons/FontAwesome";
import { router } from "expo-router";
import { useEffect, useState } from "react";
import { Pressable, ScrollView, Text, View } from "react-native";

import { RecipePhoto as Photo } from "@/components/RecipePhoto";
import { SearchField } from "@/components/SearchField";
import { ErrorCard } from "@/components/States";
import { api, type RecipeCard } from "@/lib/api";
import { makeStyles, useColors, useUi } from "@/lib/theme";
import { useApi } from "@/lib/useApi";

const POLL_MS = 15000;
const DEBOUNCE_MS = 300;
const SEARCH_LIMIT = 15;

const open = (id: number) =>
  router.push({ pathname: "/recipe/[id]", params: { id } });

/** "You have 4 of 6" (swaps count as having it). */
function haveText(r: RecipeCard): string | null {
  if (!r.ingredient_count) return null;
  return `You have ${r.have_count + r.swaps.length} of ${r.ingredient_count}`;
}

/** "35 min", "1 hr 10 min" — active time plus waiting. */
function timeText(r: RecipeCard): string | null {
  const total = (r.minutes ?? 0) + (r.inactive_min ?? 0);
  if (!total) return null;
  const h = Math.floor(total / 60);
  const m = total % 60;
  return h ? `${h} hr${m ? ` ${m} min` : ""}` : `${m} min`;
}

/**
 * Recipes: a row of dishes you can nearly make already (at least half the ingredients on hand),
 * then search for anything, and Cook tonight's ideas below — browse first, search second, like
 * the recipe apps people like.
 */
export default function Recipes() {
  const ui = useUi();
  const styles = useStyles();
  const ready = useApi(api.readyRecipes, POLL_MS, "ready");
  const tonight = useApi(api.tonight, POLL_MS, "tonight");
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<RecipeCard[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const q = query.trim();
  const shown = q ? results : null; // what's on screen: the last results, only while searching

  useEffect(() => {
    if (!q) return;
    let cancelled = false;
    const id = setTimeout(() => {
      api
        .suggestRecipes({ q, limit: SEARCH_LIMIT })
        .then((r) => !cancelled && (setResults(r), setError(null)))
        .catch((e) => !cancelled && setError(String(e.message ?? e)));
    }, DEBOUNCE_MS);
    return () => {
      cancelled = true;
      clearTimeout(id);
    };
  }, [q]);

  return (
    <ScrollView
      style={ui.screen}
      contentContainerStyle={ui.content}
      keyboardShouldPersistTaps="handled"
    >
      <View>
        <Text style={ui.h2}>Ready to cook</Text>
        <Text style={ui.muted}>You have at least half of what these need</Text>
      </View>
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        contentContainerStyle={styles.carousel}
        style={styles.bleed}
      >
        {(ready.data ?? []).map((r) => (
          <ReadyCard key={r.id} recipe={r} />
        ))}
        {ready.data == null &&
          [0, 1, 2].map((i) => (
            <View key={i} style={[styles.ready, styles.placeholder]} />
          ))}
        {ready.data?.length === 0 && (
          <Text style={[ui.detail, { paddingVertical: 24 }]}>
            Nothing yet — add a few things to the fridge.
          </Text>
        )}
      </ScrollView>

      <SearchField
        value={query}
        onChange={setQuery}
        placeholder="Search recipes: chicken, pasta, soup…"
        label="Search recipes"
      />
      {error && <ErrorCard message={error} />}

      {q ? (
        <>
          {shown?.length === 0 && (
            <Text style={ui.detail}>
              No recipes for &ldquo;{q}&rdquo;. Try fewer words.
            </Text>
          )}
          {shown && shown.length > 0 && <RecipeList recipes={shown} />}
        </>
      ) : (
        (tonight.data?.length ?? 0) > 0 && (
          <>
            <Text style={ui.h2}>Cook tonight</Text>
            <RecipeList
              recipes={(tonight.data ?? []).filter((r) => !r.leftovers)}
            />
          </>
        )
      )}
    </ScrollView>
  );
}

/** A photo-first card for the Ready to cook row. */
function ReadyCard({ recipe }: { recipe: RecipeCard }) {
  const styles = useStyles();
  const ui = useUi();
  const have = haveText(recipe);
  return (
    <Pressable
      onPress={() => open(recipe.id)}
      accessibilityRole="button"
      style={({ pressed }) => [styles.ready, pressed && { opacity: 0.8 }]}
    >
      <Photo uri={recipe.image_url} style={styles.readyPhoto} />
      <View style={styles.readyText}>
        <Text style={[ui.text, { fontWeight: "600" }]} numberOfLines={2}>
          {recipe.name}
        </Text>
        {have && <Text style={styles.have}>{have}</Text>}
      </View>
    </Pressable>
  );
}

/** Search results and Cook tonight: thumbnail, name, time and how much you have. */
function RecipeList({ recipes }: { recipes: RecipeCard[] }) {
  const ui = useUi();
  const styles = useStyles();
  const c = useColors();
  return (
    <View style={[ui.card, { paddingVertical: 4 }]}>
      {recipes.map((r, i) => (
        <Pressable
          key={r.id}
          onPress={() => open(r.id)}
          accessibilityRole="button"
          style={({ pressed }) => [
            styles.row,
            i < recipes.length - 1 && ui.divider,
            pressed && { opacity: 0.7 },
          ]}
        >
          <Photo uri={r.image_url} style={styles.thumb} />
          <View style={{ flex: 1, gap: 2 }}>
            <Text style={[ui.text, { fontWeight: "600" }]} numberOfLines={2}>
              {r.name}
            </Text>
            <Text style={ui.muted} numberOfLines={1}>
              {[timeText(r), haveText(r)].filter(Boolean).join(" · ")}
            </Text>
          </View>
          <FontAwesome name="chevron-right" color={c.textSecondary} />
        </Pressable>
      ))}
    </View>
  );
}

const useStyles = makeStyles((c, size) => ({
  // The row runs to the screen's edges, like a shelf, while its first card lines up with the content.
  bleed: { marginHorizontal: -16 },
  carousel: { gap: 12, paddingHorizontal: 16 },
  ready: {
    width: 176,
    backgroundColor: c.card,
    borderColor: c.border,
    borderWidth: 1,
    borderRadius: 14,
    overflow: "hidden",
  },
  placeholder: { height: 200, backgroundColor: c.placeholder, borderWidth: 0 },
  readyPhoto: { width: "100%", height: 120 },
  readyText: { padding: 10, gap: 4, minHeight: size(20) * 2 + size(18) + 24 },
  have: {
    color: c.accent,
    fontSize: size(13),
    lineHeight: size(18),
    fontWeight: "600",
  },
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    paddingVertical: 10,
    paddingHorizontal: 12,
  },
  thumb: { width: 64, height: 64, borderRadius: 10 },
}));
