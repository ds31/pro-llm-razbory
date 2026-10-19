# CLAUDE.md — пакет 01 «Почему AI-агент врёт в цифрах»

Отвечай по-русски.

## Что это

Эксперимент: агент на Claude API отвечает на 30 вопросов о синтетической розничной сети по сырым таблицам (A) и через слой метрик (B); eval сверяет ответы с живыми эталонами (`check_sql` по `raw` с правилами компании).

## Команды

- тесты: `uv run pytest -q` (в API не ходят);
- база: `uv run razbor01 data` → `data/retail.duckdb`;
- прогон: `uv run razbor01 eval [--only Q07,Q19] [--variants B] [--limit N] [--model M] [--offline]`;
- всё сразу: `uv run razbor01 all`;
- через OpenRouter: `ANTHROPIC_BASE_URL=https://openrouter.ai/api`, ключ — `ANTHROPIC_AUTH_TOKEN`, модель `anthropic/claude-sonnet-5.5`.

## Устройство

| Путь | Что |
|---|---|
| `src/razbor01/synth.py` | генератор `raw` с ловушками |
| `src/razbor01/layers.sql`, `layers.py` | `stg` и `mart`: правила очистки |
| `metrics.yaml`, `src/razbor01/metrics.py` | слой метрик и компилятор запроса |
| `src/razbor01/guard.py`, `tools.py` | шлюз SQL, инструменты A и B |
| `src/razbor01/agent.py` | цикл tool use, цена (`PRICES`) |
| `src/razbor01/runner.py`, `report.py`, `cli.py` | прогон, отчёт, команда |
| `eval/questions.yaml`, `src/razbor01/golden.py` | вопросы, эталоны, допуск ±0,5 % |

## Правила

1. Только синтетические данные; реальные базы, выгрузки и названия компаний не подключать.
2. Правило очистки меняется только в `layers.sql`, определение метрики — только в `metrics.yaml`; тест — в том же коммите.
3. Новый вопрос — с `check_sql`; если проверяет ловушку — с `trap_sql`, и `test_trap_bites` проходит. Допуск не менять.
4. Платный прогон без `--offline` — только по просьбе человека; сначала `--only` на одном-двух вопросах.
5. Ключ API — только из окружения; `.env` не читать и не коммитить.

## Скиллы

`add-metric`, `add-eval-question`, `explain-run` — в `.claude/skills/`.
