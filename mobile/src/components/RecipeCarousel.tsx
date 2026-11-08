import { router } from "expo-router";
import { useEffect, useRef, type ComponentRef } from "react";
import {
  type NativeScrollEvent,
  type NativeSyntheticEvent,
  Pressable,
  ScrollView,
  Text,
  View,
} from "react-native";

import { RecipePhoto } from "@/components/RecipePhoto";
import type { RecipeCard } from "@/lib/api";
import { makeStyles, useUi } from "@/lib/theme";

export const CARD_W = 240;
const GAP = 16;
/** How fast it drifts on its own, in px per second. */
const SPEED = 24;
/** After you drag or swipe it, it waits this long before drifting again. */
const RESUME_MS = 2000;
/** The list is drawn this many times in a row, so it can loop without an edge. */
const COPIES = 3;

export type CarouselItem = {
  recipe: RecipeCard;
  /** Under the name: "You have 4 of 6". */
  caption?: string | null;
  /** A tag over the photo: "Best to cook now". */
  badge?: string | null;
};

/**
 * Recipe photos drifting slowly past, in an endless loop. Drag or swipe it and it stops to let
 * you, then carries on from wherever you left it. Only recipes with a photo, when enough have one.
 */
export function RecipeCarousel({
  items,
  loading = false,
}: {
  items: CarouselItem[];
  loading?: boolean;
}) {
  const styles = useStyles();
  const ui = useUi();
  const ref = useRef<ComponentRef<typeof ScrollView>>(null);
  const withPhoto = items.filter((i) => i.recipe.image_url);
  const shown = withPhoto.length >= 3 ? withPhoto : items;
  const count = shown.length;
  const cycle = count * (CARD_W + GAP);
  const x = useRef(0);
  const expected = useRef(0);
  const pausedUntil = useRef(0);
  const ready = useRef(false);

  // The drift: a frame loop that nudges the row along, and wraps it a whole cycle back so it
  // never reaches an end.
  useEffect(() => {
    if (count < 2) return;
    let frame = 0;
    let last = 0;
    const tick = (t: number) => {
      const dt = last ? Math.min(t - last, 64) : 0;
      last = t;
      if (ready.current && Date.now() >= pausedUntil.current) {
        let next = x.current + (SPEED * dt) / 1000;
        if (next >= 2 * cycle) next -= cycle;
        expected.current = next;
        x.current = next;
        ref.current?.scrollTo({ x: next, animated: false });
      }
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [count, cycle]);

  const pause = () => {
    pausedUntil.current = Date.now() + RESUME_MS;
  };

  const onScroll = (e: NativeSyntheticEvent<NativeScrollEvent>) => {
    const now = e.nativeEvent.contentOffset.x;
    // The drift's own scrolls come back rounded to a whole pixel; keep its fractional position,
    // or a fraction of a pixel per frame would round away and it would never move.
    if (Math.abs(now - expected.current) <= 3) return;
    pause(); // you moved it, not the drift
    x.current = now;
    expected.current = now;
    // Keep you in the middle copy so there's always more on both sides.
    if (now < cycle * 0.5 || now >= 2.5 * cycle) {
      const wrapped = now < cycle * 0.5 ? now + cycle : now - cycle;
      x.current = wrapped;
      expected.current = wrapped;
      ref.current?.scrollTo({ x: wrapped, animated: false });
    }
  };

  const onLayout = () => {
    if (ready.current || count < 2) return;
    x.current = cycle;
    expected.current = cycle;
    ref.current?.scrollTo({ x: cycle, animated: false });
    ready.current = true;
  };

  if (loading && count === 0) {
    return (
      <View style={[styles.bleed, styles.row, { flexDirection: "row" }]}>
        {[0, 1].map((i) => (
          <View
            key={i}
            style={[styles.card, styles.placeholder]}
            accessibilityLabel="Loading recipes"
          />
        ))}
      </View>
    );
  }
  if (count === 0) return <Text style={ui.muted}>Empty</Text>;

  const looped =
    count < 2 ? shown : Array.from({ length: COPIES }, () => shown).flat();
  return (
    <ScrollView
      ref={ref}
      horizontal
      showsHorizontalScrollIndicator={false}
      onScroll={onScroll}
      onScrollBeginDrag={pause}
      onScrollEndDrag={pause}
      onMomentumScrollEnd={pause}
      onTouchStart={pause}
      onLayout={onLayout}
      scrollEventThrottle={16}
      style={styles.bleed}
      contentContainerStyle={styles.row}
    >
      {looped.map((item, i) => (
        <Card key={`${item.recipe.id}-${i}`} item={item} />
      ))}
    </ScrollView>
  );
}

function Card({ item }: { item: CarouselItem }) {
  const styles = useStyles();
  const ui = useUi();
  const { recipe, caption, badge } = item;
  return (
    <Pressable
      onPress={() =>
        router.push({ pathname: "/recipe/[id]", params: { id: recipe.id } })
      }
      accessibilityRole="button"
      accessibilityLabel={`${recipe.name}${caption ? `, ${caption}` : ""}`}
      style={({ pressed }) => [styles.card, pressed && { opacity: 0.85 }]}
    >
      <View>
        <RecipePhoto uri={recipe.image_url} style={styles.photo} />
        {badge && (
          <View style={styles.badge}>
            <Text style={styles.badgeText}>{badge}</Text>
          </View>
        )}
      </View>
      <View style={styles.text}>
        <Text style={[ui.text, { fontWeight: "600" }]} numberOfLines={2}>
          {recipe.name}
        </Text>
        {caption && (
          <Text style={styles.caption} numberOfLines={1}>
            {caption}
          </Text>
        )}
      </View>
    </Pressable>
  );
}

const useStyles = makeStyles((c, size) => ({
  // The row runs to the screen's edges, while its first card lines up with the content.
  bleed: { marginHorizontal: -16 },
  row: { gap: GAP, paddingHorizontal: 16 },
  card: {
    width: CARD_W,
    backgroundColor: c.card,
    borderColor: c.border,
    borderWidth: 1,
    borderRadius: 16,
    overflow: "hidden",
  },
  placeholder: {
    height: 150 + size(20) * 2 + size(18) + 28,
    backgroundColor: c.placeholder,
    borderWidth: 0,
  },
  photo: { width: "100%", height: 150 },
  badge: {
    position: "absolute",
    left: 10,
    top: 10,
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 999,
    backgroundColor: c.accent,
  },
  badgeText: { color: c.onAccent, fontSize: size(12), fontWeight: "700" },
  // Fixed height for two lines of name and one of caption, so every card in the row matches.
  text: { padding: 12, gap: 4, height: size(20) * 2 + size(18) + 4 + 24 },
  caption: {
    color: c.accent,
    fontSize: size(13),
    lineHeight: size(18),
    fontWeight: "600",
  },
}));

/** "You have 4 of 6" (a swap you have counts as having it). */
export function haveCaption(r: RecipeCard): string | null {
  if (!r.ingredient_count) return null;
  return `You have ${r.have_count + r.swaps.length} of ${r.ingredient_count}`;
}
