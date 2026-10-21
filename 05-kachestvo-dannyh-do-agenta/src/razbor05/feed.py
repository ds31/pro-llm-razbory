"""Живой поток загрузок поверх истории пакета 01.

История — база пакета 01 (seed 43) до 30.09.2026: сентябрь закрыт. Дальше данные приходят файлами:
- продажи — файл на магазин за день, приходит утром следующего дня;
- снимок остатков на конец месяца — файл на магазин, приходит 2-го числа следующего месяца;
- справочник товаров — файл с новыми карточками, когда они появляются.

`make_feed` даёт «правду» (что было на самом деле) и чистый поток загрузок; дефекты вносит `defects.py`.
"""
from __future__ import annotations

import csv
import random
import tempfile
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

import duckdb

from razbor01.synth import SEASON, START, generate

HISTORY_END = date(2026, 9, 30)      # история закрыта по 30.09.2026
FEED_START = date(2026, 10, 1)       # первый день живого потока
FEED_END = date(2026, 11, 14)        # последний день продаж в потоке
MONTH = date(2026, 10, 1)            # месяц, который закрываем
MONTH_END = date(2026, 10, 31)
SIM_START = date(2026, 10, 1)        # первое утро потока (файлы продаж — со 2-го)
SIM_END = date(2026, 11, 15)         # последнее утро прогона
STOCK_LAG = 2                        # снимок остатков на конец месяца приходит 2-го числа
FEED_SEED = 46                       # неделя W46


def days(a: date, b: date) -> list[date]:
    return [a + timedelta(n) for n in range((b - a).days + 1)]


def calendar_closed_through(as_of: date) -> date:
    """Закрытие «по календарю»: 1-го числа предыдущий месяц считается закрытым."""
    return as_of.replace(day=1) - timedelta(days=1)


def build_base(path: Path | str) -> Path:
    """История сети: база пакета 01 без октябрьских строк + справочные цены SKU за сентябрь."""
    path = generate(path)
    con = duckdb.connect(str(path))
    try:
        con.execute("DELETE FROM raw.sales WHERE sale_date > ?", [HISTORY_END])
        con.execute("CREATE SCHEMA gen")
        con.execute("""CREATE TABLE gen.sku_price AS
                       SELECT sku, median(amount / qty) AS price FROM raw.sales
                       WHERE qty > 0 AND abs(qty) < 1000 AND sale_date >= '2026-09-01' GROUP BY sku""")
    finally:
        con.close()
    return Path(path)


@dataclass
class Load:
    load_id: int
    kind: str                       # sales | stock | products
    store_id: int | None
    business_date: date | None      # день продаж или дата снимка
    received_on: date | None        # утро, когда файл пришёл; None — придёт только по запросу
    replaces: bool = False          # исправленный файл заменяет раздел (магазин × день)
    on_request: bool = False        # источник пришлёт его, только если ворота попросили
    lag: int = 0                    # через сколько дней после запроса
    label: str = ""


@dataclass
class Feed:
    seed: int
    stores: list[tuple]                                  # (store_id, region)
    skus: list[str]
    prices: dict[str, float]
    next_sale_id: int
    loads: dict[int, Load] = field(default_factory=dict)
    sales: dict[int, list[list]] = field(default_factory=dict)      # load_id → [sale_id, sale_date, store_id, sku, qty, amount]
    stock: dict[int, list[list]] = field(default_factory=dict)      # load_id → [snapshot_date, store_id, sku, qty_on_hand]
    products: dict[int, list[list]] = field(default_factory=dict)   # load_id → [sku, product_name, category, brand, loaded_at]
    truth_sales: dict[tuple, list[tuple]] = field(default_factory=dict)   # (store_id, day) → строки продаж
    truth_stock: dict[int, list[tuple]] = field(default_factory=dict)     # store_id → снимок на конец месяца
    truth_products: list[tuple] = field(default_factory=list)            # новые карточки (без дублей)
    injections: list = field(default_factory=list)

    def new_load(self, kind: str, store_id, business_date, received_on, **kw) -> Load:
        load = Load(len(self.loads) + 1, kind, store_id, business_date, received_on, **kw)
        self.loads[load.load_id] = load
        {"sales": self.sales, "stock": self.stock, "products": self.products}[kind][load.load_id] = []
        return load

    def sales_load(self, store_id: int, day: date) -> Load:
        """Исходный файл продаж магазина за день."""
        for ld in self.loads.values():
            if ld.kind == "sales" and ld.store_id == store_id and ld.business_date == day and not ld.replaces \
                    and ld.label == "":
                return ld
        raise KeyError((store_id, day))

    def stock_load(self, store_id: int) -> Load:
        for ld in self.loads.values():
            if ld.kind == "stock" and ld.store_id == store_id and not ld.replaces:
                return ld
        raise KeyError(store_id)

    def take_sale_id(self) -> int:
        self.next_sale_id += 1
        return self.next_sale_id


def _months_from_start(d: date) -> int:
    return (d.year - START.year) * 12 + d.month - START.month


def make_feed(base: Path | str, seed: int = FEED_SEED) -> Feed:
    """Правда и чистый поток: продажи 01.10–14.11.2026 по дням и магазинам, снимок остатков на 31.10."""
    rng = random.Random(seed)
    con = duckdb.connect(str(base), read_only=True)
    try:
        stores = con.execute("SELECT store_id, region FROM raw.stores ORDER BY store_id").fetchall()
        prices = dict(con.execute("SELECT sku, price FROM gen.sku_price ORDER BY sku").fetchall())
        max_id = con.execute("SELECT max(sale_id) FROM raw.sales").fetchone()[0]
    finally:
        con.close()
    skus = sorted(prices)
    feed = Feed(seed, stores, skus, {k: float(v) for k, v in prices.items()}, int(max_id) + 1000)
    sep = 1 + 0.005 * _months_from_start(HISTORY_END)
    for d in days(FEED_START, FEED_END):
        m = _months_from_start(d)
        trend, inflation = 1 + 0.01 * m, (1 + 0.005 * m) / sep
        for store_id, _ in stores:
            load = feed.new_load("sales", store_id, d, d + timedelta(1))
            rows = []
            for _ in range(rng.randint(8, 16)):
                sku = skus[rng.randrange(len(skus))]
                price = round(feed.prices[sku] * inflation, 2)
                if rng.random() < 0.03:
                    qty = -rng.randint(1, 2)
                else:
                    qty = max(1, round(rng.randint(1, 6) * SEASON[d.month] * trend))
                rows.append((feed.take_sale_id(), d, store_id, sku, qty, round(qty * price, 2)))
            feed.truth_sales[(store_id, d)] = rows
            feed.sales[load.load_id] = [list(r) for r in rows]
    for store_id, _ in stores:
        load = feed.new_load("stock", store_id, MONTH_END, MONTH_END + timedelta(STOCK_LAG))
        rows = [(MONTH_END, store_id, sku, rng.randint(0, 60)) for sku in skus]
        feed.truth_stock[store_id] = rows
        feed.stock[load.load_id] = [list(r) for r in rows]
    return feed


# --------------------------------------------------------------------------- в DuckDB
FEED_DDL = {
    "loads": "load_id INTEGER, kind VARCHAR, store_id INTEGER, business_date DATE, received_on DATE, "
             "replaces BOOLEAN, on_request BOOLEAN, lag INTEGER, label VARCHAR",
    "sales": "load_id INTEGER, row_no INTEGER, sale_id BIGINT, sale_date DATE, store_id INTEGER, sku VARCHAR, "
             "qty INTEGER, amount DECIMAL(14,2)",
    "stock": "load_id INTEGER, row_no INTEGER, snapshot_date DATE, store_id INTEGER, sku VARCHAR, qty_on_hand INTEGER",
    "products": "load_id INTEGER, row_no INTEGER, sku VARCHAR, product_name VARCHAR, category VARCHAR, "
                "brand VARCHAR, loaded_at TIMESTAMP",
}
TRUTH_DDL = {
    "sales": "sale_id BIGINT, sale_date DATE, store_id INTEGER, sku VARCHAR, qty INTEGER, amount DECIMAL(14,2)",
    "stock": "snapshot_date DATE, store_id INTEGER, sku VARCHAR, qty_on_hand INTEGER",
    "products": "sku VARCHAR, product_name VARCHAR, category VARCHAR, brand VARCHAR, loaded_at TIMESTAMP",
}


class FeedFiles:
    """CSV-копия потока и правды: каждая конфигурация (без ворот, правила 01, ворота) грузит их к себе."""

    def __init__(self, feed: Feed):
        self._tmp = tempfile.TemporaryDirectory(prefix="razbor05-")
        self.dir = Path(self._tmp.name)
        loads = [(ld.load_id, ld.kind, ld.store_id, ld.business_date, ld.received_on, ld.replaces,
                  ld.on_request, ld.lag, ld.label) for ld in feed.loads.values()]
        self._write("feed_loads", loads)
        self._write("feed_sales", [(lid, n, *r) for lid, rows in feed.sales.items() for n, r in enumerate(rows, 1)])
        self._write("feed_stock", [(lid, n, *r) for lid, rows in feed.stock.items() for n, r in enumerate(rows, 1)])
        self._write("feed_products", [(lid, n, *r) for lid, rows in feed.products.items()
                                      for n, r in enumerate(rows, 1)])
        self._write("truth_sales", [r for rows in feed.truth_sales.values() for r in rows])
        self._write("truth_stock", [r for rows in feed.truth_stock.values() for r in rows])
        self._write("truth_products", feed.truth_products)

    def _write(self, name: str, rows) -> None:
        with (self.dir / f"{name}.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            for r in rows:
                w.writerow(["" if v is None else (v.isoformat(sep=" ") if isinstance(v, datetime) else v) for v in r])

    def load_feed(self, con: duckdb.DuckDBPyConnection) -> None:
        con.execute("CREATE SCHEMA IF NOT EXISTS feed")
        for t, ddl in FEED_DDL.items():
            self._copy(con, f"feed.{t}", ddl, f"feed_{t}")

    def load_truth(self, con: duckdb.DuckDBPyConnection) -> None:
        con.execute("CREATE SCHEMA IF NOT EXISTS truth")
        for t, ddl in TRUTH_DDL.items():
            self._copy(con, f"truth.{t}", ddl, f"truth_{t}")

    def _copy(self, con, table: str, ddl: str, name: str) -> None:
        con.execute(f"CREATE TABLE {table} ({ddl})")
        path = self.dir / (name + ".csv")
        if path.stat().st_size:
            con.execute(f"COPY {table} FROM '{path.as_posix()}' (HEADER false, DELIMITER ',', QUOTE '\"', NULLSTR '')")

    def close(self) -> None:
        self._tmp.cleanup()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def copy_history(con: duckdb.DuckDBPyConnection, base: Path | str, schema: str = "raw") -> None:
    """Скопировать историю пакета 01 (raw.*) в схему schema этого соединения."""
    con.execute(f"ATTACH '{Path(base).as_posix()}' AS b (READ_ONLY)")
    try:
        con.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
        for t in ("stores", "products", "sales", "stock"):
            con.execute(f"CREATE TABLE {schema}.{t} AS SELECT * FROM b.raw.{t}")
    finally:
        con.execute("DETACH b")
