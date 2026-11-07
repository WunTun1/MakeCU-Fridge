import { useCallback, useRef, useState } from 'react';

import { api, type RecipeCard } from '@/lib/api';

export type ChatMessage = { id: number; role: 'user' | 'assistant'; text: string; recipes?: RecipeCard[] };

/** Conversation state shared by the phone's Chat tab and the fridge screen. */
export function useChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [sending, setSending] = useState(false);
  const nextId = useRef(1);
  const busy = useRef(false);

  const send = useCallback(async (text: string) => {
    const message = text.trim();
    if (!message || busy.current) return;
    busy.current = true;
    setSending(true);
    const add = (m: Omit<ChatMessage, 'id'>) => setMessages((all) => [...all, { ...m, id: nextId.current++ }]);
    add({ role: 'user', text: message });
    try {
      const { reply, recipes } = await api.chat(message);
      add({ role: 'assistant', text: reply, recipes });
    } catch (e) {
      add({ role: 'assistant', text: `Couldn't reach ReFridge: ${(e as Error).message}` });
    } finally {
      busy.current = false;
      setSending(false);
    }
  }, []);

  const reset = useCallback(() => setMessages([]), []);

  return { messages, sending, send, reset };
}
