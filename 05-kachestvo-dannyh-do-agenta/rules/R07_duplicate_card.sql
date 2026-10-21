-- R07 · Вторая карточка на SKU
-- table: products
-- severity: warn
-- action: pass
-- fix: none
-- why: на SKU одна карточка. Новая заменяет старую (последняя загруженная — как в слое stg пакета 01), а предупреждение показывает, что справочник завёл дубль: без этого join размножит продажи.
SELECT p.load_id, p.row_no, 'вторая карточка ' || p.sku || ': «' || p.product_name || '»' AS detail
FROM stage.products p
WHERE EXISTS (SELECT 1 FROM core.products c WHERE c.sku = p.sku)
UNION ALL
SELECT load_id, row_no, 'вторая карточка ' || sku || ' в одной загрузке: «' || product_name || '»' AS detail
FROM (SELECT load_id, row_no, sku, product_name,
             row_number() OVER (PARTITION BY sku ORDER BY loaded_at, row_no) AS k
      FROM stage.products)
WHERE k > 1;
