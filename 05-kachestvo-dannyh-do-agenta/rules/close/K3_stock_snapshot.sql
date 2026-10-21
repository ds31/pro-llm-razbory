-- K3 · Снимок остатков на конец месяца принят по каждому магазину
SELECT st.store_id, 'нет снимка остатков на ' || $month_end::DATE AS problem
FROM core.stores st
WHERE st.opened_on <= $month_end::DATE
  AND NOT EXISTS (SELECT 1 FROM core.stock k WHERE k.store_id = st.store_id AND k.snapshot_date = $month_end::DATE);
