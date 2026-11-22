"""Синтетическая информационная база «1С» вымышленной розничной сети и её выгрузка в файлы обмена.

База живёт в DuckDB (схема ib) и изображает объекты 1С, а не таблицы СУБД: справочники
(Магазины, Номенклатура, Контрагенты), документы с табличной частью «Товары» (РозничныеПродажи,
ПоступлениеТоваров, ВводОстатков) и движения регистра накопления ОстаткиТоваров по регистратору.
Имена упрощены и не повторяют ни одну конфигурацию: в вашей базе они будут свои.

Выгрузка изображает HTTP-сервис в расширении: отдаёт объекты постранично (PAGE_OBJECTS объектов
или PAGE_ROWS движений на запрос) в формате, похожем на стандартный интерфейс OData
(Ref_Key, DataVersion, Posted, DeletionMark, табличная часть массивом). Поля ДатаИзменения
в типовой 1С у документа нет — его выставляет доработка в расширении при записи объекта.

Каждый день бизнеса (advance) добавляет продажи и поступления и делает то, что ломает наивный
инкремент: правки задним числом, отмену проведения, пометку на удаление, прямое удаление
и запись, начатую до ночной выгрузки, а зафиксированную после неё.
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path

import duckdb

PAGE_OBJECTS = 500          # объектов (справочник, документ) на один запрос к сервису
PAGE_ROWS = 5000            # движений регистра на один запрос
EMPTY_REF = "00000000-0000-0000-0000-000000000000"
EXPORT_AT = time(2, 0)      # ночная выгрузка в 02:00 следующего дня
LATE_SHARE = 10             # «поздняя» запись: один магазин из десяти (минимум один)
EDIT_WINDOW = 45            # правки задним числом — документы последних 45 дней

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
N_PARTNERS = 12
DOC_TYPES = ["РозничныеПродажи", "ПоступлениеТоваров", "ВводОстатков"]
REGISTER = "AccumulationRegister_ОстаткиТоваров_RecordType"


@dataclass(frozen=True)
class Volume:
    name: str
    stores: int
    skus: int
    history_days: int
    lines: int              # строк в документе продаж магазина за день


VOLUMES = {
    "S": Volume("S", stores=5, skus=300, history_days=365, lines=25),
    "M": Volume("M", stores=20, skus=1000, history_days=730, lines=40),
    "L": Volume("L", stores=60, skus=2000, history_days=1095, lines=40),
}


def export_time(day: date) -> datetime:
    """Ночная выгрузка после бизнес-дня day."""
    return datetime.combine(day + timedelta(days=1), EXPORT_AT)


@dataclass(frozen=True)
class DocFilter:
    kind: str                                   # all | doc_date | changed_since | store_months
    date_from: date | None = None
    date_to: date | None = None
    since: datetime | None = None
    pairs: tuple[tuple[str, date], ...] = field(default_factory=tuple)

    @classmethod
    def all(cls) -> "DocFilter":
        return cls("all")

    @classmethod
    def doc_date(cls, date_from: date, date_to: date) -> "DocFilter":
        return cls("doc_date", date_from=date_from, date_to=date_to)

    @classmethod
    def changed_since(cls, since: datetime) -> "DocFilter":
        return cls("changed_since", since=since)

    @classmethod
    def store_months(cls, pairs) -> "DocFilter":
        return cls("store_months", pairs=tuple(sorted((s, m) for s, m in pairs)))

    def to_json(self) -> dict:
        out: dict = {"kind": self.kind}
        if self.kind == "doc_date":
            out.update({"from": self.date_from.isoformat(), "to": self.date_to.isoformat()})
        elif self.kind == "changed_since":
            out["since"] = self.since.isoformat()
        elif self.kind == "store_months":
            out["pairs"] = [[s, m.isoformat()] for s, m in self.pairs]
        return out

    @staticmethod
    def from_json(d: dict) -> "DocFilter":
        k = d["kind"]
        if k == "doc_date":
            return DocFilter.doc_date(date.fromisoformat(d["from"]), date.fromisoformat(d["to"]))
        if k == "changed_since":
            return DocFilter.changed_since(datetime.fromisoformat(d["since"]))
        if k == "store_months":
            return DocFilter.store_months((s, date.fromisoformat(m)) for s, m in d["pairs"])
        return DocFilter.all()


MACROS = r"""
CREATE OR REPLACE MACRO uref(kind, id) AS
  regexp_replace(md5(kind || ':' || id::VARCHAR), '^(.{8})(.{4})(.{4})(.{4})(.{12})$', '\1-\2-\3-\4-\5');
CREATE OR REPLACE MACRO rnd(s, a, b, c) AS ((hash(s, a, b, c) % 1000003)::DOUBLE / 1000003);
"""

SCHEMA = """
CREATE SCHEMA IF NOT EXISTS ib;
CREATE TABLE ib.stores (ref VARCHAR PRIMARY KEY, code INTEGER, name VARCHAR, region VARCHAR, opened_on DATE,
  deletion_mark BOOLEAN, version INTEGER, modified_at TIMESTAMP);
CREATE TABLE ib.products (ref VARCHAR PRIMARY KEY, code VARCHAR, name VARCHAR, category VARCHAR, brand VARCHAR,
  unit VARCHAR, price DECIMAL(12,2), deletion_mark BOOLEAN, version INTEGER, modified_at TIMESTAMP);
CREATE TABLE ib.partners (ref VARCHAR PRIMARY KEY, name VARCHAR, kind VARCHAR, deletion_mark BOOLEAN,
  version INTEGER, modified_at TIMESTAMP);
CREATE TABLE ib.docs (ref VARCHAR, doc_type VARCHAR, number VARCHAR, doc_date DATE, store_ref VARCHAR,
  partner_ref VARCHAR, posted BOOLEAN, deletion_mark BOOLEAN, version INTEGER, modified_at TIMESTAMP,
  visible_at TIMESTAMP);
CREATE TABLE ib.doc_lines (doc_ref VARCHAR, line_no INTEGER, product_ref VARCHAR, qty INTEGER,
  amount DECIMAL(14,2));
CREATE TABLE ib.moves (recorder VARCHAR, recorder_type VARCHAR, line_no INTEGER, period DATE,
  record_type VARCHAR, store_ref VARCHAR, product_ref VARCHAR, qty INTEGER);
"""


class Source1C:
    """Информационная база и сервис выгрузки. Счётчики requests/rows_read/bytes_out — нагрузка на источник."""

    def __init__(self, con: duckdb.DuckDBPyConnection, volume: Volume, sim_start: date, seed: int):
        self.con = con
        self.volume = volume
        self.sim_start = sim_start
        self.history_start = sim_start - timedelta(days=volume.history_days)
        self.seed = seed
        self.requests = 0
        self.rows_read = 0
        self.bytes_out = 0

    # ---------- создание истории ----------
    @classmethod
    def create(cls, path, volume: Volume, sim_start: date, seed: int = 8) -> "Source1C":
        if path != ":memory:":
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            for f in (p, p.with_suffix(p.suffix + ".wal")):
                if f.exists():
                    f.unlink()
        con = duckdb.connect(str(path))
        con.execute("SET enable_progress_bar = false")
        con.execute(MACROS)
        con.execute(SCHEMA)
        src = cls(con, volume, sim_start, seed)
        src._history()
        return src

    def close(self) -> None:
        self.con.close()

    def _history(self) -> None:
        v, s, c = self.volume, self.seed, self.con
        hs = self.history_start
        c.execute("""
          INSERT INTO ib.stores
          SELECT uref('store', i), i, 'Магазин №' || i, ?[1 + (i - 1) % 4], ?, false, 1, ?::TIMESTAMP
          FROM range(1, ? + 1) t(i)""", [REGIONS, hs, datetime.combine(hs, time(9)), v.stores])
        cats = list(CATEGORIES)
        lo = [CATEGORIES[k][0] for k in cats]
        hi = [CATEGORIES[k][1] for k in cats]
        c.execute("""
          INSERT INTO ib.products
          SELECT uref('product', k), 'SKU-' || lpad(k::VARCHAR, 5, '0'), 'Товар ' || k,
                 ?[1 + ci], ?[1 + (hash(?, 'brand', k, 0) % 10)::BIGINT], 'шт',
                 round(?[1 + ci] + (?[1 + ci] - ?[1 + ci]) * rnd(?, 'price', k, 0), 2), false, 1, ?::TIMESTAMP
          FROM (SELECT k, (hash(?, 'cat', k, 0) % 6)::BIGINT AS ci FROM range(1, ? + 1) t(k))""",
                  [cats, BRANDS, s, lo, hi, lo, s, datetime.combine(hs, time(9)), s, v.skus])
        c.execute("""
          INSERT INTO ib.partners
          SELECT uref('partner', i), 'Поставщик ' || lpad(i::VARCHAR, 2, '0'), 'Поставщик', false, 1, ?::TIMESTAMP
          FROM range(1, ? + 1) t(i)""", [datetime.combine(hs, time(9)), N_PARTNERS])
        # ввод остатков на первый день истории: по 100 шт. каждого товара в каждом магазине
        c.execute("""
          INSERT INTO ib.docs
          SELECT uref('opening', st.code), 'ВводОстатков', 'ВО-' || lpad(st.code::VARCHAR, 3, '0'), ?,
                 st.ref, NULL, true, false, 1, ?::TIMESTAMP, ?::TIMESTAMP FROM ib.stores st""",
                  [hs, datetime.combine(hs, time(8)), datetime.combine(hs, time(8))])
        c.execute("""
          INSERT INTO ib.doc_lines
          SELECT uref('opening', st.code), row_number() OVER (PARTITION BY st.code ORDER BY p.code),
                 p.ref, 100, round(100 * p.price * 0.7, 2)
          FROM ib.stores st CROSS JOIN ib.products p""")
        self._sales_days(hs, self.sim_start - timedelta(days=1))
        self._receipt_days(hs, self.sim_start - timedelta(days=1))
        c.execute("""
          INSERT INTO ib.moves
          SELECT l.doc_ref, d.doc_type, l.line_no, d.doc_date,
                 CASE WHEN d.doc_type = 'РозничныеПродажи' AND l.qty > 0 THEN 'Expense' ELSE 'Receipt' END,
                 d.store_ref, l.product_ref, abs(l.qty)
          FROM ib.doc_lines l JOIN ib.docs d ON d.ref = l.doc_ref WHERE d.posted AND NOT d.deletion_mark""")

    def _sales_days(self, d_from: date, d_to: date, late_codes: tuple[int, ...] = ()) -> None:
        """Документ продаж магазина за день: lines разных товаров, ~3 % строк — возвраты."""
        v, s, c = self.volume, self.seed, self.con
        late = list(late_codes) or [-1]
        c.execute("""
          CREATE OR REPLACE TEMP TABLE new_docs AS
          SELECT uref('sale', st.code || ':' || d.day::DATE) AS ref, st.code, st.ref AS store_ref, d.day::DATE AS day
          FROM ib.stores st CROSS JOIN range(?::DATE, ?::DATE + 1, INTERVAL 1 DAY) d(day)""", [d_from, d_to])
        c.execute("""
          INSERT INTO ib.docs
          SELECT ref, 'РозничныеПродажи', 'РП' || strftime(day, '%y%m%d') || '-' || lpad(code::VARCHAR, 3, '0'),
                 day, store_ref, NULL, true, false, 1,
                 CASE WHEN list_contains(?, code) THEN day + INTERVAL 1 DAY + INTERVAL 117 MINUTE
                      ELSE day + INTERVAL 21 HOUR + code * INTERVAL 1 MINUTE END,
                 CASE WHEN list_contains(?, code) THEN day + INTERVAL 1 DAY + INTERVAL 124 MINUTE
                      ELSE day + INTERVAL 21 HOUR + code * INTERVAL 1 MINUTE END
          FROM new_docs""", [late, late])
        c.execute("""
          INSERT INTO ib.doc_lines
          SELECT n.ref, k + 1, p.ref, q.qty, round(q.qty * p.price, 2)
          FROM new_docs n CROSS JOIN range(0, ?) t(k)
          CROSS JOIN LATERAL (SELECT 1 + ((hash(?, n.code, n.day, 0) % ?) + k * 7919) % ? AS idx) i
          JOIN ib.products p ON p.code = 'SKU-' || lpad(i.idx::VARCHAR, 5, '0')
          CROSS JOIN LATERAL (SELECT CASE WHEN rnd(?, n.ref, k, 'ret') < 0.03 THEN -(1 + hash(?, n.ref, k, 'q') % 2)::INTEGER
                                          ELSE (1 + hash(?, n.ref, k, 'q') % 8)::INTEGER END AS qty) q""",
                  [v.lines, s, v.skus, v.skus, s, s, s])

    def _receipt_days(self, d_from: date, d_to: date) -> None:
        """Поступление в магазин раз в неделю: 2 × lines товаров по 5–23 шт. — примерно столько, сколько продано."""
        v, s, c = self.volume, self.seed, self.con
        hs = self.history_start
        c.execute("""
          CREATE OR REPLACE TEMP TABLE new_docs AS
          SELECT uref('receipt', st.code || ':' || d.day::DATE) AS ref, st.code, st.ref AS store_ref, d.day::DATE AS day
          FROM ib.stores st CROSS JOIN range(?::DATE, ?::DATE + 1, INTERVAL 1 DAY) d(day)
          WHERE (d.day::DATE - ?::DATE) % 7 = st.code % 7""", [d_from, d_to, hs])
        c.execute("""
          INSERT INTO ib.docs
          SELECT n.ref, 'ПоступлениеТоваров', 'ПТ' || strftime(day, '%y%m%d') || '-' || lpad(code::VARCHAR, 3, '0'),
                 day, store_ref, uref('partner', 1 + hash(?, n.ref, 0, 0) % ?), true, false, 1,
                 day + INTERVAL 11 HOUR + code * INTERVAL 1 MINUTE, day + INTERVAL 11 HOUR + code * INTERVAL 1 MINUTE
          FROM new_docs n""", [s, N_PARTNERS])
        c.execute("""
          INSERT INTO ib.doc_lines
          SELECT n.ref, k + 1, p.ref, q.qty, round(q.qty * p.price * 0.7, 2)
          FROM new_docs n CROSS JOIN range(0, ?) t(k)
          CROSS JOIN LATERAL (SELECT 1 + ((hash(?, 'r', n.code, n.day) % ?) + k * 7907) % ? AS idx) i
          JOIN ib.products p ON p.code = 'SKU-' || lpad(i.idx::VARCHAR, 5, '0')
          CROSS JOIN LATERAL (SELECT (5 + hash(?, n.ref, k, 'q') % 19)::INTEGER AS qty) q""",
                  [2 * v.lines, s, v.skus, v.skus, s])

    def _repost(self, refs: list[str]) -> None:
        """Перезаписать движения регистра по регистраторам — как при записи документа в 1С."""
        if not refs:
            return
        c = self.con
        c.execute("DELETE FROM ib.moves WHERE list_contains(?, recorder)", [refs])
        c.execute("""
          INSERT INTO ib.moves
          SELECT l.doc_ref, d.doc_type, l.line_no, d.doc_date,
                 CASE WHEN d.doc_type = 'РозничныеПродажи' AND l.qty > 0 THEN 'Expense' ELSE 'Receipt' END,
                 d.store_ref, l.product_ref, abs(l.qty)
          FROM ib.doc_lines l JOIN ib.docs d ON d.ref = l.doc_ref
          WHERE list_contains(?, d.ref) AND d.posted AND NOT d.deletion_mark""", [refs])

    # ---------- бизнес-день ----------
    def advance(self, day: date) -> dict:
        """События дня day. Возвращает сводку: сколько документов каждого вида затронуто."""
        v, c = self.volume, self.con
        rng = random.Random(f"{self.seed}:{day.isoformat()}")
        codes = [r[0] for r in c.execute("SELECT code FROM ib.stores ORDER BY code").fetchall()]
        n_late = max(1, v.stores // LATE_SHARE)
        late = tuple(sorted(rng.sample(codes, n_late)))
        # кандидаты для правок — проведённые продажи последних EDIT_WINDOW дней (выборка без повторов)
        pool = [r[0] for r in c.execute("""
            SELECT ref FROM ib.docs WHERE doc_type = 'РозничныеПродажи' AND posted AND NOT deletion_mark
              AND doc_date BETWEEN ? AND ? ORDER BY ref""",
            [day - timedelta(days=EDIT_WINDOW), day - timedelta(days=1)]).fetchall()]
        n_edit, n_unpost, n_mark = max(2, v.stores // 3), max(1, v.stores // 10), max(1, v.stores // 20)
        n_del = 1 if (day - self.sim_start).days % 3 == 2 else 0
        picked = rng.sample(pool, n_edit + n_unpost + n_mark + n_del)
        edits = picked[:n_edit]
        unposts = picked[n_edit:n_edit + n_unpost]
        marks = picked[n_edit + n_unpost:n_edit + n_unpost + n_mark]
        deletes = picked[n_edit + n_unpost + n_mark:]

        self._sales_days(day, day, late)
        n_receipts = c.execute("SELECT count(*) FROM ib.docs WHERE doc_type = 'ПоступлениеТоваров'").fetchone()[0]
        self._receipt_days(day, day)
        n_receipts = c.execute("SELECT count(*) FROM ib.docs WHERE doc_type = 'ПоступлениеТоваров'").fetchone()[0] - n_receipts
        new_refs = [r[0] for r in c.execute("SELECT ref FROM ib.docs WHERE doc_date = ? AND version = 1", [day]).fetchall()]

        for i, ref in enumerate(edits):           # правка задним числом: +1 шт. в двух строках
            c.execute("""
              UPDATE ib.doc_lines SET qty = qty + 1,
                amount = round((qty + 1) * (SELECT price FROM ib.products p WHERE p.ref = product_ref), 2)
              WHERE doc_ref = ? AND qty > 0 AND line_no IN (SELECT line_no FROM ib.doc_lines
                WHERE doc_ref = ? AND qty > 0 ORDER BY line_no LIMIT 2)""", [ref, ref])
            self._touch(ref, datetime.combine(day, time(10)) + timedelta(minutes=i))
        for i, ref in enumerate(unposts):         # отмена проведения
            c.execute("UPDATE ib.docs SET posted = false WHERE ref = ?", [ref])
            self._touch(ref, datetime.combine(day, time(12)) + timedelta(minutes=i))
        for i, ref in enumerate(marks):           # пометка на удаление снимает проведение
            c.execute("UPDATE ib.docs SET posted = false, deletion_mark = true WHERE ref = ?", [ref])
            self._touch(ref, datetime.combine(day, time(14)) + timedelta(minutes=i))
        for ref in deletes:                       # прямое удаление: следа в базе не остаётся
            for t, col in (("ib.moves", "recorder"), ("ib.doc_lines", "doc_ref"), ("ib.docs", "ref")):
                c.execute(f"DELETE FROM {t} WHERE {col} = ?", [ref])
        self._repost(edits + unposts + marks + new_refs)

        # справочник: одна карточка меняет категорию, другая — наименование
        prods = [r[0] for r in c.execute("SELECT ref FROM ib.products ORDER BY ref").fetchall()]
        p_cat, p_name = rng.sample(prods, 2)
        new_cat = rng.choice(list(CATEGORIES))
        ts = datetime.combine(day, time(16))
        c.execute("UPDATE ib.products SET category = ?, version = version + 1, modified_at = ? WHERE ref = ?",
                  [new_cat, ts, p_cat])
        c.execute("""UPDATE ib.products SET name = split_part(name, ' (', 1) || ' (ред. ' || strftime(?::DATE, '%d.%m') || ')',
                     version = version + 1, modified_at = ? WHERE ref = ?""", [day, ts, p_name])
        return {"day": day.isoformat(), "new_sales": v.stores, "receipts": n_receipts, "edited": len(edits),
                "unposted": len(unposts), "marked": len(marks), "deleted": len(deletes), "late": len(late),
                "catalog_changes": 2}

    def _touch(self, ref: str, ts: datetime) -> None:
        self.con.execute("UPDATE ib.docs SET version = version + 1, modified_at = ?, visible_at = ? WHERE ref = ?",
                         [ts, ts, ref])

    # ---------- выгрузка ----------
    def _doc_where(self, f: DocFilter) -> tuple[str, list]:
        if f.kind == "all":
            return "true", []
        if f.kind == "doc_date":
            return "d.doc_date BETWEEN ? AND ?", [f.date_from, f.date_to]
        if f.kind == "changed_since":
            return "d.modified_at > ?", [f.since]
        if f.kind == "store_months":
            if not f.pairs:
                return "false", []
            return ("list_contains(?, d.store_ref || '|' || strftime(date_trunc('month', d.doc_date), '%Y-%m-%d'))",
                    [[f"{s}|{m.isoformat()}" for s, m in f.pairs]])
        raise ValueError(f.kind)

    def export(self, out_dir, at: datetime, f: DocFilter) -> dict:
        """Выгрузить справочники целиком и документы по фильтру — то, что видно в базе на момент at."""
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        c = self.con
        objects: dict[str, dict] = {}

        def _write(name: str, sql: str) -> Path:
            path = out / f"{name}.json"
            c.execute(f"COPY ({sql}) TO '{path.as_posix()}' (FORMAT json)")
            return path

        catalogs = {
            "Catalog_Магазины": """SELECT ref AS Ref_Key, lpad(code::VARCHAR, 9, '0') AS Code, name AS Description,
                 region AS Регион, strftime(opened_on, '%Y-%m-%dT00:00:00') AS ДатаОткрытия, deletion_mark AS DeletionMark,
                 version::VARCHAR AS DataVersion FROM ib.stores ORDER BY code""",
            "Catalog_Номенклатура": """SELECT ref AS Ref_Key, code AS Code, name AS Description, category AS Категория,
                 brand AS Бренд, unit AS ЕдиницаИзмерения, deletion_mark AS DeletionMark, version::VARCHAR AS DataVersion
                 FROM ib.products ORDER BY code""",
            "Catalog_Контрагенты": """SELECT ref AS Ref_Key, name AS Description, kind AS ВидКонтрагента,
                 deletion_mark AS DeletionMark, version::VARCHAR AS DataVersion FROM ib.partners ORDER BY name""",
        }
        for name, sql in catalogs.items():
            p = _write(name, sql)
            n = c.execute(f"SELECT count(*) FROM ({sql})").fetchone()[0]
            objects[name] = {"file": p.name, "count": n, "requests": max(1, -(-n // PAGE_OBJECTS)),
                             "bytes": p.stat().st_size}

        where, params = self._doc_where(f)
        c.execute(f"""CREATE OR REPLACE TEMP TABLE sel AS SELECT d.* FROM ib.docs d
                      WHERE d.visible_at <= ? AND {where}""", [at] + params)
        for dt in DOC_TYPES:
            name = f"Document_{dt}"
            sql = f"""
              SELECT d.ref AS Ref_Key, d.number AS Number, strftime(d.doc_date, '%Y-%m-%dT00:00:00') AS Date,
                     d.posted AS Posted, d.deletion_mark AS DeletionMark, d.version::VARCHAR AS DataVersion,
                     strftime(d.modified_at, '%Y-%m-%dT%H:%M:%S') AS ДатаИзменения, d.store_ref AS Магазин_Key,
                     coalesce(d.partner_ref, '{EMPTY_REF}') AS Контрагент_Key,
                     list(struct_pack(LineNumber := l.line_no, Номенклатура_Key := l.product_ref,
                                      Количество := l.qty, Сумма := l.amount) ORDER BY l.line_no) AS Товары
              FROM sel d JOIN ib.doc_lines l ON l.doc_ref = d.ref
              WHERE d.doc_type = '{dt}'
              GROUP BY ALL ORDER BY ДатаИзменения, Ref_Key"""
            p = _write(name, sql)
            n, n_lines, total = c.execute(f"""
              SELECT count(DISTINCT d.ref), count(l.line_no), coalesce(sum(l.amount), 0)
              FROM sel d JOIN ib.doc_lines l ON l.doc_ref = d.ref WHERE d.doc_type = '{dt}'""").fetchone()
            objects[name] = {"file": p.name, "count": n, "lines": n_lines, "sum": str(total),
                             "requests": max(1, -(-n // PAGE_OBJECTS)), "bytes": p.stat().st_size}

        sql = """SELECT m.recorder AS Recorder, 'StandardODATA.Document_' || m.recorder_type AS Recorder_Type,
                        strftime(m.period, '%Y-%m-%dT00:00:00') AS Period, m.line_no AS LineNumber, true AS Active,
                        m.record_type AS RecordType, m.store_ref AS Магазин_Key, m.product_ref AS Номенклатура_Key,
                        m.qty AS Количество
                 FROM ib.moves m WHERE m.recorder IN (SELECT ref FROM sel) ORDER BY m.recorder, m.line_no"""
        p = _write(REGISTER, sql)
        n, qty = c.execute("""SELECT count(*), coalesce(sum(qty), 0) FROM ib.moves
                              WHERE recorder IN (SELECT ref FROM sel)""").fetchone()
        recorders = c.execute("SELECT count(*) FROM sel").fetchone()[0]
        objects[REGISTER] = {"file": p.name, "count": n, "qty": int(qty), "recorders": recorders,
                             "requests": max(1, -(-n // PAGE_ROWS)), "bytes": p.stat().st_size}

        rows = sum(o["count"] + o.get("lines", 0) for o in objects.values())
        stats = {"requests": sum(o["requests"] for o in objects.values()), "rows": rows,
                 "bytes": sum(o["bytes"] for o in objects.values())}
        self.requests += stats["requests"]
        self.rows_read += rows
        self.bytes_out += stats["bytes"]
        manifest = {"exported_at": at.isoformat(), "filter": f.to_json(), "objects": objects, "stats": stats}
        (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
        return manifest

    def control_totals(self, at: datetime) -> list[dict]:
        """Контрольные суммы проведённых документов по магазину и месяцу — один лёгкий запрос."""
        rows = self.con.execute("""
          SELECT d.store_ref, date_trunc('month', d.doc_date)::DATE AS month, count(DISTINCT d.ref) AS docs,
                 sum(l.qty) AS qty, sum(l.amount) AS amount
          FROM ib.docs d JOIN ib.doc_lines l ON l.doc_ref = d.ref
          WHERE d.posted AND NOT d.deletion_mark AND d.visible_at <= ?
          GROUP BY ALL ORDER BY 1, 2""", [at]).fetchall()
        out = [{"store_ref": r[0], "month": r[1], "docs": r[2], "qty": int(r[3]), "amount": r[4]} for r in rows]
        self.requests += 1
        self.rows_read += len(out)
        self.bytes_out += len(json.dumps(out, default=str))
        return out
