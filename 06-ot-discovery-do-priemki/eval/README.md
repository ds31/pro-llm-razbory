# eval

- кейсы приёмки — не отдельный файл вопросов, а вывод `scaffold` из `examples/retail/discovery.yaml` (`examples/retail/acceptance.yaml`);
- эталон кейса — `golden_sql` владельца числа, считается живым запросом по базе пакета 01;
- ответы агента — записанный прогон пакета 01 (`../01-agent-vret-v-cifrah/eval/reference-run.json`), привязка по варианту и дословному тексту вопроса; свои прогоны — `--results eval/out/agent-root-<вариант>/eval/out/results.jsonl`;
- критерий «прошёл» — `examples/retail/prototype.yaml`: каждое число в допуске ±0,5 %, ответ агента на каждый кейс и каждую строку разреза, средняя цена ответа ≤ $0,05, среднее время ≤ 15 с;
- `reference-run.json` — прогон автора, цифры статьи; `uv run razbor06 all` даёт то же самое, кроме даты (тест `test_reference_run_matches_fresh_run`);
- `out/` — ваши прогоны, в git не попадают.
