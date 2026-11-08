import FontAwesome from "@expo/vector-icons/FontAwesome";
import { Image, View } from "react-native";

import { useColors } from "@/lib/theme";

/** The recipe's photo, or a quiet tile with a fork and knife when it has none. */
export function RecipePhoto({
  uri,
  style,
}: {
  uri: string | null;
  style: object;
}) {
  const c = useColors();
  if (uri)
    return (
      <Image
        source={{ uri }}
        style={style}
        resizeMode="cover"
        accessibilityIgnoresInvertColors
      />
    );
  return (
    <View
      style={[
        style,
        {
          backgroundColor: c.input,
          alignItems: "center",
          justifyContent: "center",
        },
      ]}
    >
      <FontAwesome name="cutlery" size={20} color={c.muted} />
    </View>
  );
}
