import { useState, type ReactNode } from 'react';
import { Platform, Pressable, StyleSheet, Text, useWindowDimensions, View } from 'react-native';

/** The 7" panels we might mount on the door. */
export const SCREENS = [
  { key: '1024x600', width: 1024, height: 600 },
  { key: '800x480', width: 800, height: 480 },
] as const;
type ScreenKey = (typeof SCREENS)[number]['key'];

const STORAGE_KEY = 'refridge.kiosk.simScreen';
// Room for the toolbar and bezel around the largest panel.
const MIN_WINDOW_W = SCREENS[0].width + 80;
const MIN_WINDOW_H = SCREENS[0].height + 120;

function load(): ScreenKey {
  try {
    const v = globalThis.localStorage?.getItem(STORAGE_KEY);
    return SCREENS.some((s) => s.key === v) ? (v as ScreenKey) : SCREENS[0].key;
  } catch {
    return SCREENS[0].key;
  }
}

/**
 * On a desktop browser, renders the kiosk inside a fixed-size frame so the
 * layout can be checked at the real panel resolutions. On the fridge itself
 * the browser window *is* the panel (too small for the frame), so children
 * render full-screen and nothing changes.
 */
export function ScreenSimulator({ children }: { children: ReactNode }) {
  const win = useWindowDimensions();
  const [key, setKey] = useState<ScreenKey>(load);
  const roomy = Platform.OS === 'web' && win.width >= MIN_WINDOW_W && win.height >= MIN_WINDOW_H;
  if (!roomy) return <View style={{ flex: 1 }}>{children}</View>;

  const screen = SCREENS.find((s) => s.key === key) ?? SCREENS[0];
  const choose = (k: ScreenKey) => {
    setKey(k);
    try {
      globalThis.localStorage?.setItem(STORAGE_KEY, k);
    } catch {
      // Not remembered; fine.
    }
  };

  return (
    <View style={styles.page}>
      <View style={styles.toolbar}>
        <Text style={styles.label}>Simulated 7″ screen</Text>
        {SCREENS.map((s) => (
          <Pressable key={s.key} onPress={() => choose(s.key)} style={[styles.option, s.key === key && styles.optionOn]}>
            <Text style={[styles.optionText, s.key === key && styles.optionTextOn]}>
              {s.width}×{s.height}
            </Text>
          </Pressable>
        ))}
      </View>
      <View style={styles.bezel}>
        {/* The kiosk sees exactly the panel's size; overlays stay inside it. */}
        <View style={{ width: screen.width, height: screen.height, overflow: 'hidden' }}>{children}</View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  page: { flex: 1, backgroundColor: '#3a3936', alignItems: 'center', justifyContent: 'center', gap: 16 },
  toolbar: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  label: { color: '#d6d4cc', fontSize: 14, marginRight: 8 },
  option: { paddingHorizontal: 12, paddingVertical: 6, borderRadius: 8, borderWidth: 1, borderColor: '#6b6a65' },
  optionOn: { backgroundColor: '#faf9f5', borderColor: '#faf9f5' },
  optionText: { color: '#d6d4cc', fontSize: 14, fontWeight: '600' },
  optionTextOn: { color: '#141413' },
  bezel: { padding: 14, borderRadius: 18, backgroundColor: '#111' },
});
