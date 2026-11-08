import FontAwesome from "@expo/vector-icons/FontAwesome";
import { Tabs } from "expo-router";
import type { ComponentProps } from "react";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { AlertsButton } from "@/components/AlertsButton";
import { SettingsButton } from "@/components/SettingsButton";
import { TAB_BAR_HEIGHT } from "@/components/Snackbar";
import { BAR_HEIGHT, useColors, useTextScale } from "@/lib/theme";

type IconName = ComponentProps<typeof FontAwesome>["name"];

/** Tab labels are 12 px (14 at Large text). */
const TAB_LABEL_PX = 12;

// React Navigation types tab colors as ColorValue (can be null/number); ours are always strings.
function TabIcon({ name, color }: { name: IconName; color: unknown }) {
  const c = useColors();
  return (
    <FontAwesome
      size={24}
      name={name}
      color={typeof color === "string" ? color : c.muted}
    />
  );
}

export default function TabLayout() {
  const insets = useSafeAreaInsets();
  const c = useColors();
  const scale = useTextScale();
  const extra = Math.round(TAB_LABEL_PX * scale) - TAB_LABEL_PX;
  return (
    <Tabs
      screenOptions={{
        tabBarActiveTintColor: c.accent,
        tabBarInactiveTintColor: c.muted,
        tabBarStyle: {
          backgroundColor: c.card,
          borderTopColor: c.border,
          height: TAB_BAR_HEIGHT + extra + insets.bottom,
        },
        tabBarLabelStyle: {
          fontSize: TAB_LABEL_PX + extra,
          lineHeight: 16 + extra,
          fontWeight: "600",
          marginBottom: 4,
        },
        headerStyle: {
          backgroundColor: c.bar,
          height: BAR_HEIGHT + insets.top,
        },
        headerTintColor: c.onBar,
        headerTitleStyle: { fontSize: 19, fontWeight: "700" },
        headerShadowVisible: false,
        sceneStyle: { backgroundColor: c.bg },
        // Settings (goals, diet, allergies, display) behind the gear, alerts behind the bell, on every tab.
        headerLeft: () => <SettingsButton />,
        headerRight: () => <AlertsButton />,
        headerTitleAlign: "center",
      }}
    >
      <Tabs.Screen
        name="index"
        options={{
          title: "ShelfLife",
          tabBarLabel: "Home",
          tabBarIcon: ({ color }) => <TabIcon name="home" color={color} />,
        }}
      />
      <Tabs.Screen
        name="grocery"
        options={{
          title: "Grocery list",
          tabBarLabel: "Grocery",
          tabBarIcon: ({ color }) => (
            <TabIcon name="shopping-cart" color={color} />
          ),
        }}
      />
      <Tabs.Screen
        name="chat"
        options={{
          title: "Chat",
          tabBarIcon: ({ color }) => <TabIcon name="comments" color={color} />,
        }}
      />
      <Tabs.Screen
        name="browse"
        options={{
          title: "Your Fridge",
          tabBarIcon: ({ color }) => <TabIcon name="th-list" color={color} />,
        }}
      />
      <Tabs.Screen
        name="recipes"
        options={{
          title: "Recipes",
          tabBarIcon: ({ color }) => <TabIcon name="cutlery" color={color} />,
        }}
      />
    </Tabs>
  );
}
