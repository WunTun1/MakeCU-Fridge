import { ActivityIndicator, Text, View } from 'react-native';

import { API_URL } from '@/lib/api';
import { colors, ui } from '@/lib/theme';

export function Loading() {
  return (
    <View style={[ui.screen, { justifyContent: 'center' }]}>
      <ActivityIndicator color={colors.accent} />
    </View>
  );
}

export function ErrorCard({ message }: { message: string }) {
  return (
    <View style={[ui.card, { borderLeftColor: colors.danger, borderLeftWidth: 4 }]}>
      <Text style={ui.text}>Cannot reach the ReFridge backend.</Text>
      <Text style={ui.muted}>
        {message}
        {'\n'}Trying {API_URL} — set EXPO_PUBLIC_API_URL in mobile/.env.local if that is wrong.
      </Text>
    </View>
  );
}
