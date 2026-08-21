#include "ButtonMap.h"
#include <HID-Project.h>

uint8_t resolveMouseButton(const char *name) {
  if (strcmp(name, "LEFT") == 0) return MOUSE_LEFT;
  if (strcmp(name, "RIGHT") == 0) return MOUSE_RIGHT;
  if (strcmp(name, "MIDDLE") == 0) return MOUSE_MIDDLE;
  return 0;
}
