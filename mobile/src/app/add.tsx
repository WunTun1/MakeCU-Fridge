import { router } from 'expo-router';
import { useState } from 'react';
import { Pressable, ScrollView, Text, TextInput, View } from 'react-native';

import { Button } from '@/components/Button';
import { api } from '@/lib/api';
import { colors, ui } from '@/lib/theme';

const LOCATIONS = ['pantry', 'fridge', 'freezer'] as const;

export default function AddItem() {
  const [name, setName] = useState('');
  const [grams, setGrams] = useState('');
  const [location, setLocation] = useState<(typeof LOCATIONS)[number]>('pantry');
  const [status, setStatus] = useState<string | null>(null);

  async function submit() {
    const g = Number(grams);
    if (!name.trim() || !g) {
      setStatus('Enter a name and an amount in grams.');
      return;
    }
    try {
      await api.addItem({ name: name.trim(), grams: g, location });
      router.back();
    } catch (e) {
      setStatus(`Couldn't add: ${(e as Error).message}`);
    }
  }

  return (
    <ScrollView style={ui.screen} contentContainerStyle={ui.content} keyboardShouldPersistTaps="handled">
      <Button title="Scan a barcode" variant="secondary" onPress={() => router.push('/scan')} />

      <Text style={ui.h2}>Or type it in</Text>
      <View style={[ui.card, { gap: 12 }]}>
        <TextInput
          style={ui.input}
          placeholder="Name (e.g. Rice)"
          placeholderTextColor={colors.muted}
          value={name}
          onChangeText={setName}
        />
        <TextInput
          style={ui.input}
          placeholder="Grams (e.g. 2000)"
          placeholderTextColor={colors.muted}
          value={grams}
          onChangeText={setGrams}
          keyboardType="numeric"
        />
        <View style={ui.row}>
          {LOCATIONS.map((loc) => (
            <Pressable
              key={loc}
              onPress={() => setLocation(loc)}
              style={[
                ui.card,
                { flex: 1, padding: 10, alignItems: 'center' },
                loc === location && { borderColor: colors.accent },
              ]}
            >
              <Text style={[ui.text, loc === location && { color: colors.accent }]}>
                {loc[0].toUpperCase() + loc.slice(1)}
              </Text>
            </Pressable>
          ))}
        </View>
        <Button title="Add" onPress={submit} />
        {status && <Text style={ui.muted}>{status}</Text>}
      </View>
    </ScrollView>
  );
}
