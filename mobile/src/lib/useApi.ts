import { useFocusEffect } from 'expo-router';
import { useCallback, useEffect, useRef, useState } from 'react';

const reloaders = new Set<() => void>();

/** Reload every screen's data now, e.g. after an Undo changed the inventory. */
export function refreshAll() {
  reloaders.forEach((reload) => reload());
}

/** Loads data when the screen gains focus, and optionally re-polls while focused. */
export function useApi<T>(fetcher: () => Promise<T>, pollMs?: number) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const fetcherRef = useRef(fetcher);
  useEffect(() => {
    fetcherRef.current = fetcher;
  });

  const reload = useCallback(async () => {
    try {
      setData(await fetcherRef.current());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

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
