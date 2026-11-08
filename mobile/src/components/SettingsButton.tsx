import FontAwesome from "@expo/vector-icons/FontAwesome";
import { router } from "expo-router";
import { Pressable } from "react-native";

import { AlertsButton } from "@/components/AlertsButton";
import { useColors } from "@/lib/theme";

/**
 * The gear in every tab's top-left corner: goals, diet, allergies and display live in
 * Settings, not in the tab bar, so the tabs stay the five things you do every day.
 */
export function SettingsButton() {
  const c = useColors();
  return (
    <Pressable
      onPress={() => router.push("/settings")}
      accessibilityRole="button"
      accessibilityLabel="Settings"
      hitSlop={8}
      style={({ pressed }) => ({
        width: 44,
        height: 44,
        marginLeft: 4,
        alignItems: "center",
        justifyContent: "center",
        opacity: pressed ? 0.5 : 1,
      })}
    >
      <FontAwesome name="cog" size={22} color={c.onBar} />
    </Pressable>
  );
}

/** A tab's own top-bar action next to the alerts bell (Chat's New chat). */
export function WithAlerts({ children }: { children?: React.ReactNode }) {
  return (
    <>
      {children}
      <AlertsButton />
    </>
  );
}
