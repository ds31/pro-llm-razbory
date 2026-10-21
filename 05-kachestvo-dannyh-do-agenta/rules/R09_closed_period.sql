-- R09 · Закрытый месяц
-- table: sales
-- severity: block
-- action: hold
-- fix: reopen
-- why: закрытый месяц не меняется молча: агент и отчёты уже ответили по нему. Строка ждёт решения человека — переоткрыть месяц или отклонить.
SELECT s.load_id, s.row_no, 'месяц ' || strftime(s.sale_date, '%Y-%m') || ' закрыт' AS detail
FROM stage.sales s
JOIN core.closures c ON c.month = date_trunc('month', s.sale_date)::DATE;
