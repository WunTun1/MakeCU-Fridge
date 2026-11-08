import { router } from "expo-router";
import { useEffect, useRef, useState, type ComponentRef } from "react";
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
import { makeStyles, useColors, useUi } from "@/lib/theme";

export const CARD_W = 240;
const GAP = 16; // the page margin: a card that's turned away leaves no sliver at the edge
const ROTATE_MS = 4000;
/** After you swipe, it waits this long before rotating again. */
const PAUSE_MS = 10000;

export type CarouselItem = {
  recipe: RecipeCard;
  /** Under the name: "You have 4 of 6", "Saves 560 g chicken breast". */
  caption?: string | null;
  /** A tag over the photo: "Best to cook now". */
  badge?: string | null;
};

/**
 * Recipe photos you swipe through — and that turn by themselves every few seconds, with dots
 * showing where you are (like an app store's featured row). Tapping one opens it.
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
  const [index, setIndex] = useState(0);
  const pausedUntil = useRef(0);
  const count = items.length;

  useEffect(() => {
    if (count < 2) return;
    const id = setInterval(() => {
      if (Date.now() < pausedUntil.current) return;
      setIndex((i) => {
        const next = (i + 1) % count;
        ref.current?.scrollTo({ x: next * (CARD_W + GAP), animated: true });
        return next;
      });
    }, ROTATE_MS);
    return () => clearInterval(id);
  }, [count]);

  const onScroll = (e: NativeSyntheticEvent<NativeScrollEvent>) =>
    setIndex(
      Math.min(
        Math.max(Math.round(e.nativeEvent.contentOffset.x / (CARD_W + GAP)), 0),
        Math.max(count - 1, 0),
      ),
    );

  if (loading && count === 0) {
    return (
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        style={styles.bleed}
        contentContainerStyle={styles.row}
      >
        {[0, 1].map((i) => (
          <View
            key={i}
            style={[styles.card, styles.placeholder]}
            accessibilityLabel="Loading recipes"
          />
        ))}
      </ScrollView>
    );
  }
  if (count === 0)
    return (
      <Text style={ui.detail}>
        No ideas yet. Add a few things to the fridge.
      </Text>
    );

  return (
    <View style={{ gap: 10 }}>
      <ScrollView
        ref={ref}
        horizontal
        showsHorizontalScrollIndicator={false}
        snapToInterval={CARD_W + GAP}
        decelerationRate="fast"
        onScroll={onScroll}
        onScrollBeginDrag={() => (pausedUntil.current = Date.now() + PAUSE_MS)}
        onTouchStart={() => (pausedUntil.current = Date.now() + PAUSE_MS)}
        scrollEventThrottle={64}
        style={styles.bleed}
        contentContainerStyle={styles.row}
      >
        {items.map((item) => (
          <Card key={item.recipe.id} item={item} />
        ))}
      </ScrollView>
      {count > 1 && <Dots count={count} index={index} />}
    </View>
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
          <Text style={styles.caption} numberOfLines={2}>
            {caption}
          </Text>
        )}
      </View>
    </Pressable>
  );
}

function Dots({ count, index }: { count: number; index: number }) {
  const c = useColors();
  return (
    <View
      style={{ flexDirection: "row", gap: 6, justifyContent: "center" }}
      accessibilityLabel={`${index + 1} of ${count}`}
    >
      {Array.from({ length: count }, (_, i) => (
        <View
          key={i}
          style={{
            width: i === index ? 16 : 6,
            height: 6,
            borderRadius: 3,
            backgroundColor: i === index ? c.accent : c.border,
          }}
        />
      ))}
    </View>
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
    height: 150 + size(20) * 2 + size(18) * 2 + 32,
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
  // Fixed height for two lines of name and two of caption, so every card in the row matches.
  text: { padding: 12, gap: 4, height: size(20) * 2 + size(18) * 2 + 4 + 24 },
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
