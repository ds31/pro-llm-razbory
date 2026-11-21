# CLAUDE.md — пакет 06 «От discovery до приёмки»

Отвечай по-русски.

## Что это

Путь FDE на одном файле: `discovery.yaml` (вопросы руководства, карта данных, владельцы, эталоны) → проверка «готов к приёмке» → каркас кейсов приёмки → ворота G1–G5 по вариантам прототипа. Сквозной пример — синтетическая розничная сеть пакета 01; база, слой метрик и записанные ответы агента берутся из `../01-agent-vret-v-cifrah` (path-зависимость `razbor01`).

## Команды

- тесты: `uv run pytest -q` (в API не ходят);
- всё на примере: `uv run razbor06 all` → `eval/out/report.md`, `eval/out/summary.json`;
- проверка discovery: `uv run razbor06 check <discovery.yaml> [--no-catalog]`;
- каркас кейсов: `uv run razbor06 scaffold <discovery.yaml> -o <acceptance.yaml>`;
- ворота: `uv run razbor06 accept [--prototype <prototype.yaml>] [--variants B] [--results <results.jsonl>]`;
- прогон агента на вопросах без ответа: `uv run razbor01 eval --root eval/out/agent-root-B --variants B` (платно, ключ в окружении).

## Устройство

| Путь | Что |
|---|---|
| `src/razbor06/discovery.py` | загрузка и проверка discovery: обязательные поля, роли, карта данных, покрытие проблем и альтернатив |
| `src/razbor06/scaffold.py` | каркас кейсов приёмки: базовый кейс на вопрос, кейсы-пробы, TODO на непокрытое |
| `src/razbor06/accept.py` | эталон, ответ слоя метрик, ворота G1–G5, вердикт |
| `src/razbor06/answers.py` | ответы агента: прогон автора пакета 01 и свои `results.jsonl` |
| `src/razbor06/export.py` | вопросы без ответа → папка для `razbor01 eval --root` |
| `src/razbor06/profile.py` | профиль данных примера: строки-ошибки по месяцам, последний день продаж |
| `examples/retail/` | discovery после первой встречи и после недели, спека прототипа, кейсы приёмки |
| `templates/` | шаблоны: discovery, вопросы интервью, спека прототипа на страницу, протокол приёмки |
| `eval/reference-run.json` | прогон автора — цифры статьи |

## Правила

1. Только синтетические данные и роли вместо имён; реальные базы, выгрузки и названия компаний не подключать.
2. `examples/retail/acceptance.yaml` — вывод `scaffold`: правится `discovery.yaml`, затем `uv run razbor06 scaffold examples/retail/discovery.yaml -o examples/retail/acceptance.yaml`; тест сверяет.
3. Новое обязательное поле discovery — в `REQUIRED` (`discovery.py`) вместе с тестом и строкой шаблона.
4. Пороги приёмки — только в `prototype.yaml`; допуск по умолчанию ±0,5 %, как в пакете 01.
5. Платный прогон агента — только по просьбе человека, сначала на одном-двух вопросах.
6. Ключ API — только из окружения; `.env` не читать и не коммитить.

## Скиллы

`discovery`, `acceptance` — в `.claude/skills/`.
