"""Editor for future timer/HP/MP driven macros.

This module deliberately only edits configuration.  It does not open the
serial port, capture the screen, or execute HID actions.  Runtime support can
therefore be added and hardware-tested as a separate development step.
"""
from __future__ import annotations

import copy
import tkinter as tk
import uuid
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk
from typing import Any

from pc.ui.settings_store import SettingsStore


KEYS = tuple(f"F{number}" for number in range(1, 13))
ACTION_LABELS = {
    "KEY": "키 입력",
    "MOUSE_MOVE": "마우스 이동",
    "MOUSE_CLICK": "마우스 클릭",
    "WAIT": "대기",
}


def default_macro(index: int = 1) -> dict[str, Any]:
    return {
        "id": uuid.uuid4().hex,
        "name": f"매크로 {index}",
        "interval_seconds": 30.0,
        "steps": [],
    }


def describe_step(step: dict[str, Any]) -> str:
    kind = step.get("type", "")
    if kind == "KEY":
        return f"{step.get('key', 'F1')} / 누름 {step.get('hold_ms', 50)}ms"
    if kind == "MOUSE_MOVE":
        return f"x={step.get('x', 0)}, y={step.get('y', 0)}"
    if kind == "MOUSE_CLICK":
        return f"{step.get('button', 'LEFT')} / 누름 {step.get('hold_ms', 30)}ms"
    if kind == "WAIT":
        return f"{step.get('ms', 100)}ms"
    return "알 수 없는 동작"


class MacroSettingsWindow(tk.Toplevel):
    def __init__(self, parent: tk.Misc, settings_path: Path):
        super().__init__(parent)
        self.title("매크로 설정")
        self.geometry("900x620")
        self.minsize(780, 540)
        self.transient(parent)

        self.store = SettingsStore(settings_path)
        saved = self.store.data.get("user_macros", [])
        self.macros: list[dict[str, Any]] = copy.deepcopy(list(saved or []))
        for macro in self.macros:
            macro.setdefault("id", uuid.uuid4().hex)
            # Migrate settings saved by the first UI-only draft.
            old_trigger = macro.pop("trigger", {})
            macro.setdefault("interval_seconds", old_trigger.get("interval_seconds", 30.0))
            macro.pop("enabled", None)
            macro.pop("cooldown_seconds", None)
        self.current_index: int | None = None
        self._loading = False

        self.name_var = tk.StringVar()
        self.interval_var = tk.StringVar(value="30")
        conditions = self.store.data.get("macro_conditions", {}) or {}
        hp_condition = conditions.get("hp_below", {}) or {}
        self.hp_enabled_var = tk.BooleanVar(value=bool(hp_condition.get("enabled", False)))
        self.hp_threshold_var = tk.StringVar(value=str(hp_condition.get("threshold_percent", 70)))
        self.hp_cooldown_var = tk.StringVar(value=str(hp_condition.get("cooldown_seconds", 3)))
        self.hp_macro_var = tk.StringVar()
        self._saved_hp_macro_id = str(hp_condition.get("macro_id", ""))

        self._build_widgets()
        self._refresh_macro_list()
        if self.macros:
            self.macro_list.selection_set(0)
            self._select_macro(0)
        else:
            self._add_macro()

    def _build_widgets(self) -> None:
        outer = ttk.Frame(self, padding=10)
        outer.pack(fill="both", expand=True)

        left = ttk.LabelFrame(outer, text="매크로 목록", padding=8)
        left.pack(side="left", fill="y", padx=(0, 8))
        self.macro_list = tk.Listbox(left, width=23, exportselection=False)
        self.macro_list.pack(fill="both", expand=True)
        self.macro_list.bind("<<ListboxSelect>>", self._on_macro_selected)
        list_buttons = ttk.Frame(left)
        list_buttons.pack(fill="x", pady=(8, 0))
        ttk.Button(list_buttons, text="추가", command=self._add_macro).pack(
            side="left", expand=True, fill="x", padx=(0, 3)
        )
        ttk.Button(list_buttons, text="삭제", command=self._delete_macro).pack(
            side="left", expand=True, fill="x", padx=(3, 0)
        )

        right = ttk.Frame(outer)
        right.pack(side="left", fill="both", expand=True)

        basic = ttk.LabelFrame(right, text="상시 실행 설정", padding=8)
        basic.pack(fill="x")
        ttk.Label(basic, text="이름").grid(row=0, column=0, sticky="w", pady=3)
        ttk.Entry(basic, textvariable=self.name_var).grid(
            row=0, column=1, columnspan=3, sticky="ew", padx=6, pady=3
        )
        ttk.Label(basic, text="반복 간격(초)").grid(row=1, column=0, sticky="w", pady=3)
        self.interval_entry = ttk.Entry(basic, textvariable=self.interval_var, width=12)
        self.interval_entry.grid(row=1, column=1, sticky="w", padx=6, pady=3)
        ttk.Label(
            basic, text="매크로 모드가 실행되면 목록의 모든 매크로가 각 간격으로 반복됩니다."
        ).grid(row=1, column=2, columnspan=3, sticky="w", padx=6, pady=3)
        basic.columnconfigure(1, weight=1)
        basic.columnconfigure(3, weight=1)

        hp = ttk.LabelFrame(right, text="HP 조건 실행", padding=8)
        hp.pack(fill="x", pady=(8, 0))
        ttk.Checkbutton(hp, text="사용", variable=self.hp_enabled_var).grid(
            row=0, column=0, sticky="w", padx=(0, 8)
        )
        ttk.Label(hp, text="HP").grid(row=0, column=1, sticky="e")
        ttk.Entry(hp, textvariable=self.hp_threshold_var, width=7).grid(
            row=0, column=2, padx=4
        )
        ttk.Label(hp, text="% 이하 →").grid(row=0, column=3, sticky="w")
        self.hp_macro_combo = ttk.Combobox(
            hp, textvariable=self.hp_macro_var, state="readonly", width=20
        )
        self.hp_macro_combo.grid(row=0, column=4, padx=6, sticky="ew")
        self.hp_macro_combo.bind(
            "<<ComboboxSelected>>", lambda _event: self._remember_hp_macro()
        )
        ttk.Label(hp, text="쿨다운(초)").grid(row=0, column=5, sticky="e")
        ttk.Entry(hp, textvariable=self.hp_cooldown_var, width=7).grid(
            row=0, column=6, padx=(4, 0)
        )
        hp.columnconfigure(4, weight=1)

        actions = ttk.LabelFrame(right, text="입력 순서", padding=8)
        actions.pack(fill="both", expand=True, pady=(8, 0))
        self.step_tree = ttk.Treeview(
            actions, columns=("order", "type", "detail"), show="headings", height=12
        )
        self.step_tree.heading("order", text="#")
        self.step_tree.heading("type", text="동작")
        self.step_tree.heading("detail", text="설정")
        self.step_tree.column("order", width=38, anchor="center", stretch=False)
        self.step_tree.column("type", width=120, anchor="center", stretch=False)
        self.step_tree.column("detail", width=360)
        self.step_tree.pack(fill="both", expand=True)

        add_buttons = ttk.Frame(actions)
        add_buttons.pack(fill="x", pady=(8, 0))
        for label, kind in (
            ("F1~F12", "KEY"), ("마우스 이동", "MOUSE_MOVE"),
            ("마우스 클릭", "MOUSE_CLICK"), ("대기", "WAIT"),
        ):
            ttk.Button(
                add_buttons, text=label,
                command=lambda selected=kind: self._add_step(selected),
            ).pack(side="left", padx=(0, 5))
        ttk.Button(add_buttons, text="위로", command=lambda: self._move_step(-1)).pack(side="right")
        ttk.Button(add_buttons, text="아래로", command=lambda: self._move_step(1)).pack(
            side="right", padx=5
        )
        ttk.Button(add_buttons, text="삭제", command=self._delete_step).pack(side="right")

        footer = ttk.Frame(self, padding=(10, 0, 10, 10))
        footer.pack(fill="x")
        ttk.Label(
            footer,
            text="현재 단계에서는 설정만 저장하며 매크로를 실행하지 않습니다.",
            foreground="#7c2d12",
        ).pack(side="left")
        ttk.Button(footer, text="닫기", command=self.destroy).pack(side="right")
        ttk.Button(footer, text="저장", command=self._save).pack(side="right", padx=6)

    def _refresh_macro_list(self, selected: int | None = None) -> None:
        self._loading = True
        self.macro_list.delete(0, "end")
        for macro in self.macros:
            self.macro_list.insert("end", str(macro.get("name", "이름 없음")))
        if selected is not None and 0 <= selected < len(self.macros):
            self.macro_list.selection_set(selected)
            self.macro_list.activate(selected)
        self._loading = False
        self._refresh_hp_macro_choices()

    def _on_macro_selected(self, _event: tk.Event) -> None:
        if self._loading:
            return
        selection = self.macro_list.curselection()
        if not selection:
            return
        new_index = int(selection[0])
        if self.current_index is not None and new_index != self.current_index:
            if not self._commit_form(show_error=True):
                self._refresh_macro_list(self.current_index)
                return
        self._select_macro(new_index)

    def _select_macro(self, index: int) -> None:
        self.current_index = index
        macro = self.macros[index]
        self.name_var.set(str(macro.get("name", "")))
        self.interval_var.set(str(macro.get("interval_seconds", 30)))
        self._refresh_steps()

    def _commit_form(self, show_error: bool) -> bool:
        if self.current_index is None:
            return True
        try:
            name = self.name_var.get().strip()
            if not name:
                raise ValueError("매크로 이름을 입력하세요.")
            interval = float(self.interval_var.get())
            if interval <= 0:
                raise ValueError("실행 간격은 0보다 커야 합니다.")
        except ValueError as error:
            if show_error:
                messagebox.showerror("입력 오류", str(error), parent=self)
            return False
        macro = self.macros[self.current_index]
        if self.hp_macro_var.get() == str(macro.get("name", "")):
            self._saved_hp_macro_id = str(macro.get("id", ""))
        macro.update({
            "name": name,
            "interval_seconds": interval,
        })
        return True

    def _refresh_hp_macro_choices(self) -> None:
        names = [str(macro.get("name", "")) for macro in self.macros]
        self.hp_macro_combo.configure(values=names)
        selected_id = self._selected_hp_macro_id() or self._saved_hp_macro_id
        selected = next(
            (str(macro.get("name", "")) for macro in self.macros if macro.get("id") == selected_id),
            "",
        )
        if selected:
            self.hp_macro_var.set(selected)
        elif self.hp_macro_var.get() not in names:
            self.hp_macro_var.set(names[0] if names else "")
            self._remember_hp_macro()

    def _remember_hp_macro(self) -> None:
        self._saved_hp_macro_id = self._selected_hp_macro_id()

    def _selected_hp_macro_id(self) -> str:
        selected_name = self.hp_macro_var.get()
        for macro in self.macros:
            if str(macro.get("name", "")) == selected_name:
                return str(macro.get("id", ""))
        return ""

    def _add_macro(self) -> None:
        if not self._commit_form(show_error=True):
            return
        self.macros.append(default_macro(len(self.macros) + 1))
        index = len(self.macros) - 1
        self._refresh_macro_list(index)
        self._select_macro(index)

    def _delete_macro(self) -> None:
        if self.current_index is None:
            return
        macro = self.macros[self.current_index]
        if str(macro.get("id", "")) == self._selected_hp_macro_id() and self.hp_enabled_var.get():
            messagebox.showerror(
                "매크로 삭제",
                "HP 조건에서 선택된 매크로입니다. HP 조건을 해제하거나 다른 매크로를 선택하세요.",
                parent=self,
            )
            return
        if not messagebox.askyesno("매크로 삭제", "선택한 매크로를 삭제할까요?", parent=self):
            return
        deleted_index = self.current_index
        del self.macros[deleted_index]
        self.current_index = None
        if not self.macros:
            self.macros.append(default_macro())
        index = min(deleted_index, len(self.macros) - 1)
        self._refresh_macro_list(index)
        self._select_macro(index)

    def _steps(self) -> list[dict[str, Any]]:
        if self.current_index is None:
            return []
        return self.macros[self.current_index].setdefault("steps", [])

    def _refresh_steps(self, selected: int | None = None) -> None:
        self.step_tree.delete(*self.step_tree.get_children())
        for index, step in enumerate(self._steps()):
            item = self.step_tree.insert(
                "", "end", values=(index + 1, ACTION_LABELS.get(step.get("type"), "알 수 없음"), describe_step(step))
            )
            if selected == index:
                self.step_tree.selection_set(item)
                self.step_tree.focus(item)

    def _add_step(self, kind: str) -> None:
        step: dict[str, Any] | None = None
        if kind == "KEY":
            key = self._choose_key()
            if key:
                hold = simpledialog.askinteger(
                    "키 입력", "키 누름 시간(ms)", initialvalue=100, minvalue=1, parent=self
                )
                if hold is not None:
                    step = {"type": "KEY", "key": key, "hold_ms": hold}
        elif kind == "MOUSE_MOVE":
            x = simpledialog.askinteger("마우스 이동", "X 좌표", initialvalue=0, parent=self)
            if x is not None:
                y = simpledialog.askinteger("마우스 이동", "Y 좌표", initialvalue=0, parent=self)
                if y is not None:
                    step = {"type": "MOUSE_MOVE", "x": x, "y": y}
        elif kind == "MOUSE_CLICK":
            button = simpledialog.askstring(
                "마우스 클릭", "버튼(LEFT/RIGHT/MIDDLE)", initialvalue="LEFT", parent=self
            )
            if button and button.upper() in {"LEFT", "RIGHT", "MIDDLE"}:
                step = {"type": "MOUSE_CLICK", "button": button.upper(), "hold_ms": 30}
            elif button:
                messagebox.showerror("입력 오류", "LEFT, RIGHT, MIDDLE 중 하나를 입력하세요.", parent=self)
        elif kind == "WAIT":
            duration = simpledialog.askinteger(
                "대기", "대기 시간(ms)", initialvalue=100, minvalue=0, parent=self
            )
            if duration is not None:
                step = {"type": "WAIT", "ms": duration}
        if step is not None:
            self._steps().append(step)
            self._refresh_steps(len(self._steps()) - 1)

    def _choose_key(self) -> str | None:
        dialog = tk.Toplevel(self)
        dialog.title("키 선택")
        dialog.transient(self)
        dialog.grab_set()
        value = tk.StringVar(value="F1")
        ttk.Label(dialog, text="입력할 키").pack(padx=18, pady=(14, 5))
        ttk.Combobox(dialog, textvariable=value, values=KEYS, state="readonly", width=10).pack(padx=18)
        result: list[str] = []

        def accept() -> None:
            result.append(value.get())
            dialog.destroy()

        ttk.Button(dialog, text="확인", command=accept).pack(pady=14)
        dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)
        self.wait_window(dialog)
        return result[0] if result else None

    def _selected_step_index(self) -> int | None:
        selection = self.step_tree.selection()
        if not selection:
            return None
        return self.step_tree.index(selection[0])

    def _delete_step(self) -> None:
        index = self._selected_step_index()
        if index is not None:
            del self._steps()[index]
            self._refresh_steps()

    def _move_step(self, offset: int) -> None:
        index = self._selected_step_index()
        if index is None:
            return
        target = index + offset
        steps = self._steps()
        if 0 <= target < len(steps):
            steps[index], steps[target] = steps[target], steps[index]
            self._refresh_steps(target)

    def _save(self) -> None:
        if not self._commit_form(show_error=True):
            return
        names = [str(macro.get("name", "")).casefold() for macro in self.macros]
        if len(names) != len(set(names)):
            messagebox.showerror("입력 오류", "매크로 이름은 중복될 수 없습니다.", parent=self)
            return
        try:
            hp_threshold = float(self.hp_threshold_var.get())
            hp_cooldown = float(self.hp_cooldown_var.get())
            if not 0 <= hp_threshold <= 100:
                raise ValueError("HP 임계값은 0~100 사이여야 합니다.")
            if hp_cooldown < 0:
                raise ValueError("HP 쿨다운은 0 이상이어야 합니다.")
            hp_macro_id = self._selected_hp_macro_id()
            if self.hp_enabled_var.get() and not hp_macro_id:
                raise ValueError("HP 조건에서 실행할 매크로를 선택하세요.")
        except ValueError as error:
            messagebox.showerror("입력 오류", str(error), parent=self)
            return
        self.store.data["user_macros"] = copy.deepcopy(self.macros)
        conditions = self.store.data.setdefault("macro_conditions", {})
        conditions["hp_below"] = {
            "enabled": bool(self.hp_enabled_var.get()),
            "threshold_percent": hp_threshold,
            "cooldown_seconds": hp_cooldown,
            "macro_id": hp_macro_id,
        }
        self._saved_hp_macro_id = hp_macro_id
        self.store.save()
        self._refresh_macro_list(self.current_index)
        messagebox.showinfo("저장 완료", "매크로 설정을 저장했습니다.", parent=self)


def open_macro_settings(parent: tk.Misc, settings_path: Path) -> MacroSettingsWindow:
    return MacroSettingsWindow(parent, settings_path)
