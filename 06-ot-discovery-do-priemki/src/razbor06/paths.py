"""Пути пакета 06 и пакета 01, на котором стоит сквозной пример."""
from __future__ import annotations

from pathlib import Path

import razbor01

ROOT = Path(__file__).resolve().parents[2]          # папка пакета 06
PKG01 = Path(razbor01.__file__).resolve().parents[2]  # папка пакета 01 (path-зависимость)
EXAMPLE = ROOT / "examples" / "retail"
