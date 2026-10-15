-- raw → stg → mart. Каждое правило — в одном месте, с комментарием.
CREATE SCHEMA IF NOT EXISTS stg;
CREATE SCHEMA IF NOT EXISTS mart;

-- Справочник без дублей: на SKU одна карточка — последняя загруженная.
CREATE OR REPLACE TABLE stg.products AS
SELECT sku, product_name, category, brand
FROM raw.products
QUALIFY row_number() OVER (PARTITION BY sku ORDER BY loaded_at DESC) = 1;

-- Продажи без аномалий: |qty| >= 1000 — ошибка сканера, в аналитику не идёт.
CREATE OR REPLACE TABLE stg.sales AS
SELECT sale_id, sale_date, store_id, sku, qty, amount
FROM raw.sales
WHERE abs(qty) < 1000;

-- Календарь месяцев: закрыт месяц, если по нему есть снимок остатков на конец месяца.
CREATE OR REPLACE TABLE mart.months AS
WITH m AS (
  SELECT DISTINCT date_trunc('month', sale_date)::DATE AS month FROM raw.sales
)
SELECT m.month,
       EXISTS (SELECT 1 FROM raw.stock s WHERE date_trunc('month', s.snapshot_date) = m.month) AS is_closed
FROM m;

-- Продажи по дням × магазин × SKU, только закрытые месяцы.
CREATE OR REPLACE TABLE mart.sales_daily AS
SELECT s.sale_date,
       date_trunc('month', s.sale_date)::DATE AS month,
       s.store_id, st.region, s.sku, p.category, p.brand,
       sum(s.qty) AS net_qty,
       sum(s.amount) AS net_amount,
       sum(CASE WHEN s.qty < 0 THEN -s.amount ELSE 0 END) AS return_amount
FROM stg.sales s
JOIN stg.products p USING (sku)
JOIN raw.stores st USING (store_id)
JOIN mart.months mo ON mo.month = date_trunc('month', s.sale_date) AND mo.is_closed
GROUP BY ALL;

-- Остатки на конец месяца (полуаддитивная мера).
CREATE OR REPLACE TABLE mart.stock_month_end AS
SELECT k.snapshot_date AS month_end,
       date_trunc('month', k.snapshot_date)::DATE AS month,
       k.store_id, st.region, k.sku, p.category, p.brand,
       k.qty_on_hand
FROM raw.stock k
JOIN stg.products p USING (sku)
JOIN raw.stores st USING (store_id);

CREATE OR REPLACE TABLE mart.stores AS SELECT store_id, store_name, region, opened_on FROM raw.stores;
CREATE OR REPLACE TABLE mart.products AS SELECT * FROM stg.products;
