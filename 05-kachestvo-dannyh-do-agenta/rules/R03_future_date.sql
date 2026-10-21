-- R03 · Дата из будущего
-- table: sales
-- severity: block
-- action: hold
-- fix: resend
-- why: продажа не может быть позже дня, когда пришёл файл. Обычно это сбитые часы кассы; строка держится в карантине до исправленного файла.
SELECT s.load_id, s.row_no, 'sale_date ' || s.sale_date || ' позже прихода файла ' || l.received_on AS detail
FROM stage.sales s
JOIN stage.loads l USING (load_id)
WHERE s.sale_date > l.received_on;
