import { Stack, useLocalSearchParams } from 'expo-router';
import { ScrollView, Text, View } from 'react-native';

import { ErrorCard, Loading } from '@/components/States';
import { averagePerDay, UsageChart } from '@/components/UsageChart';
import { api } from '@/lib/api';
import { formatGrams, ui } from '@/lib/theme';
import { useApi } from '@/lib/useApi';

export default function ItemDetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { data, error, loading } = useApi(() => api.usage(Number(id)));

  if (loading && !data) return <Loading />;

  return (
    <ScrollView style={ui.screen} contentContainerStyle={ui.content}>
      <Stack.Screen options={{ title: data?.name ?? 'Item' }} />
      {error && <ErrorCard message={error} />}
      {data && (
        <>
          <View style={[ui.card, ui.row, { justifyContent: 'space-around' }]}>
            <Stat label="On hand" value={formatGrams(data.on_hand_g)} />
            <Stat label="Days left" value={data.days_left != null ? data.days_left.toFixed(1) : '—'} />
            <Stat label="Avg / day" value={formatGrams(averagePerDay(data.daily_usage_g))} />
          </View>

          <Text style={ui.h2}>Usage, last 4 weeks</Text>
          <View style={ui.card}>
            <UsageChart dailyUsage={data.daily_usage_g} />
          </View>
        </>
      )}
    </ScrollView>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <View style={{ alignItems: 'center' }}>
      <Text style={[ui.text, { fontSize: 20, fontWeight: '700' }]}>{value}</Text>
      <Text style={ui.muted}>{label}</Text>
    </View>
  );
}
