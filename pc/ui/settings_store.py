"""Loads pc/config/settings.yaml with ruamel.yaml (round-trip mode) so
the UI's Save Settings button can write edits back without wiping out
the file's comments.

pc/config/config_loader.py (used everywhere else) intentionally stays on
plain PyYAML (yaml.safe_load) for simple read-only access -- it's
lighter weight and every other module only ever reads settings, never
edits and re-saves them. Round-trip preservation only matters here,
where the UI writes the file back out.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

_yaml = YAML()
_yaml.preserve_quotes = True


class SettingsStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        with open(self.path, "r", encoding="utf-8") as f:
            self.data = _yaml.load(f)

    def get(self, dotted_key: str) -> Any:
        """e.g. store.get("conditions.hp_low.threshold_percent")"""
        node = self.data
        for part in dotted_key.split("."):
            node = node[part]
        return node

    def set(self, dotted_key: str, value: Any) -> None:
        """e.g. store.set("conditions.hp_low.threshold_percent", 25)"""
        parts = dotted_key.split(".")
        node = self.data
        for part in parts[:-1]:
            node = node[part]
        node[parts[-1]] = value

    def save(self) -> None:
        with open(self.path, "w", encoding="utf-8") as f:
            _yaml.dump(self.data, f)
