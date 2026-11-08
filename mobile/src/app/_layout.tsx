import { DarkTheme, DefaultTheme, Stack, ThemeProvider, type Theme } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { useMemo } from 'react';

import { SnackbarProvider } from '@/components/Snackbar';
import { DisplayProvider, useDisplay } from '@/lib/display';
import { useColors } from '@/lib/theme';

export default function RootLayout() {
  return (
    <DisplayProvider>
      <ThemedApp />
    </DisplayProvider>
  );
}

function ThemedApp() {
  const c = useColors();
  const { mode } = useDisplay();
  // Navigation chrome in the app's own colors, so headers and the tab bar have no stray rules.
  const navTheme: Theme = useMemo(() => {
    const base = mode === 'dark' ? DarkTheme : DefaultTheme;
    return {
      ...base,
      colors: { ...base.colors, background: c.bg, card: c.bg, border: c.border, text: c.text, primary: c.accent, notification: c.danger },
    };
  }, [c, mode]);

  return (
    <ThemeProvider value={navTheme}>
      <SnackbarProvider>
        <StatusBar style={mode === 'dark' ? 'light' : 'dark'} />
        <Stack
          screenOptions={{
            headerStyle: { backgroundColor: c.bg },
            headerTintColor: c.text,
            contentStyle: { backgroundColor: c.bg },
          }}
        >
          <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
          <Stack.Screen name="item/[id]" options={{ title: 'Item' }} />
          <Stack.Screen name="recipe/[id]" options={{ title: 'Recipe' }} />
          <Stack.Screen name="review" options={{ title: 'Review queue' }} />
          <Stack.Screen name="today" options={{ title: 'Today' }} />
          <Stack.Screen name="settings" options={{ title: 'Settings' }} />
          <Stack.Screen name="add" options={{ title: 'Add food', presentation: 'modal' }} />
          <Stack.Screen name="scan" options={{ title: 'Scan barcode', presentation: 'fullScreenModal' }} />
          <Stack.Screen name="kiosk" options={{ headerShown: false }} />
        </Stack>
      </SnackbarProvider>
    </ThemeProvider>
  );
}
