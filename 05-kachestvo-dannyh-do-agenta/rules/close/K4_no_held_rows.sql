-- K4 · В карантине нет удержанных строк за месяц
SELECT 'продажи' AS kind, rules, count(*) AS n_rows, 'удержано в карантине' AS problem
FROM q.sales
WHERE status = 'held' AND business_date BETWEEN $month::DATE AND $month_end::DATE
GROUP BY ALL
UNION ALL
SELECT 'остатки', rules, count(*), 'удержано в карантине'
FROM q.stock
WHERE status = 'held' AND business_date BETWEEN $month::DATE AND $month_end::DATE
GROUP BY ALL;
