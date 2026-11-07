import { useFocusEffect } from 'expo-router';
import { useCallback, useEffect, useRef, useState } from 'react';

const reloaders = new Set<() => void>();
/** Last good response per cache key, so a screen mounted again shows it at once while refreshing. */
const memory = new Map<string, unknown>();

/** Reload every screen's data now, e.g. after an Undo changed the inventory. */
export function refreshAll() {
  reloaders.forEach((reload) => reload());
}

/**
 * Loads data when the screen gains focus, and optionally re-polls while focused.
 * With `cacheKey`, the last response is shown immediately on the next mount and refreshed in place.
 */
export function useApi<T>(fetcher: () => Promise<T>, pollMs?: number, cacheKey?: string) {
  const [data, setData] = useState<T | null>(() => (cacheKey ? ((memory.get(cacheKey) as T | undefined) ?? null) : null));
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(data == null);
  const fetcherRef = useRef(fetcher);
  useEffect(() => {
    fetcherRef.current = fetcher;
  });

  const reload = useCallback(async () => {
    try {
      const fresh = await fetcherRef.current();
      if (cacheKey) memory.set(cacheKey, fresh);
      setData(fresh);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [cacheKey]);

  useEffect(() => {
    reloaders.add(reload);
    return () => {
      reloaders.delete(reload);
    };
  }, [reload]);

  useFocusEffect(
    useCallback(() => {
      reload();
      if (!pollMs) return;
      const id = setInterval(reload, pollMs);
      return () => clearInterval(id);
    }, [reload, pollMs]),
  );

  return { data, error, loading, reload };
}
