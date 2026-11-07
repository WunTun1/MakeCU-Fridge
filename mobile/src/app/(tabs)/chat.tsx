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
import { api } from '@/lib/api';
import { colors, ui } from '@/lib/theme';

type Message = { role: 'user' | 'assistant'; text: string };

const SUGGESTIONS = ["I'm feeling Italian and need more protein", 'Something quick with what expires soon'];

export default function Chat() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const scrollRef = useRef<ScrollViewInstance>(null);

  async function send(text: string) {
    const message = text.trim();
    if (!message || sending) return;
    setInput('');
    setSending(true);
    setMessages((m) => [...m, { role: 'user', text: message }]);
    try {
      const { reply } = await api.chat(message);
      setMessages((m) => [...m, { role: 'assistant', text: reply }]);
    } catch (e) {
      setMessages((m) => [...m, { role: 'assistant', text: `Couldn't reach the backend: ${(e as Error).message}` }]);
    } finally {
      setSending(false);
    }
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
              Ask for meal ideas — recipes are checked against your real inventory, goals, and allergies.
              General wellness info, not medical advice.
            </Text>
            {SUGGESTIONS.map((s) => (
              <Text key={s} style={[ui.card, ui.text]} onPress={() => send(s)}>
                {s}
              </Text>
            ))}
          </View>
        )}
        {messages.map((m, i) => (
          <View key={i} style={[styles.bubble, m.role === 'user' ? styles.user : styles.assistant]}>
            <Text style={{ color: m.role === 'user' ? colors.onAccent : colors.text, fontSize: 15 }}>{m.text}</Text>
          </View>
        ))}
        {sending && <Text style={ui.muted}>…thinking</Text>}
      </ScrollView>

      <View style={[ui.row, { padding: 12, borderTopColor: colors.border, borderTopWidth: 1 }]}>
        <TextInput
          style={[ui.input, { flex: 1 }]}
          placeholder="Ask the nutritionist…"
          placeholderTextColor={colors.muted}
          value={input}
          onChangeText={setInput}
          onSubmitEditing={() => send(input)}
          returnKeyType="send"
        />
        <View style={{ width: 80 }}>
          <Button title="Send" onPress={() => send(input)} disabled={sending} />
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
