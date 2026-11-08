import { createContext, useContext, useMemo } from 'react';
import { StyleSheet, type ImageStyle, type TextStyle, type ViewStyle } from 'react-native';

export const darkColors = {
  bg: '#0f1115',
  card: '#1a1d24',
  border: '#2a2e37',
  text: '#e8e9ec',
  /** Detail lines a person acts on ("Buy feta cheese", "Uses your spinach"). */
  textSecondary: '#c4c8d0',
  /** Captions and metadata only. */
  muted: '#9aa0ac',
  accent: '#4ade80',
  onAccent: '#06230f',
  warn: '#fbbf24',
  good: '#4ade80',
  danger: '#f87171',
  input: '#11131a',
  /** Flat stand-in for a card that's still loading. */
  placeholder: '#232733',
};

export type Palette = typeof darkColors;
export type ThemeMode = 'dark' | 'light';

/** The fridge screen's light theme: warm ivory and clay, after Claude's light theme. */
export const lightColors: Palette = {
  bg: '#faf9f5',
  card: '#ffffff',
  border: '#e5e2d9',
  text: '#141413',
  textSecondary: '#5e5d59',
  muted: '#6f6e69',
  accent: '#ad5233',
  onAccent: '#ffffff',
  warn: '#a15c07',
  good: '#2f8a4a',
  danger: '#b53333',
  input: '#f0eee6',
  placeholder: '#ebe8df',
};

/** Fridge screen palettes (it has its own toggle). */
export const palettes: Record<ThemeMode, Palette> = { dark: darkColors, light: lightColors };

/**
 * The phone's brand is a deep wine red: buttons, links, the selected tab. Green stays for
 * "you have it", and "need to buy" is a brighter red so the two never blur.
 */
export const phonePalettes: Record<ThemeMode, Palette> = {
  dark: { ...darkColors, accent: '#e8787a', onAccent: '#2a0b0d', danger: '#ff8a7a' },
  light: { ...lightColors, accent: '#8e2b33', onAccent: '#ffffff', danger: '#d1402f' },
};

/** Live palette. Defaults to dark, so components outside a provider look as before. */
export const ThemeContext = createContext<Palette>(darkColors);
/** 1 at Default text size, 1.2 at Large. The fridge screen always uses 1. */
export const TextScaleContext = createContext(1);

export const useColors = () => useContext(ThemeContext);
export const useTextScale = () => useContext(TextScaleContext);

/** A type size at the current text scale, in whole px. */
export type Size = (px: number) => number;

/**
 * Styles that follow the theme and text size: `const useStyles = makeStyles((c, size) => ({...}))`
 * at module level, then `const styles = useStyles()` in the component.
 */
type Styles = Record<string, ViewStyle | TextStyle | ImageStyle>;

export function makeStyles<T extends Styles>(factory: (c: Palette, size: Size) => T & Styles) {
  return function useStyles(): Readonly<T> {
    const c = useColors();
    const scale = useTextScale();
    return useMemo(() => StyleSheet.create(factory(c, (px) => Math.round(px * scale))), [c, scale]);
  };
}

/**
 * Shared roles (design_principles.md type scale): text = Body 15/20, detail = Detail 15/20 in
 * textSecondary (lines a person acts on), muted = Caption 13/18 (metadata only), h2 = Title M 17/22,
 * label = Label 13/16 (badges).
 */
export const useUi = makeStyles((c, size) => ({
  screen: { flex: 1, backgroundColor: c.bg },
  content: { padding: 16, paddingBottom: 32, gap: 12 },
  card: {
    backgroundColor: c.card,
    borderColor: c.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 16,
  },
  h2: { color: c.text, fontSize: size(17), lineHeight: size(22), fontWeight: '600', marginTop: 4 },
  text: { color: c.text, fontSize: size(15), lineHeight: size(20) },
  detail: { color: c.textSecondary, fontSize: size(15), lineHeight: size(20) },
  muted: { color: c.muted, fontSize: size(13), lineHeight: size(18) },
  label: { fontSize: size(13), lineHeight: size(16), fontWeight: '600' },
  input: {
    backgroundColor: c.input,
    borderColor: c.muted,
    borderWidth: 1,
    borderRadius: 8,
    padding: 12,
    color: c.text,
    fontSize: size(16),
  },
  row: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  divider: { borderBottomColor: c.border, borderBottomWidth: StyleSheet.hairlineWidth },
}));
