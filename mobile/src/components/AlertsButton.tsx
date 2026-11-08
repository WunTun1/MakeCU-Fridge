import FontAwesome from "@expo/vector-icons/FontAwesome";
import { router } from "expo-router";
import { Pressable, Text, View } from "react-native";

import { alertKey, useSeenAlerts } from "@/lib/alerts";
import { api } from "@/lib/api";
import { makeStyles, useColors } from "@/lib/theme";
import { useApi } from "@/lib/useApi";

const POLL_MS = 10000;

/**
 * The bell in every tab's top-right corner: fridge too warm or cold, food about to go bad,
 * running out, items to name. A red number says how many are new since you last looked.
 */
export function AlertsButton() {
  const c = useColors();
  const styles = useStyles();
  const summary = useApi(api.summary, POLL_MS, "summary");
  const seen = useSeenAlerts();
  const s = summary.data;
  const keys = [
    ...(s?.alerts ?? []).map(alertKey),
    ...(s && s.review_queue_count > 0 ? ["review"] : []),
  ];
  const fresh = keys.filter((k) => !seen.has(k)).length;
  return (
    <Pressable
      onPress={() => router.push("/alerts")}
      accessibilityRole="button"
      accessibilityLabel={fresh ? `Alerts, ${fresh} new` : "Alerts"}
      hitSlop={8}
      style={({ pressed }) => [styles.button, pressed && { opacity: 0.5 }]}
    >
      <FontAwesome name="bell" size={21} color={c.textSecondary} />
      {fresh > 0 && (
        <View style={styles.badge}>
          <Text style={styles.badgeText}>{fresh > 9 ? "9+" : fresh}</Text>
        </View>
      )}
    </Pressable>
  );
}

const useStyles = makeStyles((c) => ({
  button: { padding: 10, marginRight: 6 },
  badge: {
    position: "absolute",
    top: 4,
    right: 2,
    minWidth: 18,
    height: 18,
    paddingHorizontal: 4,
    borderRadius: 9,
    backgroundColor: c.danger,
    alignItems: "center",
    justifyContent: "center",
    borderWidth: 2,
    borderColor: c.bg,
  },
  badgeText: {
    color: "#ffffff",
    fontSize: 10,
    fontWeight: "800",
    lineHeight: 12,
  },
}));
