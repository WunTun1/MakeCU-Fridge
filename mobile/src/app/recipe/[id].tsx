import { useLocalSearchParams } from 'expo-router';

import { RecipeDetailView } from '@/components/recipes/RecipeDetailView';

export default function RecipeScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  return <RecipeDetailView recipeId={Number(id)} />;
}
