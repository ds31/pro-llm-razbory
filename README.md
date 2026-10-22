# Разборы Pro LLM

Пакеты к разборам на [pro-llm.ru](https://pro-llm.ru): как устроены AI-агенты и платформы данных под ними — со схемами, метриками и всем, чтобы применить у себя.

Каждая папка — один разбор: `CLAUDE.md` и скиллы для Claude Code, синтетические данные, eval с эталонами и запуск одной командой. Цифры из статьи воспроизводятся прогоном `eval/`.

## Разборы

| № | Рубрика | Тема | Статья | Пакет |
|---|---|---|---|---|
| 01 | Платформа под агентом | Почему AI-агент врёт в цифрах — и какая платформа данных это лечит | [статья](https://pro-llm.ru/blog/pochemu-ai-agent-vret-v-cifrah.html) | [`01-agent-vret-v-cifrah`](https://github.com/ds31/pro-llm-razbory/tree/razbor-01/01-agent-vret-v-cifrah) |
| 02 | Как читать AI | Агент покупает в чате: кого он выберет | [статья](https://pro-llm.ru/blog/agent-pokupaet-v-chate-kogo-vyberet.html) | [`02-agent-vybiraet-kartochku`](https://github.com/ds31/pro-llm-razbory/tree/razbor-02/02-agent-vybiraet-kartochku) |
| 03 | Агент в проде | Как доказать, что AI-агент считает правильно | [статья](https://pro-llm.ru/blog/kak-dokazat-chto-ai-agent-schitaet-pravilno.html) | [`03-eval-agenta-analitika`](https://github.com/ds31/pro-llm-razbory/tree/razbor-03/03-eval-agenta-analitika) |
| 04 | Как читать AI | Какую модель брать агенту-аналитику — бенчмарк на своих данных | [статья](https://pro-llm.ru/blog/kakuyu-model-vybrat-agentu-benchmark-na-svoih-dannyh.html) | [`04-benchmark-na-svoih-dannyh`](https://github.com/ds31/pro-llm-razbory/tree/razbor-04/04-benchmark-na-svoih-dannyh) |
| 05 | Платформа под агентом | Откуда агент знает, что месяц закрыт: качество данных до агента | [статья](https://pro-llm.ru/blog/kachestvo-dannyh-do-agenta-mesyac-zakryt.html) | [`05-kachestvo-dannyh-do-agenta`](https://github.com/ds31/pro-llm-razbory/tree/razbor-05/05-kachestvo-dannyh-do-agenta) |

Рубрики: **Платформа под агентом** · **Агент в проде** · **FDE в поле** · **Как читать AI**.

## Как пользоваться

1. Склонировать репозиторий на тег разбора (`git clone -b razbor-NN https://github.com/ds31/pro-llm-razbory`) и открыть папку разбора в Claude Code.
2. Выполнить команду запуска из `README.md` папки.
3. Сверить свои цифры с цифрами в статье.

Данные во всех пакетах синтетические.

## Автор

Денис Асалханов — Forward Deployed Engineer, [pro-llm.ru](https://pro-llm.ru), Telegram [@pro_llm](https://t.me/pro_llm).
Сотрудничество: asalhanvip@gmail.com.

## Лицензия

Код — MIT, тексты и схемы — CC BY 4.0. См. [LICENSE](LICENSE).
