// Game Screen Monitor + Arduino HID Macro -- Arduino firmware.
//
// Step 6 added real USB HID keyboard output:
//   KEY <name> [holdMs]        -- tap: press, auto-release after holdMs (default 30ms)
//   KEYDOWN <name>             -- hold a key down until KEYUP
//   KEYUP <name>               -- release a held key
//   KEYCOMBO <name1>+<name2> [holdMs] -- press both together ("double key"), auto-release together
//
// Step 7 added absolute-coordinate USB HID mouse output (via HID-Project's
// AbsoluteMouse -- the stock Arduino Mouse library only does relative
// movement):
//   MOUSE_MOVE <x> <y>         -- move to (x, y) in AbsoluteMouse's own
//                                  coordinate units, NOT screen pixels --
//                                  the PC side converts pixel -> unit
//                                  (see pc/action/mouse_coords.py) since
//                                  only it knows the screen resolution.
//   MOUSE_CLICK <LEFT|RIGHT|MIDDLE> [holdMs] -- click, auto-release after holdMs
//   MOUSE_DOWN <LEFT|RIGHT|MIDDLE>  -- hold a button down until MOUSE_UP
//   MOUSE_UP <LEFT|RIGHT|MIDDLE>    -- release a held button
//
// STOP releases every key AND mouse button this firmware is tracking
// (safety). PING is unchanged from Step 5.
//
// Step 10 (full integration) adds a connection watchdog: if no command
// arrives for WATCHDOG_TIMEOUT_MS, everything gets released
// automatically. This is what makes "Serial connection drops -> safe
// state" (spec section 11) hold even if the PC side never gets a chance
// to send STOP (crashed, USB unplugged, etc.) -- KEY/MOUSE_CLICK taps
// already auto-release on their own via MacroKeyboard/MacroMouse
// regardless of the link, but a KEYDOWN/MOUSE_DOWN hold with no matching
// KEYUP/MOUSE_UP would otherwise stay stuck forever. The PC side sends a
// PING roughly once a second even when idle specifically to keep this
// watchdog satisfied during a legitimate long hold.
//
// loop() never blocks: every update()/handleCommand() call only touches
// state that's already available and returns immediately.

#include <SerialProtocol.h>
#include <MacroKeyboard.h>
#include <KeyMap.h>
#include <MacroMouse.h>
#include <ButtonMap.h>

SerialProtocol protocol(Serial);
MacroKeyboard macroKeyboard;
MacroMouse macroMouse;

const unsigned long DEFAULT_HOLD_MS = 30;
const unsigned long WATCHDOG_TIMEOUT_MS = 5000;

unsigned long lastCommandMillis = 0;
bool watchdogTripped = false;

void handleCommand(const Command &cmd);

void setup() {
  Serial.begin(115200);
  macroKeyboard.begin();
  macroMouse.begin();
  lastCommandMillis = millis();
}

void loop() {
  protocol.update();
  macroKeyboard.update();
  macroMouse.update();

  // Drain every command that's arrived, not just one -- the queue can
  // hold several if they arrived in a burst (see SerialProtocol.h).
  if (protocol.hasCommand()) {
    lastCommandMillis = millis();
    watchdogTripped = false;
    while (protocol.hasCommand()) {
      Command cmd = protocol.getCommand();
      handleCommand(cmd);
    }
  }

  if (!watchdogTripped && (millis() - lastCommandMillis) > WATCHDOG_TIMEOUT_MS) {
    macroKeyboard.releaseAll();
    macroMouse.releaseAll();
    watchdogTripped = true;  // don't re-trigger every loop while still silent
  }
}

void handleCommand(const Command &cmd) {
  if (strcmp(cmd.type, "PING") == 0) {
    protocol.sendAck(cmd.id);
    return;
  }

  if (strcmp(cmd.type, "KEY") == 0) {
    char keyName[16];
    unsigned long holdMs = DEFAULT_HOLD_MS;
    int parsed = sscanf(cmd.args, "%15s %lu", keyName, &holdMs);
    if (parsed < 1) {
      protocol.sendError(cmd.id, "BAD_ARGS");
      return;
    }
    uint8_t code = resolveKeyCode(keyName);
    if (code == 0) {
      protocol.sendError(cmd.id, "UNKNOWN_KEY");
      return;
    }
    if (!macroKeyboard.tap(code, holdMs)) {
      protocol.sendError(cmd.id, "BUSY");
      return;
    }
    protocol.sendAck(cmd.id);
    return;
  }

  if (strcmp(cmd.type, "KEYDOWN") == 0) {
    uint8_t code = resolveKeyCode(cmd.args);
    if (code == 0) {
      protocol.sendError(cmd.id, "UNKNOWN_KEY");
      return;
    }
    macroKeyboard.keyDown(code);
    protocol.sendAck(cmd.id);
    return;
  }

  if (strcmp(cmd.type, "KEYUP") == 0) {
    uint8_t code = resolveKeyCode(cmd.args);
    if (code == 0) {
      protocol.sendError(cmd.id, "UNKNOWN_KEY");
      return;
    }
    macroKeyboard.keyUp(code);
    protocol.sendAck(cmd.id);
    return;
  }

  if (strcmp(cmd.type, "KEYCOMBO") == 0) {
    char combo[32];
    unsigned long holdMs = DEFAULT_HOLD_MS;
    int parsed = sscanf(cmd.args, "%31s %lu", combo, &holdMs);
    if (parsed < 1) {
      protocol.sendError(cmd.id, "BAD_ARGS");
      return;
    }
    char *plus = strchr(combo, '+');
    if (plus == nullptr) {
      protocol.sendError(cmd.id, "BAD_ARGS");
      return;
    }
    *plus = '\0';
    uint8_t code1 = resolveKeyCode(combo);
    uint8_t code2 = resolveKeyCode(plus + 1);
    if (code1 == 0 || code2 == 0) {
      protocol.sendError(cmd.id, "UNKNOWN_KEY");
      return;
    }
    if (!macroKeyboard.tapCombo(code1, code2, holdMs)) {
      protocol.sendError(cmd.id, "BUSY");
      return;
    }
    protocol.sendAck(cmd.id);
    return;
  }

  if (strcmp(cmd.type, "MOUSE_MOVE") == 0) {
    int x, y;
    int parsed = sscanf(cmd.args, "%d %d", &x, &y);
    if (parsed != 2) {
      protocol.sendError(cmd.id, "BAD_ARGS");
      return;
    }
    macroMouse.moveTo(x, y);
    protocol.sendAck(cmd.id);
    return;
  }

  if (strcmp(cmd.type, "MOUSE_CLICK") == 0) {
    char buttonName[8];
    unsigned long holdMs = DEFAULT_HOLD_MS;
    int parsed = sscanf(cmd.args, "%7s %lu", buttonName, &holdMs);
    if (parsed < 1) {
      protocol.sendError(cmd.id, "BAD_ARGS");
      return;
    }
    uint8_t button = resolveMouseButton(buttonName);
    if (button == 0) {
      protocol.sendError(cmd.id, "UNKNOWN_BUTTON");
      return;
    }
    if (!macroMouse.click(button, holdMs)) {
      protocol.sendError(cmd.id, "BUSY");
      return;
    }
    protocol.sendAck(cmd.id);
    return;
  }

  if (strcmp(cmd.type, "MOUSE_DOWN") == 0) {
    uint8_t button = resolveMouseButton(cmd.args);
    if (button == 0) {
      protocol.sendError(cmd.id, "UNKNOWN_BUTTON");
      return;
    }
    macroMouse.buttonDown(button);
    protocol.sendAck(cmd.id);
    return;
  }

  if (strcmp(cmd.type, "MOUSE_UP") == 0) {
    uint8_t button = resolveMouseButton(cmd.args);
    if (button == 0) {
      protocol.sendError(cmd.id, "UNKNOWN_BUTTON");
      return;
    }
    macroMouse.buttonUp(button);
    protocol.sendAck(cmd.id);
    return;
  }

  if (strcmp(cmd.type, "STOP") == 0) {
    macroKeyboard.releaseAll();
    macroMouse.releaseAll();
    protocol.sendAck(cmd.id);
    return;
  }

  protocol.sendError(cmd.id, "UNKNOWN_CMD");
}
