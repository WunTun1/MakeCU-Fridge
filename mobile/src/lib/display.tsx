import AsyncStorage from '@react-native-async-storage/async-storage';
import { createContext, type ReactNode, useCallback, useContext, useEffect, useState } from 'react';
import { Platform, useColorScheme } from 'react-native';

import { phonePalettes, TextScaleContext, ThemeContext, type ThemeMode } from '@/lib/theme';

export type Appearance = 'system' | 'light' | 'dark';
export type TextSize = 'default' | 'large';
export type Display = { appearance: Appearance; textSize: TextSize };

const KEY = 'refridge.display.v1';
const DEFAULT: Display = { appearance: 'system', textSize: 'default' };
export const LARGE_TEXT_SCALE = 1.2;

function parse(raw: string | null | undefined): Display {
  try {
    const saved = raw ? (JSON.parse(raw) as Partial<Display>) : {};
    return {
      appearance: saved.appearance === 'light' || saved.appearance === 'dark' ? saved.appearance : 'system',
      textSize: saved.textSize === 'large' ? 'large' : 'default',
    };
  } catch {
    return DEFAULT;
  }
}

/** On the web the saved setting is read synchronously, so the first paint already uses it. */
function readNow(): Display | null {
  if (Platform.OS !== 'web') return null;
  try {
    return parse(globalThis.localStorage?.getItem(KEY));
  } catch {
    return DEFAULT;
  }
}

function save(display: Display) {
  const raw = JSON.stringify(display);
  try {
    if (Platform.OS === 'web') globalThis.localStorage?.setItem(KEY, raw);
    else AsyncStorage.setItem(KEY, raw).catch(() => {});
  } catch {
    // Not remembered on this device; the setting still applies until the app closes.
  }
}

const DisplayContext = createContext<{ display: Display; mode: ThemeMode; setDisplay: (d: Display) => void }>({
  display: DEFAULT,
  mode: 'dark',
  setDisplay: () => {},
});

/** Appearance and text size for this device (Profile > Display). */
export const useDisplay = () => useContext(DisplayContext);

/**
 * The phone app's theme: Phone setting (the system's light/dark), Light or Dark, and Default or
 * Large text. Native apps wait for the saved setting before drawing, so nothing flashes.
 */
export function DisplayProvider({ children }: { children: ReactNode }) {
  const system = useColorScheme();
  const [display, setState] = useState<Display | null>(readNow);

  useEffect(() => {
    if (display) return;
    AsyncStorage.getItem(KEY)
      .then(parse, () => DEFAULT)
      .then(setState);
  }, [display]);

  const setDisplay = useCallback((d: Display) => {
    setState(d);
    save(d);
  }, []);

  if (!display) return null;
  const mode: ThemeMode = display.appearance === 'system' ? (system === 'light' ? 'light' : 'dark') : display.appearance;
  return (
    <DisplayContext.Provider value={{ display, mode, setDisplay }}>
      <ThemeContext.Provider value={phonePalettes[mode]}>
        <TextScaleContext.Provider value={display.textSize === 'large' ? LARGE_TEXT_SCALE : 1}>{children}</TextScaleContext.Provider>
      </ThemeContext.Provider>
    </DisplayContext.Provider>
  );
}
