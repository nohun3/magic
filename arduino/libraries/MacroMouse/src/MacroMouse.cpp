#include "MacroMouse.h"
#include <HID-Project.h>

MacroMouse::MacroMouse() {
  for (uint8_t i = 0; i < MM_MAX_PENDING_RELEASES; i++) {
    _pending[i].active = false;
  }
}

void MacroMouse::begin() {
  AbsoluteMouse.begin();
}

void MacroMouse::update() {
  unsigned long now = millis();
  for (uint8_t i = 0; i < MM_MAX_PENDING_RELEASES; i++) {
    if (_pending[i].active && (long)(now - _pending[i].releaseAtMillis) >= 0) {
      AbsoluteMouse.release(_pending[i].button);
      _pending[i].active = false;
    }
  }
}

void MacroMouse::moveTo(int x, int y) {
  AbsoluteMouse.moveTo(x, y);
}

bool MacroMouse::click(uint8_t button, unsigned long holdMs) {
  for (uint8_t i = 0; i < MM_MAX_PENDING_RELEASES; i++) {
    if (!_pending[i].active) {
      _pending[i].button = button;
      _pending[i].releaseAtMillis = millis() + holdMs;
      _pending[i].active = true;
      AbsoluteMouse.press(button);
      return true;
    }
  }
  return false;  // no free slot
}

void MacroMouse::buttonDown(uint8_t button) {
  AbsoluteMouse.press(button);
}

void MacroMouse::buttonUp(uint8_t button) {
  AbsoluteMouse.release(button);
  for (uint8_t i = 0; i < MM_MAX_PENDING_RELEASES; i++) {
    if (_pending[i].active && _pending[i].button == button) {
      _pending[i].active = false;
    }
  }
}

void MacroMouse::releaseAll() {
  AbsoluteMouse.releaseAll();
  for (uint8_t i = 0; i < MM_MAX_PENDING_RELEASES; i++) {
    _pending[i].active = false;
  }
}
