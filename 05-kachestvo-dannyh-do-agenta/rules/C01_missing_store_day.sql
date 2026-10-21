-- C01 · Магазин не прислал файл за день
-- table: completeness
-- severity: block
-- action: hold
-- fix: wait
-- why: выручка дня без одного магазина правдоподобна, но неверна. По каждому открытому магазину за каждый день периода должен быть принятый файл продаж; пока его нет, месяц не закрывается.
SELECT st.store_id, d.day::DATE AS business_date, 'нет принятого файла продаж' AS detail
FROM core.stores st
CROSS JOIN range($date_from::TIMESTAMP, $date_to::TIMESTAMP + INTERVAL 1 DAY, INTERVAL 1 DAY) AS d(day)
WHERE st.opened_on <= d.day::DATE
  AND NOT EXISTS (SELECT 1 FROM core.loads l
                  WHERE l.kind = 'sales' AND l.store_id = st.store_id
                    AND l.business_date = d.day::DATE AND l.accepted_rows > 0)
ORDER BY 2, 1;
