-- raw → stg → mart. Витрины пересобираются целиком из raw каждую ночь: это дёшево,
-- дорого — читать источник. Параметр: getvariable('as_of') — последний загруженный бизнес-день.
CREATE SCHEMA IF NOT EXISTS stg;
CREATE SCHEMA IF NOT EXISTS mart;

-- В аналитику идут только проведённые документы без пометки удаления: так их видят отчёты 1С.
CREATE OR REPLACE TABLE stg.docs AS
SELECT * FROM raw.docs WHERE posted AND NOT deletion_mark;

CREATE OR REPLACE TABLE stg.stores AS
SELECT ref AS store_ref, code::INTEGER AS store_id, name AS store_name, region, opened_on FROM raw.stores;

-- Справочник — текущее состояние карточки (без истории): категория меняется задним числом во всех отчётах.
CREATE OR REPLACE TABLE stg.products AS
SELECT ref AS product_ref, code AS sku, name AS product_name, category, brand FROM raw.products;

-- Продажи по дням × магазин × SKU — те же колонки, что у витрины пакета 01: слой метрик подключается без правок.
CREATE OR REPLACE TABLE mart.sales_daily AS
SELECT d.doc_date AS sale_date,
       date_trunc('month', d.doc_date)::DATE AS month,
       s.store_id, s.region, p.sku, p.category, p.brand,
       sum(l.qty)::BIGINT AS net_qty,
       sum(l.amount) AS net_amount,
       sum(CASE WHEN l.qty < 0 THEN -l.amount ELSE 0 END) AS return_amount
FROM stg.docs d
JOIN raw.doc_lines l ON l.doc_ref = d.ref
JOIN stg.stores s ON s.store_ref = d.store_ref
JOIN stg.products p ON p.product_ref = l.product_ref
WHERE d.doc_type = 'РозничныеПродажи'
GROUP BY ALL;

-- Поступления от поставщиков по дням.
CREATE OR REPLACE TABLE mart.receipts_daily AS
SELECT d.doc_date AS receipt_date, s.store_id, s.region, coalesce(pt.name, '—') AS partner,
       p.sku, p.category, sum(l.qty)::BIGINT AS qty, sum(l.amount) AS amount
FROM stg.docs d
JOIN raw.doc_lines l ON l.doc_ref = d.ref
JOIN stg.stores s ON s.store_ref = d.store_ref
JOIN stg.products p ON p.product_ref = l.product_ref
LEFT JOIN raw.partners pt ON pt.ref = d.partner_ref
WHERE d.doc_type = 'ПоступлениеТоваров'
GROUP BY ALL;

-- Остатки считаются из движений регистра, как в 1С: приход плюс, расход минус.
CREATE OR REPLACE TEMP TABLE mv AS
SELECT store_ref, product_ref, date_trunc('month', period)::DATE AS month,
       sum(CASE record_type WHEN 'Receipt' THEN qty ELSE -qty END)::BIGINT AS delta
FROM raw.moves WHERE active AND period <= getvariable('as_of')
GROUP BY ALL;

-- Остаток на конец каждого полного месяца (полуаддитивная мера, как в пакете 01).
CREATE OR REPLACE TABLE mart.stock_month_end AS
WITH months AS (
  SELECT range::DATE AS month
  FROM range((SELECT min(month) FROM mv), date_trunc('month', getvariable('as_of'))::DATE, INTERVAL 1 MONTH)
), grid AS (SELECT DISTINCT store_ref, product_ref FROM mv),
bal AS (
  SELECT g.store_ref, g.product_ref, m.month,
         sum(coalesce(mv.delta, 0)) OVER (PARTITION BY g.store_ref, g.product_ref ORDER BY m.month) AS qty_on_hand
  FROM grid g CROSS JOIN months m
  LEFT JOIN mv ON mv.store_ref = g.store_ref AND mv.product_ref = g.product_ref AND mv.month = m.month
)
SELECT (b.month + INTERVAL 1 MONTH - INTERVAL 1 DAY)::DATE AS month_end, b.month,
       s.store_id, s.region, p.sku, p.category, p.brand, b.qty_on_hand::BIGINT AS qty_on_hand
FROM bal b
JOIN stg.stores s ON s.store_ref = b.store_ref
JOIN stg.products p ON p.product_ref = b.product_ref;

-- Остаток на последний загруженный день.
CREATE OR REPLACE TABLE mart.stock_current AS
SELECT getvariable('as_of')::DATE AS as_of, s.store_id, s.region, p.sku, p.category, p.brand,
       sum(mv.delta)::BIGINT AS qty_on_hand
FROM mv
JOIN stg.stores s ON s.store_ref = mv.store_ref
JOIN stg.products p ON p.product_ref = mv.product_ref
GROUP BY ALL;

CREATE OR REPLACE TABLE mart.stores AS SELECT store_id, store_name, region, opened_on FROM stg.stores;
CREATE OR REPLACE TABLE mart.products AS SELECT sku, product_name, category, brand FROM stg.products;
