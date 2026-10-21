# CLAUDE.md — пакет 03 «Как доказать, что AI-агент считает правильно»

Отвечай по-русски.

## Что это

Каркас eval агента-аналитика: вопросы руководителя с живыми эталонами (`check_sql` по сырым данным), проверка «ловушка кусает», прогон с повторами, сравнение прогонов с кодом выхода для CI и судья-LLM как сравнительный режим. Агент под проверкой — агент пакета 01 (варианты A и B) на той же синтетической розничной сети; пакет 01 подключён path-зависимостью `../01-agent-vret-v-cifrah`.

## Команды

- тесты: `uv run pytest -q` (в API не ходят);
- всё офлайн, по ответам автора: `uv run razbor03 all --offline`;
- базы сценариев: `uv run razbor03 data` → `data/*.duckdb`;
- эталоны и ловушки: `uv run razbor03 refs [--scenario reload]`;
- прогон (платно): `uv run razbor03 run --scenario base --variant B [--tag anomaly | --only Q19] [--repeats 3]`;
- проверка: `uv run razbor03 check <прогон> [--by frozen]`; судья (платно): `uv run razbor03 judge <прогон> [--model …]`;
- устойчивость: `uv run razbor03 stability <прогон> <прогон> <прогон>`;
- ворота: `uv run razbor03 compare --old <до…> --new <после…>` — код выхода 1 при регрессии;
- прогон — путь к `eval/out/runs/*.json` или `ref:<имя>` из `eval/reference-run.json`;
- через OpenRouter: `ANTHROPIC_BASE_URL=https://openrouter.ai/api`, ключ — `ANTHROPIC_AUTH_TOKEN`, модели `anthropic/…`.

## Устройство

| Путь | Что |
|---|---|
| `eval/questions.yaml` | 30 вопросов: тег-ловушка, `check_sql`, `trap_sql`, допуск |
| `src/razbor03/spec.py` | формат набора и его проверки |
| `src/razbor03/reference.py` | живой эталон, допуск, «ловушка кусает» |
| `src/razbor03/scenarios.py` | сценарии: base, reload (дозагрузка), reload-stale, no-anomaly-rule |
| `src/razbor03/agent.py` | адаптер агента: `answer(question) -> Answer`; цены моделей |
| `src/razbor03/runs.py` | прогон: только ответы и трассы, без вердиктов |
| `src/razbor03/checkers.py` | проверяющие: live, frozen, judge; сравнение проверяющего с живым эталоном |
| `src/razbor03/gate.py` | pass@1, pass^k, плавающие вопросы; ворота `compare` |
| `src/razbor03/experiment.py`, `report.py`, `cli.py` | эксперимент статьи, отчёт, команды |
| `eval/reference-run.json` | прогон автора: ответы, вердикты судей, сводка — цифры статьи |

## Правила

1. Только синтетические данные; реальные базы, выгрузки и названия компаний не подключать.
2. Эталон — запрос, а не число. Относительное время — через данные, без дат-литералов.
3. Эталон не идёт через витрины и слой метрик агента: он проверяет их, а не повторяет.
4. Новый вопрос с ловушкой — с `trap_sql`, и `uv run razbor03 refs` не пишет «ловушка не кусает». Допуск не подгонять под ответ.
5. Ответ и вердикт хранятся раздельно; вердикт пересчитывается, ответ — нет.
6. Платный прогон — только по просьбе человека; сначала `--only` на одном-двух вопросах.
7. Ключ API — только из окружения; `.env` не читать и не коммитить.

## Скиллы

`add-eval-question`, `compare-runs`, `explain-failure` — в `.claude/skills/`.
