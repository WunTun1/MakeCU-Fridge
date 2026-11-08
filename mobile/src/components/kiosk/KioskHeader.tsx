import FontAwesome from "@expo/vector-icons/FontAwesome";
import { type ComponentProps, useMemo } from "react";
import { StyleSheet, Text, View } from "react-native";

import type { Conditions } from "@/lib/api";
import { type Palette, useColors } from "@/lib/theme";
import { useNow } from "@/lib/useNow";

const FRIDGE_TOO_WARM_C = 7;
/** A reading older than this is shown as missing: the sensor (or the Pi) has stopped reporting. */
const STALE_READING_MS = 5 * 60_000;

/** The top bar: clock, the fridge's sensor readings, and whether the door is open. Display only. */
export function KioskHeader({
  conditions,
  doorOpen,
  compact = false,
}: {
  conditions: Conditions | null;
  doorOpen: boolean;
  /** Tighter sizing for the 800x480 panel. */
  compact?: boolean;
}) {
  const colors = useColors();
  const styles = useMemo(() => makeStyles(colors), [colors]);
  const nowMs = useNow();
  const now = new Date(nowMs);
  const fresh =
    conditions != null &&
    nowMs - Date.parse(conditions.occurred_at) < STALE_READING_MS;
  const temp = fresh ? conditions.temperature_c : null;
  const humidity = fresh ? conditions.humidity_pct : null;
  const pressure = fresh ? conditions.pressure_hpa : null;
  const warm = temp != null && temp > FRIDGE_TOO_WARM_C;

  return (
    <View style={[styles.bar, compact && styles.barCompact]}>
      <View>
        <Text style={[styles.time, compact && { fontSize: 24 }]}>
          {now.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}
        </Text>
        <Text style={styles.date}>
          {now.toLocaleDateString(undefined, {
            weekday: compact ? "short" : "long",
            month: compact ? "short" : "long",
            day: "numeric",
          })}
        </Text>
      </View>

      <View style={[styles.right, compact && { gap: 8 }]}>
        <View style={[styles.readout, compact && styles.readoutCompact]}>
          <Reading
            icon="thermometer-half"
            label={warm ? "Too warm" : "Fridge"}
            value={temp == null ? "—" : `${temp.toFixed(1)}°C`}
            tone={warm ? "danger" : "ok"}
            compact={compact}
          />
          <View style={styles.divider} />
          <Reading
            icon="tint"
            label="Humidity"
            value={humidity == null ? "—" : `${Math.round(humidity)}%`}
            tone="ok"
            compact={compact}
          />
          <View style={styles.divider} />
          <Reading
            icon="tachometer"
            label="Pressure"
            value={pressure == null ? "—" : `${Math.round(pressure)} hPa`}
            tone="ok"
            compact={compact}
          />
        </View>
        <View
          style={[
            styles.door,
            compact && styles.readoutCompact,
            doorOpen && { borderColor: colors.warn },
          ]}
        >
          <FontAwesome
            name={doorOpen ? "unlock" : "lock"}
            size={compact ? 15 : 18}
            color={doorOpen ? colors.warn : colors.muted}
          />
          <Text
            style={[
              styles.doorText,
              compact && { fontSize: 14 },
              doorOpen && { color: colors.warn },
            ]}
          >
            {doorOpen ? "Door open" : "Door closed"}
          </Text>
        </View>
      </View>
    </View>
  );
}

type Tone = "ok" | "danger";

function Reading({
  icon,
  label,
  value,
  tone,
  compact,
}: {
  icon: ComponentProps<typeof FontAwesome>["name"];
  label: string;
  value: string;
  tone: Tone;
  compact: boolean;
}) {
  const colors = useColors();
  const styles = useMemo(() => makeStyles(colors), [colors]);
  const color = tone === "danger" ? colors.danger : colors.text;
  return (
    <View style={[styles.reading, compact && { minWidth: 64 }]}>
      <View style={styles.readingLabel}>
        <FontAwesome
          name={icon}
          size={compact ? 11 : 13}
          color={tone === "danger" ? colors.danger : colors.muted}
        />
        <Text
          style={[styles.label, tone === "danger" && { color: colors.danger }]}
        >
          {label}
        </Text>
      </View>
      <Text style={[styles.value, compact && { fontSize: 17 }, { color }]}>
        {value}
      </Text>
    </View>
  );
}

const makeStyles = (colors: Palette) =>
  StyleSheet.create({
    bar: {
      flexDirection: "row",
      alignItems: "center",
      justifyContent: "space-between",
      paddingHorizontal: 12,
      paddingVertical: 12,
      borderBottomColor: colors.border,
      borderBottomWidth: 1,
    },
    barCompact: { paddingHorizontal: 8, paddingVertical: 8 },
    time: { color: colors.text, fontSize: 30, fontWeight: "700" },
    date: { color: colors.muted, fontSize: 14 },
    right: {
      flexDirection: "row",
      alignItems: "center",
      gap: 12,
      flexShrink: 1,
    },
    readout: {
      flexDirection: "row",
      alignItems: "center",
      gap: 14,
      paddingHorizontal: 16,
      paddingVertical: 8,
      borderRadius: 14,
      borderWidth: 1,
      borderColor: colors.border,
      backgroundColor: colors.card,
    },
    readoutCompact: { paddingHorizontal: 10, paddingVertical: 5, gap: 8 },
    reading: { minWidth: 78 },
    readingLabel: { flexDirection: "row", alignItems: "center", gap: 5 },
    label: {
      color: colors.muted,
      fontSize: 12,
      fontWeight: "600",
      textTransform: "uppercase",
      letterSpacing: 0.5,
    },
    value: {
      color: colors.text,
      fontSize: 20,
      fontWeight: "700",
      marginTop: 1,
    },
    divider: { width: 1, alignSelf: "stretch", backgroundColor: colors.border },
    door: {
      flexDirection: "row",
      alignItems: "center",
      gap: 8,
      paddingHorizontal: 14,
      paddingVertical: 14,
      borderRadius: 14,
      borderWidth: 1,
      borderColor: colors.border,
      backgroundColor: colors.card,
    },
    doorText: { color: colors.text, fontSize: 16, fontWeight: "600" },
  });
