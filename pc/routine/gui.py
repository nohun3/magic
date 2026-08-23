"""Small desktop controller for the 1-4 step routine.

Run from the project root with::

    python -m pc.routine.gui

Pause and Stop both request the routine's normal KeyboardInterrupt cleanup.
Pause keeps a distinct GUI state so Start can be used later; every new process
begins from the Step 2 entry precondition.
"""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter.scrolledtext import ScrolledText
from typing import Optional


PROJECT_ROOT = Path(__file__).resolve().parents[2]
VENV_PYTHON = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"


def routine_python() -> str:
    """Use the project's dependency-complete venv even if GUI used `py`."""
    return str(VENV_PYTHON) if VENV_PYTHON.exists() else sys.executable


class RoutineController:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.process: Optional[subprocess.Popen[str]] = None
        self.messages: queue.Queue[tuple[str, str]] = queue.Queue()
        self.desired_end_state = "중지"

        root.title("업무 도우미")
        root.geometry("450x600")
        root.minsize(420, 420)
        root.protocol("WM_DELETE_WINDOW", self.close)

        header = tk.Frame(root, padx=12, pady=10)
        header.pack(fill="x")
        tk.Label(header, text="1~4단계 루틴", font=("맑은 고딕", 15, "bold")).pack(side="left")
        self.status = tk.Label(
            header, text="중지", fg="#9b1c1c", font=("맑은 고딕", 12, "bold")
        )
        self.status.pack(side="right")

        controls = tk.Frame(root, padx=12, pady=4)
        controls.pack(fill="x")
        self.start_button = tk.Button(controls, text="시작", width=14, command=self.start)
        self.start_button.pack(side="left", padx=(0, 8))
        self.wait_button = tk.Button(
            controls, text="대기", width=14, command=self.pause, state="disabled"
        )
        self.wait_button.pack(side="left", padx=(0, 8))
        self.stop_button = tk.Button(
            controls, text="종료", width=14, command=self.stop, state="disabled"
        )
        self.stop_button.pack(side="left")

        self.log = ScrolledText(
            root, wrap="word", state="disabled", font=("Consolas", 10),
            bg="#111827", fg="#e5e7eb", insertbackground="white",
        )
        self.log.pack(fill="both", expand=True, padx=12, pady=12)
        self.root.after(100, self._drain_messages)

    def _set_status(self, text: str, colour: str) -> None:
        self.status.config(text=text, fg=colour)

    def _append(self, text: str) -> None:
        self.log.config(state="normal")
        self.log.insert("end", text)
        self.log.see("end")
        self.log.config(state="disabled")

    def start(self) -> None:
        if self.process is not None and self.process.poll() is None:
            return
        environment = os.environ.copy()
        environment["ROUTINE_CONTROL_STDIN"] = "1"
        # Windows otherwise encodes a piped Python stdout with the active
        # legacy code page (usually CP949), while this GUI reads UTF-8.
        environment["PYTHONIOENCODING"] = "utf-8"
        environment["PYTHONUTF8"] = "1"
        creationflags = 0
        if os.name == "nt":
            creationflags = subprocess.CREATE_NO_WINDOW
        try:
            self.process = subprocess.Popen(
                [routine_python(), "-u", "-m", "pc.routine.run_all"],
                cwd=PROJECT_ROOT,
                env=environment,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=creationflags,
            )
        except OSError as error:
            self._append(f"[GUI] 시작 실패: {error}\n")
            return
        self.desired_end_state = "중지"
        self._set_status("실행 중", "#15803d")
        self.start_button.config(state="disabled")
        self.wait_button.config(state="normal")
        self.stop_button.config(state="normal")
        self._append("[GUI] 루틴을 시작합니다.\n")
        threading.Thread(target=self._read_output, daemon=True).start()

    def _read_output(self) -> None:
        process = self.process
        if process is None or process.stdout is None:
            return
        for line in process.stdout:
            self.messages.put(("log", line))
        return_code = process.wait()
        self.messages.put(("ended", str(return_code)))

    def _request_end(self, state: str) -> None:
        process = self.process
        if process is None or process.poll() is not None:
            self._finish_state(state, 0)
            return
        self.desired_end_state = state
        self._set_status("정리 중", "#a16207")
        self.wait_button.config(state="disabled")
        self.stop_button.config(state="disabled")
        try:
            if process.stdin is not None:
                process.stdin.write("STOP\n")
                process.stdin.flush()
        except (BrokenPipeError, OSError):
            pass
        threading.Thread(target=self._terminate_if_needed, args=(process,), daemon=True).start()

    def _terminate_if_needed(self, process: subprocess.Popen[str]) -> None:
        try:
            process.wait(timeout=8.0)
        except subprocess.TimeoutExpired:
            process.terminate()

    def pause(self) -> None:
        self._append("[GUI] 안전 정리 후 대기 상태로 전환합니다.\n")
        self._request_end("대기")

    def stop(self) -> None:
        self._append("[GUI] 루틴 종료를 요청합니다.\n")
        self._request_end("중지")

    def _finish_state(self, state: str, return_code: int) -> None:
        self.process = None
        colour = "#a16207" if state == "대기" else "#9b1c1c"
        self._set_status(state, colour)
        self.start_button.config(state="normal")
        self.wait_button.config(state="disabled")
        self.stop_button.config(state="disabled")
        self._append(f"[GUI] 프로세스 종료 코드: {return_code}, 상태: {state}\n")

    def _drain_messages(self) -> None:
        try:
            while True:
                kind, value = self.messages.get_nowait()
                if kind == "log":
                    self._append(value)
                elif kind == "ended":
                    self._finish_state(self.desired_end_state, int(value))
        except queue.Empty:
            pass
        self.root.after(100, self._drain_messages)

    def close(self) -> None:
        process = self.process
        if process is not None and process.poll() is None:
            try:
                if process.stdin is not None:
                    process.stdin.write("STOP\n")
                    process.stdin.flush()
                process.wait(timeout=3.0)
            except (BrokenPipeError, OSError, subprocess.TimeoutExpired):
                process.terminate()
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    RoutineController(root)
    root.mainloop()


if __name__ == "__main__":
    main()
