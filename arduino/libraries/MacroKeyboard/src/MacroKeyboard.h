// Non-blocking wrapper around the stock Arduino Keyboard (USB HID)
// library. A "tap" needs to stay down for at least a few milliseconds
// for most applications/games to register it (an instant press+release
// can land between two of the target app's input polls and be missed
// entirely) -- but this firmware never uses delay(), so the release is
// scheduled with millis() instead and applied from update(), which must
// be called every loop() iteration.
#ifndef MACRO_KEYBOARD_H
#define MACRO_KEYBOARD_H

#include <Arduino.h>

#define MK_MAX_PENDING_RELEASES 4

class MacroKeyboard {
public:
  MacroKeyboard();

  void begin();

  // Call every loop() iteration. Releases any keys whose hold time has
  // elapsed. Never blocks.
  void update();

  // Press `keycode` now and schedule an automatic release after
  // `holdMs`. Returns false (and presses nothing) if there's no free
  // release slot -- callers should surface that as an error rather than
  // silently pressing a key that might never auto-release.
  bool tap(uint8_t keycode, unsigned long holdMs);

  // Press two keys together (a "double key" combo, e.g. Shift+1),
  // auto-released together after holdMs. Needs two free slots.
  bool tapCombo(uint8_t keycode1, uint8_t keycode2, unsigned long holdMs);

  // Manual hold control, for keys that should stay down until
  // explicitly released (e.g. a movement key) rather than on a timer.
  void keyDown(uint8_t keycode);
  void keyUp(uint8_t keycode);

  // Release every key this class knows about right now (safety stop).
  void releaseAll();

private:
  struct PendingRelease {
    uint8_t keycode;
    unsigned long releaseAtMillis;
    bool active;
  };

  PendingRelease _pending[MK_MAX_PENDING_RELEASES];

  bool schedule(uint8_t keycode, unsigned long holdMs);
};

#endif
