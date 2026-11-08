import { Text, View } from "react-native";
import Svg, { Circle, Line, Path } from "react-native-svg";

import { makeStyles, useColors, useUi, type Palette } from "@/lib/theme";

/** Within this of 0 the dial reads "Balanced" (the green middle). */
export const BALANCED = 25;

export type StockBand = "under" | "balanced" | "over";

export const bandOf = (score: number): StockBand =>
  score <= -BALANCED ? "under" : score >= BALANCED ? "over" : "balanced";

export const BAND_TEXT: Record<StockBand, { title: string; detail: string }> = {
  under: {
    title: "Understocked",
    detail: "Less than you usually keep — time to shop",
  },
  balanced: {
    title: "Balanced",
    detail: "About what you usually keep and can finish",
  },
  over: {
    title: "Overstocked",
    detail: "More than you'll likely finish in time",
  },
};

export const bandColor = (band: StockBand, c: Palette) =>
  band === "under" ? c.danger : band === "over" ? c.warn : c.good;

/** Score -100..100 → angle on the half circle: -100 at the left (180°), +100 at the right (0°). */
const angleOf = (score: number) =>
  Math.PI - ((Math.max(-100, Math.min(100, score)) + 100) / 200) * Math.PI;

function arc(
  cx: number,
  cy: number,
  r: number,
  from: number,
  to: number,
): string {
  const a1 = angleOf(from);
  const a2 = angleOf(to);
  const x1 = cx + r * Math.cos(a1);
  const y1 = cy - r * Math.sin(a1);
  const x2 = cx + r * Math.cos(a2);
  const y2 = cy - r * Math.sin(a2);
  return `M ${x1} ${y1} A ${r} ${r} 0 0 1 ${x2} ${y2}`;
}

/**
 * A half-circle gauge: red on the left (understocked), green in the middle (balanced),
 * yellow on the right (overstocked), and a needle at the score.
 */
export function StockDial({
  score,
  size = 240,
}: {
  score: number;
  size?: number;
}) {
  const c = useColors();
  const styles = useStyles();
  const stroke = Math.round(size * 0.085);
  const r = size / 2 - stroke / 2 - 2;
  const cx = size / 2;
  const cy = size / 2;
  const height = size / 2 + stroke;
  const needle = angleOf(score);
  const tip = r - stroke * 0.9;
  const band = bandOf(score);
  return (
    <View
      style={{ alignItems: "center" }}
      accessibilityLabel={`Stock score ${score}: ${BAND_TEXT[band].title}`}
    >
      <Svg width={size} height={height}>
        <Path
          d={arc(cx, cy, r, -100, -BALANCED - 1)}
          stroke={c.danger}
          strokeWidth={stroke}
          fill="none"
          strokeLinecap="round"
        />
        <Path
          d={arc(cx, cy, r, -BALANCED + 1, BALANCED - 1)}
          stroke={c.good}
          strokeWidth={stroke}
          fill="none"
        />
        <Path
          d={arc(cx, cy, r, BALANCED + 1, 100)}
          stroke={c.warn}
          strokeWidth={stroke}
          fill="none"
          strokeLinecap="round"
        />
        <Line
          x1={cx}
          y1={cy}
          x2={cx + tip * Math.cos(needle)}
          y2={cy - tip * Math.sin(needle)}
          stroke={c.text}
          strokeWidth={4}
          strokeLinecap="round"
        />
        <Circle cx={cx} cy={cy} r={stroke * 0.45} fill={c.text} />
      </Svg>
      <View style={[styles.ends, { width: size }]}>
        <Text style={styles.end}>Under</Text>
        <Text style={styles.end}>Over</Text>
      </View>
    </View>
  );
}

const useStyles = makeStyles((c, size) => ({
  ends: {
    flexDirection: "row",
    justifyContent: "space-between",
    marginTop: -4,
  },
  end: {
    color: c.muted,
    fontSize: size(12),
    lineHeight: size(16),
    fontWeight: "600",
  },
}));

/** The dial with its verdict underneath, for Home's top card and the stock screen. */
export function StockVerdict({ score }: { score: number }) {
  const ui = useUi();
  const c = useColors();
  const band = bandOf(score);
  return (
    <View style={{ alignItems: "center", gap: 2 }}>
      <Text
        style={{
          color: bandColor(band, c),
          fontSize: 22,
          lineHeight: 28,
          fontWeight: "800",
        }}
      >
        {BAND_TEXT[band].title}
      </Text>
      <Text style={[ui.detail, { textAlign: "center" }]}>
        {BAND_TEXT[band].detail}
      </Text>
    </View>
  );
}
