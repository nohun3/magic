# Game Screen Monitor + Arduino HID Macro

Monitors HP/MP on screen via OCR and triggers real USB HID keyboard/mouse
input through an Arduino when they drop below configured thresholds. See
[CLAUDE.md](CLAUDE.md) for the full spec and design rules this project
follows.

Status: all 11 development steps (screen capture through UI/settings)
are implemented and individually tested. See "Development steps" below
for what was verified at each stage.

## Requirements

- Windows (uses `pywin32` for window lookup and DPI-affected coordinates)
- Python 3.10+
- An Arduino Leonardo or Pro Micro (ATmega32u4 -- needs native USB HID;
  boards like the Uno/Nano can't do this)
- [`arduino-cli`](https://arduino.github.io/arduino-cli/) with the
  `arduino:avr` core and the `HID-Project` library installed

## Setup

1. **PC-side Python environment**
   ```
   python -m venv .venv
   ./.venv/Scripts/python -m pip install -r pc/requirements.txt
   ```

2. **Arduino firmware** -- compile and upload `arduino/main`:
   ```
   arduino-cli compile --fqbn arduino:avr:leonardo --libraries arduino/libraries --upload -p COMxx arduino/main
   ```
   Find the port with:
   ```
   ./.venv/Scripts/python -c "import serial.tools.list_ports as lp; [print(p) for p in lp.comports()]"
   ```
   The board re-enumerates (and its COM port can change) on every
   upload/reset -- re-check the port after uploading and update
   `pc/config/settings.yaml`'s `serial.port` (or the UI's "Serial port"
   field + Save Settings).

3. **Configure `pc/config/settings.yaml`** -- see the comments in the
   file itself for what each section does. At minimum:
   - `capture.window_title`: a substring of your game window's title
   - `hpmp_anchor.template` + `hp.content_offset` / `mp.content_offset`:
     the HP/MP bar location (see `templates/roi_hpmp_anchor.png` for the
     current example, and [pc/detector/README.md](pc/detector/README.md)
     for how to make your own if the UI theme/resolution differs)
   - `conditions.hp_low` / `conditions.mp_low`: thresholds, cooldowns,
     and which key each fires
   - `serial.port`: your Arduino's current COM port

## Running

**GUI** (recommended -- lets you view/edit settings and Start/STOP without touching a terminal):
```
./.venv/Scripts/python -m pc.ui.app_window
```

**CLI** (same pipeline, no GUI):
```
./.venv/Scripts/python -m pc.main
```
Ctrl+C to stop.

Both always run the same safety-stop sequence on exit (clear the action
queue, tell the Arduino to release every key/mouse button, reset
condition cooldowns) -- see `MacroApp.stop()` in `pc/main.py`. The
Arduino also self-releases everything if it goes 5 seconds without
hearing from the PC at all (`WATCHDOG_TIMEOUT_MS` in
`arduino/main/main.ino`), so a crashed process or unplugged USB cable
doesn't leave a key stuck down.

## Project structure

```
pc/
  capture/    screen/window capture (mss + win32 window lookup)
  detector/   HP/MP reading: template match + PaddleOCR
  condition/  threshold + cooldown trigger logic
  action/     action sequences (multi-step, non-blocking, with waits)
  queue/      PC-side outgoing action queue + dispatcher
  serial/     serial link to the Arduino (background reader thread)
  config/     settings.yaml + loaders
  ui/         Tkinter control panel
  main.py     full pipeline entry point (capture -> ... -> serial)

arduino/
  libraries/  SerialProtocol, MacroKeyboard, MacroMouse (each its own
              Arduino library rather than the flat folders CLAUDE.md's
              structure sketch shows, since a sketch's .ino must share
              its folder's name -- libraries were the practical way to
              keep the same one-concern-per-file split while staying
              buildable)
  main/       the actual sketch (main.ino)
```

## Development steps

Each step was implemented and tested individually before moving to the
next, per `CLAUDE.md`'s development rules:

1. Screen capture (`pc/capture`) -- window-based, position resolved once at startup
2. HP detection (`pc/detector`) -- verified against known HP values
3. MP detection (`pc/detector`) -- verified against known MP values (needed OCR, not color-fill -- see `pc/detector/README.md`)
4. HP/MP condition judgment (`pc/condition`) -- cooldown + independence verified via unit test
5. Arduino serial communication (`arduino/libraries/SerialProtocol`, `pc/serial`) -- round-trip verified (~5ms RTT)
6. Arduino keyboard input (`arduino/libraries/MacroKeyboard`) -- verified by typing into a real text editor
7. Arduino mouse input (`arduino/libraries/MacroMouse`) -- absolute positioning verified via `GetCursorPos` (max 1px error)
8. Event queue (`pc/queue`, `arduino/libraries/SerialProtocol`) -- found and fixed a command-loss bug under burst load
9. Action sequences (`pc/action`) -- non-blocking timing verified against real hardware (~10ms accuracy)
10. Full integration (`pc/main.py`) -- end-to-end run against the live game; added the connection watchdog
11. UI + settings persistence (`pc/ui`) -- comment-preserving settings save verified; Start/STOP exercised against the real pipeline

## Known limitations / things to revisit

- **DPI scaling**: screen capture happens in physical pixels, but
  `GetCursorPos`/`GetSystemMetrics`/window rects are in DPI-virtualized
  logical pixels on a scaled display. `pc/action/mouse_coords.py`
  assumes whatever screen size it's given is consistent with the mouse
  coordinate space it's converting into -- if you wire a detected
  on-screen position into a mouse-click target, double check both sides
  are in the same coordinate space first.
- **`sequences.hp_low_example`** in `settings.yaml` is not wired to a
  real condition and uses placeholder mouse coordinates (0, 0) -- add
  `sequence: hp_low_example` to a condition and fix the coordinates
  before relying on it.
- The HP/MP detector anchor (`templates/roi_hpmp_anchor.png`) is
  specific to the current game window size; see `pc/detector/README.md`
  to recalibrate if that changes.
