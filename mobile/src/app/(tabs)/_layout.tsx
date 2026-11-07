import FontAwesome from '@expo/vector-icons/FontAwesome';
import { Tabs } from 'expo-router';
import type { ComponentProps } from 'react';

import { colors } from '@/lib/theme';

type IconName = ComponentProps<typeof FontAwesome>['name'];

// React Navigation types tab colors as ColorValue (can be null/number); ours are always strings.
function TabIcon({ name, color }: { name: IconName; color: unknown }) {
  return <FontAwesome size={22} name={name} color={typeof color === 'string' ? color : colors.muted} />;
}

export default function TabLayout() {
  return (
    <Tabs
      screenOptions={{
        tabBarActiveTintColor: colors.accent,
        tabBarInactiveTintColor: colors.muted,
        tabBarStyle: { backgroundColor: colors.card, borderTopColor: colors.border },
        headerStyle: { backgroundColor: colors.bg },
        headerTintColor: colors.text,
        sceneStyle: { backgroundColor: colors.bg },
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
        options={{ title: 'Nutritionist', tabBarLabel: 'Chat', tabBarIcon: ({ color }) => <TabIcon name="comments" color={color} /> }}
      />
      <Tabs.Screen
        name="profile"
        options={{ title: 'Profile', tabBarIcon: ({ color }) => <TabIcon name="user" color={color} /> }}
      />
    </Tabs>
  );
}
