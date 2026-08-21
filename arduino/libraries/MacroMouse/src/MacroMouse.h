// Non-blocking wrapper around HID-Project's AbsoluteMouse.
//
// Absolute positioning (moveTo) means the PC can place the cursor at an
// exact screen coordinate in one command instead of walking it there
// with relative deltas -- but it requires HID-Project (the stock
// Arduino Mouse library only supports relative movement).
//
// Same auto-release-on-a-timer design as MacroKeyboard, for the same
// reason: a click needs to stay down a few milliseconds to reliably
// register, and this firmware never uses delay().
//
// Coordinate values passed to moveTo() here are NOT screen pixels --
// they're whatever AbsoluteMouse.moveTo() expects (signed 16-bit, 0 =
// screen center, see AbsoluteMouseAPI.hpp). Converting a real screen
// pixel coordinate into that range is the PC side's job (it's the one
// that knows the screen resolution); see pc/action/mouse_coords.py.
#ifndef MACRO_MOUSE_H
#define MACRO_MOUSE_H

#include <Arduino.h>

#define MM_MAX_PENDING_RELEASES 4

class MacroMouse {
public:
  MacroMouse();

  void begin();

  // Call every loop() iteration. Releases any buttons whose hold time
  // has elapsed. Never blocks.
  void update();

  void moveTo(int x, int y);

  // Press `button` now and schedule an automatic release after holdMs.
  // Returns false (and presses nothing) if there's no free release slot.
  bool click(uint8_t button, unsigned long holdMs);

  // Manual hold control.
  void buttonDown(uint8_t button);
  void buttonUp(uint8_t button);

  // Release every button this class knows about right now (safety stop).
  void releaseAll();

private:
  struct PendingRelease {
    uint8_t button;
    unsigned long releaseAtMillis;
    bool active;
  };

  PendingRelease _pending[MM_MAX_PENDING_RELEASES];
};

#endif
