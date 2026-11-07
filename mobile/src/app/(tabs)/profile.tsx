import { useState } from 'react';
import { ScrollView, Text, TextInput, View } from 'react-native';

import { ChoiceChips, ListField } from '@/components/Chips';
import { Segmented } from '@/components/Segmented';
import { useSnackbar } from '@/components/Snackbar';
import { ErrorCard, Loading } from '@/components/States';
import { api, type Profile } from '@/lib/api';
import { ui } from '@/lib/theme';
import { useApi } from '@/lib/useApi';

type Goals = Pick<Profile, 'daily_calories' | 'daily_protein_g' | 'daily_carbs_g' | 'daily_fat_g'>;
type GoalKey = keyof Goals;
type Preset = 'maintain' | 'protein' | 'lighter';

const PRESETS: { value: Preset; label: string; goals: Goals }[] = [
  { value: 'maintain', label: 'Maintain', goals: { daily_calories: 2000, daily_protein_g: 100, daily_carbs_g: 225, daily_fat_g: 65 } },
  { value: 'protein', label: 'More protein', goals: { daily_calories: 2200, daily_protein_g: 160, daily_carbs_g: 200, daily_fat_g: 70 } },
  { value: 'lighter', label: 'Lighter', goals: { daily_calories: 1700, daily_protein_g: 110, daily_carbs_g: 170, daily_fat_g: 55 } },
];

const GOAL_FIELDS: { key: GoalKey; label: string; saved: string }[] = [
  { key: 'daily_calories', label: 'Daily calories', saved: 'Calorie goal saved' },
  { key: 'daily_protein_g', label: 'Daily protein (g)', saved: 'Protein goal saved' },
  { key: 'daily_carbs_g', label: 'Daily carbs (g)', saved: 'Carb goal saved' },
  { key: 'daily_fat_g', label: 'Daily fat (g)', saved: 'Fat goal saved' },
];

const DIETS = [
  { value: 'none', label: 'None' },
  { value: 'vegetarian', label: 'Vegetarian' },
  { value: 'vegan', label: 'Vegan' },
  { value: 'pescatarian', label: 'Pescatarian' },
  { value: 'gluten-free', label: 'Gluten-free' },
];

/** The preset whose four numbers match the goals exactly; otherwise none (custom goals). */
const presetFor = (p: Goals): Preset | null =>
  PRESETS.find((preset) => GOAL_FIELDS.every(({ key }) => preset.goals[key] === p[key]))?.value ?? null;

export default function ProfileScreen() {
  const { data, error, loading } = useApi(api.profile);
  if (loading && !data) return <Loading />;
  if (!data) return <View style={[ui.screen, ui.content]}>{error && <ErrorCard message={error} />}</View>;
  return <ProfileForm initial={data} />;
}

/** Every change saves right away, so what's on screen is always what ReFridge uses. */
function ProfileForm({ initial }: { initial: Profile }) {
  const [profile, setProfile] = useState<Profile>(initial);
  const showSnack = useSnackbar();

  async function save(patch: Partial<Profile>, message: string) {
    const before = profile;
    setProfile((p) => ({ ...p, ...patch }));
    try {
      await api.saveProfile(patch);
      showSnack({ message });
    } catch (e) {
      setProfile(before);
      showSnack({ message: `Couldn't save: ${(e as Error).message}` });
    }
  }

  const preset = presetFor(profile);

  return (
    <ScrollView style={ui.screen} contentContainerStyle={ui.content} keyboardShouldPersistTaps="handled">
      <Text style={ui.h2}>Daily goals</Text>
      <Segmented
        label="Goal preset"
        options={PRESETS}
        value={preset}
        onChange={(v) => {
          const p = PRESETS.find((x) => x.value === v)!;
          save(p.goals, `Goals set to ${p.label.toLowerCase()}`);
        }}
      />
      {preset == null && <Text style={ui.muted}>Custom goals</Text>}
      <View style={[ui.card, { gap: 12 }]}>
        {GOAL_FIELDS.map((f) => (
          <GoalField
            key={`${f.key}-${profile[f.key]}`}
            label={f.label}
            value={profile[f.key]}
            onSave={(v) => save({ [f.key]: v }, f.saved)}
          />
        ))}
      </View>
      <Text style={ui.muted}>General wellness info, not medical advice.</Text>

      <Text style={ui.h2}>Diet</Text>
      <ChoiceChips
        label="Diet"
        options={DIETS}
        value={profile.diet_type}
        onChange={(v) => save({ diet_type: v }, 'Diet saved')}
      />

      <Text style={ui.h2}>Allergies</Text>
      <Text style={ui.muted}>ReFridge never suggests recipes with these.</Text>
      <ListField
        label="allergies"
        placeholder="e.g. peanuts"
        values={profile.allergies}
        onChange={(allergies) => save({ allergies }, 'Allergies saved')}
      />

      <Text style={ui.h2}>Dislikes</Text>
      <Text style={ui.muted}>Left out of Cook tonight and One item away. Chat skips them unless you ask.</Text>
      <ListField
        label="dislikes"
        placeholder="e.g. mushrooms"
        values={profile.dislikes}
        onChange={(dislikes) => save({ dislikes }, 'Dislikes saved')}
      />

      <LearnedTastes />
    </ScrollView>
  );
}

/** A number that saves when you leave the field. */
function GoalField({ label, value, onSave }: { label: string; value: number | null; onSave: (v: number) => void }) {
  const [text, setText] = useState(value?.toString() ?? '');
  const commit = () => {
    const n = Number(text.replace(',', '.'));
    if (text.trim() !== '' && n > 0 && n !== value) onSave(n);
  };
  return (
    <View style={{ gap: 4 }}>
      <Text style={ui.muted}>{label}</Text>
      <TextInput
        style={ui.input}
        value={text}
        onChangeText={setText}
        onBlur={commit}
        onSubmitEditing={commit}
        keyboardType="numeric"
        returnKeyType="done"
        accessibilityLabel={label}
      />
    </View>
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
        <Text style={ui.muted}>Cook, rate, and ask for recipes and this fills in. Suggestions adapt as it does.</Text>
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
