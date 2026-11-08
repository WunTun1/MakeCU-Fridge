import FontAwesome from "@expo/vector-icons/FontAwesome";
import { useState } from "react";
import {
  type LayoutChangeEvent,
  RefreshControl,
  ScrollView,
  Text,
  View,
} from "react-native";
import Svg, {
  Circle,
  Line,
  Polyline,
  Rect,
  Text as SvgText,
} from "react-native-svg";

import { ErrorCard, Loading } from "@/components/States";
import {
  BALANCED,
  bandColor,
  bandOf,
  StockDial,
  StockVerdict,
} from "@/components/StockDial";
import { api, type StockFood } from "@/lib/api";
import { makeStyles, useColors, useUi } from "@/lib/theme";
import { useApi } from "@/lib/useApi";

const CHART_H = 180;
const PAD = { left: 34, right: 10, top: 10, bottom: 22 };

/**
 * The stock score up close: today's dial, the last 30 days of it (the green band is your
 * normal), and the foods pulling it each way. Worked out on Tiger Data from your history.
 */
export default function Stock() {
  const ui = useUi();
  const c = useColors();
  const styles = useStyles();
  const stock = useApi(api.stockScore, 30000, "stock");
  const s = stock.data;
  if (stock.loading && !s) return <Loading />;

  return (
    <ScrollView
      style={ui.screen}
      contentContainerStyle={[ui.content, { gap: 16 }]}
      refreshControl={
        <RefreshControl
          refreshing={false}
          onRefresh={stock.reload}
          tintColor={c.accent}
        />
      }
    >
      {stock.error && <ErrorCard message={stock.error} />}
      {s && (
        <>
          <View
            style={[
              ui.card,
              { alignItems: "center", gap: 8, paddingVertical: 20 },
            ]}
          >
            <StockDial score={s.score} size={260} />
            <StockVerdict score={s.score} />
            <Text style={ui.muted}>
              Score {s.score > 0 ? "+" : ""}
              {s.score} · 0 is your usual
            </Text>
          </View>

          <View style={{ gap: 8 }}>
            <Text style={ui.h2}>Over time</Text>
            <View style={[ui.card, { paddingHorizontal: 8 }]}>
              <HistoryChart history={s.history} />
            </View>
          </View>

          {s.low.length > 0 && (
            <FoodList
              title="Running low"
              icon="arrow-down"
              color={c.danger}
              foods={s.low}
            />
          )}
          {s.high.length > 0 && (
            <FoodList
              title="More than usual"
              icon="arrow-up"
              color={c.warn}
              foods={s.high}
            />
          )}
          {s.at_risk.length > 0 && (
            <View style={{ gap: 8 }}>
              <Text style={ui.h2}>May not finish in time</Text>
              <View style={[ui.card, { paddingVertical: 4 }]}>
                {s.at_risk.map((f, i) => (
                  <View
                    key={f.name}
                    style={[styles.row, i < s.at_risk.length - 1 && ui.divider]}
                  >
                    <Text style={[ui.text, { flex: 1, fontWeight: "600" }]}>
                      {f.name}
                    </Text>
                    <Text style={[ui.detail, { color: c.warn }]}>
                      About {f.at_risk_g} g
                    </Text>
                  </View>
                ))}
              </View>
            </View>
          )}

          <View style={[ui.card, { gap: 6 }]}>
            <Text style={[ui.text, { fontWeight: "700" }]}>How it works</Text>
            <Text style={ui.detail}>
              For each food you use, it compares how many days what you have
              would last against your usual for that food (your median over the
              last month). Foods you eat more of count more. Food you likely
              can&apos;t finish before it goes bad pushes it toward overstocked.
            </Text>
            {s.source === "tiger" && (
              <View style={[ui.row, { gap: 6, marginTop: 4 }]}>
                <FontAwesome name="database" size={11} color={c.muted} />
                <Text style={ui.muted}>
                  Calculated on Tiger Data from your fridge&apos;s history
                </Text>
              </View>
            )}
          </View>
        </>
      )}
    </ScrollView>
  );
}

function FoodList({
  title,
  icon,
  color,
  foods,
}: {
  title: string;
  icon: "arrow-down" | "arrow-up";
  color: string;
  foods: StockFood[];
}) {
  const ui = useUi();
  const styles = useStyles();
  return (
    <View style={{ gap: 8 }}>
      <Text style={ui.h2}>{title}</Text>
      <View style={[ui.card, { paddingVertical: 4 }]}>
        {foods.map((f, i) => (
          <View
            key={f.product_id}
            style={[styles.row, i < foods.length - 1 && ui.divider]}
          >
            <FontAwesome name={icon} size={14} color={color} />
            <Text style={[ui.text, { flex: 1, fontWeight: "600" }]}>
              {f.name}
            </Text>
            <Text style={ui.detail}>
              {f.days_of_supply} days · usually {f.usual_days}
            </Text>
          </View>
        ))}
      </View>
    </View>
  );
}

/** -100..100 over the days, with your normal (the balanced band) shaded green. */
function HistoryChart({
  history,
}: {
  history: { day: string; score: number }[];
}) {
  const c = useColors();
  const [width, setWidth] = useState(0);
  const w = Math.max(width - PAD.left - PAD.right, 1);
  const h = CHART_H - PAD.top - PAD.bottom;
  const x = (i: number) =>
    PAD.left + (history.length > 1 ? (i / (history.length - 1)) * w : w / 2);
  const y = (score: number) =>
    PAD.top + ((100 - Math.max(-100, Math.min(100, score))) / 200) * h;
  const label = (iso: string) =>
    new Date(`${iso}T12:00:00`).toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
    });
  const last = history[history.length - 1];
  return (
    <View
      onLayout={(e: LayoutChangeEvent) => setWidth(e.nativeEvent.layout.width)}
      style={{ height: CHART_H }}
    >
      {width > 0 && history.length > 0 && (
        <Svg width={width} height={CHART_H}>
          <Rect
            x={PAD.left}
            y={y(BALANCED)}
            width={w}
            height={y(-BALANCED) - y(BALANCED)}
            fill={c.good}
            opacity={0.12}
          />
          {[100, 0, -100].map((v) => (
            <Line
              key={v}
              x1={PAD.left}
              x2={PAD.left + w}
              y1={y(v)}
              y2={y(v)}
              stroke={c.border}
              strokeWidth={1}
            />
          ))}
          <SvgText
            x={PAD.left - 6}
            y={y(100) + 4}
            fontSize={10}
            fill={c.muted}
            textAnchor="end"
          >
            Over
          </SvgText>
          <SvgText
            x={PAD.left - 6}
            y={y(0) + 4}
            fontSize={10}
            fill={c.muted}
            textAnchor="end"
          >
            Usual
          </SvgText>
          <SvgText
            x={PAD.left - 6}
            y={y(-100) + 4}
            fontSize={10}
            fill={c.muted}
            textAnchor="end"
          >
            Under
          </SvgText>
          <Polyline
            points={history.map((p, i) => `${x(i)},${y(p.score)}`).join(" ")}
            fill="none"
            stroke={c.accent}
            strokeWidth={2.5}
            strokeLinejoin="round"
          />
          {last && (
            <Circle
              cx={x(history.length - 1)}
              cy={y(last.score)}
              r={5}
              fill={bandColor(bandOf(last.score), c)}
            />
          )}
          <SvgText x={PAD.left} y={CHART_H - 4} fontSize={10} fill={c.muted}>
            {label(history[0].day)}
          </SvgText>
          <SvgText
            x={PAD.left + w}
            y={CHART_H - 4}
            fontSize={10}
            fill={c.muted}
            textAnchor="end"
          >
            Today
          </SvgText>
        </Svg>
      )}
    </View>
  );
}

const useStyles = makeStyles(() => ({
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    paddingVertical: 12,
    paddingHorizontal: 12,
  },
}));
