-- R04 · Сумма не в том масштабе
-- table: sales
-- severity: block
-- action: hold
-- fix: resend
-- why: цена единицы в 20 раз выше или ниже медианы SKU за 90 дней — это копейки вместо рублей (или наоборот), а не скидка. Ждём исправленный файл.
SELECT s.load_id, s.row_no,
       'цена ' || round(s.amount / s.qty, 2) || ' при медиане ' || round(r.price, 2) AS detail
FROM stage.sales s
JOIN core.ref_price r USING (sku)
WHERE s.qty <> 0
  AND (s.amount / s.qty > 20 * r.price OR s.amount / s.qty < r.price / 20);
