-- R06 · Отрицательный остаток
-- table: stock
-- severity: block
-- action: hold
-- fix: resend
-- why: остаток на полке не бывает меньше нуля; минус — непроведённое списание или перемещение. Снимок по этим SKU ждёт исправления.
SELECT load_id, row_no, 'остаток ' || qty_on_hand || ' по ' || sku AS detail
FROM stage.stock
WHERE qty_on_hand < 0;
