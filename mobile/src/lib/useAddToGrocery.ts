import { useCallback } from 'react';

import { useSnackbar } from '@/components/Snackbar';
import { api } from '@/lib/api';
import { capitalize } from '@/lib/time';

/**
 * Puts one thing on the grocery list ("Chicken breast 700 g") and says so with an Undo that takes the
 * new row off again. Something already on the list is left as it was. `what` names it in the
 * snackbar ("700 g chicken breast"). `onChange` runs after the add and after an Undo.
 */
export function useAddToGrocery(onChange?: () => void) {
  const showSnack = useSnackbar();
  return useCallback(
    async (entry: string, what: string) => {
      try {
        const { ids, new: fresh } = await api.addToGrocery({ names: [entry] });
        onChange?.();
        if (!fresh[0]) {
          showSnack({ message: `${capitalize(what)} is already on your grocery list` });
          return;
        }
        showSnack({
          message: `Added ${what} to your grocery list`,
          action: { label: 'Undo', onPress: () => api.hideGrocery(ids[0], true).then(onChange, () => {}) },
        });
      } catch (e) {
        showSnack({ message: `Couldn't add it: ${(e as Error).message}` });
      }
    },
    [onChange, showSnack],
  );
}
