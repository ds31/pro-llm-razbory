"""Ворота загрузки: stage → правила → core (что прошло) или карантин q (что нет) → закрытие месяца.

Каждое утро `process_day` берёт пришедшие файлы, перепроверяет карантин и решает по каждой строке:
- нарушено правило с action=drop — строка отбрасывается (мусор, обратно её не ждут);
- нарушено правило с action=hold — строка ждёт в карантине: исправленного файла (fix=resend), карточки
  в справочнике (fix=wait) или решения человека (fix=reopen);
- иначе строка принимается в core; предупреждения (warn) только пишутся в журнал.
Исправленный файл (replaces) заменяет раздел «магазин × день» целиком. Агент читает витрины, собранные из core.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import duckdb

from .feed import HISTORY_END, copy_history
from .rules import RULES_DIR, Rule, load_rules, run_rule

HISTORY_IDS = {"sales": 0, "stock": -1, "products": -2}
HISTORY_RECEIVED = HISTORY_END + timedelta(1)

DDL = """
CREATE SCHEMA core; CREATE SCHEMA stage; CREATE SCHEMA q; CREATE SCHEMA log;
CREATE TABLE core.stores AS SELECT * FROM hist.stores;
CREATE TABLE core.products (sku VARCHAR, product_name VARCHAR, category VARCHAR, brand VARCHAR, loaded_at TIMESTAMP);
CREATE TABLE core.sales (sale_id BIGINT, sale_date DATE, store_id INTEGER, sku VARCHAR, qty INTEGER,
                         amount DECIMAL(14,2), load_id INTEGER, business_date DATE);
CREATE TABLE core.stock (snapshot_date DATE, store_id INTEGER, sku VARCHAR, qty_on_hand INTEGER, load_id INTEGER);
CREATE TABLE core.loads (load_id INTEGER, kind VARCHAR, store_id INTEGER, business_date DATE, received_on DATE,
                         replaces BOOLEAN, n_rows INTEGER, accepted_rows INTEGER, held_rows INTEGER,
                         dropped_rows INTEGER, status VARCHAR);
CREATE TABLE core.closures (month DATE, closed_on DATE);
-- справочная цена SKU для R04: медиана цены единицы за последние 90 дней истории
CREATE TABLE core.ref_price AS
  SELECT sku, median(amount / qty) AS price FROM hist.sales
  WHERE qty > 0 AND abs(qty) < 1000 AND sale_date > DATE '2026-09-30' - INTERVAL 90 DAY GROUP BY sku;
CREATE TABLE stage.loads (load_id INTEGER, kind VARCHAR, store_id INTEGER, business_date DATE, received_on DATE,
                          replaces BOOLEAN, recheck BOOLEAN);
CREATE TABLE stage.sales (load_id INTEGER, row_no INTEGER, sale_id BIGINT, sale_date DATE, store_id INTEGER,
                          sku VARCHAR, qty INTEGER, amount DECIMAL(14,2), recheck BOOLEAN);
CREATE TABLE stage.stock (load_id INTEGER, row_no INTEGER, snapshot_date DATE, store_id INTEGER, sku VARCHAR,
                          qty_on_hand INTEGER, recheck BOOLEAN);
CREATE TABLE stage.products (load_id INTEGER, row_no INTEGER, sku VARCHAR, product_name VARCHAR, category VARCHAR,
                             brand VARCHAR, loaded_at TIMESTAMP);
CREATE TABLE stage.v (tbl VARCHAR, load_id INTEGER, row_no INTEGER, rule_id VARCHAR, action VARCHAR, detail VARCHAR);
CREATE TABLE q.sales (load_id INTEGER, row_no INTEGER, sale_id BIGINT, sale_date DATE, store_id INTEGER, sku VARCHAR,
                      qty INTEGER, amount DECIMAL(14,2), business_date DATE, rules VARCHAR, action VARCHAR,
                      status VARCHAR, since DATE, resolved_on DATE);
CREATE TABLE q.stock (load_id INTEGER, row_no INTEGER, snapshot_date DATE, store_id INTEGER, sku VARCHAR,
                      qty_on_hand INTEGER, business_date DATE, rules VARCHAR, action VARCHAR, status VARCHAR,
                      since DATE, resolved_on DATE);
CREATE TABLE log.violations (day DATE, tbl VARCHAR, load_id INTEGER, row_no INTEGER, rule_id VARCHAR,
                             action VARCHAR, detail VARCHAR);
CREATE TABLE log.completeness (day DATE, store_id INTEGER, business_date DATE);
CREATE TABLE log.requests (day DATE, kind VARCHAR, store_id INTEGER, business_date DATE, rules VARCHAR);
"""

ROW_TABLES = {"sales": ("sale_id, sale_date, store_id, sku, qty, amount", "sales"),
              "stock": ("snapshot_date, store_id, sku, qty_on_hand", "stock")}


@dataclass
class DayResult:
    day: date
    loads: int = 0
    accepted: int = 0
    held: int = 0
    dropped: int = 0
    released: int = 0
    warnings: int = 0
    requests: list = field(default_factory=list)   # (kind, store_id, business_date)


class Gate:
    def __init__(self, con: duckdb.DuckDBPyConnection, base: Path | str, rules_dir: Path | str = RULES_DIR):
        self.con = con
        self.rules = load_rules(rules_dir)
        self.rules_dir = Path(rules_dir)
        self.by_id = {r.id: r for r in self.rules}
        copy_history(con, base, "hist")
        con.execute(DDL)
        self.history = self._load_history()

    # ------------------------------------------------------------------ история
    def _load_history(self) -> dict:
        """История пакета 01 проходит через те же правила одной загрузкой: что поймают R01 и R07."""
        con = self.con
        h = HISTORY_IDS
        con.execute("INSERT INTO stage.loads VALUES (?, 'history', NULL, NULL, ?, false, false)",
                    [h["sales"], HISTORY_RECEIVED])
        con.execute("INSERT INTO stage.loads VALUES (?, 'history', NULL, NULL, ?, false, false)",
                    [h["stock"], HISTORY_RECEIVED])
        con.execute(f"""INSERT INTO stage.sales SELECT {h['sales']}, row_number() OVER (ORDER BY sale_id),
                        sale_id, sale_date, store_id, sku, qty, amount, false FROM hist.sales""")
        con.execute(f"""INSERT INTO stage.stock SELECT {h['stock']}, row_number() OVER (ORDER BY snapshot_date, store_id, sku),
                        snapshot_date, store_id, sku, qty_on_hand, false FROM hist.stock""")
        con.execute(f"""INSERT INTO stage.products SELECT {h['products']}, row_number() OVER (ORDER BY loaded_at, sku),
                        sku, product_name, category, brand, loaded_at FROM hist.products""")
        res = self._run_batch(HISTORY_RECEIVED, history=True)
        con.execute("""INSERT INTO core.closures
                       SELECT DISTINCT date_trunc('month', sale_date)::DATE, ? FROM core.sales""", [HISTORY_RECEIVED])
        counts = dict(con.execute("SELECT rule_id, count(*) FROM log.violations GROUP BY 1 ORDER BY 1").fetchall())
        return {"accepted": res.accepted, "dropped": res.dropped, "held": res.held, "by_rule": counts}

    # ------------------------------------------------------------------ день
    def process_day(self, day: date, load_ids: list[int]) -> DayResult:
        con = self.con
        for t in ("loads", "sales", "stock", "products", "v"):
            con.execute(f"DELETE FROM stage.{t}")
        if load_ids:
            con.execute("CREATE OR REPLACE TEMP TABLE due AS SELECT unnest(?::INTEGER[]) AS load_id", [load_ids])
            con.execute("""INSERT INTO stage.loads SELECT load_id, kind, store_id, business_date, ?, replaces, false
                           FROM feed.loads WHERE load_id IN (SELECT load_id FROM due)""", [day])
            self._apply_replaces(day)
            con.execute("""INSERT INTO stage.sales SELECT load_id, row_no, sale_id, sale_date, store_id, sku, qty, amount,
                           false FROM feed.sales WHERE load_id IN (SELECT load_id FROM due)""")
            con.execute("""INSERT INTO stage.stock SELECT load_id, row_no, snapshot_date, store_id, sku, qty_on_hand, false
                           FROM feed.stock WHERE load_id IN (SELECT load_id FROM due)""")
            con.execute("""INSERT INTO stage.products SELECT load_id, row_no, sku, product_name, category, brand, loaded_at
                           FROM feed.products WHERE load_id IN (SELECT load_id FROM due)""")
        # карантин перепроверяется каждой загрузкой: вдруг пришла карточка или правило уже не срабатывает
        con.execute("""INSERT INTO stage.sales SELECT load_id, row_no, sale_id, sale_date, store_id, sku, qty, amount, true
                       FROM q.sales WHERE status = 'held'""")
        con.execute("""INSERT INTO stage.stock SELECT load_id, row_no, snapshot_date, store_id, sku, qty_on_hand, true
                       FROM q.stock WHERE status = 'held'""")
        con.execute("""INSERT INTO stage.loads SELECT load_id, kind, store_id, business_date, received_on, replaces, true
                       FROM core.loads WHERE load_id IN (SELECT load_id FROM q.sales WHERE status = 'held'
                                                          UNION SELECT load_id FROM q.stock WHERE status = 'held')""")
        res = self._run_batch(day)
        res.loads = len(load_ids)
        self._log_completeness(day)
        return res

    def _apply_replaces(self, day: date) -> None:
        """Исправленный файл заменяет раздел целиком: принятые строки раздела — долой, удержанные — «заменено»."""
        con = self.con
        fix = ("EXISTS (SELECT 1 FROM stage.loads f WHERE f.replaces AND f.kind = '{k}' "
               "AND f.store_id = {t}.store_id AND f.business_date = {t}.{d})")
        con.execute("DELETE FROM core.sales WHERE " + fix.format(k="sales", t="core.sales", d="business_date"))
        con.execute("DELETE FROM core.stock WHERE " + fix.format(k="stock", t="core.stock", d="snapshot_date"))
        for k in ("sales", "stock"):
            con.execute(f"UPDATE q.{k} AS t SET status = 'replaced', resolved_on = ? WHERE t.status = 'held' AND "
                        + fix.format(k=k, t="t", d="business_date"), [day])
        con.execute("""UPDATE core.loads AS t SET status = 'replaced', accepted_rows = 0, held_rows = 0
                       WHERE NOT t.replaces AND EXISTS (SELECT 1 FROM stage.loads f WHERE f.replaces AND f.kind = t.kind
                         AND f.store_id = t.store_id AND f.business_date = t.business_date)""")

    def _rules(self, *tables: str) -> list[Rule]:
        return [r for r in self.rules if r.table in tables]

    def _run_batch(self, day: date, history: bool = False) -> DayResult:
        con = self.con
        res = DayResult(day)
        # 1. справочник: предупреждения, затем upsert «последняя карточка на SKU»
        for r in self._rules("products"):
            self._collect(r, "products")
        con.execute("DELETE FROM core.products WHERE sku IN (SELECT sku FROM stage.products)")
        con.execute("""INSERT INTO core.products SELECT sku, product_name, category, brand, loaded_at FROM stage.products
                       QUALIFY row_number() OVER (PARTITION BY sku ORDER BY loaded_at DESC, row_no DESC) = 1""")
        # 2. продажи, файлы продаж, остатки
        for r in self._rules("sales", "sales_file"):
            self._collect(r, "sales")
        for r in self._rules("stock"):
            self._collect(r, "stock")
        con.execute("""INSERT INTO log.violations
                       SELECT ?, v.tbl, v.load_id, v.row_no, v.rule_id, v.action, v.detail FROM stage.v v
                       WHERE v.row_no IS NULL OR v.tbl = 'products' OR NOT EXISTS (
                         SELECT 1 FROM stage.sales s WHERE v.tbl = 'sales' AND s.load_id = v.load_id
                           AND s.row_no = v.row_no AND s.recheck
                         UNION ALL
                         SELECT 1 FROM stage.stock s WHERE v.tbl = 'stock' AND s.load_id = v.load_id
                           AND s.row_no = v.row_no AND s.recheck)""", [day])
        res.warnings = con.execute("SELECT count(*) FROM stage.v WHERE action = 'pass'").fetchone()[0]
        for tbl, (cols, _) in ROW_TABLES.items():
            self._decide(tbl, cols, day, res, history)
        self._register_loads(res)
        if not history:
            res.requests = self._requests(day)
        return res

    def _collect(self, rule: Rule, tbl: str) -> None:
        self.con.execute(f"INSERT INTO stage.v SELECT '{tbl}', load_id, row_no, '{rule.id}', '{rule.action}', detail "
                         f"FROM ({rule.sql}) AS r")

    def _decide(self, tbl: str, cols: str, day: date, res: DayResult, history: bool) -> None:
        con = self.con
        bdate = "s.sale_date" if tbl == "sales" else "s.snapshot_date"
        con.execute(f"""CREATE OR REPLACE TEMP TABLE dec AS
            SELECT s.*, coalesce(l.business_date, {bdate}) AS business_date,
                   CASE WHEN bool_or(v.action = 'drop') THEN 'drop'
                        WHEN bool_or(v.action = 'hold') THEN 'hold' ELSE 'accept' END AS decision,
                   string_agg(DISTINCT v.rule_id, ',' ORDER BY v.rule_id)
                     FILTER (WHERE v.action IN ('drop', 'hold')) AS rules
            FROM stage.{tbl} s
            LEFT JOIN stage.loads l USING (load_id)
            LEFT JOIN stage.v v ON v.tbl = '{tbl}' AND v.load_id = s.load_id AND v.row_no = s.row_no
            GROUP BY ALL""")
        if tbl == "sales":
            con.execute("""INSERT INTO core.sales SELECT sale_id, sale_date, store_id, sku, qty, amount, load_id, business_date
                           FROM dec WHERE decision = 'accept'""")
        else:
            con.execute("""INSERT INTO core.stock SELECT snapshot_date, store_id, sku, qty_on_hand, load_id
                           FROM dec WHERE decision = 'accept'""")
        con.execute(f"""INSERT INTO q.{tbl} SELECT load_id, row_no, {cols}, business_date, rules, decision,
                        CASE decision WHEN 'drop' THEN 'dropped' ELSE 'held' END, ?, NULL
                        FROM dec WHERE NOT recheck AND decision <> 'accept'""", [day])
        con.execute(f"""UPDATE q.{tbl} AS t SET status = 'released', resolved_on = ?
                        FROM dec WHERE dec.recheck AND dec.decision = 'accept'
                          AND t.load_id = dec.load_id AND t.row_no = dec.row_no""", [day])
        con.execute(f"""UPDATE q.{tbl} AS t SET rules = dec.rules,
                          status = CASE dec.decision WHEN 'drop' THEN 'dropped' ELSE 'held' END
                        FROM dec WHERE dec.recheck AND dec.decision <> 'accept'
                          AND t.load_id = dec.load_id AND t.row_no = dec.row_no""")
        n = dict(con.execute("SELECT decision || CASE WHEN recheck THEN '_re' ELSE '' END, count(*) FROM dec GROUP BY 1")
                 .fetchall())
        res.accepted += n.get("accept", 0)
        res.held += n.get("hold", 0)
        res.dropped += n.get("drop", 0)
        res.released += n.get("accept_re", 0)
        con.execute("CREATE OR REPLACE TEMP TABLE dec_counts AS SELECT load_id, recheck, count(*) AS n, "
                    "count(*) FILTER (WHERE decision = 'accept') AS a, count(*) FILTER (WHERE decision = 'hold') AS h, "
                    "count(*) FILTER (WHERE decision = 'drop') AS d FROM dec GROUP BY ALL")
        con.execute(f"CREATE OR REPLACE TEMP TABLE dec_counts_{tbl} AS SELECT * FROM dec_counts")

    def _register_loads(self, res: DayResult) -> None:
        con = self.con
        con.execute("""CREATE OR REPLACE TEMP TABLE dc AS
                       SELECT * FROM dec_counts_sales UNION ALL SELECT * FROM dec_counts_stock""")
        con.execute("""INSERT INTO core.loads
            SELECT l.load_id, l.kind, l.store_id, l.business_date, l.received_on, l.replaces,
                   coalesce(c.n, 0), coalesce(c.a, 0), coalesce(c.h, 0), coalesce(c.d, 0),
                   CASE WHEN l.kind = 'products' THEN 'accepted'
                        WHEN coalesce(c.h, 0) > 0 THEN 'held'
                        WHEN coalesce(c.a, 0) = 0 AND coalesce(c.d, 0) > 0 THEN 'dropped' ELSE 'accepted' END
            FROM stage.loads l LEFT JOIN dc c ON c.load_id = l.load_id AND NOT c.recheck
            WHERE NOT l.recheck""")
        # перепроверенные строки: отпущенные добавляются к принятым
        con.execute("""UPDATE core.loads AS t SET accepted_rows = t.accepted_rows + c.a, held_rows = c.h,
                         status = CASE WHEN c.h > 0 THEN 'held' ELSE 'accepted' END
                       FROM dc c WHERE c.recheck AND c.load_id = t.load_id AND t.status <> 'replaced'""")

    def _requests(self, day: date) -> list[tuple]:
        """Новые удержания с fix=resend → запрос исправленного файла у источника (один раз на раздел)."""
        con = self.con
        resend = [r.id for r in self.rules if r.fix == "resend"]
        if not resend:
            return []
        pat = "|".join(resend)
        rows = con.execute(f"""
            SELECT DISTINCT kind, store_id, business_date, rules FROM (
              SELECT 'sales' AS kind, store_id, business_date, rules FROM q.sales
              WHERE status = 'held' AND since = ? AND regexp_matches(rules, '{pat}')
              UNION ALL
              SELECT 'stock', store_id, business_date, rules FROM q.stock
              WHERE status = 'held' AND since = ? AND regexp_matches(rules, '{pat}')) t
            WHERE NOT EXISTS (SELECT 1 FROM log.requests r WHERE r.kind = t.kind AND r.store_id = t.store_id
                                AND r.business_date = t.business_date)
            ORDER BY 1, 2, 3""", [day, day]).fetchall()
        seen = {}
        for kind, store_id, bdate, rules in rows:
            seen.setdefault((kind, store_id, bdate), rules)
        out = []
        for (kind, store_id, bdate), rules in seen.items():
            con.execute("INSERT INTO log.requests VALUES (?, ?, ?, ?, ?)", [day, kind, store_id, bdate, rules])
            out.append((kind, store_id, bdate))
        return out

    def _log_completeness(self, day: date) -> None:
        """C01 каждое утро: по каждому дню открытых месяцев до вчерашнего — есть ли принятый файл магазина."""
        start = self.first_open_month()
        to = day - timedelta(1)
        if to < start:
            return
        rows = run_rule(self.con, self.by_id["C01"], date_from=start, date_to=to)
        if rows:
            self.con.executemany("INSERT INTO log.completeness VALUES (?, ?, ?)", [(day, r[0], r[1]) for r in rows])

    # ------------------------------------------------------------------ закрытие
    def first_open_month(self) -> date:
        last = self.con.execute("SELECT max(month) FROM core.closures").fetchone()[0]
        return date(last.year + (last.month == 12), last.month % 12 + 1, 1)

    def closed_through(self) -> date:
        return self.first_open_month() - timedelta(1)

    def try_close(self, day: date):
        """Закрыть по порядку все месяцы, которые прошли чек-лист к утру day."""
        from .close import close_month
        out = []
        while True:
            month = self.first_open_month()
            month_end = date(month.year + (month.month == 12), month.month % 12 + 1, 1) - timedelta(1)
            if month_end >= day:
                return out
            res = close_month(self.con, month, day, self.rules_dir)
            out.append(res)
            if not res.closed:
                return out
