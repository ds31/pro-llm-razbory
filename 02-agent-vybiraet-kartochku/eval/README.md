# eval

- `scenarios.yaml` — пять покупателей с жёсткими фильтрами в форме Shop MCP; пул подходящих товаров считается по `data/catalog_erp.csv`, видимость — по `data/catalog.csv`;
- `fixtures/` — обезличенный снимок Shop MCP от 17.10.2026 (`meta.json` — запросы и дата): `tools.json`, `search.json` (поиск с фильтром по полу), `search-base.json` и `search-filtered.json` (50 товаров без фильтра и с `rating.variant {min: 4, min_count: 20}`);
- прогон — `uv run razbor02 all` из папки пакета;
- критерий «прошёл» — свежий офлайн-прогон `eval/out/run.json` совпадает с `reference-run.json` (сравнение JSON, допуск 0: всё детерминировано seed и снимком); команда печатает «прогон совпадает»;
- `reference-run.json` — прогон автора, цифры статьи;
- `out/` — ваши прогоны (`live/` — живой Shop MCP), в git не попадают.
