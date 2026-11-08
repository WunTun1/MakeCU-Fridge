import FontAwesome from "@expo/vector-icons/FontAwesome";
import { Link } from "expo-router";
import { type ComponentProps, useEffect } from "react";
import {
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { ErrorCard, Loading } from "@/components/States";
import { alertKey, alertText, markAlertsSeen } from "@/lib/alerts";
import { api, type Alert, type InventoryEntry } from "@/lib/api";
import { urgency } from "@/lib/expiry";
import { makeStyles, useColors, useUi } from "@/lib/theme";
import { useApi } from "@/lib/useApi";

type Icon = ComponentProps<typeof FontAwesome>["name"];

const ICONS: Record<Alert["reason"], Icon> = {
  fridge_temp_high: "thermometer-full",
  fridge_temp_low: "snowflake-o",
  expiring_soon: "clock-o",
  staple_out: "shopping-basket",
  low_days_left: "hourglass-half",
  low_fraction: "hourglass-end",
};

/** Everything that wants your attention, most urgent first. Opening it clears the bell's number. */
export default function Alerts() {
  const ui = useUi();
  const c = useColors();
  const styles = useStyles();
  const summary = useApi(api.summary, 10000, "summary");
  const s = summary.data;

  const keys = s
    ? [
        ...s.alerts.map(alertKey),
        ...(s.review_queue_count > 0 ? ["review"] : []),
      ]
    : null;
  const keysText = keys?.join("|");
  useEffect(() => {
    if (keysText != null) markAlertsSeen(keysText ? keysText.split("|") : []);
  }, [keysText]);

  if (summary.loading && !s) return <Loading />;
  const entryFor = (id: number | null) =>
    s?.inventory.find(
      (e: InventoryEntry) => e.product_id === id && e.location !== "freezer",
    );

  return (
    <ScrollView
      style={ui.screen}
      contentContainerStyle={ui.content}
      refreshControl={
        <RefreshControl
          refreshing={false}
          onRefresh={summary.reload}
          tintColor={c.accent}
        />
      }
    >
      {summary.error && <ErrorCard message={summary.error} />}
      {s && s.alerts.length === 0 && s.review_queue_count === 0 && (
        <View style={[ui.card, styles.empty]}>
          <FontAwesome name="check-circle" size={28} color={c.good} />
          <Text style={ui.text}>All good. Nothing needs your attention.</Text>
        </View>
      )}

      {s && s.review_queue_count > 0 && (
        <Link href="/review" asChild>
          <Pressable
            style={StyleSheet.flatten([
              styles.row,
              { borderLeftColor: c.warn },
            ])}
          >
            <FontAwesome
              name="question-circle"
              size={20}
              color={c.warn}
              style={styles.icon}
            />
            <Text style={[ui.text, { flex: 1 }]}>
              <Text style={{ fontWeight: "700" }}>
                {s.review_queue_count === 1
                  ? "1 thing"
                  : `${s.review_queue_count} things`}
              </Text>{" "}
              the camera saw need an answer
            </Text>
            <FontAwesome name="chevron-right" color={c.textSecondary} />
          </Pressable>
        </Link>
      )}

      {s?.alerts.map((a, i) => {
        const entry = entryFor(a.product_id);
        const tone = a.reason.startsWith("fridge_temp")
          ? "danger"
          : entry
            ? urgency(entry)
            : "warn";
        const color = tone ? c[tone] : c.muted;
        const body = (
          <>
            <FontAwesome
              name={ICONS[a.reason] ?? "bell"}
              size={20}
              color={color}
              style={styles.icon}
            />
            <Text style={[ui.text, { flex: 1 }]}>
              <Text style={{ fontWeight: "700" }}>{a.product_name}</Text> ·{" "}
              {alertText(a, entry)}
            </Text>
          </>
        );
        const style = StyleSheet.flatten([
          styles.row,
          { borderLeftColor: color },
        ]);
        return a.product_id == null ? (
          <View key={`${alertKey(a)}-${i}`} style={style}>
            {body}
          </View>
        ) : (
          <Link
            key={`${alertKey(a)}-${i}`}
            href={{ pathname: "/item/[id]", params: { id: a.product_id } }}
            asChild
          >
            <Pressable style={style}>
              {body}
              <FontAwesome name="chevron-right" color={c.textSecondary} />
            </Pressable>
          </Link>
        );
      })}
    </ScrollView>
  );
}

const useStyles = makeStyles((c) => ({
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    padding: 16,
    backgroundColor: c.card,
    borderColor: c.border,
    borderWidth: 1,
    borderLeftWidth: 4,
    borderRadius: 12,
  },
  icon: { width: 22, textAlign: "center" },
  empty: { alignItems: "center", gap: 10, paddingVertical: 28 },
}));
