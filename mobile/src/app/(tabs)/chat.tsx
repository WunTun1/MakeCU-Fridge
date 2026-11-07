import { router } from 'expo-router';
import { useRef, useState } from 'react';
import {
  KeyboardAvoidingView,
  Platform,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
  type ScrollViewInstance,
} from 'react-native';

import { Button } from '@/components/Button';
import { RecipeCardView } from '@/components/recipes/RecipeCardView';
import { colors, ui } from '@/lib/theme';
import { useChat } from '@/lib/useChat';

const SUGGESTIONS = [
  "I'm feeling Italian and need more protein",
  'Something quick with what expires soon',
  'What can I make without shopping?',
];

export default function Chat() {
  const { messages, sending, send } = useChat();
  const [input, setInput] = useState('');
  const scrollRef = useRef<ScrollViewInstance>(null);

  function submit(text: string) {
    setInput('');
    send(text);
  }

  return (
    <KeyboardAvoidingView
      style={ui.screen}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      keyboardVerticalOffset={90}
    >
      <ScrollView
        ref={scrollRef}
        contentContainerStyle={[ui.content, { flexGrow: 1 }]}
        onContentSizeChange={() => scrollRef.current?.scrollToEnd({ animated: true })}
      >
        {messages.length === 0 && (
          <View style={{ gap: 8 }}>
            <Text style={ui.muted}>
              Ask for anything — &quot;Italian tonight&quot;, &quot;high protein, under 30 minutes&quot;. Suggestions are real
              recipes, ranked by what&apos;s in your fridge, what&apos;s expiring, your goals and tastes. General wellness
              info, not medical advice.
            </Text>
            {SUGGESTIONS.map((s) => (
              <Text key={s} style={[ui.card, ui.text]} onPress={() => submit(s)}>
                {s}
              </Text>
            ))}
          </View>
        )}
        {messages.map((m) => (
          <View key={m.id} style={{ gap: 8 }}>
            <View style={[styles.bubble, m.role === 'user' ? styles.user : styles.assistant]}>
              <Text style={{ color: m.role === 'user' ? colors.onAccent : colors.text, fontSize: 15 }}>{m.text}</Text>
            </View>
            {m.recipes && m.recipes.length > 0 && (
              <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 10 }}>
                {m.recipes.map((r) => (
                  <RecipeCardView
                    key={r.id}
                    card={r}
                    onPress={() => router.push({ pathname: '/recipe/[id]', params: { id: r.id } })}
                  />
                ))}
              </ScrollView>
            )}
          </View>
        ))}
        {sending && <Text style={ui.muted}>…finding recipes</Text>}
      </ScrollView>

      <View style={[ui.row, { padding: 12, borderTopColor: colors.border, borderTopWidth: 1 }]}>
        <TextInput
          style={[ui.input, { flex: 1 }]}
          placeholder="I want Italian…"
          placeholderTextColor={colors.muted}
          value={input}
          onChangeText={setInput}
          onSubmitEditing={() => submit(input)}
          returnKeyType="send"
        />
        <View style={{ width: 80 }}>
          <Button title="Send" onPress={() => submit(input)} disabled={sending} />
        </View>
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  bubble: { padding: 12, borderRadius: 14, maxWidth: '85%' },
  user: { alignSelf: 'flex-end', backgroundColor: colors.accent },
  assistant: { alignSelf: 'flex-start', backgroundColor: colors.card, borderColor: colors.border, borderWidth: 1 },
});
