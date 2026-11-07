import FontAwesome from '@expo/vector-icons/FontAwesome';
import { type ReactNode, useMemo } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import { type Palette, useColors } from '@/lib/theme';

/**
 * Touch-friendly panel; tap outside or the big X to close. Drawn as an overlay
 * inside the kiosk (not a native Modal) so it stays within the screen, including
 * the desktop screen simulator. Render it as the last child of the kiosk root.
 */
export function KioskModal({
  visible,
  title,
  onClose,
  children,
}: {
  visible: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  const colors = useColors();
  const styles = useMemo(() => makeStyles(colors), [colors]);
  if (!visible) return null;
  return (
    <Pressable style={styles.backdrop} onPress={onClose}>
      {/* Inner Pressable swallows taps so touching the panel doesn't close it. */}
      <Pressable style={styles.panel} onPress={() => {}}>
        <View style={styles.header}>
          <Text style={styles.title}>{title}</Text>
          <Pressable onPress={onClose} hitSlop={16} style={styles.close}>
            <FontAwesome name="close" size={26} color={colors.text} />
          </Pressable>
        </View>
        <ScrollView contentContainerStyle={{ gap: 14, paddingBottom: 8 }}>{children}</ScrollView>
      </Pressable>
    </Pressable>
  );
}

const makeStyles = (colors: Palette) =>
  StyleSheet.create({
    backdrop: {
      position: 'absolute',
      top: 0,
      right: 0,
      bottom: 0,
      left: 0,
      zIndex: 10,
      backgroundColor: '#000b',
      justifyContent: 'center',
      alignItems: 'center',
      padding: 20,
    },
    panel: {
      width: '100%',
      maxWidth: 760,
      maxHeight: '100%',
      backgroundColor: colors.bg,
      borderColor: colors.border,
      borderWidth: 1,
      borderRadius: 20,
      padding: 18,
      gap: 12,
    },
    header: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
    },
    title: { color: colors.text, fontSize: 24, fontWeight: '700', flex: 1 },
    close: {
      width: 52,
      height: 52,
      alignItems: 'center',
      justifyContent: 'center',
    },
  });
