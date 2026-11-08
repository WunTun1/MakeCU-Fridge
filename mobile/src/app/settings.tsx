import { useState } from "react";
import { ScrollView, Text, TextInput, View } from "react-native";

import { ListField } from "@/components/Chips";
import { Segmented } from "@/components/Segmented";
import { useSnackbar } from "@/components/Snackbar";
import { ErrorCard, Loading } from "@/components/States";
import { api, type Profile } from "@/lib/api";
import { type Appearance, type TextSize, useDisplay } from "@/lib/display";
import { makeStyles, useColors, useUi } from "@/lib/theme";
import { useApi } from "@/lib/useApi";

const APPEARANCES: { value: Appearance; label: string }[] = [
  { value: "system", label: "Automatic" },
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
];

const TEXT_SIZES: { value: TextSize; label: string }[] = [
  { value: "default", label: "Default" },
  { value: "large", label: "Large" },
];

export default function Settings() {
  const { data, error, loading } = useApi(api.profile);
  const ui = useUi();
  if (loading && !data) return <Loading />;
  if (!data)
    return (
      <View style={[ui.screen, ui.content]}>
        {error && <ErrorCard message={error} />}
      </View>
    );
  return <SettingsForm initial={data} />;
}

/** Your name, what you can't or won't eat, what you love, and how the app looks. Saves as you go. */
function SettingsForm({ initial }: { initial: Profile }) {
  const [profile, setProfile] = useState<Profile>(initial);
  const showSnack = useSnackbar();
  const ui = useUi();
  const styles = useStyles();

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

  return (
    <ScrollView
      style={ui.screen}
      contentContainerStyle={styles.page}
      keyboardShouldPersistTaps="handled"
    >
      <NameHeader
        name={profile.name ?? ""}
        onSave={(name) => save({ name }, "Name saved")}
      />

      <Section title="Allergies" note="Recipes with these are never suggested.">
        <ListField
          label="allergies"
          placeholder="Add an allergy, e.g. peanuts"
          values={profile.allergies}
          onChange={(allergies) => save({ allergies }, "Allergies saved")}
        />
      </Section>

      <Section
        title="Dislikes"
        note="Left out of suggestions unless you ask for them."
      >
        <ListField
          label="dislikes"
          placeholder="Add a dislike, e.g. mushrooms"
          values={profile.dislikes}
          onChange={(dislikes) => save({ dislikes }, "Dislikes saved")}
        />
      </Section>

      <Section
        title="Likes"
        note="Foods and cuisines you love come up more often."
      >
        <ListField
          label="likes"
          placeholder="Add a like, e.g. Italian or salmon"
          values={profile.likes ?? []}
          onChange={(likes) => save({ likes }, "Likes saved")}
        />
      </Section>

      <DisplaySettings />
    </ScrollView>
  );
}

/** An initials circle and your name, which saves when you leave the field. */
function NameHeader({
  name,
  onSave,
}: {
  name: string;
  onSave: (name: string) => void;
}) {
  const styles = useStyles();
  const c = useColors();
  const [text, setText] = useState(name);
  const initials =
    text
      .trim()
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((w) => w[0]?.toUpperCase())
      .join("") || "?";
  const commit = () => {
    if (text.trim() !== name.trim()) onSave(text.trim());
  };
  return (
    <View style={styles.header}>
      <View style={styles.avatar}>
        <Text style={styles.initials}>{initials}</Text>
      </View>
      <TextInput
        style={styles.nameInput}
        value={text}
        onChangeText={setText}
        onBlur={commit}
        onSubmitEditing={commit}
        placeholder="Your name"
        placeholderTextColor={c.muted}
        returnKeyType="done"
        textAlign="center"
        accessibilityLabel="Your name"
      />
    </View>
  );
}

function Section({
  title,
  note,
  children,
}: {
  title: string;
  note?: string;
  children: React.ReactNode;
}) {
  const styles = useStyles();
  const ui = useUi();
  return (
    <View style={styles.section}>
      <Text style={styles.sectionTitle}>{title}</Text>
      <View style={styles.card}>{children}</View>
      {note && <Text style={[ui.muted, styles.note]}>{note}</Text>}
    </View>
  );
}

/** How the app looks on this phone: kept on the phone, not in your profile. */
function DisplaySettings() {
  const ui = useUi();
  const styles = useStyles();
  const { display, setDisplay } = useDisplay();
  return (
    <View style={styles.section}>
      <Text style={styles.sectionTitle}>Display</Text>
      <View style={[styles.card, { gap: 16 }]}>
        <View style={{ gap: 8 }}>
          <Text style={ui.text}>Appearance</Text>
          <Segmented
            label="Appearance"
            options={APPEARANCES}
            value={display.appearance}
            onChange={(appearance) => setDisplay({ ...display, appearance })}
          />
        </View>
        <View style={{ gap: 8 }}>
          <Text style={ui.text}>Text size</Text>
          <Segmented
            label="Text size"
            options={TEXT_SIZES}
            value={display.textSize}
            onChange={(textSize) => setDisplay({ ...display, textSize })}
          />
        </View>
      </View>
    </View>
  );
}

const useStyles = makeStyles((c, size) => ({
  page: { padding: 16, paddingBottom: 40, gap: 24 },
  header: { alignItems: "center", gap: 12, paddingTop: 8 },
  avatar: {
    width: 72,
    height: 72,
    borderRadius: 36,
    backgroundColor: c.accent,
    alignItems: "center",
    justifyContent: "center",
  },
  initials: { color: c.onAccent, fontSize: 28, fontWeight: "700" },
  nameInput: {
    minWidth: 220,
    minHeight: 44,
    paddingHorizontal: 16,
    borderRadius: 12,
    backgroundColor: c.input,
    color: c.text,
    fontSize: size(20),
    fontWeight: "600",
  },
  section: { gap: 8 },
  sectionTitle: {
    color: c.textSecondary,
    fontSize: size(13),
    lineHeight: size(18),
    fontWeight: "600",
    textTransform: "uppercase",
    letterSpacing: 0.6,
    paddingHorizontal: 4,
  },
  card: {
    backgroundColor: c.card,
    borderColor: c.border,
    borderWidth: 1,
    borderRadius: 14,
    padding: 16,
  },
  note: { paddingHorizontal: 4 },
}));
