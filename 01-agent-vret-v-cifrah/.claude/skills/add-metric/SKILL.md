---
name: add-metric
description: Используй, когда в слой метрик пакета 01 нужно добавить метрику или измерение — например, «добавь маржу» или «нужна выручка по неделям».
---

# Добавить метрику

1. Убедиться, что нужные колонки есть в `mart.*` (`src/razbor01/layers.sql`); если нет — сначала добавить колонку в витрину.
2. Написать тест в `tests/test_metrics.py`: значение метрики через `compile_query` равно независимому SQL по `raw` с правилами компании.
3. `uv run pytest tests/test_metrics.py -q` — новый тест падает.
4. Добавить метрику в `metrics.yaml`: `id`, `label`, `description`, `table`, `time_column`, `time_rule` (`range` | `period_end` | `period_avg`), `expr`, `dimensions`, `synonyms`.
5. Тесты зелёные; если метрика отвечает на вопрос eval — добавить вопросу `metric_query`.
