import { usePathname } from 'expo-router';
import { createContext, type ReactNode, useCallback, useContext, useEffect, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { colors } from '@/lib/theme';

export type Snack = { message: string; action?: { label: string; onPress: () => void } };

const PLAIN_MS = 5000;
const WITH_ACTION_MS = 8000;
export const TAB_BAR_HEIGHT = 56;
const TAB_PATHS = new Set(['/', '/search', '/grocery', '/chat', '/profile']);

const SnackbarContext = createContext<(snack: Snack) => void>(() => {});

/** Brief feedback after an action, with at most one action (usually Undo). */
export const useSnackbar = () => useContext(SnackbarContext);

export function SnackbarProvider({ children }: { children: ReactNode }) {
  const [current, setCurrent] = useState<(Snack & { key: number }) | null>(null);
  const insets = useSafeAreaInsets();
  const pathname = usePathname();

  const show = useCallback((snack: Snack) => setCurrent({ ...snack, key: Date.now() }), []);

  useEffect(() => {
    if (!current) return;
    const id = setTimeout(() => setCurrent(null), current.action ? WITH_ACTION_MS : PLAIN_MS);
    return () => clearTimeout(id);
  }, [current]);

  const bottom = insets.bottom + 16 + (TAB_PATHS.has(pathname) ? TAB_BAR_HEIGHT : 0);

  return (
    <SnackbarContext.Provider value={show}>
      {children}
      {current && pathname !== '/kiosk' && (
        <View style={[styles.bar, { bottom }]} accessibilityLiveRegion="polite" role="status">
          <Text style={styles.message} numberOfLines={2}>
            {current.message}
          </Text>
          {current.action && (
            <Pressable
              onPress={() => {
                current.action?.onPress();
                setCurrent(null);
              }}
              hitSlop={8}
              style={styles.action}
            >
              <Text style={styles.actionLabel}>{current.action.label}</Text>
            </Pressable>
          )}
        </View>
      )}
    </SnackbarContext.Provider>
  );
}

const styles = StyleSheet.create({
  bar: {
    position: 'absolute',
    left: 16,
    right: 16,
    minHeight: 48,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    paddingLeft: 16,
    paddingRight: 8,
    paddingVertical: 4,
    borderRadius: 8,
    backgroundColor: colors.border,
  },
  message: { flex: 1, color: colors.text, fontSize: 15, lineHeight: 20, paddingVertical: 8 },
  action: { minHeight: 44, minWidth: 64, paddingHorizontal: 8, alignItems: 'center', justifyContent: 'center' },
  actionLabel: { color: colors.accent, fontSize: 15, fontWeight: '700' },
});
