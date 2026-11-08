import FontAwesome from '@expo/vector-icons/FontAwesome';
import { Tabs } from 'expo-router';
import type { ComponentProps } from 'react';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { TAB_BAR_HEIGHT } from '@/components/Snackbar';
import { useColors, useTextScale } from '@/lib/theme';

type IconName = ComponentProps<typeof FontAwesome>['name'];

/** Tab labels are 12 px (14 at Large text). */
const TAB_LABEL_PX = 12;

// React Navigation types tab colors as ColorValue (can be null/number); ours are always strings.
function TabIcon({ name, color }: { name: IconName; color: unknown }) {
  const c = useColors();
  return <FontAwesome size={24} name={name} color={typeof color === 'string' ? color : c.muted} />;
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
        tabBarLabelStyle: { fontSize: TAB_LABEL_PX + extra, lineHeight: 16 + extra, fontWeight: '600', marginBottom: 4 },
        headerStyle: { backgroundColor: c.bg },
        headerTintColor: c.text,
        sceneStyle: { backgroundColor: c.bg },
      }}
    >
      <Tabs.Screen
        name="index"
        options={{ title: 'ReFridge', tabBarLabel: 'Home', tabBarIcon: ({ color }) => <TabIcon name="home" color={color} /> }}
      />
      <Tabs.Screen
        name="search"
        options={{ title: 'Search', tabBarIcon: ({ color }) => <TabIcon name="search" color={color} /> }}
      />
      <Tabs.Screen
        name="grocery"
        options={{
          title: 'Grocery list',
          tabBarLabel: 'Grocery',
          tabBarIcon: ({ color }) => <TabIcon name="shopping-cart" color={color} />,
        }}
      />
      <Tabs.Screen
        name="chat"
        options={{ title: 'Chat', tabBarIcon: ({ color }) => <TabIcon name="comments" color={color} /> }}
      />
      <Tabs.Screen
        name="profile"
        options={{ title: 'Profile', tabBarIcon: ({ color }) => <TabIcon name="user" color={color} /> }}
      />
    </Tabs>
  );
}
