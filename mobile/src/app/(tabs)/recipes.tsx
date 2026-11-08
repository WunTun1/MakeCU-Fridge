import FontAwesome from "@expo/vector-icons/FontAwesome";
import { router } from "expo-router";
import { useEffect, useState } from "react";
import { Pressable, ScrollView, Text, View } from "react-native";

import { haveCaption, RecipeCarousel } from "@/components/RecipeCarousel";
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
      contentContainerStyle={[ui.content, { gap: 16 }]}
      keyboardShouldPersistTaps="handled"
    >
      <View style={{ gap: 10 }}>
        <View>
          <Text style={ui.h2}>Ready to cook</Text>
          <Text style={ui.muted}>
            You have at least half of what these need
          </Text>
        </View>
        <RecipeCarousel
          items={(ready.data ?? []).map((r) => ({
            recipe: r,
            caption: haveCaption(r),
          }))}
          loading={ready.data == null}
        />
      </View>

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
              {[timeText(r), haveCaption(r)].filter(Boolean).join(" · ")}
            </Text>
          </View>
          <FontAwesome name="chevron-right" color={c.textSecondary} />
        </Pressable>
      ))}
    </View>
  );
}

const useStyles = makeStyles((c, size) => ({
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    paddingVertical: 10,
    paddingHorizontal: 12,
  },
  thumb: { width: 64, height: 64, borderRadius: 10 },
}));
