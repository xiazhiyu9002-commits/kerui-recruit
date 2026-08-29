from __future__ import annotations

import json
from pathlib import Path


class SettingsStore:
    """Persist runtime settings to a JSON file.

    The file lives under the data directory's ``config`` folder. Values are
    plain JSON; sensitive keys are encrypted by the caller before saving.
    """

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
