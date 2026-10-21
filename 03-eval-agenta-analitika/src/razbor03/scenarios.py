"""Сценарии данных и платформы, на которых проверяется агент.

base             — выгрузка 10.10.2026, как в пакете 01: сентябрь закрыт, октябрь — десять дней.
reload           — дозагрузка 10.11.2026: продажи 11.10–10.11 и остатки на 31.10; октябрь закрыт,
                   closed_through в слое метрик сдвинут на 2026-10-31.
reload-stale     — та же дозагрузка, но closed_through забыли сдвинуть (платформа устарела).
no-anomaly-rule  — данные base, но из layers.sql убрано правило «|qty| >= 1000 — ошибка сканера».

Сырые данные (raw) сценария не зависят от платформы: эталон check_sql считается по raw,
поэтому поломка витрин не ломает эталон.
"""
from __future__ import annotations

import dataclasses
import random
import shutil
from dataclasses import dataclass
from datetime import date, timedelta
from importlib.resources import files
from pathlib import Path

import duckdb
import razbor01
from razbor01 import synth
from razbor01.layers import prepare_db
from razbor01.metrics import Catalog, load_catalog
from razbor01.tools import open_db

PLATFORM_ROOT = Path(razbor01.__file__).resolve().parents[2]   # папка пакета 01: metrics.yaml
RELOAD_UNTIL = date(2026, 11, 10)
RELOAD_CLOSED = date(2026, 10, 31)
RELOAD_SEED = 44
ANOMALY_RULE = "\nWHERE abs(qty) < 1000;"


@dataclass(frozen=True)
class Scenario:
    name: str
    db: str                 # файл базы в папке данных
    closed_through: date    # что записано в слое метрик
    note: str


SCENARIOS = {s.name: s for s in [
    Scenario("base", "base.duckdb", date(2026, 9, 30), "выгрузка 10.10.2026: сентябрь закрыт, октябрь — 10 дней"),
    Scenario("reload", "reload.duckdb", RELOAD_CLOSED,
             "дозагрузка 10.11.2026: октябрь закрыт, ноябрь — 10 дней; closed_through сдвинут"),
    Scenario("reload-stale", "reload.duckdb", date(2026, 9, 30),
             "дозагрузка 10.11.2026, но closed_through в слое метрик не сдвинут"),
    Scenario("no-anomaly-rule", "no-anomaly-rule.duckdb", date(2026, 9, 30),
             "из layers.sql убрано правило аномалий"),
]}


def layers_sql(without_anomaly_rule: bool = False) -> str:
    sql = files("razbor01").joinpath("layers.sql").read_text(encoding="utf-8")
    if without_anomaly_rule:
        if sql.count(ANOMALY_RULE) != 1:
            raise ValueError("правило аномалий в layers.sql не найдено — сценарий устарел")
        sql = sql.replace(ANOMALY_RULE, ";")
    return sql


def append_reload(con: duckdb.DuckDBPyConnection, until: date = RELOAD_UNTIL, closed: date = RELOAD_CLOSED,
                  seed: int = RELOAD_SEED) -> None:
    """Дописать в raw продажи после последней даты по `until` и остатки на концы месяцев по `closed`.

    История не меняется: новые строки генерируются отдельным генератором случайных чисел.
    """
    rng = random.Random(seed)
    stores = con.execute("SELECT store_id, opened_on FROM raw.stores ORDER BY store_id").fetchall()
    prices = dict(con.execute(
        "SELECT sku, arg_max(amount / qty, sale_date) FROM raw.sales WHERE qty > 0 AND qty < 1000 GROUP BY sku "
        "ORDER BY sku").fetchall())
    skus = sorted(prices)
    sale_id = con.execute("SELECT max(sale_id) FROM raw.sales").fetchone()[0]
    d = con.execute("SELECT max(sale_date) FROM raw.sales").fetchone()[0] + timedelta(days=1)
    sales = []
    while d <= until:
        months = (d.year - synth.START.year) * 12 + d.month - synth.START.month
        trend = 1 + 0.01 * months
        for store_id, opened in stores:
            if d < opened:
                continue
            for _ in range(rng.randint(8, 16)):
                sku = skus[rng.randrange(len(skus))]
                price = float(prices[sku])
                qty = -rng.randint(1, 2) if rng.random() < 0.03 else max(1, round(rng.randint(1, 6) * synth.SEASON[d.month] * trend))
                sale_id += 1
                sales.append((sale_id, d, store_id, sku, qty, round(qty * price, 2)))
        d += timedelta(days=1)
    con.executemany("INSERT INTO raw.sales VALUES (?, ?, ?, ?, ?, ?)", sales)
    last_snap = con.execute("SELECT max(snapshot_date) FROM raw.stock").fetchone()[0]
    stock = []
    for me in synth._month_ends(date(last_snap.year, last_snap.month, 1), date(closed.year, closed.month, 1)):
        if me <= last_snap:
            continue
        stock += [(me, sid, sku, rng.randint(0, 60)) for sid, opened in stores if me >= opened for sku in skus]
    con.executemany("INSERT INTO raw.stock VALUES (?, ?, ?, ?)", stock)


def build_data(data_dir: Path | str) -> dict[str, Path]:
    """Собрать базы всех сценариев. Возвращает {файл: путь}."""
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    base = prepare_db(data_dir / "base.duckdb")
    out = {"base.duckdb": base}
    for name, change in (("reload.duckdb", "reload"), ("no-anomaly-rule.duckdb", "no_anomaly")):
        path = data_dir / name
        path.unlink(missing_ok=True)
        shutil.copyfile(base, path)
        con = duckdb.connect(str(path))
        try:
            if change == "reload":
                append_reload(con)
            con.execute(layers_sql(without_anomaly_rule=change == "no_anomaly"))
        finally:
            con.close()
        out[name] = path
    return out


def open_scenario(data_dir: Path | str, name: str) -> tuple[duckdb.DuckDBPyConnection, Catalog]:
    """База сценария только на чтение и слой метрик с его closed_through."""
    sc = SCENARIOS[name]
    con = open_db(Path(data_dir) / sc.db)
    cat = dataclasses.replace(load_catalog(PLATFORM_ROOT / "metrics.yaml"), closed_through=sc.closed_through)
    return con, cat
