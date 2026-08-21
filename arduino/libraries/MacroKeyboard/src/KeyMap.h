// Maps a key name string (as sent over serial, e.g. "F1", "A", "CTRL")
// to the keycode value the stock Arduino Keyboard library expects.
#ifndef KEY_MAP_H
#define KEY_MAP_H

#include <Arduino.h>

// Returns 0 if `name` isn't a recognized key. 0 is not a valid keycode
// for any real key, so callers can treat it as "unresolved".
uint8_t resolveKeyCode(const char *name);

#endif
