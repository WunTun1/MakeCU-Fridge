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

      <LearnedTastes />
    </ScrollView>
  );
}

/** What the taste profile has picked up from cooking, ratings, requests, and habits. */
function LearnedTastes() {
  const { data } = useApi(api.taste);
  if (!data) return null;
  const nothingYet = data.cuisines.length === 0 && data.ingredients.length === 0;
  return (
    <View style={[ui.card, { gap: 6, marginTop: 8 }]}>
      <Text style={ui.h2}>What ReFridge has learned</Text>
      {nothingYet ? (
        <Text style={ui.muted}>Cook, rate, and ask for recipes and this fills in — suggestions adapt as it does.</Text>
      ) : (
        <>
          {data.cuisines.length > 0 && (
            <Text style={ui.text}>
              You enjoy: <Text style={{ textTransform: 'capitalize' }}>{data.cuisines.map((c) => c.replace('-', ' ')).join(', ')}</Text>
            </Text>
          )}
          {data.ingredients.length > 0 && <Text style={ui.text}>Favorite ingredients: {data.ingredients.join(', ')}</Text>}
          <Text style={ui.muted}>Recent habits count more; older ones fade over about a month.</Text>
        </>
      )}
    </View>
  );
}
