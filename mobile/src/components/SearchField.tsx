import FontAwesome from "@expo/vector-icons/FontAwesome";
import { Pressable, TextInput, View } from "react-native";

import { makeStyles, useColors } from "@/lib/theme";

/** A rounded search bar with a magnifier and a clear button (Browse, Recipes). */
export function SearchField({
  value,
  onChange,
  placeholder,
  label,
}: {
  value: string;
  onChange: (text: string) => void;
  placeholder: string;
  /** For screen readers: what is being searched. */
  label: string;
}) {
  const styles = useStyles();
  const c = useColors();
  return (
    <View style={styles.bar}>
      <FontAwesome name="search" size={16} color={c.muted} />
      <TextInput
        style={styles.input}
        value={value}
        onChangeText={onChange}
        placeholder={placeholder}
        placeholderTextColor={c.muted}
        autoCorrect={false}
        returnKeyType="search"
        accessibilityLabel={label}
      />
      {value !== "" && (
        <Pressable
          onPress={() => onChange("")}
          hitSlop={10}
          accessibilityRole="button"
          accessibilityLabel="Clear search"
        >
          <FontAwesome name="times-circle" size={18} color={c.muted} />
        </Pressable>
      )}
    </View>
  );
}

const useStyles = makeStyles((c, size) => ({
  bar: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    minHeight: 44,
    paddingHorizontal: 14,
    borderRadius: 12,
    backgroundColor: c.input,
  },
  input: { flex: 1, color: c.text, fontSize: size(16), paddingVertical: 10 },
}));
