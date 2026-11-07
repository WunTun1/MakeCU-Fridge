import { useState } from 'react';
import { ScrollView, Text, TextInput, View } from 'react-native';

import { Button } from '@/components/Button';
import { ErrorCard, Loading } from '@/components/States';
import { api, type Profile } from '@/lib/api';
import { colors, ui } from '@/lib/theme';
import { useApi } from '@/lib/useApi';

type Form = Record<'calories' | 'protein' | 'carbs' | 'fat' | 'diet' | 'allergies' | 'dislikes', string>;

const PRESETS: { label: string; values: Partial<Form> }[] = [
  { label: 'Maintain', values: { calories: '2000', protein: '100', carbs: '225', fat: '65' } },
  { label: 'High protein', values: { calories: '2200', protein: '160', carbs: '200', fat: '70' } },
  { label: 'Lighter', values: { calories: '1700', protein: '110', carbs: '170', fat: '55' } },
];

const toList = (s: string) => s.split(',').map((x) => x.trim()).filter(Boolean);
const toNum = (s: string) => (s.trim() === '' ? null : Number(s));

function toForm(p: Profile): Form {
  return {
    calories: p.daily_calories?.toString() ?? '',
    protein: p.daily_protein_g?.toString() ?? '',
    carbs: p.daily_carbs_g?.toString() ?? '',
    fat: p.daily_fat_g?.toString() ?? '',
    diet: p.diet_type ?? '',
    allergies: p.allergies.join(', '),
    dislikes: p.dislikes.join(', '),
  };
}

export default function ProfileScreen() {
  const { data, error, loading } = useApi(api.profile);
  if (loading && !data) return <Loading />;
  if (!data) return <View style={[ui.screen, ui.content]}>{error && <ErrorCard message={error} />}</View>;
  return <ProfileForm initial={data} />;
}

function ProfileForm({ initial }: { initial: Profile }) {
  const [form, setForm] = useState<Form>(() => toForm(initial));
  const [status, setStatus] = useState<string | null>(null);

  const set = (key: keyof Form) => (v: string) => setForm((f) => ({ ...f, [key]: v }));

  async function save() {
    try {
      await api.saveProfile({
        daily_calories: toNum(form.calories),
        daily_protein_g: toNum(form.protein),
        daily_carbs_g: toNum(form.carbs),
        daily_fat_g: toNum(form.fat),
        diet_type: form.diet || null,
        allergies: toList(form.allergies),
        dislikes: toList(form.dislikes),
      });
      setStatus('Saved.');
    } catch (e) {
      setStatus(`Save failed: ${(e as Error).message}`);
    }
  }

  const field = (label: string, key: keyof Form, numeric = false, placeholder?: string) => (
    <View style={{ gap: 4 }}>
      <Text style={ui.muted}>{label}</Text>
      <TextInput
        style={ui.input}
        value={form[key]}
        onChangeText={set(key)}
        keyboardType={numeric ? 'numeric' : 'default'}
        placeholder={placeholder}
        placeholderTextColor={colors.muted}
      />
    </View>
  );

  return (
    <ScrollView style={ui.screen} contentContainerStyle={ui.content} keyboardShouldPersistTaps="handled">
      <Text style={ui.h2}>Goal preset</Text>
      <View style={ui.row}>
        {PRESETS.map((p) => (
          <Button key={p.label} title={p.label} variant="secondary" onPress={() => setForm((f) => ({ ...f, ...p.values }))} />
        ))}
      </View>

      <View style={[ui.card, { gap: 12 }]}>
        {field('Daily calories', 'calories', true)}
        {field('Daily protein (g)', 'protein', true)}
        {field('Daily carbs (g)', 'carbs', true)}
        {field('Daily fat (g)', 'fat', true)}
        {field('Diet type', 'diet', false, 'none, vegetarian, keto…')}
        {field('Allergies (comma separated)', 'allergies', false, 'peanut, shellfish')}
        {field('Dislikes (comma separated)', 'dislikes')}
      </View>

      <Text style={ui.muted}>
        Allergies are enforced in code — the assistant can never suggest a recipe containing them.
      </Text>
      <Button title="Save" onPress={save} />
      {status && <Text style={ui.muted}>{status}</Text>}
    </ScrollView>
  );
}
