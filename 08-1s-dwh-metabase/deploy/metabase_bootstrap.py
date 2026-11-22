"""Первичная настройка Metabase через API: администратор, подключение к витринам, подписи, вопросы, дашборд.

Запуск после `docker compose up -d` и `uv run --extra pg razbor08 publish`:

    MB_ADMIN_PASSWORD=... python3 deploy/metabase_bootstrap.py

Только стандартная библиотека. Повторный запуск не плодит дубли: вход вместо настройки,
база, вопросы и дашборд ищутся по имени.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

MB = os.environ.get("MB_URL", "http://localhost:3030")
EMAIL = os.environ.get("MB_ADMIN_EMAIL", "admin@example.com")
PASSWORD = os.environ.get("MB_ADMIN_PASSWORD", "razbor08-admin-1")
READER_PASSWORD = os.environ.get("MB_READER_PASSWORD", "reader")
DB_NAME = "Хранилище: витрины"
DASH_NAME = "Продажи и остатки сети"

TABLES = {"sales_daily": "Продажи по дням", "receipts_daily": "Поступления по дням",
          "stock_month_end": "Остатки на конец месяца", "stock_current": "Остатки сейчас",
          "stores": "Магазины", "products": "Товары"}
FIELDS = {"sale_date": "Дата продажи", "receipt_date": "Дата поступления", "month": "Месяц",
          "month_end": "Конец месяца", "as_of": "На дату", "store_id": "Магазин №", "store_name": "Магазин",
          "region": "Регион", "sku": "Артикул", "product_name": "Товар", "category": "Категория", "brand": "Бренд",
          "partner": "Поставщик", "net_qty": "Продано, шт.", "net_amount": "Выручка, ₽",
          "return_amount": "Возвраты, ₽", "qty": "Количество, шт.", "amount": "Сумма, ₽",
          "qty_on_hand": "Остаток, шт.", "opened_on": "Дата открытия"}


def call(method: str, path: str, body=None, session: str | None = None):
    req = urllib.request.Request(MB + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    if session:
        req.add_header("X-Metabase-Session", session)
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read()
    return json.loads(raw) if raw else None


def wait_health() -> None:
    for _ in range(120):
        try:
            if call("GET", "/api/health").get("status") == "ok":
                return
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            pass
        time.sleep(3)
    sys.exit("Metabase не поднялся за 6 минут")


def session() -> str:
    token = call("GET", "/api/session/properties").get("setup-token")
    if token:
        r = call("POST", "/api/setup", {
            "token": token,
            "user": {"first_name": "Админ", "last_name": "DWH", "email": EMAIL, "password": PASSWORD,
                     "site_name": "Розничная сеть"},
            "prefs": {"site_name": "Розничная сеть", "site_locale": "ru", "allow_tracking": False}})
        return r["id"]
    return call("POST", "/api/session", {"username": EMAIL, "password": PASSWORD})["id"]


def database(s: str) -> int:
    for db in call("GET", "/api/database", session=s)["data"]:
        if db["name"] == DB_NAME:
            return db["id"]
    db = call("POST", "/api/database", {
        "engine": "postgres", "name": DB_NAME,
        "details": {"host": "postgres", "port": 5432, "dbname": "dwh", "user": "metabase_reader",
                    "password": READER_PASSWORD, "ssl": False,
                    "schema-filters-type": "inclusion", "schema-filters-patterns": "mart"}}, session=s)
    return db["id"]


def fields(s: str, db_id: int) -> dict[str, dict[str, int]]:
    for _ in range(60):
        meta = call("GET", f"/api/database/{db_id}/metadata", session=s)
        tables = {t["name"]: t for t in meta.get("tables", []) if t.get("schema") == "mart"}
        if "sales_daily" in tables and tables["sales_daily"].get("fields"):
            return {name: {"_id": t["id"], **{f["name"]: f["id"] for f in t["fields"]}} for name, t in tables.items()}
        call("POST", f"/api/database/{db_id}/sync_schema", {}, session=s)
        time.sleep(3)
    sys.exit("Metabase не увидел схему mart")


def russian_names(s: str, f: dict[str, dict[str, int]]) -> None:
    """Подписи по-русски: руководитель видит «Выручка, ₽», а не net_amount."""
    for table, ids in f.items():
        if table in TABLES:
            call("PUT", f"/api/table/{ids['_id']}", {"display_name": TABLES[table]}, session=s)
        for name, fid in ids.items():
            if name in FIELDS:
                call("PUT", f"/api/field/{fid}", {"display_name": FIELDS[name]}, session=s)
    # разделители чисел: пробел для тысяч, запятая для дробной части
    call("PUT", "/api/setting/custom-formatting",
         {"value": {"type/Number": {"number_separators": ", "}}}, session=s)


def card(s: str, db_id: int, name: str, query: dict, display: str, viz: dict | None = None) -> int:
    for c in call("GET", "/api/card", session=s):
        if c["name"] == name:
            return c["id"]
    return call("POST", "/api/card", {
        "name": name, "display": display, "visualization_settings": viz or {},
        "dataset_query": {"type": "query", "database": db_id, "query": query}}, session=s)["id"]


def main() -> None:
    wait_health()
    s = session()
    db_id = database(s)
    f = fields(s, db_id)
    russian_names(s, f)
    sd, se = f["sales_daily"], f["stock_month_end"]
    amount = ["sum", ["field", sd["net_amount"], None]]
    cards = [
        card(s, db_id, "Выручка по месяцам и регионам", {
            "source-table": sd["_id"], "aggregation": [amount],
            "breakout": [["field", sd["sale_date"], {"temporal-unit": "month"}], ["field", sd["region"], None]],
            "filter": ["time-interval", ["field", sd["sale_date"], None], -24, "month"]}, "line"),
        card(s, db_id, "Выручка по категориям за прошлый месяц", {
            "source-table": sd["_id"], "aggregation": [amount],
            "breakout": [["field", sd["category"], None]],
            "filter": ["time-interval", ["field", sd["sale_date"], None], -1, "month"],
            "order-by": [["desc", ["aggregation", 0]]]}, "bar"),
        card(s, db_id, "Остаток на конец месяца, шт.", {
            "source-table": se["_id"], "aggregation": [["sum", ["field", se["qty_on_hand"], None]]],
            "breakout": [["field", se["month_end"], {"temporal-unit": "month"}]],
            "filter": ["time-interval", ["field", se["month_end"], None], -24, "month"]}, "bar"),
        card(s, db_id, "Магазины: выручка за прошлый месяц", {
            "source-table": sd["_id"], "aggregation": [amount],
            "breakout": [["field", sd["store_id"], None], ["field", sd["region"], None]],
            "filter": ["time-interval", ["field", sd["sale_date"], None], -1, "month"],
            "order-by": [["desc", ["aggregation", 0]]]}, "table"),
    ]
    dash = next((d for d in call("GET", "/api/dashboard", session=s) if d["name"] == DASH_NAME), None)
    if dash is None:
        dash = call("POST", "/api/dashboard", {"name": DASH_NAME}, session=s)
    layout = [(0, 0, 24, 8), (8, 0, 12, 8), (8, 12, 12, 8), (16, 0, 24, 8)]
    call("PUT", f"/api/dashboard/{dash['id']}", {"dashcards": [
        {"id": -(i + 1), "card_id": cid, "row": r, "col": c, "size_x": w, "size_y": h}
        for i, (cid, (r, c, w, h)) in enumerate(zip(cards, layout))]}, session=s)
    print(json.dumps({"database": db_id, "cards": cards, "dashboard": dash["id"]}))


if __name__ == "__main__":
    main()
