import { Stack, router, useLocalSearchParams } from 'expo-router';
import { useRef, useState } from 'react';
import {
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  Text,
  TextInput,
  View,
  type ScrollViewInstance,
} from 'react-native';

import { Button } from '@/components/Button';
import { RecipeCardView } from '@/components/recipes/RecipeCardView';
import { useSnackbar } from '@/components/Snackbar';
import { api } from '@/lib/api';
import { makeStyles, useColors, useUi } from '@/lib/theme';
import { useApi } from '@/lib/useApi';
import { useChat, type ChatMessage } from '@/lib/useChat';

const SUGGESTIONS = [
  "I'm feeling Italian and need more protein",
  'Something quick with what expires soon',
  'What can I make without shopping?',
];

export default function Chat() {
  const { messages, sending, send, reset, undoTurn } = useChat();
  const proteinFirst = useApi(api.profile).data?.protein_mode ?? false;
  // "Ask for more ideas" on Home opens chat with a question ready to send.
  const { ask } = useLocalSearchParams<{ ask?: string }>();
  const [input, setInput] = useState(ask ?? '');
  const scrollRef = useRef<ScrollViewInstance>(null);
  const ui = useUi();
  const styles = useStyles();
  const c = useColors();

  const [seenAsk, setSeenAsk] = useState(ask);
  if (ask !== seenAsk) {
    setSeenAsk(ask);
    if (ask) setInput(ask);
  }

  function submit(text: string) {
    setInput('');
    router.setParams({ ask: undefined });
    send(text);
  }

  return (
    <KeyboardAvoidingView style={ui.screen} behavior={Platform.OS === 'ios' ? 'padding' : undefined} keyboardVerticalOffset={90}>
      <Stack.Screen
        options={{
          headerRight: () =>
            messages.length > 0 ? (
              <Pressable onPress={reset} style={styles.newChat} accessibilityRole="button">
                <Text style={styles.link}>New chat</Text>
              </Pressable>
            ) : null,
        }}
      />
      <ScrollView
        ref={scrollRef}
        contentContainerStyle={[ui.content, { flexGrow: 1 }]}
        onContentSizeChange={() => scrollRef.current?.scrollToEnd({ animated: true })}
      >
        {messages.length === 0 && (
          <View style={{ gap: 8 }}>
            <Text style={ui.detail}>
              Ask for recipes (&quot;Italian tonight&quot;, &quot;high protein, under 30 minutes&quot;) or tell it what you ate.
              Recipes are real ones, ranked by what&apos;s in your fridge, what goes bad soon, your goals and tastes.
            </Text>
            <Text style={ui.muted}>General wellness info, not medical advice.</Text>
            {SUGGESTIONS.map((s) => (
              <Pressable key={s} style={styles.suggestion} onPress={() => submit(s)} accessibilityRole="button">
                <Text style={ui.text}>{s}</Text>
              </Pressable>
            ))}
          </View>
        )}
        {messages.map((m) => (
          <View key={m.id} style={{ gap: 8 }}>
            <View style={[styles.bubble, m.role === 'user' ? styles.user : styles.assistant]}>
              <Text style={m.role === 'user' ? styles.userText : ui.text}>{m.text}</Text>
            </View>
            {m.undo && <UndoTurn message={m} onUndo={undoTurn} />}
            {m.recipes && m.recipes.length > 0 && (
              <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 12, alignItems: 'flex-start' }}>
                {m.recipes.map((r) => (
                  <RecipeCardView
                    key={r.id}
                    card={r}
                    proteinFirst={proteinFirst}
                    onPress={() => router.push({ pathname: '/recipe/[id]', params: { id: r.id } })}
                  />
                ))}
              </ScrollView>
            )}
          </View>
        ))}
        {sending && <Text style={ui.detail}>Finding recipes…</Text>}
      </ScrollView>

      <View style={styles.composer}>
        <TextInput
          style={[ui.input, { flex: 1 }]}
          placeholder="e.g. Italian tonight"
          placeholderTextColor={c.muted}
          value={input}
          onChangeText={setInput}
          onSubmitEditing={() => submit(input)}
          returnKeyType="send"
          accessibilityLabel="Message"
        />
        <View style={{ width: 88 }}>
          <Button title="Send" onPress={() => submit(input)} disabled={sending} />
        </View>
      </View>
    </KeyboardAvoidingView>
  );
}

/** "Undo: puts back 400 g chicken breast, 30 g butter" under the reply that did it; "Undone" afterwards. */
function UndoTurn({ message, onUndo }: { message: ChatMessage; onUndo: (m: ChatMessage) => Promise<void> }) {
  const styles = useStyles();
  const showSnack = useSnackbar();
  const [busy, setBusy] = useState(false);
  const done = !!message.undone;

  async function undo() {
    setBusy(true);
    try {
      await onUndo(message);
    } catch (e) {
      showSnack({ message: `Couldn't undo: ${(e as Error).message}` });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Pressable
      onPress={undo}
      disabled={done || busy}
      accessibilityRole="button"
      accessibilityState={{ disabled: done || busy }}
      style={({ pressed }) => [styles.undo, done && styles.undone, pressed && { opacity: 0.6 }]}
    >
      <Text style={[styles.undoLabel, done && styles.undoneLabel]}>{done ? 'Undone' : message.undo}</Text>
    </Pressable>
  );
}

const useStyles = makeStyles((c, size) => ({
  newChat: { minHeight: 44, justifyContent: 'center', paddingHorizontal: 16 },
  link: { color: c.accent, fontSize: size(15), fontWeight: '600' },
  bubble: { padding: 12, borderRadius: 12, maxWidth: '85%' },
  user: { alignSelf: 'flex-end', backgroundColor: c.accent },
  userText: { color: c.onAccent, fontSize: size(15), lineHeight: size(20) },
  assistant: { alignSelf: 'flex-start', backgroundColor: c.card, borderColor: c.border, borderWidth: 1 },
  suggestion: { backgroundColor: c.card, borderColor: c.border, borderWidth: 1, borderRadius: 12, padding: 16, minHeight: 48 },
  undo: {
    alignSelf: 'flex-start',
    maxWidth: '85%',
    minHeight: 44,
    justifyContent: 'center',
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: c.accent,
  },
  undone: { borderColor: c.border },
  undoLabel: { color: c.accent, fontSize: size(15), lineHeight: size(20), fontWeight: '600' },
  undoneLabel: { color: c.textSecondary },
  composer: { flexDirection: 'row', alignItems: 'center', gap: 8, padding: 12, borderTopColor: c.border, borderTopWidth: 1 },
}));
