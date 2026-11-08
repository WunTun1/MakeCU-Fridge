import AsyncStorage from '@react-native-async-storage/async-storage';
import { useCallback, useEffect, useRef, useState } from 'react';

import { api, type RecipeCard } from '@/lib/api';
import { refreshAll } from '@/lib/useApi';

export type ChatMessage = {
  id: number;
  role: 'user' | 'assistant';
  text: string;
  recipes?: RecipeCard[];
  /** A reply that changed stock: its turn, the Undo label, and whether it was undone. */
  turnId?: number | null;
  undo?: string | null;
  undone?: boolean;
};

const STORAGE_KEY = 'refridge.chat.v1';
const KEEP_MESSAGES = 50;

/** The phone's chat, kept across tab switches and reloads (last 50 messages, recipe cards included). */
export function useChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [sending, setSending] = useState(false);
  const restored = useRef(false);
  const nextId = useRef(1);
  const busy = useRef(false);

  useEffect(() => {
    AsyncStorage.getItem(STORAGE_KEY)
      .then((raw) => {
        const saved: ChatMessage[] = raw ? JSON.parse(raw) : [];
        nextId.current = Math.max(0, ...saved.map((m) => m.id)) + 1;
        // Anything sent before the restore finished goes after the saved history.
        setMessages((current) => [...saved, ...current.map((m) => ({ ...m, id: nextId.current++ }))]);
      })
      .catch(() => {})
      .finally(() => {
        restored.current = true;
      });
  }, []);

  useEffect(() => {
    if (!restored.current) return;
    AsyncStorage.setItem(STORAGE_KEY, JSON.stringify(messages.slice(-KEEP_MESSAGES))).catch(() => {});
  }, [messages]);

  const send = useCallback(async (text: string) => {
    const message = text.trim();
    if (!message || busy.current) return;
    busy.current = true;
    setSending(true);
    const add = (m: Omit<ChatMessage, 'id'>) => setMessages((all) => [...all, { ...m, id: nextId.current++ }]);
    add({ role: 'user', text: message });
    try {
      const { reply, recipes, turn_id, undo } = await api.chat(message);
      add({ role: 'assistant', text: reply, recipes, turnId: turn_id, undo });
      if (turn_id != null) refreshAll();
    } catch (e) {
      add({ role: 'assistant', text: `Couldn't reach ReFridge: ${(e as Error).message}` });
    } finally {
      busy.current = false;
      setSending(false);
    }
  }, []);

  /** Puts back everything one reply changed. Already undone elsewhere (409) counts as undone too. */
  const undoTurn = useCallback(async (message: ChatMessage) => {
    if (message.turnId == null) return;
    const markUndone = () => setMessages((all) => all.map((m) => (m.id === message.id ? { ...m, undone: true } : m)));
    try {
      await api.undoTurn(message.turnId);
      markUndone();
      refreshAll();
    } catch (e) {
      if ((e as Error).message === 'already undone') markUndone();
      else throw e;
    }
  }, []);

  /** Starts over on the screen and in the assistant's memory, so the next reply doesn't lean on the old chat. */
  const reset = useCallback(async () => {
    setMessages([]);
    await Promise.all([AsyncStorage.removeItem(STORAGE_KEY), api.clearChat()]).catch(() => {});
  }, []);

  return { messages, sending, send, reset, undoTurn };
}
