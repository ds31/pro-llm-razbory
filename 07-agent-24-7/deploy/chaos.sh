#!/usr/bin/env bash
# Хаос-тест шаблона деплоя: N задач (по умолчанию 100), 10 % отправлены дважды с тем же ключом,
# воркер убивает себя kill -9 сразу после письма в CHAOS_KILL_P задач (по умолчанию 10 %).
# Проверка: все задачи done или в dead-letter, дублей писем нет, воркеры перезапускались.
# KEEP=1 — не сносить стенд после проверки.
set -euo pipefail
cd "$(dirname "$0")"
export TIME_SCALE="${TIME_SCALE:-0.02}" CHAOS_KILL_P="${CHAOS_KILL_P:-0.1}" API_PORT="${API_PORT:-18087}"
P="docker compose -p razbor07 -f docker-compose.yml"

$P up -d --build --wait
$P exec -T api python -m razbor07 load --url http://localhost:8080 -n "${N:-100}"
status=0
$P exec -T api python -m razbor07 check --db /data/queue.db --wait 600 || status=$?
echo "Перезапуски контейнеров воркеров:"
for id in $($P ps -aq worker); do docker inspect -f '{{.Name}} restarts={{.RestartCount}}' "$id"; done
echo "Последние события трассы:"
$P logs --no-log-prefix worker | grep -E '"event": "(lease_expired|send_deduped)"' | tail -n 6 || true
[ "${KEEP:-0}" = 1 ] || $P down -v
exit $status
