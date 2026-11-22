"""Хранилище: загрузка пакета выгрузки в raw с проверками, витрины, контрольные суммы.

Пакет — папка с manifest.json и файлами объектов (см. source.export). Порядок загрузки:
1. прочитать файлы во временные таблицы;
2. проверки K1 (полнота против манифеста) и K2 (ключи) — провал отклоняет пакет целиком,
   raw и водяной знак не меняются;
3. K3 (ссылки на справочники) — документ с битой ссылкой задерживается в meta.held, остальные идут;
4. заменить в raw область выгрузки: всё / даты документов / изменённые объекты / магазин × месяц.
"""
from __future__ import annotations

import json
import time as _time
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

import duckdb

from .source import DOC_TYPES, EMPTY_REF, REGISTER

MARTS_SQL = Path(__file__).with_name("marts.sql")

SCHEMA = """
CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS meta;
CREATE TABLE IF NOT EXISTS raw.stores (ref VARCHAR, code VARCHAR, name VARCHAR, region VARCHAR, opened_on DATE,
  deletion_mark BOOLEAN, data_version VARCHAR, batch_id INTEGER);
CREATE TABLE IF NOT EXISTS raw.products (ref VARCHAR, code VARCHAR, name VARCHAR, category VARCHAR, brand VARCHAR,
  unit VARCHAR, deletion_mark BOOLEAN, data_version VARCHAR, batch_id INTEGER);
CREATE TABLE IF NOT EXISTS raw.partners (ref VARCHAR, name VARCHAR, kind VARCHAR, deletion_mark BOOLEAN,
  data_version VARCHAR, batch_id INTEGER);
CREATE TABLE IF NOT EXISTS raw.docs (ref VARCHAR, doc_type VARCHAR, number VARCHAR, doc_date DATE, store_ref VARCHAR,
  partner_ref VARCHAR, posted BOOLEAN, deletion_mark BOOLEAN, data_version VARCHAR, modified_at TIMESTAMP,
  batch_id INTEGER);
CREATE TABLE IF NOT EXISTS raw.doc_lines (doc_ref VARCHAR, line_no INTEGER, product_ref VARCHAR, qty INTEGER,
  amount DECIMAL(14,2));
CREATE TABLE IF NOT EXISTS raw.moves (recorder VARCHAR, recorder_type VARCHAR, line_no INTEGER, period DATE,
  record_type VARCHAR, store_ref VARCHAR, product_ref VARCHAR, qty INTEGER, active BOOLEAN);
CREATE TABLE IF NOT EXISTS meta.loads (batch_id INTEGER, exported_at TIMESTAMP, filter_kind VARCHAR, status VARCHAR,
  docs INTEGER, lines INTEGER, moves INTEGER, held INTEGER, seconds DOUBLE, checks VARCHAR);
CREATE TABLE IF NOT EXISTS meta.held (batch_id INTEGER, doc_ref VARCHAR, doc_type VARCHAR, check_id VARCHAR,
  detail VARCHAR);
CREATE TABLE IF NOT EXISTS meta.state (key VARCHAR PRIMARY KEY, value VARCHAR);
"""

LINE_T = 'STRUCT("LineNumber" INTEGER, "Номенклатура_Key" VARCHAR, "Количество" INTEGER, "Сумма" DECIMAL(14,2))[]'
COLUMNS = {
    "Catalog_Магазины": {"Ref_Key": "VARCHAR", "Code": "VARCHAR", "Description": "VARCHAR", "Регион": "VARCHAR",
                         "ДатаОткрытия": "VARCHAR", "DeletionMark": "BOOLEAN", "DataVersion": "VARCHAR"},
    "Catalog_Номенклатура": {"Ref_Key": "VARCHAR", "Code": "VARCHAR", "Description": "VARCHAR",
                             "Категория": "VARCHAR", "Бренд": "VARCHAR", "ЕдиницаИзмерения": "VARCHAR",
                             "DeletionMark": "BOOLEAN", "DataVersion": "VARCHAR"},
    "Catalog_Контрагенты": {"Ref_Key": "VARCHAR", "Description": "VARCHAR", "ВидКонтрагента": "VARCHAR",
                            "DeletionMark": "BOOLEAN", "DataVersion": "VARCHAR"},
    "doc": {"Ref_Key": "VARCHAR", "Number": "VARCHAR", "Date": "VARCHAR", "Posted": "BOOLEAN",
            "DeletionMark": "BOOLEAN", "DataVersion": "VARCHAR", "ДатаИзменения": "VARCHAR",
            "Магазин_Key": "VARCHAR", "Контрагент_Key": "VARCHAR", "Товары": LINE_T},
    REGISTER: {"Recorder": "VARCHAR", "Recorder_Type": "VARCHAR", "Period": "VARCHAR", "LineNumber": "INTEGER",
               "Active": "BOOLEAN", "RecordType": "VARCHAR", "Магазин_Key": "VARCHAR",
               "Номенклатура_Key": "VARCHAR", "Количество": "INTEGER"},
}


@dataclass
class LoadResult:
    batch_id: int
    status: str                       # applied | rejected
    checks: list[dict]
    held: list[str] = field(default_factory=list)
    docs: int = 0
    lines: int = 0
    moves: int = 0
    seconds: float = 0.0


def _cols_sql(cols: dict) -> str:
    return "{" + ", ".join(f"'{k}': '{v}'" for k, v in cols.items()) + "}"


class Warehouse:
    def __init__(self, path=":memory:"):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.con = duckdb.connect(str(path))
        self.con.execute("SET enable_progress_bar = false")
        self.con.execute(SCHEMA)
        self._k3_rows: list = []

    def close(self) -> None:
        self.con.close()

    # ---------- состояние ----------
    def get_state(self, key: str, default: str | None = None) -> str | None:
        r = self.con.execute("SELECT value FROM meta.state WHERE key = ?", [key]).fetchone()
        return r[0] if r else default

    def set_state(self, key: str, value: str) -> None:
        self.con.execute("INSERT OR REPLACE INTO meta.state VALUES (?, ?)", [key, value])

    # ---------- загрузка ----------
    def _read(self, tmp: str, path: Path, cols: dict) -> None:
        c = self.con
        if path.stat().st_size == 0:
            c.execute(f"CREATE OR REPLACE TEMP TABLE {tmp} AS SELECT * FROM (SELECT "
                      + ", ".join(f'NULL::{t} AS "{k}"' for k, t in cols.items()) + ") WHERE false")
        else:
            c.execute(f"""CREATE OR REPLACE TEMP TABLE {tmp} AS SELECT * FROM read_json('{path.as_posix()}',
                          format = 'newline_delimited', columns = {_cols_sql(cols)})""")

    def load_batch(self, batch_dir) -> LoadResult:
        t0 = _time.perf_counter()
        d = Path(batch_dir)
        man = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
        objs = man["objects"]
        c = self.con
        batch_id = (c.execute("SELECT coalesce(max(batch_id), 0) FROM meta.loads").fetchone()[0] or 0) + 1
        tmp = {"Catalog_Магазины": "b_stores", "Catalog_Номенклатура": "b_products",
               "Catalog_Контрагенты": "b_partners", REGISTER: "b_moves"}
        for name, t in tmp.items():
            self._read(t, d / objs[name]["file"], COLUMNS[name])
        parts = []
        for dt in DOC_TYPES:
            name = f"Document_{dt}"
            self._read(f"b_doc_{len(parts)}", d / objs[name]["file"], COLUMNS["doc"])
            parts.append(f"SELECT '{dt}' AS doc_type, * FROM b_doc_{len(parts)}")
        c.execute("CREATE OR REPLACE TEMP TABLE b_docs AS " + " UNION ALL ".join(parts))
        c.execute("""CREATE OR REPLACE TEMP TABLE b_lines AS
                     SELECT Ref_Key AS doc_ref, doc_type, u.* FROM b_docs, unnest(Товары) AS t(u)""")

        checks = [self._k1(objs), self._k2()]
        held: list[str] = []
        self._k3_rows = []
        if all(ch["ok"] for ch in checks):
            k3 = self._k3()
            checks.append(k3)
            held = k3["held"]
            status = "applied"
        else:
            status = "rejected"
        res = LoadResult(batch_id, status, checks, held)
        if status == "applied":
            self._apply(man, batch_id, held, res)
        res.seconds = _time.perf_counter() - t0
        c.execute("INSERT INTO meta.loads VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                  [batch_id, man["exported_at"], man["filter"]["kind"], status, res.docs, res.lines, res.moves,
                   len(held), res.seconds, json.dumps(checks, ensure_ascii=False, default=str)])
        return res

    def _k1(self, objs: dict) -> dict:
        """Полнота: сколько объектов, строк и сумм обещал манифест — столько и прочитали."""
        c = self.con
        bad = []
        for name, t in (("Catalog_Магазины", "b_stores"), ("Catalog_Номенклатура", "b_products"),
                        ("Catalog_Контрагенты", "b_partners")):
            n = c.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
            if n != objs[name]["count"]:
                bad.append(f"{name}: {n} из {objs[name]['count']}")
        for dt in DOC_TYPES:
            name = f"Document_{dt}"
            n, nl, s = c.execute("""SELECT count(DISTINCT d.Ref_Key), count(l.doc_ref), coalesce(sum(l."Сумма"), 0)
                                    FROM b_docs d LEFT JOIN b_lines l ON l.doc_ref = d.Ref_Key AND l.doc_type = d.doc_type
                                    WHERE d.doc_type = ?""", [dt]).fetchone()
            o = objs[name]
            if n != o["count"] or nl != o["lines"] or Decimal(s) != Decimal(o["sum"]):
                bad.append(f"{name}: документов {n} из {o['count']}, строк {nl} из {o['lines']}, сумма {s} из {o['sum']}")
        n, q = c.execute('SELECT count(*), coalesce(sum("Количество"), 0) FROM b_moves').fetchone()
        o = objs[REGISTER]
        if n != o["count"] or q != o["qty"]:
            bad.append(f"{REGISTER}: записей {n} из {o['count']}, количество {q} из {o['qty']}")
        return {"id": "K1", "name": "полнота пакета против манифеста", "ok": not bad, "detail": bad}

    def _k2(self) -> dict:
        """Ключи: ссылка заполнена, не пустая и не повторяется; у документа есть дата и магазин."""
        c = self.con
        bad = []
        for t in ("b_stores", "b_products", "b_partners", "b_docs"):
            n_bad, n_dup = c.execute(f"""SELECT count(*) FILTER (WHERE Ref_Key IS NULL OR Ref_Key = '{EMPTY_REF}'),
                                                count(*) - count(DISTINCT Ref_Key) FROM {t}""").fetchone()
            if n_bad or n_dup:
                bad.append(f"{t}: пустых ссылок {n_bad}, повторов {n_dup}")
        n = c.execute(f"""SELECT count(*) FROM b_docs WHERE Date IS NULL OR Магазин_Key IS NULL
                          OR Магазин_Key = '{EMPTY_REF}'""").fetchone()[0]
        if n:
            bad.append(f"документов без даты или магазина: {n}")
        return {"id": "K2", "name": "ключи и обязательные поля", "ok": not bad, "detail": bad}

    def _k3(self) -> dict:
        """Ссылки: товар и магазин документа есть в справочниках этого же пакета."""
        rows = self.con.execute("""
          SELECT DISTINCT d.Ref_Key, d.doc_type, 'нет магазина ' || d.Магазин_Key FROM b_docs d
          WHERE d.Магазин_Key NOT IN (SELECT Ref_Key FROM b_stores)
          UNION
          SELECT DISTINCT l.doc_ref, l.doc_type, 'нет товара ' || coalesce(l."Номенклатура_Key", 'NULL') FROM b_lines l
          WHERE l."Номенклатура_Key" IS NULL OR l."Номенклатура_Key" NOT IN (SELECT Ref_Key FROM b_products)
          ORDER BY 1""").fetchall()
        self._k3_rows = rows
        held = sorted({r[0] for r in rows})
        return {"id": "K3", "name": "ссылки на справочники", "ok": not held,
                "detail": [f"{r[1]} {r[0]}: {r[2]}" for r in rows[:20]], "held": held}

    def _apply(self, man: dict, batch_id: int, held: list[str], res: LoadResult) -> None:
        c = self.con
        f = man["filter"]
        c.execute("BEGIN TRANSACTION")
        try:
            for t, sql in (
                ("raw.stores", """SELECT Ref_Key, Code, Description, Регион, date_trunc('day', ДатаОткрытия::TIMESTAMP)::DATE,
                                  DeletionMark, DataVersion, ? FROM b_stores"""),
                ("raw.products", """SELECT Ref_Key, Code, Description, Категория, Бренд, ЕдиницаИзмерения, DeletionMark,
                                    DataVersion, ? FROM b_products"""),
                ("raw.partners", "SELECT Ref_Key, Description, ВидКонтрагента, DeletionMark, DataVersion, ? FROM b_partners"),
            ):
                c.execute(f"DELETE FROM {t}")                      # справочники — целиком каждую ночь
                c.execute(f"INSERT INTO {t} {sql}", [batch_id])
            # область замены документов
            c.execute("CREATE OR REPLACE TEMP TABLE b_ok AS SELECT * FROM b_docs WHERE NOT list_contains(?, Ref_Key)",
                      [held or ["-"]])
            if f["kind"] == "all":
                scope = "true", []
            elif f["kind"] == "doc_date":
                scope = "doc_date BETWEEN ? AND ?", [f["from"], f["to"]]
            elif f["kind"] == "changed_since":
                scope = "ref IN (SELECT Ref_Key FROM b_ok)", []
            elif f["kind"] == "store_months":
                keys = [f"{s}|{m}" for s, m in f["pairs"]] or ["-"]
                scope = ("list_contains(?, store_ref || '|' || strftime(date_trunc('month', doc_date), '%Y-%m-%d'))",
                         [keys])
            else:
                raise ValueError(f["kind"])
            c.execute(f"CREATE OR REPLACE TEMP TABLE gone AS SELECT ref FROM raw.docs WHERE {scope[0]}", scope[1])
            c.execute("""CREATE OR REPLACE TEMP TABLE gone AS SELECT ref FROM gone
                         UNION SELECT Ref_Key FROM b_ok""")
            c.execute("DELETE FROM raw.moves WHERE recorder IN (SELECT ref FROM gone)")
            c.execute("DELETE FROM raw.doc_lines WHERE doc_ref IN (SELECT ref FROM gone)")
            c.execute("DELETE FROM raw.docs WHERE ref IN (SELECT ref FROM gone)")
            c.execute("""INSERT INTO raw.docs SELECT Ref_Key, doc_type, Number, Date::TIMESTAMP::DATE, Магазин_Key,
                           nullif(Контрагент_Key, ?), Posted, DeletionMark, DataVersion, ДатаИзменения::TIMESTAMP, ?
                         FROM b_ok""", [EMPTY_REF, batch_id])
            c.execute("""INSERT INTO raw.doc_lines SELECT l.doc_ref, l.LineNumber, l."Номенклатура_Key",
                           l."Количество", l."Сумма" FROM b_lines l WHERE l.doc_ref IN (SELECT Ref_Key FROM b_ok)""")
            c.execute("""INSERT INTO raw.moves SELECT Recorder, replace(Recorder_Type, 'StandardODATA.Document_', ''),
                           LineNumber, Period::TIMESTAMP::DATE, RecordType, Магазин_Key, Номенклатура_Key, Количество, Active
                         FROM b_moves WHERE Recorder IN (SELECT Ref_Key FROM b_ok)""")
            for ref, dt, detail in self._k3_rows:
                c.execute("INSERT INTO meta.held VALUES (?, ?, ?, 'K3', ?)", [batch_id, ref, dt, detail])
            c.execute("COMMIT")
        except Exception:
            c.execute("ROLLBACK")
            raise
        res.docs = c.execute("SELECT count(*) FROM b_ok").fetchone()[0]
        res.lines = c.execute("SELECT count(*) FROM b_lines WHERE doc_ref IN (SELECT Ref_Key FROM b_ok)").fetchone()[0]
        res.moves = c.execute("SELECT count(*) FROM b_moves WHERE Recorder IN (SELECT Ref_Key FROM b_ok)").fetchone()[0]

    # ---------- витрины и сверка ----------
    def build_marts(self, as_of: date) -> float:
        t0 = _time.perf_counter()
        self.con.execute(f"SET VARIABLE as_of = DATE '{as_of.isoformat()}'")
        self.con.execute(MARTS_SQL.read_text(encoding="utf-8"))
        return _time.perf_counter() - t0

    def control_totals(self) -> list[dict]:
        rows = self.con.execute("""
          SELECT d.store_ref, date_trunc('month', d.doc_date)::DATE AS month, count(DISTINCT d.ref),
                 sum(l.qty), sum(l.amount)
          FROM raw.docs d JOIN raw.doc_lines l ON l.doc_ref = d.ref
          WHERE d.posted AND NOT d.deletion_mark GROUP BY ALL ORDER BY 1, 2""").fetchall()
        return [{"store_ref": r[0], "month": r[1], "docs": r[2], "qty": int(r[3]), "amount": r[4]} for r in rows]
