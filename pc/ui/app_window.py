"""Control panel (development Step 11): view/edit settings, start/stop
the macro, watch live HP/MP.

Usage (run from the project root, with the venv active):

    python -m pc.ui.app_window

Wraps pc.main.MacroApp -- Start runs its tick() loop on a background
thread so the GUI stays responsive; STOP (and closing the window) calls
the same safety-stop path used everywhere else (queue clear, Arduino
STOP, condition reset).
"""
from __future__ import annotations

import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Optional

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))

from pc.config.config_loader import load_settings  # noqa: E402
from pc.main import MacroApp  # noqa: E402
from pc.ui.settings_store import SettingsStore  # noqa: E402

SETTINGS_PATH = _PROJECT_ROOT / "pc" / "config" / "settings.yaml"


class MacroController:
    """Runs MacroApp.tick() on a background thread.

    The GUI polls the plain attributes below (hp/mp/queued/active_seq/
    running/error) on a timer instead of using a lock -- they're only
    ever simple read/write of primitives from one writer thread, which
    is safe enough under the GIL for a status display like this.
    """

    def __init__(self, settings: dict):
        self._settings = settings
        self._app: Optional[MacroApp] = None
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self.running = False
        self.error: Optional[str] = None
        self.hp: Optional[float] = None
        self.mp: Optional[float] = None
        self.queued = 0
        self.active_seq = 0

    def start(self) -> None:
        if self.running:
            return
        self._stop_event.clear()
        self.error = None
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        try:
            self._app = MacroApp(self._settings)
        except Exception as e:  # surfaced to the GUI via self.error
            self.error = str(e)
            return

        self.running = True
        try:
            while not self._stop_event.is_set():
                try:
                    readings = self._app.tick()
                except Exception as e:
                    self.error = str(e)
                    break
                self.hp = readings["hp"]
                self.mp = readings["mp"]
                self.queued = len(self._app.action_queue)
                self.active_seq = self._app.runner.active_count
        finally:
            if self._app is not None:
                self._app.stop()  # safety stop: queue clear + Arduino STOP + cooldown reset
                self._app.close()
            self.running = False

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)


class App(tk.Tk):
    FIELDS = [
        ("hp_threshold", "HP threshold %", "conditions.hp_low.threshold_percent", float),
        ("hp_cooldown", "HP cooldown (s)", "conditions.hp_low.cooldown_seconds", float),
        ("hp_key", "HP key", "conditions.hp_low.key", str),
        ("mp_threshold", "MP threshold %", "conditions.mp_low.threshold_percent", float),
        ("mp_cooldown", "MP cooldown (s)", "conditions.mp_low.cooldown_seconds", float),
        ("mp_key", "MP key", "conditions.mp_low.key", str),
        ("serial_port", "Serial port", "serial.port", str),
    ]

    def __init__(self):
        super().__init__()
        self.title("Game Screen Monitor + Arduino HID Macro")
        self.geometry("360x420")
        self.resizable(False, False)

        self.store = SettingsStore(SETTINGS_PATH)
        self.controller: Optional[MacroController] = None
        self.field_vars: dict = {}

        self._build_widgets()
        self._load_fields()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._poll_status()

    def _build_widgets(self) -> None:
        pad = {"padx": 8, "pady": 4}

        status_frame = ttk.LabelFrame(self, text="Status")
        status_frame.pack(fill="x", **pad)
        self.hp_var = tk.StringVar(value="HP: --")
        self.mp_var = tk.StringVar(value="MP: --")
        self.state_var = tk.StringVar(value="Stopped")
        ttk.Label(status_frame, textvariable=self.hp_var).pack(anchor="w", padx=6)
        ttk.Label(status_frame, textvariable=self.mp_var).pack(anchor="w", padx=6)
        ttk.Label(status_frame, textvariable=self.state_var).pack(anchor="w", padx=6, pady=(0, 4))

        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill="x", **pad)
        self.start_btn = ttk.Button(btn_frame, text="Start", command=self._on_start)
        self.start_btn.pack(side="left", expand=True, fill="x", padx=(0, 4))
        self.stop_btn = ttk.Button(btn_frame, text="STOP", command=self._on_stop)
        self.stop_btn.pack(side="left", expand=True, fill="x", padx=(4, 0))
        self.stop_btn.state(["disabled"])

        settings_frame = ttk.LabelFrame(self, text="Settings")
        settings_frame.pack(fill="both", expand=True, **pad)
        for i, (key, label, _dotted, _type) in enumerate(self.FIELDS):
            ttk.Label(settings_frame, text=label).grid(row=i, column=0, sticky="w", padx=6, pady=4)
            var = tk.StringVar()
            ttk.Entry(settings_frame, textvariable=var).grid(row=i, column=1, sticky="ew", padx=6, pady=4)
            self.field_vars[key] = var
        settings_frame.columnconfigure(1, weight=1)

        ttk.Button(self, text="Save Settings", command=self._on_save).pack(fill="x", **pad)

    def _load_fields(self) -> None:
        for key, _label, dotted, _type in self.FIELDS:
            self.field_vars[key].set(str(self.store.get(dotted)))

    def _on_save(self) -> None:
        try:
            parsed = {
                key: _type(self.field_vars[key].get())
                for key, _label, _dotted, _type in self.FIELDS
            }
        except ValueError:
            messagebox.showerror("Invalid input", "Threshold/cooldown fields must be numbers")
            return

        for key, _label, dotted, _type in self.FIELDS:
            self.store.set(dotted, parsed[key])
        self.store.save()
        messagebox.showinfo("Saved", f"Settings saved to {SETTINGS_PATH.name}")

    def _on_start(self) -> None:
        if self.controller and self.controller.running:
            return
        settings = load_settings()  # reload from disk in case Save Settings was just clicked
        self.controller = MacroController(settings)
        self.controller.start()
        self.start_btn.state(["disabled"])
        self.stop_btn.state(["!disabled"])
        self.state_var.set("Starting...")

    def _on_stop(self) -> None:
        if self.controller:
            self.controller.stop()
        self.start_btn.state(["!disabled"])
        self.stop_btn.state(["disabled"])
        self.state_var.set("Stopped")

    def _poll_status(self) -> None:
        c = self.controller
        if c is not None:
            if c.error:
                self.state_var.set(f"Error: {c.error}")
                self.start_btn.state(["!disabled"])
                self.stop_btn.state(["disabled"])
            elif c.running:
                self.state_var.set("Running")
                hp = f"{c.hp:.1f}%" if c.hp is not None else "N/A"
                mp = f"{c.mp:.1f}%" if c.mp is not None else "N/A"
                self.hp_var.set(f"HP: {hp}   (queued={c.queued})")
                self.mp_var.set(f"MP: {mp}   (active_seq={c.active_seq})")
        self.after(200, self._poll_status)

    def _on_close(self) -> None:
        if self.controller:
            self.controller.stop()
        self.destroy()


def main() -> None:
    App().mainloop()


if __name__ == "__main__":
    main()
