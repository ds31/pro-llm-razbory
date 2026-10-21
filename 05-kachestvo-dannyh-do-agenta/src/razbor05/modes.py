"""Три способа пустить живой поток к агенту — и правда.

- `raw`     без ворот: файлы дописываются в слой как пришли; месяц закрыт по календарю (1-го числа).
- `rules01` правила пакета 01 в слоях stg/mart (|qty| < 1000, одна карточка на SKU); месяц закрыт, когда есть
            снимок остатков (так mart.months пакета 01 решает is_closed).
- `gate`    ворота: правила на каждой загрузке, карантин, закрытие месяца по чек-листу.
Во всех трёх агент читает одинаковые витрины mart.* и один слой метрик; разное только то, что в них попало,
и `closed_through`.
"""
from __future__ import annotations

from datetime import date
from importlib.resources import files
from pathlib import Path

import duckdb

from razbor01.layers import build_layers

from .feed import FeedFiles, calendar_closed_through, copy_history
from .gate import DayResult, Gate
from .questions import answer_all, revenue_of

LABELS = {
    "raw": "без ворот: сырые загрузки, закрытие по календарю",
    "rules01": "правила 01 в слоях, закрытие по снимку остатков",
    "gate": "ворота: правила, карантин, закрытие по чек-листу",
}
SHORT = {"raw": "без ворот", "rules01": "правила 01", "gate": "ворота"}


class Mode:
    key = ""

    def __init__(self, base: Path | str, ff: FeedFiles):
        self.con = duckdb.connect()
        ff.load_feed(self.con)
        self.setup(base)

    def setup(self, base) -> None:
        copy_history(self.con, base, "raw")

    def ingest(self, day: date, load_ids: list[int]) -> DayResult:
        """Дописать файлы как есть (без ворот и в правилах 01 загрузчик одинаковый)."""
        res = DayResult(day, loads=len(load_ids))
        if not load_ids:
            return res
        con = self.con
        con.execute("CREATE OR REPLACE TEMP TABLE due AS SELECT unnest(?::INTEGER[]) AS load_id", [load_ids])
        con.execute("""INSERT INTO raw.sales SELECT sale_id, sale_date, store_id, sku, qty, amount
                       FROM feed.sales WHERE load_id IN (SELECT load_id FROM due)""")
        con.execute("""INSERT INTO raw.stock SELECT snapshot_date, store_id, sku, qty_on_hand
                       FROM feed.stock WHERE load_id IN (SELECT load_id FROM due)""")
        con.execute("""INSERT INTO raw.products SELECT sku, product_name, category, brand, loaded_at
                       FROM feed.products WHERE load_id IN (SELECT load_id FROM due)""")
        return res

    def closed_through(self, day: date) -> date:
        raise NotImplementedError

    def build_mart(self) -> None:
        raise NotImplementedError

    def answers(self, day: date) -> dict:
        return answer_all(self.con, self.closed_through(day))

    def revenue(self, day: date, month: date) -> float | None:
        return revenue_of(self.con, self.closed_through(day), month)

    def close(self) -> None:
        self.con.close()


class RawMode(Mode):
    key = "raw"

    def setup(self, base) -> None:
        super().setup(base)
        # история до октября уже вычищена (как в пакете 01) — меряем только то, что делают новые загрузки
        self.con.execute("DELETE FROM raw.sales WHERE abs(qty) >= 1000")
        self.con.execute("""CREATE OR REPLACE TABLE raw.products AS SELECT * FROM raw.products
                            QUALIFY row_number() OVER (PARTITION BY sku ORDER BY loaded_at DESC) = 1""")

    def closed_through(self, day: date) -> date:
        return calendar_closed_through(day)

    def build_mart(self) -> None:
        self.con.execute(files("razbor05").joinpath("naive_layers.sql").read_text(encoding="utf-8"))


class Rules01Mode(Mode):
    key = "rules01"

    def closed_through(self, day: date) -> date:
        return self.con.execute("SELECT max(snapshot_date) FROM raw.stock").fetchone()[0]

    def build_mart(self) -> None:
        build_layers(self.con)


class GateMode(Mode):
    key = "gate"

    def setup(self, base) -> None:
        self.gate = Gate(self.con, base)

    def ingest(self, day: date, load_ids: list[int]) -> DayResult:
        res = self.gate.process_day(day, load_ids)
        self.closures = self.gate.try_close(day)
        return res

    def closed_through(self, day: date) -> date:
        return self.gate.closed_through()

    def build_mart(self) -> None:
        sql = files("razbor01").joinpath("layers.sql").read_text(encoding="utf-8")
        self.con.execute(sql.replace("raw.", "core."))   # слой 01 без изменений, но поверх принятого воротами


class Truth:
    """Что было на самом деле: история пакета 01 + правдивые октябрь и ноябрь, витрины пакета 01."""

    def __init__(self, base: Path | str, ff: FeedFiles):
        self.con = duckdb.connect()
        copy_history(self.con, base, "raw")
        ff.load_truth(self.con)
        self.con.execute("INSERT INTO raw.sales SELECT * FROM truth.sales")
        self.con.execute("INSERT INTO raw.stock SELECT * FROM truth.stock")
        self.con.execute("INSERT INTO raw.products SELECT * FROM truth.products")
        build_layers(self.con)

    def answers(self, closed_through: date) -> dict:
        return answer_all(self.con, closed_through)

    def revenue(self, month: date) -> float | None:
        from .questions import month_end
        return revenue_of(self.con, month_end(month), month)

    def close(self) -> None:
        self.con.close()


MODES = {"raw": RawMode, "rules01": Rules01Mode, "gate": GateMode}
