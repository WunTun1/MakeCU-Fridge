import { Link } from 'expo-router';
import { useEffect, useState } from 'react';
import { Pressable, ScrollView, Text, TextInput, View } from 'react-native';

import { ErrorCard } from '@/components/States';
import { formatAmount } from '@/lib/amount';
import { api, type SearchResult } from '@/lib/api';
import { LIKELY_WASTED, likelyWasted } from '@/lib/expiry';
import { useColors, useUi } from '@/lib/theme';
import { relativeDays } from '@/lib/time';

const DEBOUNCE_MS = 250;

function answer(r: SearchResult): string {
  if (r.on_hand_g <= 0) return "You're out.";
  const have = `You have ${formatAmount(r.on_hand_g, r.unit, r.grams_per_unit, r.product_name)}.`;
  const wasted = likelyWasted({ ...r, name: r.product_name });
  if (wasted) return `${have} ${LIKELY_WASTED}: ${wasted.toLowerCase()}.`;
  return r.days_left != null ? `${have} Runs out ${relativeDays(r.days_left, true)}.` : have;
}

export default function Search() {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<SearchResult[]>([]);
  const [error, setError] = useState<string | null>(null);
  const ui = useUi();
  const c = useColors();

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
        placeholder="e.g. milk, spinach, rice"
        placeholderTextColor={c.muted}
        value={query}
        onChangeText={setQuery}
        autoCorrect={false}
        autoFocus
        accessibilityLabel="Search your food"
      />
      {error && <ErrorCard message={error} />}
      {q !== '' && visible.length === 0 && !error && <Text style={ui.detail}>No food matches &quot;{q}&quot;.</Text>}
      {visible.map((r) => (
        <Link key={r.product_id} href={{ pathname: '/item/[id]', params: { id: r.product_id } }} asChild>
          <Pressable style={ui.card}>
            <View>
              <Text style={[ui.text, { fontWeight: '600' }]}>{r.product_name}</Text>
              <Text style={ui.detail}>{answer(r)}</Text>
            </View>
          </Pressable>
        </Link>
      ))}
    </ScrollView>
  );
}
