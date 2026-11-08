import { createContext, useContext } from 'react';
import { StyleSheet } from 'react-native';

export const darkColors = {
  bg: '#0f1115',
  card: '#1a1d24',
  border: '#2a2e37',
  text: '#e8e9ec',
  muted: '#9aa0ac',
  accent: '#4ade80',
  onAccent: '#06230f',
  warn: '#fbbf24',
  good: '#4ade80',
  danger: '#f87171',
  input: '#11131a',
};

export type Palette = typeof darkColors;
export type ThemeMode = 'dark' | 'light';

/** Warm ivory and clay, after Claude's light theme. */
export const lightColors: Palette = {
  bg: '#faf9f5',
  card: '#ffffff',
  border: '#e5e2d9',
  text: '#141413',
  muted: '#6f6e69',
  accent: '#c96442',
  onAccent: '#ffffff',
  warn: '#b7791f',
  good: '#2f8a4a',
  danger: '#b53333',
  input: '#f0eee6',
};

export const palettes: Record<ThemeMode, Palette> = { dark: darkColors, light: lightColors };

/** Static palette for screens that don't support switching (the phone app). */
export const colors = darkColors;

/** Live palette. Defaults to dark, so components outside a provider look as before. */
export const ThemeContext = createContext<Palette>(darkColors);
export const useColors = () => useContext(ThemeContext);

export const ui = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.bg },
  content: { padding: 16, paddingBottom: 32, gap: 12 },
  card: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 14,
    padding: 14,
  },
  h2: { color: colors.text, fontSize: 17, fontWeight: '600', marginTop: 4 },
  text: { color: colors.text, fontSize: 15 },
  muted: { color: colors.muted, fontSize: 13 },
  input: {
    backgroundColor: colors.input,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 10,
    padding: 12,
    color: colors.text,
    fontSize: 16,
  },
  row: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  divider: { borderBottomColor: colors.border, borderBottomWidth: StyleSheet.hairlineWidth },
});

export function formatGrams(g: number): string {
  return g >= 1000 ? `${(g / 1000).toFixed(1)} kg` : `${Math.round(g)} g`;
}
