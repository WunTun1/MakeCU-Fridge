import FontAwesome from "@expo/vector-icons/FontAwesome";
import { router } from "expo-router";
import { Pressable } from "react-native";

import { useColors } from "@/lib/theme";

/**
 * The gear in every tab's top bar: goals, diet, allergies and display live in Settings,
 * not in the tab bar (like the App Store's account button), so the tabs stay the
 * five things you do every day.
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
        padding: 10,
        marginRight: 6,
        opacity: pressed ? 0.5 : 1,
      })}
    >
      <FontAwesome name="cog" size={22} color={c.textSecondary} />
    </Pressable>
  );
}

/** A tab's own top-bar action next to the gear (Home's Add food, Chat's New chat). */
export function WithSettings({ children }: { children?: React.ReactNode }) {
  return (
    <>
      {children}
      <SettingsButton />
    </>
  );
}
