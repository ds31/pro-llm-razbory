"""Где лежат вопросы и слой метрик: eval берётся из пакета 01 как есть, без копий."""
from pathlib import Path

import razbor01

BASE = Path(razbor01.__file__).resolve().parents[2]   # папка 01-agent-vret-v-cifrah
PKG = Path(__file__).resolve().parents[2]             # папка этого пакета
