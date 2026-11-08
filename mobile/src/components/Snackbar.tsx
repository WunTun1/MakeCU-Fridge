import { usePathname } from 'expo-router';
import { createContext, type ReactNode, useCallback, useContext, useEffect, useState } from 'react';
import { Pressable, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { makeStyles } from '@/lib/theme';

export type Snack = { message: string; action?: { label: string; onPress: () => void } };

const PLAIN_MS = 5000;
const WITH_ACTION_MS = 8000;
export const TAB_BAR_HEIGHT = 60;
const TAB_PATHS = new Set(['/', '/grocery', '/chat', '/browse', '/recipes']);

const SnackbarContext = createContext<(snack: Snack) => void>(() => {});
const ClearanceContext = createContext<(px: number) => void>(() => {});
/** Space between a snackbar and a screen's sticky bottom bar. */
const ABOVE_BAR = 8;

/** Brief feedback after an action, with at most one action (usually Undo). */
export const useSnackbar = () => useContext(SnackbarContext);

/** A screen with a sticky bottom bar this tall (safe area included): snackbars sit above it, never over it. */
export function useSnackbarClearance(px: number) {
  const setClearance = useContext(ClearanceContext);
  useEffect(() => {
    setClearance(px);
    return () => setClearance(0);
  }, [px, setClearance]);
}

export function SnackbarProvider({ children }: { children: ReactNode }) {
  const [current, setCurrent] = useState<(Snack & { key: number }) | null>(null);
  const [clearance, setClearance] = useState(0);
  const insets = useSafeAreaInsets();
  const pathname = usePathname();
  const styles = useStyles();

  const show = useCallback((snack: Snack) => setCurrent({ ...snack, key: Date.now() }), []);

  useEffect(() => {
    if (!current) return;
    const id = setTimeout(() => setCurrent(null), current.action ? WITH_ACTION_MS : PLAIN_MS);
    return () => clearTimeout(id);
  }, [current]);

  const bottom = clearance
    ? clearance + ABOVE_BAR
    : insets.bottom + 16 + (TAB_PATHS.has(pathname) ? TAB_BAR_HEIGHT : 0);

  return (
    <SnackbarContext.Provider value={show}>
      <ClearanceContext.Provider value={setClearance}>{children}</ClearanceContext.Provider>
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

const useStyles = makeStyles((c, size) => ({
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
    backgroundColor: c.border,
  },
  message: { flex: 1, color: c.text, fontSize: size(15), lineHeight: size(20), paddingVertical: 8 },
  action: { minHeight: 44, minWidth: 64, paddingHorizontal: 8, alignItems: 'center', justifyContent: 'center' },
  actionLabel: { color: c.accent, fontSize: size(15), fontWeight: '700' },
}));
