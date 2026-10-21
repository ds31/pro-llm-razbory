-- R05 · SKU нет в справочнике
-- table: sales
-- severity: block
-- action: hold
-- fix: wait
-- why: строку без карточки не разложить по категории и бренду. Продажа настоящая — держим её в карантине и отпускаем, когда придёт карточка.
SELECT s.load_id, s.row_no, 'нет карточки ' || s.sku AS detail
FROM stage.sales s
WHERE NOT EXISTS (SELECT 1 FROM core.products p WHERE p.sku = s.sku);
