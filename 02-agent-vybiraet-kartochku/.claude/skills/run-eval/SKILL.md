---
name: run-eval
description: Используй, когда нужно прогнать пакет 02 (Shop MCP + аудит карточек) и объяснить цифры — что вернул живой Shop MCP, сколько карточек агент не увидит и почему, совпадает ли прогон со статьёй.
---

# Прогон пакета 02

1. `uv run pytest -q` — зелёный. Если есть сеть: `uv run pytest -q -m live`.
2. `uv run razbor02 all` (без сети — `--offline`). Последняя строка — «прогон совпадает с eval/reference-run.json»; если «НЕ совпадает» — сравнить `eval/out/run.json` с `eval/reference-run.json` и найти, какое поле разошлось.
3. Живой probe: `eval/out/live/summary.json` — число инструментов, версия UCP, поля карточки (`card_fields`), эффект фильтра (`filter_effect`). Живая выдача меняется — расхождение со снимком 17.10.2026 нормально, объяснить его.
4. Аудит: `eval/out/audit.json` → `summary.scenarios` (воронка по шагам фильтра), `summary.top_blockers`, `summary.fixable`; по карточкам — `eval/out/cards.csv`.
5. Отчёт: `eval/out/report.html`, экраны `#tools`, `#search`, `#audit`. Для скриншотов — ширина окна 1200.
6. Свой каталог человека — `uv run razbor02 audit --catalog файл.csv`; сравнение с учётной системой — `--erp`.
