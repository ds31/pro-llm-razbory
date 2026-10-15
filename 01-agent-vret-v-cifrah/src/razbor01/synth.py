"""Синтетическая розничная сеть: 12 магазинов, 200 товаров, 24 закрытых месяца + незакрытый октябрь 2026.

Ловушки (намеренно):
- дубли в справочнике: у 10 SKU по две карточки в raw.products (join размножает строки продаж);
- незакрытый последний месяц: продажи 01–10.10.2026 есть, остатков на конец октября нет;
- аномальные строки: 40 строк с qty = 9999 (ошибка сканера), 8 из них — магазин 2 в августе 2026;
- возвраты: строки с отрицательными qty и amount.
"""
from __future__ import annotations

import csv
import random
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

import duckdb

SEED = 43
START = date(2024, 10, 1)
AS_OF = date(2026, 10, 10)          # данные выгружены 10.10.2026: октябрь не закрыт
LAST_CLOSED_MONTH = date(2026, 9, 1)
N_STORES = 12
N_SKUS = 200
N_DUP_SKUS = 10
ANOMALY_QTY = 9999
ANOMALY_STORE = 2                   # 8 аномальных строк в августе 2026
REGIONS = ["Север", "Юг", "Запад", "Восток"]
CATEGORIES = {  # категория: (мин. цена, макс. цена)
    "Молочные продукты": (60, 240),
    "Бакалея": (40, 320),
    "Напитки": (50, 260),
    "Бытовая химия": (90, 690),
    "Снеки": (35, 180),
    "Заморозка": (120, 560),
}
BRANDS = ["Полдень", "Северная марка", "Добрый двор", "Сокол", "Луговое",
          "Бережок", "Простые вещи", "Утро", "Ладья", "Своё"]
SEASON = {1: 0.85, 2: 0.85, 3: 0.95, 4: 1.0, 5: 1.0, 6: 1.05,
          7: 1.05, 8: 1.0, 9: 0.95, 10: 1.0, 11: 1.05, 12: 1.3}


def _month_ends(start: date, last_month: date) -> list[date]:
    out, m = [], start
    while m <= last_month:
        nxt = date(m.year + (m.month == 12), m.month % 12 + 1, 1)
        out.append(nxt - timedelta(days=1))
        m = nxt
    return out


def generate(db_path: Path | str, seed: int = SEED) -> Path:
    """Создать DuckDB-файл со схемой raw. Существующий файл перезаписывается."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    rng = random.Random(seed)

    stores = []
    for i in range(1, N_STORES + 1):
        opened = date(2025, 6, 1) if i == N_STORES else date(2023, 1, 1) + timedelta(days=30 * i)
        stores.append((i, f"Магазин №{i}", REGIONS[(i - 1) % len(REGIONS)], opened))

    products, prices = [], {}
    cats = list(CATEGORIES)
    for k in range(1, N_SKUS + 1):
        sku = f"SKU-{k:04d}"
        cat = cats[(k - 1) % len(cats)]
        lo, hi = CATEGORIES[cat]
        prices[sku] = round(rng.uniform(lo, hi), 2)
        brand = BRANDS[(k * 7) % len(BRANDS)]
        products.append((sku, f"Товар {k}", cat, brand, datetime(2024, 9, 15, 10, 0)))
    dup_ks = list(range(1, len(cats) + 1)) + rng.sample(range(len(cats) + 1, N_SKUS + 1), N_DUP_SKUS - len(cats))
    for k in dup_ks:  # первые шесть — по одному на каждую категорию
        sku, name, cat, brand, _ = products[k - 1]
        products.append((sku, f"{name} (новая карточка)", cat, brand, datetime(2025, 3, 1, 10, 0)))

    skus = list(prices)
    sales, sale_id, d = [], 0, START
    while d <= AS_OF:
        months_from_start = (d.year - START.year) * 12 + d.month - START.month
        trend = 1 + 0.01 * months_from_start
        inflation = 1 + 0.005 * months_from_start
        for store_id, _, _, opened in stores:
            if d < opened:
                continue
            for _ in range(rng.randint(8, 16)):
                sku = skus[rng.randrange(len(skus))]
                price = round(prices[sku] * inflation, 2)
                if rng.random() < 0.03:
                    qty = -rng.randint(1, 2)
                else:
                    qty = max(1, round(rng.randint(1, 6) * SEASON[d.month] * trend))
                sale_id += 1
                sales.append((sale_id, d, store_id, sku, qty, round(qty * price, 2)))
        d += timedelta(days=1)

    anomaly_dates = [date(2026, 8, 3 + 3 * i) for i in range(8)]                       # магазин ANOMALY_STORE
    anomaly_dates += [date(2025, 4, 1) + timedelta(days=rng.randrange(91)) for _ in range(32)]  # 2 кв. 2025
    for n, ad in enumerate(anomaly_dates):
        store_id = ANOMALY_STORE if n < 8 else rng.randint(1, N_STORES - 1)
        sku = skus[rng.randrange(len(skus))]
        sale_id += 1
        sales.append((sale_id, ad, store_id, sku, ANOMALY_QTY, round(ANOMALY_QTY * prices[sku], 2)))

    stock = [(me, s[0], sku, rng.randint(0, 60))
             for me in _month_ends(START, LAST_CLOSED_MONTH)
             for s in stores if me >= s[3]
             for sku in skus]

    con = duckdb.connect(str(db_path))
    try:
        con.execute("CREATE SCHEMA raw")
        con.execute("CREATE TABLE raw.stores (store_id INTEGER, store_name VARCHAR, region VARCHAR, opened_on DATE)")
        con.executemany("INSERT INTO raw.stores VALUES (?, ?, ?, ?)", stores)
        con.execute("CREATE TABLE raw.products (sku VARCHAR, product_name VARCHAR, category VARCHAR, "
                    "brand VARCHAR, loaded_at TIMESTAMP)")
        con.executemany("INSERT INTO raw.products VALUES (?, ?, ?, ?, ?)", products)
        with tempfile.TemporaryDirectory() as tmp:
            _load_csv(con, Path(tmp) / "sales.csv", sales, "raw.sales",
                      "sale_id BIGINT, sale_date DATE, store_id INTEGER, sku VARCHAR, qty INTEGER, amount DECIMAL(14,2)")
            _load_csv(con, Path(tmp) / "stock.csv", stock, "raw.stock",
                      "snapshot_date DATE, store_id INTEGER, sku VARCHAR, qty_on_hand INTEGER")
    finally:
        con.close()
    return db_path


def _load_csv(con, path: Path, rows: list[tuple], table: str, ddl: str) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(rows)
    con.execute(f"CREATE TABLE {table} ({ddl})")
    con.execute(f"COPY {table} FROM '{path.as_posix()}' (HEADER false)")
