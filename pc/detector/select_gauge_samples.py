"""Select a visually diverse subset of saved gauge crops for labelling."""
from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ROOT = PROJECT_ROOT / "output" / "suspicious_gauge_roi"


def _feature(path: Path) -> np.ndarray:
    image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise ValueError(f"cannot read {path}")
    # The small source image is already normalized to one fixed ROI.  A
    # compact grayscale vector preserves digit shapes and suppresses tiny
    # pixel noise enough for diversity selection.
    normalized = cv2.resize(image, (64, 16), interpolation=cv2.INTER_AREA)
    return normalized.astype(np.float32).reshape(-1) / 255.0


def select_diverse(paths: list[Path], count: int) -> list[Path]:
    if count >= len(paths):
        return paths
    features = np.stack([_feature(path) for path in paths])

    # Start near the population centre, then repeatedly take the image with
    # the greatest distance from its nearest selected neighbour.  This is a
    # deterministic farthest-point sample and avoids spending labels on many
    # near-identical consecutive frames.
    centre = np.mean(features, axis=0)
    first = int(np.argmin(np.mean((features - centre) ** 2, axis=1)))
    selected = [first]
    nearest = np.mean((features - features[first]) ** 2, axis=1)
    nearest[first] = -1.0
    while len(selected) < count:
        index = int(np.argmax(nearest))
        selected.append(index)
        distance = np.mean((features - features[index]) ** 2, axis=1)
        nearest = np.minimum(nearest, distance)
        nearest[selected] = -1.0
    return [paths[index] for index in selected]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("gauge", choices=("hp", "mp"))
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args()
    if args.count <= 0:
        raise SystemExit("--count must be positive")

    paths = sorted((args.root / args.gauge).glob("*.png"))
    if not paths:
        raise SystemExit(f"no {args.gauge.upper()} PNG files found")
    selected = select_diverse(paths, min(args.count, len(paths)))
    manifest = args.root / f"{args.gauge}_selection.txt"
    manifest.write_text(
        "".join(f"{path.relative_to(args.root).as_posix()}\n" for path in selected),
        encoding="utf-8",
    )
    print(f"selected {len(selected)}/{len(paths)} images -> {manifest}")


if __name__ == "__main__":
    main()
