import { ActivityIndicator, Text, View } from "react-native";

import { API_URL } from "@/lib/api";
import { useColors, useUi } from "@/lib/theme";

export function Loading() {
  const ui = useUi();
  const c = useColors();
  return (
    <View style={[ui.screen, { justifyContent: "center" }]}>
      <ActivityIndicator color={c.accent} />
    </View>
  );
}

export function ErrorCard({ message }: { message: string }) {
  const ui = useUi();
  const c = useColors();
  return (
    <View style={[ui.card, { borderLeftColor: c.danger, borderLeftWidth: 4 }]}>
      <Text style={ui.text}>Can&apos;t reach ShelfLife.</Text>
      <Text style={ui.detail}>
        {message}
        {"\n"}Trying {API_URL}. Set EXPO_PUBLIC_API_URL in mobile/.env.local if
        that&apos;s wrong.
      </Text>
    </View>
  );
}
