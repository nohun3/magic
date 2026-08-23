"""Build and cross-validate the fixed game-font model from labels.csv."""
from __future__ import annotations

import argparse
import csv
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

from pc.detector.game_font_reader import (
    ALPHABET,
    FIELD_DIGITS,
    GAUGE_CHARACTER_COUNT,
    extract_cells,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ROOT = PROJECT_ROOT / "output" / "suspicious_gauge_roi"
DEFAULT_MODEL = PROJECT_ROOT / "output" / "gauge_font_model.npz"


def load_examples(root: Path, gauge: str = "hp"):
    with (root / "labels.csv").open("r", newline="", encoding="utf-8") as handle:
        rows = [row for row in csv.DictReader(handle) if row["gauge"] == gauge]
    examples = []
    for row in rows:
        image = cv2.imread(str(root / row["path"]))
        if image is None:
            continue
        current = str(int(row["current"]))
        maximum = str(int(row["maximum"]))
        if len(current) > FIELD_DIGITS or len(maximum) > FIELD_DIGITS:
            continue
        text = f"{current:>{FIELD_DIGITS}}/{maximum:>{FIELD_DIGITS}}"
        examples.append(
            (row["path"], text, extract_cells(image, GAUGE_CHARACTER_COUNT))
        )
    return examples


def _classify(cell: np.ndarray, samples: np.ndarray, labels: np.ndarray) -> str:
    distances = np.mean(samples != cell[None, :, :], axis=(1, 2))
    return str(labels[int(np.argmin(distances))])


def cross_validate(examples) -> tuple[int, int, int, int, list[tuple[str, str, str]]]:
    """Leave one image out so duplicate glyphs in one ROI cannot self-match."""
    correct = 0
    total = 0
    character_correct = 0
    character_total = 0
    failures = []
    for held_path, held_text, held_cells in examples:
        training = [
            (character, cell)
            for path, text, cells in examples if path != held_path
            for character, cell in zip(text, cells)
        ]
        samples = np.stack([cell for _character, cell in training])
        labels = np.asarray([character for character, _cell in training], dtype="U1")
        predicted = "".join(_classify(cell, samples, labels) for cell in held_cells)
        correct += predicted == held_text
        total += 1
        character_correct += sum(a == b for a, b in zip(predicted, held_text))
        character_total += len(held_text)
        if predicted != held_text:
            failures.append((held_path, held_text, predicted))
    return correct, total, character_correct, character_total, failures


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--gauge", choices=("hp", "mp"), default="hp")
    args = parser.parse_args()

    examples = load_examples(args.root, args.gauge)
    if len(examples) < 20:
        raise SystemExit(f"need at least 20 labelled images; found {len(examples)}")
    counts = Counter(character for _path, text, _cells in examples for character in text)
    missing = set(ALPHABET) - counts.keys()
    if missing:
        raise SystemExit(f"labels do not contain: {''.join(sorted(missing))}")

    correct, total, character_correct, character_total, failures = cross_validate(examples)
    accuracy = correct / total
    print(f"leave-one-image-out exact accuracy: {correct}/{total} ({accuracy:.1%})")
    print(
        f"character accuracy: {character_correct}/{character_total} "
        f"({character_correct / character_total:.1%})"
    )
    for path, expected, predicted in failures[:20]:
        print(f"  {path}: expected {expected}, predicted {predicted}")
    if accuracy < 0.98:
        raise SystemExit("model rejected: exact validation accuracy is below 98%")

    labels = []
    samples = []
    for _path, text, cells in examples:
        labels.extend(text)
        samples.extend(cells)
    args.model.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        args.model,
        samples=np.stack(samples).astype(np.uint8),
        labels=np.asarray(labels, dtype="U1"),
    )
    print(f"saved {len(samples)} glyphs to {args.model}")


if __name__ == "__main__":
    main()
