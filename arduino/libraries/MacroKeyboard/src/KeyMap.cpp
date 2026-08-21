#include "KeyMap.h"
#include <Keyboard.h>

uint8_t resolveKeyCode(const char *name) {
  if (name[0] == '\0') return 0;

  // Function keys: F1-F12
  if ((name[0] == 'F' || name[0] == 'f') && name[1] != '\0') {
    int num = atoi(name + 1);
    switch (num) {
      case 1: return KEY_F1;
      case 2: return KEY_F2;
      case 3: return KEY_F3;
      case 4: return KEY_F4;
      case 5: return KEY_F5;
      case 6: return KEY_F6;
      case 7: return KEY_F7;
      case 8: return KEY_F8;
      case 9: return KEY_F9;
      case 10: return KEY_F10;
      case 11: return KEY_F11;
      case 12: return KEY_F12;
    }
    // fall through -- not a function key (e.g. a single-char key "F")
  }

  // Single printable character: letters and digits.
  if (name[1] == '\0') {
    char c = name[0];
    if (c >= 'a' && c <= 'z') return (uint8_t)c;
    if (c >= 'A' && c <= 'Z') return (uint8_t)(c - 'A' + 'a');  // Keyboard lib keys off lowercase ASCII
    if (c >= '0' && c <= '9') return (uint8_t)c;
  }

  // Named keys.
  if (strcmp(name, "ENTER") == 0) return KEY_RETURN;
  if (strcmp(name, "ESC") == 0) return KEY_ESC;
  if (strcmp(name, "SPACE") == 0) return ' ';
  if (strcmp(name, "TAB") == 0) return KEY_TAB;
  if (strcmp(name, "BACKSPACE") == 0) return KEY_BACKSPACE;
  if (strcmp(name, "DELETE") == 0) return KEY_DELETE;
  if (strcmp(name, "CTRL") == 0) return KEY_LEFT_CTRL;
  if (strcmp(name, "ALT") == 0) return KEY_LEFT_ALT;
  if (strcmp(name, "SHIFT") == 0) return KEY_LEFT_SHIFT;
  if (strcmp(name, "UP") == 0) return KEY_UP_ARROW;
  if (strcmp(name, "DOWN") == 0) return KEY_DOWN_ARROW;
  if (strcmp(name, "LEFT") == 0) return KEY_LEFT_ARROW;
  if (strcmp(name, "RIGHT") == 0) return KEY_RIGHT_ARROW;

  return 0;  // unresolved
}
