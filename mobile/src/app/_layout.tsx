import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';

import { colors } from '@/lib/theme';

export default function RootLayout() {
  return (
    <>
      <StatusBar style="light" />
      <Stack
        screenOptions={{
          headerStyle: { backgroundColor: colors.bg },
          headerTintColor: colors.text,
          contentStyle: { backgroundColor: colors.bg },
        }}
      >
        <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
        <Stack.Screen name="item/[id]" options={{ title: 'Item' }} />
        <Stack.Screen name="recipe/[id]" options={{ title: 'Recipe' }} />
        <Stack.Screen name="review" options={{ title: 'Review queue' }} />
        <Stack.Screen name="add" options={{ title: 'Add item', presentation: 'modal' }} />
        <Stack.Screen name="scan" options={{ title: 'Scan barcode', presentation: 'fullScreenModal' }} />
        <Stack.Screen name="kiosk" options={{ headerShown: false }} />
      </Stack>
    </>
  );
}
