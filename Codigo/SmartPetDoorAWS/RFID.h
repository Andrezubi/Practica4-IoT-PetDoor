#pragma once
#include <Arduino.h>
#include <SPI.h>
#include <MFRC522.h>

// ─────────────────────────────────────────────────────────────────────────────
// RFID — wraps MFRC522 for tag detection and UID reading
//
// Wiring (RC522 → ESP32):
//   SDA  → GPIO 5   (SS_PIN)
//   SCK  → GPIO 18
//   MOSI → GPIO 23
//   MISO → GPIO 19
//   RST  → GPIO 4   (RST_PIN)
//   3.3V → 3.3V
//   GND  → GND
// ─────────────────────────────────────────────────────────────────────────────

class RFID {
public:
  // Internal state of the RFID reader
  enum State : byte {
    IDLE,        // no tag present
    TAG_PRESENT, // a tag is in range and has been read
    TAG_REMOVED  // tag was present last tick, now gone
  };

private:
  MFRC522  mfrc522;
  State    state        = IDLE;
  String   currentUID   = "";   // UID of the tag currently in range
  String   previousUID  = "";   // UID from the previous read cycle
  unsigned long lastReadMillis  = 0;
  // If no new read arrives within this window, we consider the tag removed
  static const unsigned long TAG_TIMEOUT_MS = 1500;

public:
  // ── Constructor ────────────────────────────────────────────────────────────
  RFID(byte ssPin, byte rstPin) : mfrc522(ssPin, rstPin) {}

  // ── init() — call once in setup() after SPI.begin() ───────────────────────
  void init() {
    mfrc522.PCD_Init();
    Serial.println("[RFID] Reader initialized.");
    mfrc522.PCD_DumpVersionToSerial();
  }

  // ── update() — call every loop() ─────────────────────────────────────────
  // Returns true if state changed (new tag or tag removed)
  bool update() {
    unsigned long now = millis();
    bool changed = false;

    if (mfrc522.PICC_IsNewCardPresent() && mfrc522.PICC_ReadCardSerial()) {
      // Build UID string
      String uid = "";
      for (byte i = 0; i < mfrc522.uid.size; i++) {
        if (mfrc522.uid.uidByte[i] < 0x10) uid += "0";
        uid += String(mfrc522.uid.uidByte[i], HEX);
        if (i < mfrc522.uid.size - 1) uid += ":";
      }
      uid.toUpperCase();

      lastReadMillis = now;

      if (uid != currentUID) {
        previousUID = currentUID;
        currentUID  = uid;
        state       = TAG_PRESENT;
        changed     = true;
        Serial.print("[RFID] Tag detected → UID: ");
        Serial.println(currentUID);
      }

    } else {
      // No new card — check timeout
      if (state == TAG_PRESENT && (now - lastReadMillis > TAG_TIMEOUT_MS)) {
        Serial.print("[RFID] Tag removed → was: ");
        Serial.println(currentUID);
        previousUID = currentUID;
        currentUID  = "";
        state       = TAG_REMOVED;
        changed     = true;
      } else if (state == TAG_REMOVED) {
        state   = IDLE;
      }
    }

    return changed;
  }

  // ── Getters ────────────────────────────────────────────────────────────────
  State   getState()       const { return state; }
  String  getCurrentUID()  const { return currentUID; }
  String  getPreviousUID() const { return previousUID; }
  bool    isTagPresent()   const { return state == TAG_PRESENT; }
};