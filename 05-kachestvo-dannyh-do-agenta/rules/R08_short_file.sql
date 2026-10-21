-- R08 · Подозрительно короткий файл
-- table: sales_file
-- severity: warn
-- action: pass
-- fix: none
-- why: в файле магазина за день меньше половины обычного числа строк (медиана за 28 дней). Строки принимаются — короткий день бывает, — но файл стоит сверить с кассой.
WITH f AS (
  SELECT s.load_id, l.store_id, l.business_date, count(*) AS n
  FROM stage.sales s JOIN stage.loads l USING (load_id)
  WHERE l.kind = 'sales' AND NOT l.recheck
  GROUP BY ALL
), daily AS (
  SELECT store_id, business_date, count(*) AS n FROM core.sales GROUP BY ALL
), ref AS (
  SELECT f.load_id, median(d.n) AS m
  FROM f JOIN daily d ON d.store_id = f.store_id
   AND d.business_date BETWEEN f.business_date - INTERVAL 28 DAY AND f.business_date - INTERVAL 1 DAY
  GROUP BY f.load_id
)
SELECT f.load_id, NULL::INTEGER AS row_no, 'строк ' || f.n || ' при медиане ' || ref.m AS detail
FROM f JOIN ref USING (load_id)
WHERE f.n < 0.5 * ref.m;
