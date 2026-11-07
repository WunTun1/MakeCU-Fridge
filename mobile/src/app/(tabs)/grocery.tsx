import FontAwesome from '@expo/vector-icons/FontAwesome';
import { useState } from 'react';
import { Pressable, ScrollView, Text, View } from 'react-native';

import { ErrorCard, Loading } from '@/components/States';
import { api } from '@/lib/api';
import { colors, formatGrams, ui } from '@/lib/theme';
import { useApi } from '@/lib/useApi';

const TRIP_OPTIONS: (number | undefined)[] = [undefined, 1, 3, 7];

export default function Grocery() {
  const [tripInDays, setTripInDays] = useState<number | undefined>(undefined);

  return (
    <ScrollView style={ui.screen} contentContainerStyle={ui.content}>
      <View style={ui.row}>
        {TRIP_OPTIONS.map((d) => {
          const active = d === tripInDays;
          return (
            <Pressable
              key={String(d)}
              onPress={() => setTripInDays(d)}
              style={[ui.card, { flex: 1, padding: 8, alignItems: 'center' }, active && { borderColor: colors.accent }]}
            >
              <Text style={[ui.muted, active && { color: colors.accent }]}>{d == null ? 'Auto' : `${d}d`}</Text>
            </Pressable>
          );
        })}
      </View>
      {/* Keyed so changing the trip date remounts and refetches. */}
      <GroceryList key={String(tripInDays)} tripInDays={tripInDays} />
    </ScrollView>
  );
}

function GroceryList({ tripInDays }: { tripInDays: number | undefined }) {
  const { data, error, loading } = useApi(() => api.grocery(tripInDays));
  const [checked, setChecked] = useState<Set<number>>(new Set());

  const toggle = (id: number) =>
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  if (loading && !data) return <Loading />;
  if (error) return <ErrorCard message={error} />;
  if (!data) return null;

  return (
    <>
      <View style={ui.card}>
        <Text style={ui.text}>
          {tripInDays != null
            ? `Trip in ${tripInDays} day${tripInDays > 1 ? 's' : ''}`
            : data.trip_date
              ? `Suggested trip: ${data.trip_date}`
              : 'No trip needed soon.'}
        </Text>
      </View>

      <View style={ui.card}>
        {data.items.length === 0 && <Text style={ui.muted}>Nothing to buy yet.</Text>}
        {data.items.map((item, i) => {
          const done = checked.has(item.product_id);
          return (
            <Pressable
              key={item.product_id}
              onPress={() => toggle(item.product_id)}
              style={[ui.row, { paddingVertical: 10 }, i < data.items.length - 1 && ui.divider]}
            >
              <FontAwesome name={done ? 'check-square' : 'square-o'} size={22} color={done ? colors.accent : colors.muted} />
              <View style={{ flex: 1 }}>
                <Text style={[ui.text, done && { textDecorationLine: 'line-through', color: colors.muted }]}>
                  {item.product_name}
                </Text>
                <Text style={ui.muted}>{item.reason}</Text>
              </View>
              <Text style={ui.text}>
                {item.buy_packages ? `${item.buy_packages} pkg` : formatGrams(item.buy_grams)}
              </Text>
            </Pressable>
          );
        })}
      </View>
    </>
  );
}
