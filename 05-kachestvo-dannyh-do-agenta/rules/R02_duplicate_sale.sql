-- R02 · Повтор чека
-- table: sales
-- severity: block
-- action: drop
-- fix: none
-- why: sale_id уникален. Чек, который уже принят (или повторяется в этой же загрузке), — повторная загрузка файла; второй раз он выручкой не станет.
SELECT s.load_id, s.row_no, 'sale_id ' || s.sale_id || ' уже принят' AS detail
FROM stage.sales s
WHERE EXISTS (SELECT 1 FROM core.sales c WHERE c.sale_id = s.sale_id)
UNION ALL
SELECT load_id, row_no, 'sale_id ' || sale_id || ' повторяется в загрузке' AS detail
FROM (SELECT load_id, row_no, sale_id,
             row_number() OVER (PARTITION BY sale_id ORDER BY load_id, row_no) AS k
      FROM stage.sales)
WHERE k > 1;
