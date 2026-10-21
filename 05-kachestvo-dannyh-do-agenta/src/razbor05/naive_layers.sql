-- Без ворот: что пришло, то и в витрине. Справочник как есть (дубль карточки размножит продажи),
-- никаких фильтров строк; формулы витрин — те же, что в пакете 01.
CREATE SCHEMA IF NOT EXISTS mart;

CREATE OR REPLACE TABLE mart.sales_daily AS
SELECT s.sale_date,
       date_trunc('month', s.sale_date)::DATE AS month,
       s.store_id, st.region, s.sku, p.category, p.brand,
       sum(s.qty) AS net_qty,
       sum(s.amount) AS net_amount,
       sum(CASE WHEN s.qty < 0 THEN -s.amount ELSE 0 END) AS return_amount
FROM raw.sales s
JOIN raw.products p USING (sku)
JOIN raw.stores st USING (store_id)
GROUP BY ALL;

CREATE OR REPLACE TABLE mart.stock_month_end AS
SELECT k.snapshot_date AS month_end,
       date_trunc('month', k.snapshot_date)::DATE AS month,
       k.store_id, st.region, k.sku, p.category, p.brand,
       k.qty_on_hand
FROM raw.stock k
JOIN raw.products p USING (sku)
JOIN raw.stores st USING (store_id);
