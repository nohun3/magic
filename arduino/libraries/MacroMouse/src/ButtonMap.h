// Maps a button name string ("LEFT", "RIGHT", "MIDDLE") to the
// MOUSE_LEFT/MOUSE_RIGHT/MOUSE_MIDDLE constants HID-Project expects.
#ifndef BUTTON_MAP_H
#define BUTTON_MAP_H

#include <Arduino.h>

// Returns 0 if `name` isn't a recognized button. 0 is not a valid
// button bitmask, so callers can treat it as "unresolved".
uint8_t resolveMouseButton(const char *name);

#endif
