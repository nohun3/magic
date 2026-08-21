#include "MacroKeyboard.h"
#include <Keyboard.h>

MacroKeyboard::MacroKeyboard() {
  for (uint8_t i = 0; i < MK_MAX_PENDING_RELEASES; i++) {
    _pending[i].active = false;
  }
}

void MacroKeyboard::begin() {
  Keyboard.begin();
}

void MacroKeyboard::update() {
  unsigned long now = millis();
  for (uint8_t i = 0; i < MK_MAX_PENDING_RELEASES; i++) {
    // Signed subtraction so this still works correctly across a
    // millis() rollover (~49 days uptime), instead of a direct >= compare.
    if (_pending[i].active && (long)(now - _pending[i].releaseAtMillis) >= 0) {
      Keyboard.release(_pending[i].keycode);
      _pending[i].active = false;
    }
  }
}

bool MacroKeyboard::schedule(uint8_t keycode, unsigned long holdMs) {
  for (uint8_t i = 0; i < MK_MAX_PENDING_RELEASES; i++) {
    if (!_pending[i].active) {
      _pending[i].keycode = keycode;
      _pending[i].releaseAtMillis = millis() + holdMs;
      _pending[i].active = true;
      return true;
    }
  }
  return false;  // no free slot
}

bool MacroKeyboard::tap(uint8_t keycode, unsigned long holdMs) {
  if (!schedule(keycode, holdMs)) return false;
  Keyboard.press(keycode);
  return true;
}

bool MacroKeyboard::tapCombo(uint8_t keycode1, uint8_t keycode2, unsigned long holdMs) {
  uint8_t free1 = MK_MAX_PENDING_RELEASES, free2 = MK_MAX_PENDING_RELEASES;
  for (uint8_t i = 0; i < MK_MAX_PENDING_RELEASES; i++) {
    if (!_pending[i].active) {
      if (free1 == MK_MAX_PENDING_RELEASES) {
        free1 = i;
      } else {
        free2 = i;
        break;
      }
    }
  }
  if (free1 == MK_MAX_PENDING_RELEASES || free2 == MK_MAX_PENDING_RELEASES) return false;

  unsigned long releaseAt = millis() + holdMs;
  _pending[free1].keycode = keycode1;
  _pending[free1].releaseAtMillis = releaseAt;
  _pending[free1].active = true;
  _pending[free2].keycode = keycode2;
  _pending[free2].releaseAtMillis = releaseAt;
  _pending[free2].active = true;

  Keyboard.press(keycode1);
  Keyboard.press(keycode2);
  return true;
}

void MacroKeyboard::keyDown(uint8_t keycode) {
  Keyboard.press(keycode);
}

void MacroKeyboard::keyUp(uint8_t keycode) {
  Keyboard.release(keycode);
  // Cancel any pending auto-release for this key so update() doesn't
  // later send a redundant release for a key that's already up.
  for (uint8_t i = 0; i < MK_MAX_PENDING_RELEASES; i++) {
    if (_pending[i].active && _pending[i].keycode == keycode) {
      _pending[i].active = false;
    }
  }
}

void MacroKeyboard::releaseAll() {
  Keyboard.releaseAll();
  for (uint8_t i = 0; i < MK_MAX_PENDING_RELEASES; i++) {
    _pending[i].active = false;
  }
}
