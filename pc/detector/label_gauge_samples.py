"""Small local tool for assigning ground-truth values to saved gauge ROIs.

Run from the project root::

    python -m pc.detector.label_gauge_samples

The filename contains the *old OCR result*, which is deliberately never used
as a label.  Labels are written incrementally so closing the window is safe.
"""
from __future__ import annotations

import argparse
import csv
import re
import tkinter as tk
from pathlib import Path
from tkinter import messagebox
from typing import Dict, List, Tuple

from PIL import Image, ImageTk


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_ROOT = PROJECT_ROOT / "output" / "suspicious_gauge_roi"
LABEL_PATH = SAMPLE_ROOT / "labels.csv"
VALUE_PATTERN = re.compile(r"^\s*(\d+)\s*/\s*(\d+)\s*$")


def _load_labels() -> Dict[str, Tuple[int, int]]:
    labels: Dict[str, Tuple[int, int]] = {}
    if not LABEL_PATH.exists():
        return labels
    with LABEL_PATH.open("r", newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            labels[row["path"]] = (int(row["current"]), int(row["maximum"]))
    return labels


def _write_labels(labels: Dict[str, Tuple[int, int]]) -> None:
    LABEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = LABEL_PATH.with_suffix(".csv.tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=("path", "gauge", "current", "maximum")
        )
        writer.writeheader()
        for relative_path in sorted(labels):
            current, maximum = labels[relative_path]
            writer.writerow(
                {
                    "path": relative_path,
                    "gauge": Path(relative_path).parts[0],
                    "current": current,
                    "maximum": maximum,
                }
            )
    temporary.replace(LABEL_PATH)


def _sample_paths(gauges: tuple[str, ...] = ("hp", "mp")) -> List[Path]:
    paths: List[Path] = []
    for gauge in gauges:
        manifest = SAMPLE_ROOT / f"{gauge}_selection.txt"
        if manifest.exists():
            paths.extend(
                SAMPLE_ROOT / line.strip()
                for line in manifest.read_text(encoding="utf-8").splitlines()
                if line.strip()
            )
        else:
            paths.extend(sorted((SAMPLE_ROOT / gauge).glob("*.png")))
    return [path for path in paths if path.is_file()]


class GaugeLabeler:
    def __init__(self, root: tk.Tk, gauges: tuple[str, ...] = ("hp", "mp")):
        self.root = root
        self.labels = _load_labels()
        self.samples = _sample_paths(gauges)
        self.index = 0
        self.photo = None

        root.title(f"{'/'.join(gauge.upper() for gauge in gauges)} gauge labeler")
        root.resizable(False, False)
        self.status = tk.Label(root, anchor="w", padx=10, pady=8)
        self.status.pack(fill="x")
        self.image_label = tk.Label(root, bg="#202020", padx=16, pady=16)
        self.image_label.pack(fill="both")
        tk.Label(root, text="화면에 보이는 값을 current/max 형식으로 입력").pack(pady=(10, 2))
        self.value = tk.Entry(root, width=20, justify="center", font=("Consolas", 18))
        self.value.pack(padx=12, pady=4)

        buttons = tk.Frame(root)
        buttons.pack(pady=(4, 12))
        tk.Button(buttons, text="이전", width=10, command=self.previous).pack(side="left", padx=3)
        tk.Button(buttons, text="건너뛰기", width=10, command=self.skip).pack(side="left", padx=3)
        tk.Button(buttons, text="저장 + 다음", width=12, command=self.save).pack(side="left", padx=3)
        root.bind("<Return>", lambda _event: self.save())
        root.bind("<Escape>", lambda _event: root.destroy())
        self._seek_unlabelled()
        self.show()

    def _relative(self, path: Path) -> str:
        return path.relative_to(SAMPLE_ROOT).as_posix()

    def _seek_unlabelled(self) -> None:
        while self.index < len(self.samples):
            if self._relative(self.samples[self.index]) not in self.labels:
                return
            self.index += 1

    def show(self) -> None:
        if not self.samples or self.index >= len(self.samples):
            self.status.config(text=f"완료: {len(self.labels)}개 라벨 저장됨")
            self.image_label.config(image="", text="라벨링할 이미지가 없습니다.", fg="white")
            self.value.delete(0, "end")
            return
        path = self.samples[self.index]
        image = Image.open(path).convert("RGB")
        image = image.resize((image.width * 4, image.height * 4), Image.Resampling.NEAREST)
        self.photo = ImageTk.PhotoImage(image)
        self.image_label.config(image=self.photo, text="")
        self.status.config(
            text=f"{self.index + 1}/{len(self.samples)}  {path.parent.name.upper()}  "
                 f"(저장 {len(self.labels)}개)"
        )
        self.value.delete(0, "end")
        existing = self.labels.get(self._relative(path))
        if existing:
            self.value.insert(0, f"{existing[0]}/{existing[1]}")
        self.value.focus_set()

    def save(self) -> None:
        if self.index >= len(self.samples):
            return
        match = VALUE_PATTERN.match(self.value.get())
        if not match:
            messagebox.showerror("입력 오류", "예: 177/194 형식으로 입력하세요.")
            return
        current, maximum = map(int, match.groups())
        if maximum <= 0 or current > maximum:
            messagebox.showerror("입력 오류", "0 <= current <= maximum 이어야 합니다.")
            return
        self.labels[self._relative(self.samples[self.index])] = (current, maximum)
        _write_labels(self.labels)
        self.index += 1
        self._seek_unlabelled()
        self.show()

    def skip(self) -> None:
        if self.index < len(self.samples):
            self.index += 1
            self._seek_unlabelled()
            self.show()

    def previous(self) -> None:
        if self.index > 0:
            self.index -= 1
            self.show()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gauge", choices=("hp", "mp"))
    args = parser.parse_args()
    gauges = (args.gauge,) if args.gauge else ("hp", "mp")
    root = tk.Tk()
    GaugeLabeler(root, gauges)
    root.mainloop()


if __name__ == "__main__":
    main()
