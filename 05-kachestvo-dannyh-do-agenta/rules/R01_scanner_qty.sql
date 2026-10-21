-- R01 · Ошибка сканера
-- table: sales
-- severity: block
-- action: drop
-- fix: none
-- why: |qty| ≥ 1000 — ошибка сканера: таких покупок в магазине сети не бывает. Строка — мусор, её не ждут обратно.
SELECT load_id, row_no, 'qty = ' || qty AS detail
FROM stage.sales
WHERE abs(qty) >= 1000;
