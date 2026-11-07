import { DarkTheme, Stack, ThemeProvider, type Theme } from 'expo-router';
import { StatusBar } from 'expo-status-bar';

import { SnackbarProvider } from '@/components/Snackbar';
import { colors } from '@/lib/theme';

/** Navigation chrome in the app's own colors, so headers and the tab bar have no stray light rules. */
const navTheme: Theme = {
  ...DarkTheme,
  colors: {
    ...DarkTheme.colors,
    background: colors.bg,
    card: colors.bg,
    border: colors.border,
    text: colors.text,
    primary: colors.accent,
    notification: colors.danger,
  },
};

export default function RootLayout() {
  return (
    <ThemeProvider value={navTheme}>
      <SnackbarProvider>
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
          <Stack.Screen name="today" options={{ title: 'Today' }} />
          <Stack.Screen name="add" options={{ title: 'Add item', presentation: 'modal' }} />
          <Stack.Screen name="scan" options={{ title: 'Scan barcode', presentation: 'fullScreenModal' }} />
          <Stack.Screen name="kiosk" options={{ headerShown: false }} />
        </Stack>
      </SnackbarProvider>
    </ThemeProvider>
  );
}
