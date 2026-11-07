import { CameraView, useCameraPermissions, type BarcodeScanningResult } from 'expo-camera';
import { router } from 'expo-router';
import { useRef, useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { Button } from '@/components/Button';
import { api } from '@/lib/api';
import { colors, ui } from '@/lib/theme';

export default function Scan() {
  const [permission, requestPermission] = useCameraPermissions();
  const [status, setStatus] = useState<string | null>(null);
  // onBarcodeScanned fires repeatedly while a code is in view; only handle the first.
  const handling = useRef(false);

  if (!permission) return <View style={ui.screen} />;

  if (!permission.granted) {
    return (
      <View style={[ui.screen, ui.content, { justifyContent: 'center' }]}>
        <Text style={[ui.text, { textAlign: 'center' }]}>Camera access is needed to scan barcodes.</Text>
        <Button title="Allow camera" onPress={requestPermission} />
      </View>
    );
  }

  async function onScanned({ data }: BarcodeScanningResult) {
    if (handling.current) return;
    handling.current = true;
    setStatus(`Looking up ${data}…`);
    try {
      await api.barcode(data);
      router.dismissAll();
    } catch {
      setStatus(`Barcode ${data} not found — try typing it in instead.`);
      setTimeout(() => (handling.current = false), 2000);
    }
  }

  return (
    <View style={ui.screen}>
      <CameraView
        style={StyleSheet.absoluteFill}
        facing="back"
        barcodeScannerSettings={{ barcodeTypes: ['ean13', 'ean8', 'upc_a', 'upc_e'] }}
        onBarcodeScanned={onScanned}
      />
      <View style={styles.overlay}>
        <View style={styles.frame} />
        <Text style={styles.status}>{status ?? 'Point at a product barcode'}</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  overlay: { ...StyleSheet.absoluteFill, alignItems: 'center', justifyContent: 'center', gap: 16 },
  frame: { width: 260, height: 140, borderColor: colors.accent, borderWidth: 2, borderRadius: 12 },
  status: { color: colors.text, backgroundColor: '#000a', padding: 10, borderRadius: 8, overflow: 'hidden' },
});
