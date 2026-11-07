/*
 * ReFridge scale firmware (ESP32 + HX711 load cells + door switch)
 *
 * Streams newline-delimited JSON over USB serial:
 *   {"t":"w","shelf":0,"grams":842.3}
 *   {"t":"door","open":true}
 *
 * Accepts commands from the host over the same serial line:
 *   tare <shelf>
 *   cal <shelf> <known_grams>
 *
 * Calibration (scale factor + tare offset per shelf) is kept in flash
 * (Preferences) so it survives a reboot. Re-tare occasionally with an empty
 * shelf to cancel slow temperature drift (see architecture doc section 3).
 *
 * Library: bogde/HX711 (https://github.com/bogde/HX711)
 */

#include <HX711.h>
#include <Preferences.h>

#define NUM_SHELVES 4
#define HX711_SAMPLE_RATE_HZ 80   // RATE pin held HIGH on each HX711 module

const uint8_t DOUT_PINS[NUM_SHELVES] = {4, 16, 17, 5};
const uint8_t SCK_PINS[NUM_SHELVES]  = {2, 15, 18, 19};
const uint8_t DOOR_SWITCH_PIN = 21;  // reed/microswitch, pulled up, LOW = closed

HX711 scales[NUM_SHELVES];
Preferences prefs;

float scaleFactor[NUM_SHELVES];
long tareOffset[NUM_SHELVES];

bool lastDoorOpen = false;
unsigned long lastWeighMs = 0;
const unsigned long WEIGH_INTERVAL_MS = 100;  // ~10 Hz host-facing stream

void loadCalibration() {
  prefs.begin("refridge", /*readOnly=*/true);
  for (int i = 0; i < NUM_SHELVES; i++) {
    String sf = "sf" + String(i);
    String to = "to" + String(i);
    scaleFactor[i] = prefs.getFloat(sf.c_str(), 1.0);
    tareOffset[i] = prefs.getLong(to.c_str(), 0);
  }
  prefs.end();
}

void saveCalibration(int shelf) {
  prefs.begin("refridge", /*readOnly=*/false);
  prefs.putFloat(("sf" + String(shelf)).c_str(), scaleFactor[shelf]);
  prefs.putLong(("to" + String(shelf)).c_str(), tareOffset[shelf]);
  prefs.end();
}

void setup() {
  Serial.begin(115200);
  pinMode(DOOR_SWITCH_PIN, INPUT_PULLUP);

  loadCalibration();

  for (int i = 0; i < NUM_SHELVES; i++) {
    scales[i].begin(DOUT_PINS[i], SCK_PINS[i]);
    scales[i].set_scale(scaleFactor[i]);
    scales[i].set_offset(tareOffset[i]);
  }

  lastDoorOpen = digitalRead(DOOR_SWITCH_PIN) == LOW;
}

void handleCommand(const String &line) {
  if (line.startsWith("tare ")) {
    int shelf = line.substring(5).toInt();
    if (shelf >= 0 && shelf < NUM_SHELVES) {
      scales[shelf].tare();
      tareOffset[shelf] = scales[shelf].get_offset();
      saveCalibration(shelf);
      Serial.printf("{\"t\":\"ack\",\"cmd\":\"tare\",\"shelf\":%d}\n", shelf);
    }
  } else if (line.startsWith("cal ")) {
    int sepIdx = line.indexOf(' ', 4);
    int shelf = line.substring(4, sepIdx).toInt();
    float knownGrams = line.substring(sepIdx + 1).toFloat();
    if (shelf >= 0 && shelf < NUM_SHELVES && knownGrams > 0) {
      long rawNoTare = scales[shelf].read_average(10) - tareOffset[shelf];
      scaleFactor[shelf] = rawNoTare / knownGrams;
      scales[shelf].set_scale(scaleFactor[shelf]);
      saveCalibration(shelf);
      Serial.printf("{\"t\":\"ack\",\"cmd\":\"cal\",\"shelf\":%d,\"factor\":%.4f}\n", shelf, scaleFactor[shelf]);
    }
  }
}

void loop() {
  // Host commands (tare / cal)
  if (Serial.available()) {
    String line = Serial.readStringUntil('\n');
    line.trim();
    if (line.length() > 0) handleCommand(line);
  }

  // Door switch — report on every change, not just a poll
  bool doorOpen = digitalRead(DOOR_SWITCH_PIN) == LOW;
  if (doorOpen != lastDoorOpen) {
    lastDoorOpen = doorOpen;
    Serial.printf("{\"t\":\"door\",\"open\":%s}\n", doorOpen ? "true" : "false");
  }

  // Weight stream
  unsigned long now = millis();
  if (now - lastWeighMs >= WEIGH_INTERVAL_MS) {
    lastWeighMs = now;
    for (int i = 0; i < NUM_SHELVES; i++) {
      if (scales[i].is_ready()) {
        float grams = scales[i].get_units(1);
        Serial.printf("{\"t\":\"w\",\"shelf\":%d,\"grams\":%.1f}\n", i, grams);
      }
    }
  }
}
