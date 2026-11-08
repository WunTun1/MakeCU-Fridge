import { useState } from "react";
import {
  Image,
  Pressable,
  ScrollView,
  Text,
  TextInput,
  View,
} from "react-native";

import { useSnackbar } from "@/components/Snackbar";
import { ErrorCard, Loading } from "@/components/States";
import { API_URL, api, type UnidentifiedItem } from "@/lib/api";
import { makeStyles, useColors, useUi } from "@/lib/theme";
import { clockTime } from "@/lib/time";
import { refreshAll, useApi } from "@/lib/useApi";

/** Things the camera saw but couldn't name: its photo, and a box to say what it is. */
export default function Identify() {
  const ui = useUi();
  const list = useApi(api.unidentified);
  const common = useApi(() => api.commonProducts(8));
  const names = (common.data ?? []).map((p) => p.name);

  if (list.loading && !list.data) return <Loading />;
  return (
    <ScrollView
      style={ui.screen}
      contentContainerStyle={[ui.content, { gap: 16 }]}
      keyboardShouldPersistTaps="handled"
    >
      {list.error && <ErrorCard message={list.error} />}
      {list.data?.length === 0 && (
        <Text style={ui.detail}>
          Nothing to name. Everything in your fridge has a name.
        </Text>
      )}
      {list.data?.map((item) => (
        <NameCard
          key={item.item_id}
          item={item}
          suggestions={names}
          onNamed={list.reload}
        />
      ))}
    </ScrollView>
  );
}

function NameCard({
  item,
  suggestions,
  onNamed,
}: {
  item: UnidentifiedItem;
  suggestions: string[];
  onNamed: () => void;
}) {
  const ui = useUi();
  const styles = useStyles();
  const c = useColors();
  const showSnack = useSnackbar();
  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);

  async function save(value: string) {
    const text = value.trim();
    if (!text || saving) return;
    setSaving(true);
    try {
      await api.identify(item.item_id, text);
      showSnack({
        message: `Named it ${text}. It's on the fridge screen now.`,
      });
      refreshAll();
      onNamed();
    } catch (e) {
      showSnack({ message: `Couldn't save: ${(e as Error).message}` });
      setSaving(false);
    }
  }

  const where =
    item.location === "fridge"
      ? item.shelf === 0
        ? "on the shelf"
        : "in the fridge"
      : `in the ${item.location}`;
  return (
    <View style={[ui.card, { gap: 12 }]}>
      <Image
        source={{ uri: `${API_URL}${item.image_url}` }}
        style={styles.photo}
        resizeMode="cover"
      />
      <Text style={ui.muted}>
        Seen {clockTime(item.seen_at)} · {where}
      </Text>
      <View style={styles.row}>
        <TextInput
          style={styles.input}
          placeholder="What is it? e.g. Greek yogurt"
          placeholderTextColor={c.muted}
          value={name}
          onChangeText={setName}
          onSubmitEditing={() => save(name)}
          returnKeyType="done"
          accessibilityLabel="What is it?"
        />
        <Pressable
          onPress={() => save(name)}
          disabled={!name.trim() || saving}
          style={({ pressed }) => [
            styles.save,
            (!name.trim() || saving) && { opacity: 0.4 },
            pressed && { opacity: 0.8 },
          ]}
          accessibilityRole="button"
        >
          <Text style={styles.saveText}>Save</Text>
        </Pressable>
      </View>
      {suggestions.length > 0 && (
        <View style={styles.chips}>
          {suggestions.map((s) => (
            <Pressable
              key={s}
              onPress={() => save(s)}
              style={styles.chip}
              accessibilityRole="button"
              accessibilityLabel={`It's ${s}`}
            >
              <Text style={ui.text}>{s}</Text>
            </Pressable>
          ))}
        </View>
      )}
    </View>
  );
}

const useStyles = makeStyles((c, size) => ({
  photo: {
    width: "100%",
    height: 220,
    borderRadius: 12,
    backgroundColor: c.input,
  },
  row: { flexDirection: "row", gap: 10, alignItems: "center" },
  input: {
    flex: 1,
    minHeight: 44,
    paddingHorizontal: 14,
    borderRadius: 12,
    backgroundColor: c.input,
    color: c.text,
    fontSize: size(16),
  },
  save: {
    minHeight: 44,
    paddingHorizontal: 18,
    borderRadius: 12,
    backgroundColor: c.accent,
    justifyContent: "center",
  },
  saveText: { color: c.onAccent, fontSize: size(16), fontWeight: "700" },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  chip: {
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: c.border,
    backgroundColor: c.card,
  },
}));
