-- K1 · Предыдущий месяц закрыт
SELECT ($month::DATE - INTERVAL 1 MONTH)::DATE AS month, 'предыдущий месяц не закрыт' AS problem
WHERE NOT EXISTS (SELECT 1 FROM core.closures WHERE month = ($month::DATE - INTERVAL 1 MONTH)::DATE);
