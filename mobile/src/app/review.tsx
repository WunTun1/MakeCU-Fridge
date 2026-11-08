import { useState } from 'react';
import { ScrollView, Text, TextInput, View } from 'react-native';

import { Button } from '@/components/Button';
import { ErrorCard, Loading } from '@/components/States';
import { api, type ReviewItem } from '@/lib/api';
import { candidateName, describeReview, isUnnamedAdd } from '@/lib/review';
import { useColors, useUi } from '@/lib/theme';
import { useApi } from '@/lib/useApi';

export default function Review() {
  const { data, error, loading, reload } = useApi(api.review);
  const ui = useUi();

  if (loading && !data) return <Loading />;

  return (
    <ScrollView style={ui.screen} contentContainerStyle={ui.content} keyboardShouldPersistTaps="handled">
      {error && <ErrorCard message={error} />}
      {data?.length === 0 && (
        <View style={ui.card}>
          <Text style={ui.detail}>Nothing to review.</Text>
        </View>
      )}
      {data?.map((r) => <ReviewCard key={r.id} review={r} onResolved={reload} />)}
    </ScrollView>
  );
}

function ReviewCard({ review: r, onResolved }: { review: ReviewItem; onResolved: () => void }) {
  const unnamed = isUnnamedAdd(r);
  const [name, setName] = useState(candidateName(r) ?? '');
  const [status, setStatus] = useState<string | null>(null);
  const ui = useUi();
  const c = useColors();

  async function resolve(body: Parameters<typeof api.resolveReview>[1]) {
    try {
      await api.resolveReview(r.id, body);
      onResolved();
    } catch (e) {
      setStatus((e as Error).message);
    }
  }

  return (
    <View style={[ui.card, { gap: 10 }]}>
      <Text style={ui.text}>{describeReview(r)}</Text>
      <Text style={ui.muted}>{new Date(r.occurred_at).toLocaleString()}</Text>

      {unnamed && (
        <TextInput
          style={ui.input}
          placeholder="e.g. Milk"
          placeholderTextColor={c.muted}
          value={name}
          onChangeText={setName}
        />
      )}

      <View style={ui.row}>
        <Button title="Ignore" variant="secondary" onPress={() => resolve({ action: 'ignore' })} />
        {unnamed && (
          <Button
            title="Add it"
            disabled={!name.trim()}
            onPress={() => resolve({ action: 'add_confirmed', product_name: name.trim() })}
          />
        )}
        {r.item_id != null && (
          <Button
            title="It was removed"
            variant="danger"
            onPress={() => resolve({ action: 'remove', item_id: r.item_id! })}
          />
        )}
      </View>
      {status && <Text style={ui.detail}>{status}</Text>}
    </View>
  );
}
