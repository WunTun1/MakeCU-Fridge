import { StyleSheet } from 'react-native';

export const colors = {
  bg: '#0f1115',
  card: '#1a1d24',
  border: '#2a2e37',
  text: '#e8e9ec',
  muted: '#9aa0ac',
  accent: '#4ade80',
  onAccent: '#06230f',
  warn: '#fbbf24',
  danger: '#f87171',
  input: '#11131a',
};

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
