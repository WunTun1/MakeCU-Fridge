import { useLocalSearchParams } from 'expo-router';
import { ScrollView } from 'react-native';

import { RecipeDetailView } from '@/components/recipes/RecipeDetailView';
import { ui } from '@/lib/theme';

export default function RecipeScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  return (
    <ScrollView style={ui.screen} contentContainerStyle={ui.content}>
      <RecipeDetailView recipeId={Number(id)} />
    </ScrollView>
  );
}
