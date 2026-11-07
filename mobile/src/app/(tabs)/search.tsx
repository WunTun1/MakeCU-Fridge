import { Link } from 'expo-router';
import { useEffect, useState } from 'react';
import { Pressable, ScrollView, Text, TextInput, View } from 'react-native';

import { ErrorCard } from '@/components/States';
import { formatAmount } from '@/lib/amount';
import { api, type SearchResult } from '@/lib/api';
import { colors, ui } from '@/lib/theme';
import { relativeDays } from '@/lib/time';

const DEBOUNCE_MS = 250;

function answer(r: SearchResult): string {
  if (r.on_hand_g <= 0) return "You're out.";
  const have = `You have ${formatAmount(r.on_hand_g, r.unit, r.grams_per_unit, r.product_name)}.`;
  return r.days_left != null ? `${have} Runs out ${relativeDays(r.days_left, true)}.` : have;
}

export default function Search() {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<SearchResult[]>([]);
  const [error, setError] = useState<string | null>(null);

  const q = query.trim();
  const visible = q ? results : [];

  useEffect(() => {
    if (!q) return;
    let cancelled = false;
    const id = setTimeout(() => {
      api
        .search(q)
        .then((r) => !cancelled && (setResults(r), setError(null)))
        .catch((e) => !cancelled && setError(String(e.message ?? e)));
    }, DEBOUNCE_MS);
    return () => {
      cancelled = true;
      clearTimeout(id);
    };
  }, [q]);

  return (
    <ScrollView style={ui.screen} contentContainerStyle={ui.content} keyboardShouldPersistTaps="handled">
      <TextInput
        style={ui.input}
        placeholder="milk, spinach, rice…"
        placeholderTextColor={colors.muted}
        value={query}
        onChangeText={setQuery}
        autoCorrect={false}
        autoFocus
      />
      {error && <ErrorCard message={error} />}
      {q !== '' && visible.length === 0 && !error && <Text style={ui.muted}>No matches.</Text>}
      {visible.map((r) => (
        <Link key={r.product_id} href={{ pathname: '/item/[id]', params: { id: r.product_id } }} asChild>
          <Pressable style={ui.card}>
            <View>
              <Text style={[ui.text, { fontWeight: '600' }]}>{r.product_name}</Text>
              <Text style={ui.muted}>{answer(r)}</Text>
            </View>
          </Pressable>
        </Link>
      ))}
    </ScrollView>
  );
}
